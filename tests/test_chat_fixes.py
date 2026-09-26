"""Regression tests for chat QA fixes (M25, L21) and the search-engine swap.

- M25: ``/model provider <typo>`` must print a clean error and keep the
  REPL alive (previously the LLMError escaped ``run()`` and killed the
  session with exit 1).
- L21: a failed ``/ingest`` must not print "Bundle reloaded".
- Search: both ``rank_concepts`` call sites in chat.py now go through the
  ``okfsmith.search`` BM25 engine when installed (legacy scorer fallback
  until then), with the identical call shape ``(bundle, query, limit)`` and
  score-descending results.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

import okfsmith.cli.chat as chat_mod
from okfsmith.cli.chat import TOP_K, ChatSession, _search_bundle
from okfsmith.core.bundle import Bundle
from okfsmith.extract.llm import LLMError

# ---------------------------------------------------------------------------
# fixtures (same shape as tests/test_chat.py)
# ---------------------------------------------------------------------------


def _write_concept(root: Path, cid: str, frontmatter: str, body: str) -> None:
    path = root / f"{cid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")


@pytest.fixture()
def bundle_dir(tmp_path: Path) -> Path:
    """A tiny three-concept bundle on disk."""
    kb = tmp_path / "kb"
    _write_concept(
        kb,
        "api/auth",
        "type: Guide\ntitle: Authentication\n"
        "description: How to authenticate with Bearer tokens.\n",
        "# Authentication\n\nAll requests need a Bearer token in the Authorization "
        "header. Get a token from the dashboard under Settings.",
    )
    _write_concept(
        kb,
        "api/limits",
        "type: Guide\ntitle: Rate Limits\n",
        "# Rate Limits\n\nThe API allows 100 requests per minute per token. "
        "Exceeding the limit returns HTTP 429.",
    )
    _write_concept(
        kb,
        "guide/errors",
        "type: Guide\ntitle: Error Handling\n",
        "# Error Handling\n\nErrors use RFC 7807 problem details. Always log "
        "the request id from the X-Request-Id header.",
    )
    return kb


@pytest.fixture()
def session(bundle_dir: Path) -> ChatSession:
    """Extractive (no-LLM) session with captured output."""
    console = Console(file=io.StringIO(), width=100)
    return ChatSession(
        Bundle.load(bundle_dir), bundle_dir, backend=None, console=console
    )


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKFSMITH_HISTORY_FILE", str(tmp_path / "hist"))


def _out(session: ChatSession) -> str:
    return session.console.file.getvalue()  # type: ignore[union-attr]


def _run_with_inputs(session: ChatSession, inputs: list) -> int:
    it = iter(inputs)

    def fake_input(prompt: str) -> str:
        item = next(it)
        if isinstance(item, BaseException):
            raise item
        return item

    return session.run(input_fn=fake_input)


class _FakeEngine:
    """Stand-in for ``okfsmith.search.search_bundle``: records calls and
    returns BM25-style ``(score, Concept)`` tuples, score descending."""

    def __init__(self, hits: list) -> None:
        self.hits = hits
        self.calls: list[tuple] = []

    def __call__(self, bundle, query: str, limit: int):  # noqa: ANN001, ANN201
        self.calls.append((bundle, query, limit))
        return self.hits


# ---------------------------------------------------------------------------
# M25 — /model provider <typo> must not kill the REPL
# ---------------------------------------------------------------------------


def test_model_provider_typo_stays_in_session(session: ChatSession) -> None:
    # Unknown providers raise LLMError from pure name validation (no network),
    # which used to escape run() and kill the whole session.
    assert session.handle_slash("/model provider bogus") is None
    out = _out(session)
    assert "bad-llm-config" in out
    assert "Unknown provider 'bogus'" in out
    # The session is intact: backend untouched, provider not poisoned.
    assert session.backend is None
    assert session.llm_provider is None
    # ... and still answering slash commands afterwards.
    assert session.handle_slash("/help") is None
    assert "/ingest" in _out(session)


def test_model_provider_typo_during_run_exits_zero(session: ChatSession) -> None:
    code = _run_with_inputs(session, ["/model provider bogus", "/exit"])
    assert code == 0
    out = _out(session)
    assert "bad-llm-config" in out
    assert "Goodbye" in out  # readline history saved, session ended normally


def test_model_provider_typo_piped_stdin(
    bundle_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact QA repro: piped '/model provider bogus' must exit 0."""
    from typer.testing import CliRunner

    from okfsmith.cli.app import app

    monkeypatch.setenv("OKFSMITH_HISTORY_FILE", str(tmp_path / "hist"))
    result = CliRunner().invoke(
        app, ["chat", str(bundle_dir), "--no-llm"],
        input="/model provider bogus\n/exit\n",
    )
    assert result.exit_code == 0, result.output
    assert "bad-llm-config" in result.output
    assert "Unknown provider 'bogus'" in result.output
    assert "Goodbye" in result.output


