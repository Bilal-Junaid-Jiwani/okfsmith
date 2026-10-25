"""Chat REPL ``/search`` temporal replay (0.11.0).

The CLI (``okfsmith search --as-of``), the MCP ``search`` tool's ``as_of``
parameter, and the dashboard ``GET /api/v1/search`` all replay validity
windows and supersession at an ISO-8601 instant through the shared BM25
engine — but the chat REPL's ``/search`` slash command never accepted the
flags, so it was the one search interface stuck at "now". These tests pin
the chat slice: ``/search <keywords> [--as-of <date>] [--include-superseded]``
forwards to the MCP ``search`` tool, which already enforces the tools'
"never an exception" contract for garbage ``--as-of`` values.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from okfsmith.cli.chat import ChatSession, _parse_search_arg
from okfsmith.core.bundle import Bundle


def _write_temporal_pair(kb: Path) -> None:
    """``policy-v1`` superseded by ``policy-v2`` (``valid_from`` 2026-10-20).

    Mirrors the CLI/MCP/dashboard temporal fixtures.
    """
    bundle = Bundle(kb)
    bundle.write_concept(
        "policy-v1",
        {"title": "Refund Policy v1", "type": "policy"},
        "The old refund policy allows returns within 14 days of purchase.",
    )
    bundle.write_concept(
        "policy-v2",
        {
            "title": "Refund Policy v2",
            "type": "policy",
            "supersedes": ["policy-v1"],
            "valid_from": "2026-10-20",
        },
        "The new refund policy allows returns within 30 days of purchase.",
    )


@pytest.fixture()
def session(tmp_path: Path) -> ChatSession:
    kb = tmp_path / "kb"
    _write_temporal_pair(kb)
    console = Console(file=io.StringIO(), width=100)
    return ChatSession(
        Bundle.load(kb), kb, backend=None, console=console
    )


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKFSMITH_HISTORY_FILE", str(tmp_path / "hist"))


def _out(session: ChatSession) -> str:
    return session.console.file.getvalue()  # type: ignore[union-attr]


class TestParseSearchArg:
    def test_plain_keywords_unchanged(self) -> None:
        assert _parse_search_arg("refund policy") == (
            "refund policy",
            None,
            False,
        )

    def test_flags_anywhere(self) -> None:
        assert _parse_search_arg(
            "--as-of 2026-10-01 refund --include-superseded"
        ) == ("refund", "2026-10-01", True)

    def test_as_of_equals_form(self) -> None:
        assert _parse_search_arg("refund --as-of=2026-10-01") == (
            "refund",
            "2026-10-01",
            False,
        )

    def test_quoted_phrase_survives(self) -> None:
        assert _parse_search_arg('"refund policy" --as-of 2026-10-01') == (
            "refund policy",
            "2026-10-01",
            False,
        )

    def test_flags_only_is_unusable(self) -> None:
        assert _parse_search_arg("--as-of 2026-10-01") == (None, None, None)

    def test_as_of_without_value_is_unusable(self) -> None:
        assert _parse_search_arg("refund --as-of") == (None, None, None)


class TestSlashSearchTemporal:
    def test_as_of_past_resurrects_superseded(self, session: ChatSession) -> None:
        # Before policy-v2's valid_from, the old policy was current — and
        # the legacy "now" pre-check must NOT swallow this resurrection.
        session.handle_slash("/search refund --as-of 2026-10-01")
        out = _out(session)
        assert "policy-v1" in out
        assert "as of 2026-10-01" in out
        assert "No concepts match" not in out

    def test_as_of_future_keeps_supersession(self, session: ChatSession) -> None:
        session.handle_slash("/search refund --as-of 2027-01-01")
        out = _out(session)
        assert "policy-v2" in out
        assert "policy-v1" not in out

    def test_include_superseded_shows_both(self, session: ChatSession) -> None:
        session.handle_slash("/search refund --include-superseded")
        out = _out(session)
        assert "policy-v1" in out
        assert "policy-v2" in out

    def test_default_still_hides_superseded(self, session: ChatSession) -> None:
        session.handle_slash("/search refund")
        out = _out(session)
        assert "policy-v2" in out
        assert "policy-v1" not in out

    def test_garbage_as_of_is_clean_error_not_exception(
        self, session: ChatSession
    ) -> None:
        assert session.handle_slash("/search refund --as-of not-a-date") is None
        assert "Error:" in _out(session)
        assert "not-a-date" in _out(session)

    def test_as_of_without_value_prints_usage(
        self, session: ChatSession
    ) -> None:
        session.handle_slash("/search refund --as-of")
        assert "Usage:" in _out(session)
        assert "/search <keywords>" in _out(session)

    def test_help_lists_temporal_flags(self, session: ChatSession) -> None:
        session.handle_slash("/help")
        assert "--as-of" in _out(session)
        assert "--include-superseded" in _out(session)
