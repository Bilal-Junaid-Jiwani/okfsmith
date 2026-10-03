"""FastAPI app factory + all dashboard routes.

Every route reuses an existing okfsmith entry point; this module only
translates HTTP <-> those calls and shapes the JSON the contract specifies.
No knowledge-domain logic lives here.
"""

from __future__ import annotations

import hashlib
import inspect
import io
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from okfsmith import __version__ as _pkg_version
from okfsmith.core import Bundle
from okfsmith.core import spec as _spec
from okfsmith.dashboard import auth as _auth
from okfsmith.dashboard import jobs as _jobs

log = logging.getLogger("okfsmith.dashboard")

API = "/api/v1"
HEALTH_PATH = f"{API}/health"

# Trust-tier buckets shown by the dashboard. okfsmith's canonical tiers are
# "human-reviewed" / "machine-confirmed" / "unverified" (core/spec.py).
TIER_BUCKET = {
    "human-reviewed": "high",
    "machine-confirmed": "medium",
    "unverified": "low",
}

GRAPH_NODE_CAP = 2000
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
SESSION_IDLE_SECONDS = 30 * 60


def err(code: str, message: str, hint: str | None = None, status: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": code, "message": message, "hint": hint},
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None, field: str) -> datetime:
    if not value or not value.strip():
        raise err("bad-request", f"'{field}' is required.", f"Pass an ISO-8601 datetime for '{field}'.", 400)
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise err(
            "bad-datetime",
            f"'{field}' is not a valid ISO-8601 datetime: {value!r}.",
            "Example: 2026-09-01T00:00:00+00:00.",
            400,
        ) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _tier_of(frontmatter: dict) -> str:
    return TIER_BUCKET.get(_spec.trust_tier(frontmatter or {}), "low")


def _concept_title(concept: Any) -> str:
    return str((concept.frontmatter or {}).get("title") or concept.id)


def _concept_sources(concept: Any) -> list[str]:
    fm = concept.frontmatter or {}
    sources = fm.get("sources") or []
    if isinstance(sources, str):
        sources = [sources]
    out = [str(s) for s in sources if str(s).strip()]
    if not out:
        # The real ingest pipeline records the origin file/URL in the
        # canonical "resource" frontmatter key (parsers/ingest_no_llm.py,
        # core/sync.py) — surface it so "sources" is never silently 0 for
        # freshly ingested bundles.
        resource = fm.get("resource")
        if resource and str(resource).strip():
            out = [str(resource).strip()]
    return out


def _snippet(text: str, width: int = 300) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= width:
        return text
    return text[: width - 1].rstrip() + "…"


