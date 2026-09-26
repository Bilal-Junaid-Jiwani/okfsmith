"""Source-digest manifest for dedup.

Tracks which source files have already been ingested in
``<bundle>/.okfsmith/manifest.json``::

    {"sources": {"<sha256>": {"path": "...", "ingested_at": "..."}, ...}}

Helpers here create the directory/file on demand; reads never crash on a
missing or corrupt manifest (treated as empty).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

MANIFEST_DIRNAME = ".okfsmith"
MANIFEST_FILENAME = "manifest.json"


def sha256_of(path: str | Path) -> str:
    """Hex SHA-256 digest of a file, streamed (no full read into memory)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_path(bundle) -> Path:
    """Path of the manifest file for *bundle* (not created by this call)."""
    return Path(bundle.root) / MANIFEST_DIRNAME / MANIFEST_FILENAME


def load_manifest(bundle) -> dict:
    """Load the manifest mapping digest -> record; {} when absent/corrupt."""
    mp = manifest_path(bundle)
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        if not isinstance(exc, FileNotFoundError):
            log.warning("ignoring corrupt manifest %s: %s", mp, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    sources = data.get("sources")
    return sources if isinstance(sources, dict) else {}


def record_ingested(bundle, digest: str, source: str | Path) -> None:
    """Record *digest* as ingested (creates .okfsmith/ + manifest as needed)."""
    from okfsmith.core.spec import utc_now_iso

    mp = manifest_path(bundle)
    mp.parent.mkdir(parents=True, exist_ok=True)
    sources = load_manifest(bundle)
    # M8: source paths may hold undecodable bytes (surrogate escapes); the
    # manifest is UTF-8 JSON, so sanitize instead of crashing on write_text.
    path_text = str(source).encode("utf-8", errors="backslashreplace").decode("utf-8")
    sources[digest] = {"path": path_text, "ingested_at": utc_now_iso()}
    mp.write_text(
        json.dumps({"sources": sources}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def already_ingested(bundle, digest: str) -> bool:
    """True when *digest* is recorded in the bundle's manifest."""
    return digest in load_manifest(bundle)


__all__ = [
    "sha256_of",
    "manifest_path",
    "load_manifest",
    "record_ingested",
    "already_ingested",
    "MANIFEST_DIRNAME",
    "MANIFEST_FILENAME",
]