def test_model_provider_switch_still_works(
    session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        chat_mod, "resolve_chat_backend", lambda **kwargs: None
    )
    session.handle_slash("/model provider groq")
    out = _out(session)
    assert "Switched provider to groq" in out
    assert session.llm_provider == "groq"
    assert session.backend is None  # extractive mode kept, no crash


def test_model_name_branch_llm_error_keeps_session(
    session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(**kwargs):
        raise LLMError("Unknown provider 'bogus'. Valid providers: x.")

    monkeypatch.setattr(chat_mod, "resolve_chat_backend", _boom)
    session.llm_provider = "groq"  # pretend a good switch happened earlier
    assert session.handle_slash("/model some-model") is None
    assert "bad-llm-config" in _out(session)
    # Failed switch changed nothing.
    assert session.model is None
    assert session.backend is None
    assert session.llm_provider == "groq"


# ---------------------------------------------------------------------------
# L21 — no "Bundle reloaded" after a failed /ingest
# ---------------------------------------------------------------------------


def test_failed_ingest_prints_no_reloaded(
    session: ChatSession, capsys: pytest.CaptureFixture
) -> None:
    before = session.n_concepts()
    session.handle_slash("/ingest /nonexistent/does-not-exist")
    # The CLI command reports its own error [CODE] (via real stdout/stderr,
    # like the other /-commands that delegate to Typer functions)...
    captured = capsys.readouterr()
    assert "source-not-found" in captured.out + captured.err
    # ...but the REPL must not claim a reload.
    assert "Bundle reloaded" not in _out(session)
    assert session.n_concepts() == before
    # Session survives.
    assert session.handle_slash("/help") is None


def test_successful_ingest_still_prints_reloaded(
    session: ChatSession, tmp_path: Path
) -> None:
    pytest.importorskip(
        "okfsmith.parsers.ingest_no_llm", reason="parsers slice not installed"
    )
    doc = tmp_path / "big.md"
    doc.write_text("# Big Doc\n\n" + ("## Section\n\n" + "Content here. " * 60 + "\n\n") * 6)
    before = session.n_concepts()
    session.handle_slash(f"/ingest {doc}")
    assert session.n_concepts() > before
    assert "Bundle reloaded" in _out(session)


# ---------------------------------------------------------------------------
# search-engine swap — both call sites route through the new engine
# ---------------------------------------------------------------------------


def test_answer_routes_through_search_engine(
    session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = session.bundle.get("api/auth")
    limits = session.bundle.get("api/limits")
    engine = _FakeEngine([(0.95, auth), (0.42, limits)])
    monkeypatch.setattr(chat_mod, "_search_bundle", engine)
    text = session.answer("how do I authenticate?")
    # Called with the same shape rank_concepts had: (bundle, query, limit).
    assert engine.calls == [(session.bundle, "how do I authenticate?", TOP_K)]
    # BM25 score-descending order is what the user sees.
    assert text.index("api/auth") < text.index("api/limits")


def test_answer_empty_engine_results(session: ChatSession,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _FakeEngine([])
    monkeypatch.setattr(chat_mod, "_search_bundle", engine)
    text = session.answer("zzz-no-such-word")
    assert engine.calls == [(session.bundle, "zzz-no-such-word", TOP_K)]
    assert "couldn't find anything" in text


def test_slash_search_routes_through_search_engine(
    session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = session.bundle.get("api/auth")
    engine = _FakeEngine([(0.95, auth)])
    monkeypatch.setattr(chat_mod, "_search_bundle", engine)
    session.handle_slash("/search bearer token")
    assert engine.calls == [(session.bundle, "bearer token", 10)]
    assert "No concepts match" not in _out(session)


def test_slash_search_no_hits_message(
    session: ChatSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _FakeEngine([])
    monkeypatch.setattr(chat_mod, "_search_bundle", engine)
    session.handle_slash("/search zzz-no-such-word")
    assert "No concepts match" in _out(session)


def test_search_engine_empty_query_returns_empty(bundle_dir: Path) -> None:
    # Holds for the legacy fallback AND the future BM25 engine (spec §1).
    bundle = Bundle.load(bundle_dir)
    assert _search_bundle(bundle, "   ", 5) == []
    assert _search_bundle(bundle, "", 5) == []
