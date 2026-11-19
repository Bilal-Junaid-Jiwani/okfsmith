"""``chat --as-of`` temporal replay (0.33.0).

``search`` / ``list`` / ``read`` / ``graph`` / ``eval`` / ``validate``,
the MCP tools, and the dashboard chat session could already replay at a
past/future instant — but the interactive CLI chat answered every question
at *now*: its ``/search`` slash command had a per-query ``--as-of``, yet
the Q&A retrieval itself, ``/list``, and ``/read`` had no session replay
at all, so "what did the bundle say about refunds in October 2026?"
had no answer in a chat session. These tests pin the session replay:

- ``chat --as-of <date>`` replays answers: the top concept at a past
  instant is the one that was current *then*, not the one current now.
- the banner labels the replay instant, and the no-match message does
  too, so an answer never reads as the present.
- ``/list`` and ``/read`` evaluate statuses/badges at the session
  instant; ``/search`` defaults to it when it carries no ``--as-of``
  of its own, and a per-query ``--as-of`` still wins; ``/validate``
  and ``/graph`` replay their clock-dependent warnings / node
  statuses at it too, so the whole session replays, not just the
  answers.
- a garbage ``--as-of`` is a usage error (exit 2), like the other
  replay flags.
- without the flag, behaviour is unchanged: ``as_of`` defaults to
  ``None`` and the banner carries no replay line.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.cli.chat import ChatSession
from okfsmith.core.bundle import Bundle
from okfsmith.core.temporal import parse_temporal

runner = CliRunner()


def _plain(output: str) -> str:
    """Strip ANSI escapes and collapse whitespace in CLI output.

    On GitHub Actions Typer colorizes and wraps its rich error panel
    (it forces terminal output when ``GITHUB_ACTIONS`` is set), so a
    verbatim message substring never matches; the wording is what the
    test pins, not the wrapping.
    """
    return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", output).split())


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
def kb(tmp_path: Path) -> Path:
    path = tmp_path / "kb"
    _write_temporal_pair(path)
    return path


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OKFSMITH_HISTORY_FILE", str(tmp_path / "hist"))


def _session(kb: Path, as_of: str | None = None) -> ChatSession:
    console = Console(file=io.StringIO(), width=100)
    moment = parse_temporal(as_of) if as_of is not None else None
    return ChatSession(
        Bundle.load(kb), kb, backend=None, console=console, as_of=moment
    )


def _out(session: ChatSession) -> str:
    return session.console.file.getvalue()  # type: ignore[union-attr]


class TestAnswerReplay:
    def test_answer_at_now_prefers_current(self, kb: Path) -> None:
        session = _session(kb)
        assert session.as_of is None
        session.answer("refund policy")
        assert session.last_concepts[0].id == "policy-v2"

    def test_answer_replayed_prefers_then_current(self, kb: Path) -> None:
        # Before 2026-10-20 v2 was not yet valid, so v1 was current.
        session = _session(kb, "2026-10-01")
        session.answer("refund policy")
        assert session.last_concepts[0].id == "policy-v1"

    def test_answer_replayed_after_supersession(self, kb: Path) -> None:
        session = _session(kb, "2026-12-01")
        session.answer("refund policy")
        assert session.last_concepts[0].id == "policy-v2"


class TestBannerAndEmptyAnswer:
    def test_banner_labels_replay(self, kb: Path) -> None:
        session = _session(kb, "2026-10-01")
        session._print_banner()
        assert "Replaying as of 2026-10-01T00:00:00+00:00" in _out(session)

    def test_banner_plain_has_no_replay_line(self, kb: Path) -> None:
        session = _session(kb)
        session._print_banner()
        assert "Replaying as of" not in _out(session)

    def test_empty_answer_labels_replay(self, kb: Path) -> None:
        session = _session(kb, "2026-10-01")
        msg = session.answer("zzzqqq nothing matches this")
        assert "as of 2026-10-01T00:00:00+00:00" in msg

    def test_empty_answer_plain_has_no_replay_label(self, kb: Path) -> None:
        session = _session(kb)
        msg = session.answer("zzzqqq nothing matches this")
        assert "as of" not in msg


class TestSlashCommandsReplay:
    def test_list_replays_statuses(self, kb: Path) -> None:
        result = runner.invoke(
            app,
            ["chat", str(kb), "--no-llm", "--as-of", "2026-10-01"],
            input="/list\n/exit\n",
        )
        assert result.exit_code == 0, result.output
        # v2 was not yet valid then ("future"); nothing is "current" yet.
        # (v1 carries no temporal fields of its own, so its Valid cell is
        # "—" either way — the list's pre-existing "no noise" rule.)
        assert "future" in result.output
        assert "current" not in result.output

    def test_list_at_now_shows_current(self, kb: Path) -> None:
        result = runner.invoke(
            app, ["chat", str(kb), "--no-llm"], input="/list\n/exit\n"
        )
        assert result.exit_code == 0, result.output
        assert "current" in result.output
        assert "future" not in result.output

    def test_read_replays_badge(self, kb: Path) -> None:
        result = runner.invoke(
            app,
            ["chat", str(kb), "--no-llm", "--as-of", "2026-10-01"],
            input="/read policy-v1\n/exit\n",
        )
        assert result.exit_code == 0, result.output
        assert "superseded by policy-v2" not in result.output

    def test_read_at_now_shows_superseded_badge(self, kb: Path) -> None:
        result = runner.invoke(
            app, ["chat", str(kb), "--no-llm"], input="/read policy-v1\n/exit\n"
        )
        assert result.exit_code == 0, result.output
        assert "[temporal: superseded by policy-v2]" in result.output

    def test_search_defaults_to_session_replay(self, kb: Path) -> None:
        result = runner.invoke(
            app,
            ["chat", str(kb), "--no-llm", "--as-of", "2026-10-01"],
            input="/search refund\n/exit\n",
        )
        assert result.exit_code == 0, result.output
        assert "as of 2026-10-01" in result.output
        assert "policy-v1" in result.output

    def test_search_per_query_as_of_wins(self, kb: Path) -> None:
        result = runner.invoke(
            app,
            ["chat", str(kb), "--no-llm", "--as-of", "2026-10-01"],
            input="/search refund --as-of 2026-12-01\n/exit\n",
        )
        assert result.exit_code == 0, result.output
        assert "as of 2026-12-01" in result.output

    def test_validate_replays_clock_warnings(self, kb: Path) -> None:
        result = runner.invoke(
            app,
            ["chat", str(kb), "--no-llm", "--as-of", "2026-10-01"],
            input="/validate\n/exit\n",
        )
        assert result.exit_code == 0, result.output
        assert "Validated as of 2026-10-01" in result.output

    def test_validate_at_now_has_no_replay_label(self, kb: Path) -> None:
        result = runner.invoke(
            app, ["chat", str(kb), "--no-llm"], input="/validate\n/exit\n"
        )
        assert result.exit_code == 0, result.output
        assert "Validated as of" not in result.output

    def test_graph_replays_node_statuses(self, kb: Path) -> None:
        result = runner.invoke(
            app,
            ["chat", str(kb), "--no-llm", "--as-of", "2026-10-01"],
            input="/graph\n/exit\n",
        )
        assert result.exit_code == 0, result.output
        assert "policy-v2 (not yet valid)" in result.output
        assert "superseded by policy-v2" not in result.output

    def test_graph_at_now_shows_superseded(self, kb: Path) -> None:
        result = runner.invoke(
            app, ["chat", str(kb), "--no-llm"], input="/graph\n/exit\n"
        )
        assert result.exit_code == 0, result.output
        assert "policy-v1 (superseded by policy-v2)" in result.output
        assert "not yet valid" not in result.output

    def test_question_replays_via_cli(self, kb: Path) -> None:
        # A plain question (not a slash command) replays too: the
        # extractive table's first match is the then-current concept.
        result = runner.invoke(
            app,
            ["chat", str(kb), "--no-llm", "--as-of", "2026-10-01"],
            input="refund policy\n/exit\n",
        )
        assert result.exit_code == 0, result.output
        assert "Replaying as of 2026-10-01" in result.output
        first = result.output.index("policy-v1")
        second = result.output.index("policy-v2")
        assert first < second


class TestGarbageAsOf:
    def test_garbage_as_of_is_usage_error(self, kb: Path) -> None:
        result = runner.invoke(
            app, ["chat", str(kb), "--no-llm", "--as-of", "not-a-date"]
        )
        assert result.exit_code == 2, result.output
        assert "not an ISO-8601 date or datetime" in _plain(result.output)