def _search_snippet(text: str, query: str, width: int = 220) -> str:
    """Snippet centred on the first query-term hit (real concept text)."""
    flat = re.sub(r"\s+", " ", (text or "")).strip()
    terms = [t.lower() for t in re.findall(r"\w+", query or "") if len(t) > 2]
    pos = -1
    for term in terms:
        pos = flat.lower().find(term)
        if pos >= 0:
            break
    if pos < 0:
        return _snippet(flat, width)
    start = max(0, pos - width // 3)
    end = min(len(flat), start + width)
    frag = flat[start:end].strip()
    if start > 0:
        frag = "…" + frag
    if end < len(flat):
        frag = frag + "…"
    return frag


# ---------------------------------------------------------------------------
# Bundle registry
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bundle registry
# ---------------------------------------------------------------------------


_INDEX_VERSION_RE = re.compile(r"okf_version\s*:", re.IGNORECASE)
_LOG_DAY_RE = re.compile(r"^## \d{4}-\d{2}-\d{2}", re.MULTILINE)


def _is_okf_bundle(path: Path) -> bool:
    """Strict real-bundle test for the dashboard registry.

    The loose CLI ``_looks_like_bundle()`` heuristic (any ``*.md`` anywhere
    below the directory) is deliberately NOT used here: pointed at a repo
    checkout it "discovers" ``docs/``, ``src/``, ``.venv/`` and the workspace
    root itself as phantom bundles. A real OKF bundle carries at least one of:
    an ``index.md`` whose frontmatter declares ``okf_version``, a ``log.md``
    in OKF log format (``## YYYY-MM-DD`` day headings with ``* **Kind**:``
    entries), or a ``.okfsmith/`` ingest-manifest directory.
    Hidden directories (any ``.*`` path part) are never bundles.
    """
    try:
        if any(part.startswith(".") for part in path.parts):
            return False
        index = path / "index.md"
        if index.is_file():
            head = index.read_text(encoding="utf-8", errors="replace")[:600]
            if _INDEX_VERSION_RE.search(head):
                return True
        log = path / "log.md"
        if log.is_file():
            head = log.read_text(encoding="utf-8", errors="replace")[:1200]
            if _LOG_DAY_RE.search(head) and "* **" in head:
                return True
        if (path / ".okfsmith").is_dir():
            return True
    except OSError:
        return False
    return False


def _md_files_below(root: Path) -> set[Path]:
    """Resolved ``*.md`` files under *root* (index/log excluded)."""
    out: set[Path] = set()
    try:
        for md in root.rglob("*.md"):
            name = md.name.lower()
            if name in ("index.md", "log.md"):
                continue
            try:
                if md.is_file() and not md.is_symlink():
                    out.add(md.resolve())
            except OSError:
                continue
    except OSError:
        pass
    return out


class Registry:
    """In-memory ``sha1(abs_path)[:12]`` → bundle dir registry."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self._lock = threading.Lock()
        self._bundles: dict[str, Path] = {}
        self.refresh()

    def refresh(self) -> None:
        # Strict OKF bundle detection only (never the loose CLI heuristic),
        # then drop any candidate that is a strict ancestor of another
        # candidate without contributing markdown of its own — e.g. the
        # workspace root "looking like a bundle" only because it contains
        # a real bundle subdirectory. That used to double-count every
        # concept (one entry for the parent, one for the child).
        candidates: list[Path] = []
        try:
            roots = [self.workspace] + sorted(
                p for p in self.workspace.iterdir() if p.is_dir()
            )
        except OSError:
            roots = [self.workspace]
        for path in roots:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if _is_okf_bundle(resolved):
                candidates.append(resolved)
        md_sets = {c: _md_files_below(c) for c in candidates}
        keep: list[Path] = []
        for cand in candidates:
            descendants = []
            for other in candidates:
                if other == cand:
                    continue
                try:
                    other.relative_to(cand)
                except ValueError:
                    continue
                descendants.append(other)
            # Drop *cand* when it contributes nothing of its own beyond what
            # lives inside descendant bundle dirs — e.g. the workspace root
            # "looking like a bundle" only because it contains a real bundle
            # subdirectory. That used to double-count every concept (one entry
            # for the parent, one for the child).
            dominated = bool(descendants) and not (
                md_sets[cand] - set().union(*(md_sets[o] for o in descendants))
            )
            if not dominated:
                keep.append(cand)
        with self._lock:
            self._bundles = {
                hashlib.sha1(str(p).encode()).hexdigest()[:12]: p for p in keep
            }

    def get(self, bundle_id: str) -> Path:
        with self._lock:
            path = self._bundles.get(bundle_id)
        if path is None:
            raise err(
                "bundle-not-found",
                f"No bundle with id '{bundle_id}'.",
                "Pick a bundle from GET /api/v1/bundles.",
                404,
            )
        return path

    def list(self) -> dict[str, Path]:
        self.refresh()
        with self._lock:
            return dict(self._bundles)


def _bundle_stats(root: Path) -> dict[str, Any]:
    """Real per-bundle stats from a fresh Bundle.load()."""
    bundle = Bundle.load(root)
    concepts = list(bundle.iter_concepts())
    tiers = {"high": 0, "medium": 0, "low": 0}
    sources: set[str] = set()
    latest = 0.0
    size = 0
    for concept in concepts:
        tiers[_tier_of(concept.frontmatter)] += 1
        sources.update(_concept_sources(concept))
        try:
            st = concept.path.stat()
            latest = max(latest, st.st_mtime)
            size += st.st_size
        except OSError:
            continue
    try:
        for reserved in ("index.md", "log.md"):
            p = root / reserved
            if p.is_file():
                size += p.stat().st_size
    except OSError:
        pass
    updated = (
        datetime.fromtimestamp(latest, timezone.utc).isoformat() if latest else None
    )
    return {
        "concepts": concepts,
        "tiers": tiers,
        "n_sources": len(sources),
        "updated_at": updated,
        "size_bytes": size,
    }


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(workspace: Path, token: str) -> FastAPI:
    token_auth = _auth.TokenAuth(token)
    registry = Registry(workspace)
    job_manager = _jobs.JobManager()
    chat_sessions: dict[str, dict[str, Any]] = {}
    chat_lock = threading.Lock()
    previews: dict[str, dict[str, Any]] = {}
    preview_lock = threading.Lock()

    app = FastAPI(title="okfsmith dashboard", version=_pkg_version)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith(API) and path != HEALTH_PATH:
            if not token_auth.check(request):
                return token_auth.error_response()
        # The token is never written to logs.
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "http-error", "message": str(detail), "hint": None},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception("unhandled dashboard error")
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal",
                "message": "Unexpected server error.",
                "hint": "Retry; if it persists, check the server logs.",
            },
        )

    # -- chat session sweep -------------------------------------------------
    def sweep_chat_sessions() -> None:
        now = time.monotonic()
        with chat_lock:
            stale = [
                sid
                for sid, sess in chat_sessions.items()
                if now - sess["last_active"] > SESSION_IDLE_SECONDS
            ]
            for sid in stale:
                del chat_sessions[sid]

    def get_chat_session(sid: str) -> dict[str, Any]:
        sweep_chat_sessions()
        with chat_lock:
            sess = chat_sessions.get(sid)
        if sess is None:
            raise err("session-not-found", f"No chat session '{sid}'.",
                      "Create one with POST /api/v1/chat/sessions.", 404)
        sess["last_active"] = time.monotonic()
        return sess

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------

    @app.get(f"{API}/health")
    async def health():
        return {"status": "ok", "version": _pkg_version}

    @app.get(f"{API}/doctor")
    async def doctor():
        # Wraps the real `okfsmith doctor` check logic (extracted as
        # doctor_checks() in cli/commands.py) — checks are not reimplemented.
        from okfsmith.cli.commands import doctor_checks

        mapping = {"OK": "pass", "WARN": "warn", "MISSING": "warn", "FAIL": "fail"}
        checks = [
            {"name": name, "status": mapping.get(status, "warn"), "detail": detail}
            for name, status, detail in doctor_checks()
        ]
        return {"checks": checks}

    # ------------------------------------------------------------------
    # Bundles
    # ------------------------------------------------------------------

    @app.get(f"{API}/bundles")
    async def list_bundles():
        bundles = []
        for bid, path in sorted(registry.list().items()):
            try:
                stats = _bundle_stats(path)
            except Exception as exc:
                log.warning("bundle stats failed for %s: %s", path, exc)
                continue
            bundles.append(
                {
                    "id": bid,
                    "name": path.name,
                    "path": str(path),
                    "concepts": len(stats["concepts"]),
                    "sources": stats["n_sources"],
                    "trust_tiers": stats["tiers"],
                    "updated_at": stats["updated_at"],
                    "size_bytes": stats["size_bytes"],
                }
            )
        return {"bundles": bundles}

    def _load_bundle_or_404(bundle_id: str) -> tuple[Bundle, Path]:
        root = registry.get(bundle_id)
        try:
            return Bundle.load(root), root
        except Exception as exc:
            raise err("bundle-load-failed", f"Cannot load bundle '{bundle_id}': {exc}",
                      "The bundle directory may be unreadable.", 500) from None

    @app.get(f"{API}/bundles/{{bundle_id}}/concepts")
    async def list_concepts(
        bundle_id: str,
        q: str | None = Query(default=None),
        tier: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        per_page: int = Query(default=50, ge=1, le=200),
    ):
        bundle, _ = _load_bundle_or_404(bundle_id)
        if tier is not None and tier not in ("high", "medium", "low"):
            raise err("bad-tier", f"Unknown tier '{tier}'.", "Use high, medium, or low.", 400)
        needle = (q or "").strip().lower()
        items = []
        for concept in bundle.iter_concepts():
            ctier = _tier_of(concept.frontmatter)
            if tier is not None and ctier != tier:
                continue
            title = _concept_title(concept)
            if needle and needle not in title.lower() and needle not in concept.id.lower() \
                    and needle not in (concept.body or "").lower():
                continue
            try:
                updated = datetime.fromtimestamp(
                    concept.path.stat().st_mtime, timezone.utc
                ).isoformat()
            except OSError:
                updated = None
            items.append(
                {
                    "id": concept.id,
                    "title": title,
                    "tier": ctier,
                    "sources": _concept_sources(concept),
                    "updated_at": updated,
                }
            )
        total = len(items)
        start = (page - 1) * per_page
        return {"items": items[start: start + per_page], "total": total, "page": page}

    @app.get(f"{API}/bundles/{{bundle_id}}/concepts/{{concept_id:path}}")
    async def get_concept(bundle_id: str, concept_id: str):
        bundle, _ = _load_bundle_or_404(bundle_id)
        concept = bundle.get(concept_id)
        if concept is None:
            raise err("concept-not-found", f"No concept '{concept_id}'.",
                      "List concepts with GET /api/v1/bundles/{id}/concepts.", 404)
        fm = dict(concept.frontmatter or {})
        return {
            "id": concept.id,
            "title": _concept_title(concept),
            "tier": _tier_of(concept.frontmatter),
            "frontmatter": fm,
            "body": concept.body or "",
            "sources": _concept_sources(concept),
            "provenance": fm.get("provenance") or {},
        }

    @app.get(f"{API}/bundles/{{bundle_id}}/graph")
    async def get_graph(bundle_id: str):
        from okfsmith.viz import _build_model

        bundle, _ = _load_bundle_or_404(bundle_id)
        model = _build_model(bundle)
        raw_nodes = model.get("nodes", [])
        truncated = len(raw_nodes) > GRAPH_NODE_CAP
        kept = raw_nodes[:GRAPH_NODE_CAP]
        kept_ids = {n["id"] for n in kept}
        nodes = [
            {
                "id": n["id"],
                "label": str(n.get("title") or n["id"]),
                "tier": TIER_BUCKET.get(str(n.get("trust") or ""), "low"),
            }
            for n in kept
        ]
        edges = [
            {"from": e["from"], "to": e["to"], "dead": bool(e.get("dead"))}
            for e in model.get("edges", [])
            if e.get("from") in kept_ids and e.get("to") in kept_ids
        ]
        return {"nodes": nodes, "edges": edges, "truncated": truncated}

    @app.get(f"{API}/bundles/{{bundle_id}}/snapshot")
    async def get_snapshot(bundle_id: str, as_of: str | None = Query(default=None)):
        from okfsmith.core import temporal as _temporal

        moment = _parse_iso(as_of, "as_of")
        bundle, _ = _load_bundle_or_404(bundle_id)
        sindex = _temporal.SupersessionIndex.from_bundle(bundle)
        concepts = []
        for concept in bundle.iter_concepts():
            if not sindex.window_valid(concept.id, moment):
                continue
            # Only the head of each supersession chain is "the" concept at
            # that instant; superseded revisions are not listed.
            if sindex.resolve_head(concept.id, moment) != concept.id:
                continue
            fm = concept.frontmatter or {}

            def _iso_or_null(value: Any) -> str | None:
                parsed = _temporal.parse_temporal(value)
                return parsed.isoformat() if parsed is not None else None

            concepts.append(
                {
                    "id": concept.id,
                    "title": _concept_title(concept),
                    "tier": _tier_of(fm),
                    "valid_from": _iso_or_null(fm.get("valid_from")),
                    "valid_to": _iso_or_null(fm.get("valid_until")),
                }
            )
        return {"as_of": moment.isoformat(), "concepts": concepts}

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @app.get(f"{API}/search")
    async def search(
        q: str = Query(...),
        bundle_id: str | None = Query(default=None),
        limit: int = Query(default=25, ge=1, le=100),
    ):
        from okfsmith.search import search_bundle

        query = (q or "").strip()
        if not query:
            raise err("bad-query", "Query 'q' must not be empty.", "Pass ?q=<keywords>.", 400)
        targets: list[tuple[str, Bundle]]
        if bundle_id is not None and bundle_id != "all":
            bundle, _ = _load_bundle_or_404(bundle_id)
            targets = [(bundle_id, bundle)]
        else:
            targets = []
            for bid in sorted(registry.list()):
                try:
                    b, _ = _load_bundle_or_404(bid)
                except HTTPException:
                    continue
                targets.append((bid, b))
        per = max(1, min(limit, 100))
        results = []
        for bid, bundle in targets:
            try:
                hits = search_bundle(bundle, query, per)
            except Exception as exc:
                log.warning("search failed for %s: %s", bid, exc)
                continue
            for score, concept in hits:
                body = concept.body or ""
                fm = concept.frontmatter or {}
                desc = str(fm.get("description") or "")
                results.append(
                    {
                        "bundle_id": bid,
                        "concept_id": concept.id,
                        "title": _concept_title(concept),
                        "snippet": _search_snippet(f"{desc}\n{body}", query),
                        "score": round(float(score), 4),
                    }
                )
        results.sort(key=lambda r: r["score"], reverse=True)
        return {"results": results[:limit]}

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    _INGEST_STEPS = ["parse", "chunk", "embed", "validate", "index"]
    _SOURCE_KINDS = ("auto", "pdf", "markdown", "wiki")
    _KIND_SUFFIXES = {
        "pdf": {".pdf"},
        "markdown": {".md", ".markdown", ".txt"},
        "wiki": {".zip"},
    }
    _chunk_lock = threading.Lock()

    def _parse_bool(value: Any, field: str) -> bool:
        # Multipart forms carry booleans as strings ("true"/"false").
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off", ""):
            return False
        raise err("bad-request", f"'{field}' must be a boolean.",
                  "Use true or false.", 400)

    def _sanitize_filename(name: str | None, fallback: str) -> str:
        base = Path(name or "").name.strip() or fallback
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:120]
        return base or fallback

    async def _stage_upload(upload: UploadFile, dest_dir: Path, idx: int) -> Path:
        filename = _sanitize_filename(upload.filename, f"upload-{idx}")
        dest = dest_dir / filename
        # Avoid collisions between uploads with the same client filename.
        if dest.exists():
            dest = dest_dir / f"{idx}-{filename}"
        size = 0
        try:
            with open(dest, "wb") as fh:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise err(
                            "file-too-large",
                            f"'{filename}' exceeds the 100 MB upload cap.",
                            "Split the file or ingest a smaller one.", 413,
                        )
                    fh.write(chunk)
        finally:
            await upload.close()
        return dest

    def _kind_matches(path: Path, source_kind: str) -> bool:
        if source_kind == "auto":
            return True
        return path.suffix.lower() in _KIND_SUFFIXES[source_kind]

    def _new_bundle_dir(name: str, workspace: Path) -> tuple[Path, bool]:
        """Create a new bundle dir; return ``(target, created_new)``.

        New bundles are scaffolded exactly like ``okfsmith init`` (a real
        ``index.md`` with ``okf_version`` frontmatter plus a ``log.md``
        creation entry), so they are first-class OKF bundles — never bare
        directories. ``created_new`` is True when this call created the
        directory, letting the worker remove it again if the ingest that
        requested it produced nothing (no junk bundles left behind).
        """
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip("-")[:80]
        if not slug:
            raise err("bad-request", "'new_bundle' name is empty after sanitizing.",
                      "Use letters, numbers, dashes.", 400)
        target = (workspace / slug).resolve()
        if target.parent != workspace:
            raise err("bad-request", "Invalid bundle name.", "Use a plain directory name.", 400)
        try:
            created_new = not target.exists()
            target.mkdir(parents=True, exist_ok=True)
            from okfsmith.core import indexlog as _indexlog
            from okfsmith.core.bundle import Bundle as _Bundle

            bundle_obj = _Bundle(target)
            _indexlog.ensure_index(bundle_obj)
            if created_new:
                _indexlog.append_log(bundle_obj, kind="Creation",
                                     message="Bundle created via the okfsmith dashboard.")
        except OSError as exc:
            raise err("bundle-create-failed", f"Cannot create bundle '{slug}': {exc}",
                      "Check the workspace directory is writable.", 500) from None
        registry.refresh()
        return target, created_new

    def _ingest_worker(
        job: _jobs.Job,
        target_root: Path,
        files: list[Path],
        *,
        source_kind: str,
        chunk_size: int | None,
        dry_run: bool,
        staging_dir: Path,
        created_new_bundle: bool = False,
    ) -> None:
        from functools import partial

        from okfsmith.parsers import parse_file as _real_parse_file
        from okfsmith.parsers import sectioning
        from okfsmith.parsers.dedup import already_ingested, record_ingested, sha256_of

        parse_file = (
            partial(_real_parse_file, quiet=True)
            if "quiet" in inspect.signature(_real_parse_file).parameters
            else _real_parse_file
        )
        target = Bundle.load(target_root)
        notes: list[str] = []
        would_create = 0
        n_ok = n_skipped = n_failed = 0

        def _skip_remaining(label: str, reason: str) -> None:
            for step in _INGEST_STEPS:
                job.set_step(step, "done", f"{label}: skipped ({reason})")

        try:
            for path in files:
                label = path.name
                for step in _INGEST_STEPS:
                    job.set_step(step, "pending", label)
                if not _kind_matches(path, source_kind):
                    n_skipped += 1
                    notes.append(f"{label}: skipped (source_kind={source_kind})")
                    _skip_remaining(label, f"source_kind={source_kind}")
                    continue
                try:
                    digest = sha256_of(path)
                except OSError as exc:
                    n_failed += 1
                    notes.append(f"{label}: cannot read file: {exc}")
                    job.set_step("parse", "error", f"{label}: cannot read file")
                    _skip_remaining(label, "unreadable")
                    continue
                if not dry_run and already_ingested(target, digest):
                    n_skipped += 1
                    notes.append(f"{label}: already ingested (dedup)")
                    _skip_remaining(label, "already ingested")
                    continue

                # -- parse: real parser -------------------------------------------------
                job.set_step("parse", "running", label)
                try:
                    parsed = parse_file(path)
                except Exception as exc:
                    n_failed += 1
                    notes.append(f"{label}: parse failed: {exc}")
                    job.set_step("parse", "error", f"{label}: parse failed")
                    _skip_remaining(label, "parse failed")
                    continue
                parse_error = (parsed.meta or {}).get("error")
                if parse_error:
                    n_skipped += 1
                    notes.append(f"{label}: {parse_error}")
                    job.set_step("parse", "done", f"{label}: {parse_error}")
                    _skip_remaining(label, str(parse_error))
                    continue
                n_pages = len(parsed.pages or [])
                job.set_step("parse", "done", f"{label}: {n_pages} page(s)")

                # -- chunk: real sectioning --------------------------------------------
                job.set_step("chunk", "running", label)
                try:
                    sectioned = sectioning.section(parsed)
                except Exception as exc:
                    n_failed += 1
                    notes.append(f"{label}: sectioning failed: {exc}")
                    job.set_step("chunk", "error", f"{label}: sectioning failed")
                    _skip_remaining(label, "sectioning failed")
                    continue
                if sectioned.too_small:
                    n_skipped += 1
                    reason = (f"below {sectioning.TOO_SMALL_CHARS}-char minimum; "
                              "stub prevention")
                    notes.append(f"{label}: {reason}")
                    job.set_step("chunk", "done", f"{label}: {reason}")
                    _skip_remaining(label, reason)
                    continue
                n_sections = len(sectioned.sections)
                job.set_step("chunk", "done", f"{label}: {n_sections} section(s)")

                if dry_run:
                    if digest and already_ingested(Bundle(target_root), digest):
                        n_skipped += 1
                        notes.append(f"{label}: would skip (already ingested)")
                    else:
                        would_create += n_sections
                        n_ok += 1
                        notes.append(f"{label}: would create ~{n_sections} draft concept(s)")
                    for step in ("embed", "validate", "index"):
                        job.set_step(step, "done", f"{label}: dry run — nothing written")
                    continue

                # -- embed: real concept creation --------------------------------------
                job.set_step("embed", "running", label)
                from okfsmith.parsers import ingest_no_llm as _inm

                # Provenance: the staged filename is the sanitized original
                # upload name. Record THAT as the concept source — never the
                # /tmp/ staging path, which is deleted before the job ends
                # and would otherwise point every citation at a dead file.
                provenance = path.name
                created: list[str] = []
                if chunk_size is not None:
                    # BODY_MAX_CHARS is the real truncation knob inside
                    # ingest_no_llm; guard it while the call runs.
                    with _chunk_lock:
                        prev = _inm.BODY_MAX_CHARS
                        _inm.BODY_MAX_CHARS = chunk_size
                        try:
                            created = _inm.ingest_no_llm(target, parsed, provenance)
                        finally:
                            _inm.BODY_MAX_CHARS = prev
                else:
                    created = _inm.ingest_no_llm(target, parsed, provenance)
                if not created:
                    n_skipped += 1
                    notes.append(f"{label}: no concepts created")
                    job.set_step("embed", "done", f"{label}: no concepts created")
                    _skip_remaining(label, "no concepts created")
                    continue
                job.set_step("embed", "done", f"{label}: {len(created)} concept(s)")

                # -- validate: the real §11 check pipeline -----------------------------
                job.set_step("validate", "running", label)
                from okfsmith.validate import check as _validate_check

                report = _validate_check(bundle=target)
                vdetail = ("conformant" if report.is_conformant
                           else f"{len(report.errors)} error(s), "
                                f"{len(report.warnings)} warning(s)")
                job.set_step("validate", "done", f"{label}: {vdetail}")

                # -- index: real dedup-manifest write -----------------------------------
                job.set_step("index", "running", label)
                record_ingested(target, digest, provenance)
                job.set_step("index", "done", f"{label}: dedup manifest updated")
                n_ok += 1
                notes.append(f"{label}: ok ({len(created)} concept(s))")
        finally:
            # Staging files never leak into the workspace.
            for path in files:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                staging_dir.rmdir()
            except OSError:
                pass

        detail = (f"{n_ok} ingested, {n_skipped} skipped, {n_failed} failed "
                  f"({len(files)} file(s))")
        if dry_run:
            job.extra["dry_run_report"] = {
                "would_create": would_create,
                "would_update": 0,
                "notes": notes
                + ["no-LLM ingest creates new draft concepts; nothing is updated in place."],
            }
            detail = f"dry run: ~{would_create} concept(s) would be created"
        if n_failed and not n_ok and not n_skipped:
            job.finish("error", detail="; ".join(notes[:5]), error="; ".join(notes[:5]))
        else:
            job.finish("done", detail=detail)
        # A new bundle that ended up with zero concepts is junk: the ingest
        # produced nothing (unsupported or empty uploads) and the directory
        # was created only for this job, so remove it again. A dry run that
        # *would* create concepts keeps its directory for the real run.
        if created_new_bundle and n_ok == 0 and would_create == 0:
            try:
                if sum(1 for _ in target.iter_concepts()) == 0:
                    shutil.rmtree(target_root, ignore_errors=True)
            except OSError:
                pass
        registry.refresh()

    @app.post(f"{API}/ingest", status_code=202)
    async def post_ingest(
        files: list[UploadFile] | None = File(None, alias="files[]"),
        bundle_id: str | None = Form(default=None),
        new_bundle: str | None = Form(default=None),
        chunk_size: str | None = Form(default=None),
        dry_run: Any = Form(default="false"),
        source_kind: str = Form(default="auto"),
    ):
        if not files:
            raise err("no-files", "No files uploaded.",
                      "Attach one or more files as 'files[]'.", 400)
        if bool(bundle_id) == bool(new_bundle):
            raise err("bad-request", "Pass exactly one of 'bundle_id' or 'new_bundle'.",
                      "Use bundle_id for an existing bundle, new_bundle for a new one.", 400)
        if source_kind not in _SOURCE_KINDS:
            raise err("bad-request", f"Unknown source_kind '{source_kind}'.",
                      f"Use one of: {', '.join(_SOURCE_KINDS)}.", 400)
        dry = _parse_bool(dry_run, "dry_run")
        chunk: int | None = None
        if chunk_size not in (None, ""):
            try:
                chunk = int(str(chunk_size))
            except ValueError:
                raise err("bad-request", "'chunk_size' must be an integer.",
                          "It caps concept body characters (default 8000).", 400) from None
            if chunk < 100:
                raise err("bad-request", "'chunk_size' must be >= 100.",
                          "It caps concept body characters.", 400)
        # Reject unsupported uploads BEFORE anything is created: an .exe
        # (or any suffix outside the ingestable set) is a 400, never a 202
        # that quietly leaves a zero-concept junk bundle behind.
        if source_kind == "auto":
            allowed_suffixes = set().union(*_KIND_SUFFIXES.values())
        else:
            allowed_suffixes = _KIND_SUFFIXES[source_kind]
        for upload in files:
            suffix = Path(_sanitize_filename(upload.filename, "x")).suffix.lower()
            if suffix not in allowed_suffixes:
                raise err("unsupported-file-type",
                          f"'{upload.filename or suffix or 'file'}' is not an ingestable file type.",
                          f"Supported for source_kind '{source_kind}': "
                          f"{', '.join(sorted(allowed_suffixes))}.", 400)
        staging = Path(tempfile.mkdtemp(prefix="okfsmith-ingest-"))
        staged: list[Path] = []
        try:
            for idx, upload in enumerate(files):
                staged.append(await _stage_upload(upload, staging, idx))
        except Exception:
            for p in staged:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                staging.rmdir()
            except OSError:
                pass
            raise
        # All-empty uploads are a 400: there is nothing to ingest, and the
        # bundle directory is only created after this check passes.
        try:
            all_empty = all(p.stat().st_size == 0 for p in staged)
        except OSError:
            all_empty = False  # let the worker deal with unreadable files
        if all_empty:
            for p in staged:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                staging.rmdir()
            except OSError:
                pass
            raise err("empty-file", "All uploaded files are empty.",
                      "Upload a file with content to ingest.", 400)
        if new_bundle:
            target_root, created_new = _new_bundle_dir(new_bundle, registry.workspace)
            bid = hashlib.sha1(str(target_root).encode()).hexdigest()[:12]
        else:
            target_root = registry.get(bundle_id or "")
            bid = bundle_id or ""
            created_new = False
        filenames = [p.name for p in staged]
        signature = filenames[0] + (f" (+{len(filenames) - 1} more)" if len(filenames) > 1 else "")
        # A fast double-submit (or the user re-clicking) must not stack a
        # redundant job: reuse the still-active job for the same bundle and
        # file signature instead of queueing a duplicate.
        for existing in job_manager.list("ingest"):
            if (existing.bundle_id == bid
                    and existing.status in ("queued", "running")
                    and existing.extra.get("filename") == signature
                    and existing.extra.get("source_kind") == source_kind
                    and bool(existing.extra.get("dry_run", False)) == dry):
                # The files we just staged are unneeded — clean up before
                # handing the caller the already-running job.
                for p in staged:
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass
                try:
                    staging.rmdir()
                except OSError:
                    pass
                return {"job_id": existing.job_id, "reused": True}
        job = job_manager.submit(
            "ingest",
            bid,
            lambda j: _ingest_worker(
                j, target_root, staged,
                source_kind=source_kind, chunk_size=chunk,
                dry_run=dry, staging_dir=staging,
                created_new_bundle=created_new,
            ),
            step_names=list(_INGEST_STEPS),
            extra={
                "filename": signature,
                "source_kind": source_kind,
                "dry_run": dry,
                "n_files": len(filenames),
            },
        )
        return {"job_id": job.job_id}

    def _ingest_job_dict(job: _jobs.Job) -> dict[str, Any]:
        return {
            "job_id": job.job_id,
            "bundle_id": job.bundle_id,
            "status": job.status,
            "filename": job.extra.get("filename", ""),
            "source_kind": job.extra.get("source_kind", "auto"),
            "dry_run": bool(job.extra.get("dry_run", False)),
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "error": job.error,
        }

    @app.get(f"{API}/ingest/jobs")
    async def list_ingest_jobs():
        return {"jobs": [_ingest_job_dict(j) for j in job_manager.list("ingest")]}

    @app.get(f"{API}/ingest/jobs/{{job_id}}")
    async def get_ingest_job(job_id: str):
        job = job_manager.get(job_id)
        if job is None or job.kind != "ingest":
            raise err("job-not-found", f"No ingest job '{job_id}'.", None, 404)
        payload = _ingest_job_dict(job)
        payload["steps"] = job.steps
        payload["detail"] = job.detail
        if job.extra.get("dry_run_report") is not None:
            payload["dry_run_report"] = job.extra["dry_run_report"]
        return payload

    @app.get(f"{API}/ingest/jobs/{{job_id}}/events")
    async def ingest_events(job_id: str, request: Request):
        job = job_manager.get(job_id)
        if job is None or job.kind != "ingest":
            raise err("job-not-found", f"No ingest job '{job_id}'.", None, 404)

        def gen():
            # Replay history, then tail until the terminal status event.
            # The (events, terminal-flag) snapshot is taken under the job
            # lock — Job.finish() appends the closing event and flips the
            # status atomically under the same lock — so a fast job can never
            # end the stream without its final {"status": ...} frame.
            idx = 0
            while True:
                with job._lock:
                    batch = job.events[idx:]
                    idx = len(job.events)
                    terminal = job.status in _jobs.TERMINAL_STATUSES
                for event in batch:
                    yield _jobs.sse_format(event)
                if terminal:
                    return
                event = job_manager.wait_for_event(job, timeout=15.0)
                if event is None:
                    # Timeout (or the finish sentinel): re-snapshot; the
                    # terminal flag above ends the stream once the job is done.
                    yield ": keep-alive\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    @app.get(f"{API}/sync/sources")
    async def sync_sources(bundle_id: str | None = Query(default=None)):
        """Sync sources for one bundle (``?bundle_id=``) or all bundles.

        Response matches the contract: ``{"sources": [{name, kind,
        status: ok|stale|error|never, last_sync, detail}]}``. Staleness is
        computed from real backend state: the source record's stored sha256
        versus the current file hash.
        """
        from okfsmith.core import sync as _sync_core

        targets = []
        if bundle_id:
            bundle, _ = _load_bundle_or_404(bundle_id)
            targets.append(bundle)
        else:
            for path in registry.list().values():
                try:
                    targets.append(Bundle.load(path))
                except Exception:
                    continue

        out = []
        for bundle in targets:
            state = _sync_core.load_sync_state(bundle)
            sources_cfg: dict = state.get("sources") or {}
            failures: dict = state.get("permanent_failures") or {}
            try:
                state_mtime = _sync_core.sync_state_path(bundle).stat().st_mtime
                last_sync = datetime.fromtimestamp(state_mtime, timezone.utc).isoformat()
            except OSError:
                last_sync = None
            for raw_path, record in sorted(sources_cfg.items()):
                record = record or {}
                path = Path(raw_path)
                name = path.name or raw_path
                suffix = path.suffix.lower().lstrip(".")
                kind = {"md": "markdown", "pdf": "pdf", "txt": "text"}.get(suffix, "dir" if path.is_dir() else "file")
                if raw_path in failures:
                    status = "error"
                    detail = str((failures[raw_path] or {}).get("error") or "permanent failure recorded")
                elif not path.exists():
                    status = "error"
                    detail = "source path no longer exists"
                elif path.is_file():
                    digest = hashlib.sha256()
                    try:
                        with open(path, "rb") as fh:
                            for chunk in iter(lambda: fh.read(65536), b""):
                                digest.update(chunk)
                        if digest.hexdigest() != record.get("sha256"):
                            status = "stale"
                            detail = "source changed since last sync"
                        else:
                            status = "ok"
                            detail = f"{len(record.get('concepts') or [])} concept(s) in sync"
                    except OSError as exc:
                        status = "error"
                        detail = f"cannot read source: {exc}"
                else:  # directory source: newest content vs state write time
                    try:
                        newest = max(
                            (p.stat().st_mtime for p in path.rglob("*") if p.is_file()),
                            default=0.0,
                        )
                        if last_sync and newest > state_mtime:
                            status = "stale"
                            detail = "directory content changed since last sync"
                        else:
                            status = "ok"
                            detail = f"{len(record.get('concepts') or [])} concept(s) in sync"
                    except OSError as exc:
                        status = "error"
                        detail = f"cannot scan source: {exc}"
                out.append(
                    {
                        "name": name,
                        "kind": kind,
                        "status": status,
                        "last_sync": last_sync,
                        "detail": detail,
                    }
                )
        out.sort(key=lambda s: s["name"])
        return {"sources": out}

    def _sync_worker(job: _jobs.Job, root: Path, sources: list[Path]) -> None:
        from okfsmith.cli.sync import SyncConfig, run_once

        config = SyncConfig(no_llm=True)
        try:
            result = run_once(root, sources, config)
        except Exception as exc:
            # run_once raises CliError with a clean message on expected
            # failures (e.g. sync lock held); anything else is unexpected.
            msg = str(exc)[:500]
            job.finish("error", detail=msg, error=msg)
            return
        summary = result.summary()
        parts = [f"{k}: {v}" for k, v in summary.items() if v]
        detail = "; ".join(parts) if parts else "no changes"
        if result.dry_run:
            detail = "dry run — " + detail
        job.extra["summary"] = summary
        job.finish("done", detail=detail)
        registry.refresh()

    @app.post(f"{API}/sync/runs", status_code=202)
    async def post_sync_run(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise err("bad-json", "Request body must be JSON.",
                      "Send {\"bundle_id\": \"...\"}.", 400) from None
        bundle_id = (body or {}).get("bundle_id")
        source = (body or {}).get("source")
        if not bundle_id:
            raise err("bad-request", "'bundle_id' is required.", None, 400)
        _, root = _load_bundle_or_404(bundle_id)
        if source:
            candidate = Path(str(source))
            if not candidate.is_absolute():
                candidate = (registry.workspace / candidate).resolve()
            if not candidate.exists():
                raise err("source-not-found", f"Source '{source}' does not exist.",
                          "Pass an existing file or directory.", 400)
            sources = [candidate]
        else:
            from okfsmith.core import sync as _sync_core

            bundle, _ = _load_bundle_or_404(bundle_id)
            state = _sync_core.load_sync_state(bundle)
            sources = [Path(p) for p in sorted((state.get("sources") or {}).keys())]
            if not sources:
                raise err("no-sources", "This bundle has no synced sources yet.",
                          "Ingest sources first, or pass an explicit 'source'.", 422)
        job = job_manager.submit(
            "sync", bundle_id,
            lambda j: _sync_worker(j, root, sources),
            extra={"detail": ""},
        )
        return {"job_id": job.job_id}

    @app.get(f"{API}/sync/runs/{{job_id}}")
    async def get_sync_run(job_id: str):
        job = job_manager.get(job_id)
        if job is None or job.kind != "sync":
            raise err("job-not-found", f"No sync run '{job_id}'.", None, 404)
        return {
            "job_id": job.job_id,
            "status": job.status,
            "detail": job.detail,
            "finished_at": job.finished_at,
        }

    # ------------------------------------------------------------------
    # Validate (§11)
    # ------------------------------------------------------------------

    _RULE_CODES = [f"E00{i}" for i in range(1, 5)] + [f"W{i:03d}" for i in range(1, 21)]

    def _validate_worker(job: _jobs.Job, root: Path) -> None:
        from okfsmith.validate import check as _validate_check

        bundle = Bundle.load(root)
        report = _validate_check(bundle=bundle)
        by_rule: dict[str, dict[str, Any]] = {
            code: {"rule": code, "status": "pass", "messages": [], "concepts": []}
            for code in _RULE_CODES
        }
        for finding in list(report.errors) + list(report.warnings):
            entry = by_rule.get(finding.code)
            if entry is None:
                continue
            entry["messages"].append(finding.message)
            rel = (finding.file or "").strip()
            if rel.endswith(".md") and rel.lower() not in ("index.md", "log.md"):
                entry["concepts"].append(rel[:-3])
            if finding.code.startswith("E"):
                entry["status"] = "fail"
            elif entry["status"] == "pass":
                entry["status"] = "warn"
        rules = []
        n_pass = n_fail = n_warn = 0
        for code in _RULE_CODES:
            entry = by_rule[code]
            status = entry["status"]
            n_pass += status == "pass"
            n_fail += status == "fail"
            n_warn += status == "warn"
            rules.append(
                {
                    "rule": code,
                    "status": status,
                    "messages": entry["messages"][:25],
                    "concepts": sorted(set(entry["concepts"])),
                }
            )
        job.extra["report"] = {
            "summary": {"pass": n_pass, "fail": n_fail, "warn": n_warn},
            "rules": rules,
            "conformant": report.is_conformant,
        }
        job.finish("done", detail=(f"{n_fail} failing, {n_warn} warning, "
                                   f"{n_pass} passing rule(s)"))

    @app.post(f"{API}/validate/runs", status_code=202)
    async def post_validate_run(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise err("bad-json", "Request body must be JSON.", None, 400) from None
        bundle_id = (body or {}).get("bundle_id")
        if not bundle_id:
            raise err("bad-request", "'bundle_id' is required.", None, 400)
        _, root = _load_bundle_or_404(bundle_id)
        job = job_manager.submit(
            "validate", bundle_id, lambda j: _validate_worker(j, root)
        )
        return {"run_id": job.job_id}

    @app.get(f"{API}/validate/runs/{{run_id}}")
    async def get_validate_run(run_id: str):
        job = job_manager.get(run_id)
        if job is None or job.kind != "validate":
            raise err("run-not-found", f"No validate run '{run_id}'.", None, 404)
        report = job.extra.get("report") or {"summary": {}, "rules": []}
        summary = report.get("summary") or {}
        rules = []
        for rule in report.get("rules") or []:
            rules.append(
                {
                    "rule": rule.get("rule"),
                    "status": rule.get("status"),
                    "message": "; ".join(rule.get("messages") or []),
                    "concepts": rule.get("concepts") or [],
                }
            )
        return {
            "run_id": job.job_id,
            "bundle_id": job.bundle_id,
            "status": job.status,
            "finished_at": job.finished_at,
            "summary": {
                "pass": summary.get("pass", 0),
                "fail": summary.get("fail", 0),
                "warn": summary.get("warn", 0),
            },
            "rules": rules,
        }

    # ------------------------------------------------------------------
    # Eval (RAG triad + CI gate)
    # ------------------------------------------------------------------

    def _score_value(scores: dict[str, Any], name: str) -> float:
        s = scores.get(name)
        return round(s.value, 4) if s is not None else 0.0

    def _eval_worker(job: _jobs.Job, root: Path, fail_under: float) -> None:
        from okfsmith import eval as _eval

        try:
            bundle = Bundle.load(root)
            report = _eval.run_eval(
                bundle, root, no_llm=True, fail_under=fail_under
            )
        except _eval.EvalError as exc:
            msg = f"{exc.code}: {exc}"
            job.finish("error", detail=msg, error=msg)
            return
        means = report.metric_means()
        # Canonical engine key is "answer_relevancy" (eval/engine.py METRICS);
        # the dashboard contract keeps the "answer_relevance" output name.
        triad = {
            "context": round(means.get("context_relevancy", 0.0), 4),
            "groundedness": round(means.get("faithfulness", 0.0), 4),
            "answer_relevance": round(means.get("answer_relevancy", 0.0), 4),
        }
        verdict = report.verdict()
        ci_gate = {
            "status": verdict,
            "threshold": f"fail_under={fail_under}",
            "detail": (f"overall score {report.overall():.1f} vs CI gate "
                       f"{fail_under}: {verdict}"),
        }
        questions = []
        for q in report.questions:
            scores = q.scores or {}
            questions.append(
                {
                    "question": q.question,
                    "score": round(q.mean(), 4),
                    "context": _score_value(scores, "context_relevancy"),
                    "groundedness": _score_value(scores, "faithfulness"),
                    # Engine key is "answer_relevancy"; contract name stays
                    # "answer_relevance" (see triad above).
                    "answer_relevance": _score_value(scores, "answer_relevancy"),
                    "citations": [{"concept_id": rid} for rid in (q.retrieved_ids or [])],
                }
            )
        job.extra["report"] = {
            "ci_gate": verdict,
            "ci_gate_detail": ci_gate,
            "triad": triad,
            "questions": questions,
            "overall": round(report.overall(), 2),
        }
        job.finish("done", detail=f"overall {report.overall():.1f}, CI gate {verdict}")

    @app.post(f"{API}/eval/runs", status_code=202)
    async def post_eval_run(request: Request):
        from okfsmith import eval as _eval

        try:
            body = await request.json()
        except Exception:
            raise err("bad-json", "Request body must be JSON.", None, 400) from None
        bundle_id = (body or {}).get("bundle_id")
        if not bundle_id:
            raise err("bad-request", "'bundle_id' is required.", None, 400)
        _, root = _load_bundle_or_404(bundle_id)
        # Honest empty state: refuse synchronously when there is no golden set.
        if not _eval.golden_path(root).is_file():
            return JSONResponse(
                status_code=422,
                content={
                    "error": "no_golden_set",
                    "message": f"Bundle '{bundle_id}' has no golden set.",
                    "hint": f"Run 'okfsmith eval {root} --init-sample' to write a "
                            "starter golden set, then curate it.",
                },
            )
        fail_under = (body or {}).get("fail_under", 0.0)
        try:
            fail_under = float(fail_under)
        except (TypeError, ValueError):
            raise err("bad-request", "'fail_under' must be a number 0-100.", None, 400) from None
        if not 0.0 <= fail_under <= 100.0:
            raise err("bad-request", "'fail_under' must be between 0 and 100.", None, 400)
        job = job_manager.submit(
            "eval", bundle_id, lambda j: _eval_worker(j, root, fail_under)
        )
        return {"run_id": job.job_id}

    def _eval_run_dict(job: _jobs.Job, *, detail: bool = False) -> dict[str, Any]:
        report = job.extra.get("report") or {}
        payload = {
            "run_id": job.job_id,
            "bundle_id": job.bundle_id,
            "status": job.status,
            "started_at": job.started_at,
            "ci_gate": report.get("ci_gate"),
            "triad": report.get("triad"),
        }
        if detail:
            payload["ci_gate"] = report.get("ci_gate_detail")
            payload["questions"] = report.get("questions", [])
            if job.error:
                payload["error"] = job.error
        elif job.error:
            payload["error"] = job.error
        return payload

    @app.get(f"{API}/eval/runs")
    async def list_eval_runs():
        return {"runs": [_eval_run_dict(j) for j in job_manager.list("eval")]}

    @app.get(f"{API}/eval/runs/{{run_id}}")
    async def get_eval_run(run_id: str):
        job = job_manager.get(run_id)
        if job is None or job.kind != "eval":
            raise err("run-not-found", f"No eval run '{run_id}'.", None, 404)
        return _eval_run_dict(job, detail=True)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def _provider_list() -> list[dict[str, str]]:
        from okfsmith.extract.llm import PROVIDER_PRESETS

        items = []
        for pid, url in sorted(PROVIDER_PRESETS.items()):
            if pid == "anthropic":
                description = f"Native Anthropic Messages API via {url}"
            else:
                description = f"OpenAI-compatible chat completions via {url}"
            items.append({"id": pid, "name": pid.title(), "description": description})
        return items

    @app.get(f"{API}/chat/providers")
    async def chat_providers():
        return {"providers": _provider_list()}

    def _strip_ansi(text: str) -> str:
        text = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", text)
        text = re.sub(r"\x1b[()][AB0]", "", text)
        return text

    def _make_chat_session(
        bundle: Bundle,
        root: Path,
        backend: Any,
        provider: str | None,
        as_of: datetime | None,
    ) -> dict[str, Any]:
        from rich.console import Console

        from okfsmith.cli import chat as _chat_mod

        buf = io.StringIO()
        console = Console(file=buf, force_terminal=False, width=100)
        if as_of is not None:

            class _AsOfChatSession(_chat_mod.ChatSession):
                """ChatSession whose retrieval replays at *as_of*.

                Only the retrieval instant changes: answering (extractive or
                LLM) still runs the real ChatSession pipeline.
                """

                def answer(self, question: str) -> str:  # noqa: D102
                    from okfsmith.search import search_bundle

                    hits = search_bundle(
                        self.bundle, question, _chat_mod.TOP_K, as_of=self._as_of
                    )
                    fallback = False
                    if not hits and self.last_concepts:
                        hits = [(0, c) for c in self.last_concepts[: _chat_mod.TOP_K]]
                        fallback = True
                    concepts = [c for _, c in hits]
                    if not concepts:
                        msg = (
                            f"I couldn't find anything in '{self.bundle_label}' "
                            f"about that as of {self._as_of.isoformat()}. Try "
                            "/search with broader keywords, /list to browse, or "
                            "/ingest to add the missing material."
                        )
                        self.console.print(f"[yellow]{msg}[/yellow]")
                        return msg
                    if fallback:
                        self.console.print(
                            "[dim](no new matches — answering from the previous "
                            "question's context)[/dim]"
                        )
                    if self.backend is None:
                        return self._answer_extractive(question, concepts)
                    return self._answer_llm(question, concepts)

            session = _AsOfChatSession(bundle, root, backend=backend, console=console)
            session._as_of = as_of
        else:
            session = _chat_mod.ChatSession(bundle, root, backend=backend, console=console)
        return {
            "session": session,
            "buf": buf,
            "lock": threading.Lock(),
            "last_active": time.monotonic(),
            "provider": provider,
            "as_of": as_of.isoformat() if as_of else None,
            "extractive": backend is None,
        }

    @app.post(f"{API}/chat/sessions")
    async def post_chat_session(request: Request):
        from okfsmith.cli.chat import resolve_chat_backend
        from okfsmith.extract.llm import LLMError

        try:
            body = await request.json()
        except Exception:
            raise err("bad-json", "Request body must be JSON.", None, 400) from None
        bundle_id = (body or {}).get("bundle_id")
        provider = (body or {}).get("provider")
        as_of_raw = (body or {}).get("as_of")
        if not bundle_id:
            raise err("bad-request", "'bundle_id' is required.", None, 400)
        bundle, root = _load_bundle_or_404(bundle_id)
        as_of = _parse_iso(as_of_raw, "as_of") if as_of_raw else None
        backend = None
        if provider:
            provider = str(provider).strip().lower()
            try:
                backend = resolve_chat_backend(provider=provider)
            except LLMError as exc:
                raise err("invalid-provider", str(exc),
                          "Pick one from GET /api/v1/chat/providers.", 422) from None
        if provider and backend is None:
            log.info("chat provider '%s' unavailable; extractive fallback", provider)
        sess = _make_chat_session(bundle, root, backend, provider, as_of)
        sid = _jobs.new_id("chat-")
        with chat_lock:
            chat_sessions[sid] = sess
        return {"session_id": sid}

    @app.post(f"{API}/chat/sessions/{{sid}}/messages")
    async def post_chat_message(sid: str, request: Request):
        from starlette.concurrency import run_in_threadpool

        try:
            body = await request.json()
        except Exception:
            raise err("bad-json", "Request body must be JSON.", None, 400) from None
        message = ((body or {}).get("message") or "").strip()
        if not message:
            raise err("bad-request", "'message' must not be empty.", None, 400)
        if len(message) > 8000:
            raise err("bad-request", "'message' is too long (max 8000 chars).", None, 400)
        sess = get_chat_session(sid)
        session = sess["session"]

        def _ask() -> str:
            with sess["lock"]:
                sess["buf"].seek(0)
                sess["buf"].truncate(0)
                try:
                    # answer() returns the display text; the Rich table/markdown
                    # it also prints is style only — the string is the answer.
                    return session.answer(message)
                except Exception as exc:
                    log.warning("chat answer failed: %s", exc)
                    return f"Answer failed: {exc}"

        raw = await run_in_threadpool(_ask)
        answer = _strip_ansi(raw).strip()
        citations = []
        for concept in getattr(session, "last_concepts", []) or []:
            fm = concept.frontmatter or {}
            desc = str(fm.get("description") or "")
            citations.append(
                {
                    "concept_id": concept.id,
                    "title": _concept_title(concept),
                    "sources": _concept_sources(concept),
                    "snippet": _snippet(f"{desc}\n{concept.body or ''}".strip()),
                }
            )
        return {"answer": answer, "citations": citations}

    @app.delete(f"{API}/chat/sessions/{{sid}}")
    async def delete_chat_session(sid: str):
        with chat_lock:
            removed = chat_sessions.pop(sid, None)
        if removed is None:
            raise err("session-not-found", f"No chat session '{sid}'.", None, 404)
        return {"ok": True}

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------

    _MCP_TOOL_NAMES = [
        "index", "list", "search", "get", "neighbors", "traverse",
        "provenance", "diff",
        "preview_write_concept", "write_concept", "update_concept", "audit_log",
    ]

    def _bundle_tools(bundle: Bundle):
        from okfsmith.mcp_server.server import BundleTools

        return BundleTools(bundle)

    @app.get(f"{API}/mcp/status")
    async def mcp_status():
        try:
            from okfsmith.mcp_server.server import _require_fastmcp

            _require_fastmcp()
            fastmcp_state = "installed"
        except Exception:
            fastmcp_state = "not installed"
        return {
            "available": True,
            "transport": "in-process",
            "tools": list(_MCP_TOOL_NAMES),
            "detail": (
                f"Built-in MCP server · connected · {len(_MCP_TOOL_NAMES)} tools"
            ),
            "engine": f"in-process (fastmcp extra {fastmcp_state})",
        }

    @app.get(f"{API}/mcp/tools")
    async def mcp_tools():
        from okfsmith.mcp_server.server import BundleTools

        tools = []
        for name in _MCP_TOOL_NAMES:
            fn = getattr(BundleTools, name)
            doc = (fn.__doc__ or "").strip().splitlines()
            description = doc[0] if doc else ""
            params: dict[str, Any] = {}
            for pname, param in inspect.signature(fn).parameters.items():
                if pname == "self":
                    continue
                default = param.default
                params[pname] = {
                    "required": default is inspect.Parameter.empty,
                    "default": None if default is inspect.Parameter.empty else str(default),
                }
            tools.append({"name": name, "description": description, "params": params})
        return {"tools": tools}

    def _parse_preview_markdown(text: str) -> tuple[str, str | None, list[str]]:
        """Split a preview_write/dry-run markdown doc into summary/diff/warnings."""
        summary_lines: list[str] = []
        warnings: list[str] = []
        code: list[str] = []
        in_code = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "```markdown":
                in_code = True
                continue
            if in_code and stripped == "```":
                in_code = False
                continue
            if in_code:
                code.append(line)
                continue
            if stripped.startswith("## File content"):
                continue
            if stripped.startswith("- **"):
                plain = re.sub(r"\*+", "", stripped).strip("- ").strip()
                summary_lines.append(plain)
                if ("FAIL" in stripped or "already exists" in stripped
                        or "refuse" in stripped.lower()):
                    warnings.append(plain)
        summary = "\n".join(summary_lines[:8]) or text.splitlines()[0]
        diff = "\n".join(code).strip() or None
        return summary, diff, warnings

    @app.post(f"{API}/mcp/preview_write")
    async def mcp_preview_write(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise err("bad-json", "Request body must be JSON.", None, 400) from None
        body = body or {}
        bundle_id = body.get("bundle_id")
        operation = body.get("operation")
        concept_id = body.get("concept_id")
        payload = body.get("payload") or {}
        if not bundle_id:
            raise err("bad-request", "'bundle_id' is required.", None, 400)
        if operation not in ("create", "update"):
            raise err("bad-request", "'operation' must be 'create' or 'update'.", None, 400)
        if not isinstance(payload, dict):
            raise err("bad-request", "'payload' must be an object.", None, 400)
        bundle, _ = _load_bundle_or_404(bundle_id)
        tools = _bundle_tools(bundle)
        if operation == "create":
            title = (payload.get("title") or "").strip()
            body_text = (payload.get("body") or "").strip()
            if not title or not body_text:
                raise err("bad-request", "'payload.title' and 'payload.body' are required "
                          "for create.", None, 400)
            text = tools.preview_write_concept(
                title=title, body=body_text,
                sources=payload.get("sources"), links=payload.get("links"),
            )
        else:
            if not (concept_id or "").strip():
                raise err("bad-request", "'concept_id' is required for update.", None, 400)
            text = tools.update_concept(
                str(concept_id).strip(),
                title=payload.get("title"), body=payload.get("body"),
                sources=payload.get("sources"), links=payload.get("links"),
                downgrade_trust=bool(payload.get("downgrade_trust", False)),
                dry_run=True,
            )
        if text.startswith("Error:"):
            code = "trust_gate" if "human-reviewed" in text else "preview_refused"
            hint = ("The concept is human-reviewed: pass "
                    "'payload.downgrade_trust': true to proceed."
                    if code == "trust_gate"
                    else "Fix the input and preview again.")
            raise err(code, text[len("Error:"):].strip(), hint, 422)
        summary, diff, warnings = _parse_preview_markdown(text)
        preview_id = _jobs.new_id("preview-")
        with preview_lock:
            previews[preview_id] = {
                "bundle_id": bundle_id,
                "operation": operation,
                "concept_id": concept_id,
                "payload": payload,
                "created_at": time.monotonic(),
            }
        return {
            "preview_id": preview_id,
            "summary": summary,
            "diff": diff,
            "warnings": warnings,
        }

    @app.post(f"{API}/mcp/write")
    async def mcp_write(request: Request):
        try:
            body = await request.json()
        except Exception:
            raise err("bad-json", "Request body must be JSON.", None, 400) from None
        body = body or {}
        preview_id = body.get("preview_id")
        approved = body.get("approved")
        if approved is not True:
            raise err("not-approved", "'approved' must be true to apply a write.",
                      "Preview first with POST /api/v1/mcp/preview_write.", 422)
        with preview_lock:
            preview = previews.pop(preview_id, None)
        if preview is None:
            raise err("preview-not-found",
                      "Unknown or expired preview_id.",
                      "Previews expire after 30 minutes; preview again.", 404)
        if time.monotonic() - preview["created_at"] > 30 * 60:
            raise err("preview-expired", "Preview expired.",
                      "Preview again with POST /api/v1/mcp/preview_write.", 410)
        payload = preview["payload"]
        bundle, _ = _load_bundle_or_404(preview["bundle_id"])
        tools = _bundle_tools(bundle)
        if preview["operation"] == "create":
            result = tools.write_concept(
                title=str(payload.get("title") or "").strip(),
                body=str(payload.get("body") or "").strip(),
                sources=payload.get("sources"), links=payload.get("links"),
            )
        else:
            result = tools.update_concept(
                str(preview["concept_id"]).strip(),
                title=payload.get("title"), body=payload.get("body"),
                sources=payload.get("sources"), links=payload.get("links"),
                downgrade_trust=bool(payload.get("downgrade_trust", False)),
                dry_run=False,
            )
        if result.startswith("Error:"):
            raise err("write-refused", result[len("Error:"):].strip(),
                      "The write was refused by governance; nothing was written.", 422)
        # The real audit entry just appended by the write-back governance.
        from okfsmith.mcp_server.server import _read_audit

        entries = _read_audit(bundle, 5)
        audit_id = None
        if entries:
            entry = entries[-1]
            audit_id = hashlib.sha1(
                json.dumps(entry, sort_keys=True, default=str).encode()
            ).hexdigest()[:12]
        registry.refresh()
        return {"ok": True, "audit_id": audit_id}

    @app.get(f"{API}/mcp/audit_log")
    async def mcp_audit_log(
        limit: int = Query(default=50, ge=1, le=200),
        bundle_id: str | None = Query(default=None),
    ):
        from okfsmith.mcp_server.server import _read_audit

        if bundle_id is not None:
            bundle, _ = _load_bundle_or_404(bundle_id)
            bundles = [bundle]
        else:
            bundles = []
            for bid in sorted(registry.list()):
                try:
                    b, _ = _load_bundle_or_404(bid)
                    bundles.append(b)
                except HTTPException:
                    continue
        entries = []
        for bundle in bundles:
            for entry in _read_audit(bundle, limit):
                entries.append(
                    {
                        "ts": entry.get("ts"),
                        "actor": entry.get("actor"),
                        "action": entry.get("action"),
                        "concept_id": entry.get("concept_id"),
                        "detail": str(entry.get("summary") or ""),
                    }
                )
        entries.sort(key=lambda e: str(e.get("ts") or ""), reverse=True)
        return {"entries": entries[:limit]}

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    _SETTING_ENV = {
        "provider": "OKFSMITH_PROVIDER",
        "model": "OKFSMITH_MODEL",
        # GET reports this key as "base_url"; accept both spellings on PUT.
        "api_base": "OKFSMITH_API_BASE",
        "base_url": "OKFSMITH_API_BASE",
    }
    _SECRET_ENV = ("OKFSMITH_API_KEY", "AGENTROUTER_API_KEY", "OPENAI_API_KEY",
                   "ANTHROPIC_API_KEY")

    @app.get(f"{API}/settings")
    async def get_settings():
        from okfsmith.extract import llm as _llm

        try:
            cfg = _llm.resolve_llm_config()
            config = {
                "provider": cfg.provider,
                "base_url": cfg.base_url,
                "model": cfg.model,
            }
            default_provider = cfg.provider
        except Exception as exc:
            config = {"provider": None, "base_url": None, "model": None,
                      "error": str(exc)[:300]}
            default_provider = None
        providers = []
        for item in _provider_list():
            providers.append({**item, "is_default": item["id"] == default_provider})
        secrets_set = [name for name in _SECRET_ENV if os.environ.get(name)]
        return {"config": config, "providers": providers, "secrets_set": secrets_set}

    @app.put(f"{API}/settings")
    async def put_settings(request: Request):
        from okfsmith.extract.llm import PROVIDER_PRESETS

        try:
            body = await request.json()
        except Exception:
            raise err("bad-json", "Request body must be JSON.", None, 400) from None
        body = body or {}
        # Top-level keys are a closed contract: unknown fields are a 400,
        # never silently swallowed (a misspelled "default_provider" that
        # does nothing is worse than an error).
        allowed_top = {"config", "default_provider", "secrets"}
        unknown = [k for k in body if k not in allowed_top]
        if unknown:
            raise err("bad-request",
                      f"Unknown settings field(s): {', '.join(sorted(map(str, unknown)))}.",
                      f"Allowed: {', '.join(sorted(allowed_top))}.", 400)
        config = body.get("config") or {}
        default_provider = body.get("default_provider")
        secrets = body.get("secrets") or {}
        if not isinstance(config, dict) or not isinstance(secrets, dict):
            raise err("bad-request", "'config' and 'secrets' must be objects.", None, 400)
        if default_provider is not None:
            default_provider = str(default_provider).strip().lower()
            if default_provider not in PROVIDER_PRESETS:
                raise err("invalid-provider", f"Unknown provider '{default_provider}'.",
                          "Pick one from GET /api/v1/chat/providers.", 422)
            os.environ["OKFSMITH_PROVIDER"] = default_provider
        for key, value in config.items():
            env_name = _SETTING_ENV.get(str(key))
            if env_name is None:
                raise err("bad-request", f"Unknown config key '{key}'.",
                          f"Allowed: {', '.join(sorted(_SETTING_ENV))}.", 400)
            value = str(value or "").strip()
            if key == "provider":
                value = value.lower()
                if value not in PROVIDER_PRESETS:
                    raise err("invalid-provider", f"Unknown provider '{value}'.",
                              "Pick one from GET /api/v1/chat/providers.", 422)
            if value:
                os.environ[env_name] = value
            else:
                os.environ.pop(env_name, None)
        for key, value in secrets.items():
            if str(key) not in _SECRET_ENV:
                raise err("bad-request", f"Unknown secret key '{key}'.",
                          f"Allowed: {', '.join(_SECRET_ENV)}.", 400)
            value = str(value or "")
            if value:
                os.environ[str(key)] = value
            else:
                os.environ.pop(str(key), None)
        # Secrets are write-only: the response never echoes them.
        return {"ok": True}

    # ------------------------------------------------------------------
    # Activity
    # ------------------------------------------------------------------

    @app.get(f"{API}/activity")
    async def activity(limit: int = Query(default=20, ge=1, le=200)):
        items: list[dict[str, Any]] = []
        for bid in sorted(registry.list()):
            try:
                _, root = _load_bundle_or_404(bid)
                text = (root / "log.md").read_text(encoding="utf-8")
            except (HTTPException, OSError):
                continue
            current_date: str | None = None
            for line in text.splitlines():
                m = re.match(r"##\s+(\d{4}-\d{2}-\d{2})", line.strip())
                if m:
                    current_date = m.group(1)
                    continue
                m = re.match(r"\*\s+\*\*(.+?)\*\*:\s*(.*)", line.strip())
                if m and current_date:
                    # log.md entries are date-only: there is no time-of-day
                    # in the file, so emitting a midnight timestamp would
                    # fabricate a time the event never had. Mark them
                    # honestly and let the frontend render the plain date.
                    items.append(
                        {
                            "ts": f"{current_date}T00:00:00+00:00",
                            "date_only": True,
                            "kind": m.group(1).strip(),
                            "message": m.group(2).strip(),
                        }
                    )
        items.sort(key=lambda i: i["ts"], reverse=True)
        return {"items": items[:limit]}

    # ------------------------------------------------------------------
    # Static frontend (served last; must not shadow /api/*)
    # ------------------------------------------------------------------

    _static_dir = Path(__file__).resolve().parent / "static"

    @app.get("/")
    async def spa_index():
        index = _static_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(
            "<html><body style='background:#0d0f14;color:#e8e6e3;font-family:sans-serif'>"
            "<h1>okfsmith dashboard</h1>"
            "<p>API is live at <code>/api/v1</code>; the frontend bundle has not "
            "been built yet.</p></body></html>"
        )

    @app.get("/{path:path}")
    async def spa_static(path: str):
        if path.startswith("api/"):
            raise err("not-found", f"No route '/{path}'.", None, 404)
        candidate = (_static_dir / path).resolve()
        try:
            inside = candidate.is_relative_to(_static_dir.resolve())
        except AttributeError:  # py3.8 fallback, unreachable on 3.10+
            inside = str(candidate).startswith(str(_static_dir.resolve()))
        if inside and candidate.is_file():
            return FileResponse(candidate)
        index = _static_dir / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise err("not-found", f"No route '/{path}'.", None, 404)

    return app
