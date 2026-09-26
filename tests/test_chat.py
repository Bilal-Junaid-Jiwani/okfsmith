"""Tests for the interactive chat REPL (``okfsmith chat``).

Covers slash-command dispatch, retrieval ranking (shared with the MCP
``search`` tool), extractive vs LLM answering, follow-up context, citation
validation, graceful EOF/Ctrl-C handling, and a piped-stdin integration
test driving the real Typer command.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from okfsmith import __version__
from okfsmith.cli.app import app
from okfsmith.cli.chat import ChatSession, banner_rows, resolve_chat_backend
from okfsmith.core.bundle import Bundle
from okfsmith.extract.llm import LLMBackend, LLMResponseError
from okfsmith.mcp_server.server import rank_concepts

runner = CliRunner()


# ---------------------------------------------------------------------------
# fixtures
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
        "type: Guide\ntitle: Authentication\ndescription: How to authenticate with Bearer tokens.\nverified:\n  - by: human:alice\n",
        "# Authentication\n\nAll requests need a Bearer token in the Authorization "
        "header. Get a token from the dashboard under Settings.",
    )
    _write_concept(
        kb,
        "api/limits",
        "type: Guide\ntitle: Rate Limits\nverified:\n  - by: llm:critic\n",
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


class FakeBackend(LLMBackend):
    """Stub LLM backend that records prompts and returns canned replies."""

    name = "fake"

    def __init__(self, replies: list[str] | None = None) -> None:
        super().__init__("fake-model")
        self.replies = list(replies or ["canned answer"])
        self.seen: list[list[dict]] = []

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        self.seen.append(messages)
        return self.replies.pop(0)


# ---------------------------------------------------------------------------
# retrieval ranking (shared logic with the MCP search tool)
# ---------------------------------------------------------------------------


def test_rank_concepts_prefers_title_matches(bundle_dir: Path) -> None:
    bundle = Bundle.load(bundle_dir)
    ranked = rank_concepts(bundle, "authentication")
    assert ranked[0][1].id == "api/auth"


def test_rank_concepts_body_match(bundle_dir: Path) -> None:
    bundle = Bundle.load(bundle_dir)
    ranked = rank_concepts(bundle, "RFC 7807")
    assert [c.id for _, c in ranked] == ["guide/errors"]


def test_rank_concepts_empty_query(bundle_dir: Path) -> None:
    assert rank_concepts(Bundle.load(bundle_dir), "   ") == []


# ---------------------------------------------------------------------------
# slash commands
# ---------------------------------------------------------------------------


def test_unknown_slash_command_hint(session: ChatSession) -> None:
    assert session.handle_slash("/frobnicate") is None
    assert "Unknown command '/frobnicate'" in _out(session)


def test_slash_help_lists_commands(session: ChatSession) -> None:
    session.handle_slash("/help")
    out = _out(session)
    for cmd in ("/ingest", "/list", "/read", "/search", "/validate",
                "/graph", "/doctor", "/model", "/clear", "/exit"):
        assert cmd in out


def test_slash_names_case_insensitive(session: ChatSession) -> None:
    session.handle_slash("/HELP")
    assert "/ingest" in _out(session)


def test_slash_exit_and_quit(session: ChatSession) -> None:
    assert session.handle_slash("/exit") == "exit"
    assert session.handle_slash("/quit") == "exit"


def test_slash_read_missing_arg_hint(session: ChatSession) -> None:
    session.handle_slash("/read")
    assert "Usage:" in _out(session)


def test_slash_read_real_concept(session: ChatSession, capsys: pytest.CaptureFixture) -> None:
    # /read delegates to the CLI command, which prints via typer.echo to
    # real stdout (not the session console) — assert on captured stdout.
    session.handle_slash("/read api/auth")
    assert "Bearer token" in capsys.readouterr().out


def test_slash_read_missing_concept_no_crash(session: ChatSession) -> None:
    # The underlying CLI prints error [concept-not-found]; the REPL survives.
    session.handle_slash("/read no/such-thing")
    assert session.handle_slash("/help") is None  # still alive


def test_slash_clear_resets_conversation(session: ChatSession) -> None:
    session.answer("authentication")
    assert session.history, "expected recorded turns"
    session.handle_slash("/clear")
    assert session.history == []
    assert session.last_concepts == []
    assert "cleared" in _out(session)


def test_slash_model_reports_extractive(session: ChatSession) -> None:
    session.handle_slash("/model")
    assert "extractive mode" in _out(session)


def test_slash_ingest_reuses_real_ingest(session: ChatSession, tmp_path: Path) -> None:
    pytest.importorskip("okfsmith.parsers.ingest_no_llm", reason="parsers slice not installed")
    doc = tmp_path / "big.md"
    # Above the stub-prevention threshold so concepts are really created.
    doc.write_text("# Big Doc\n\n" + ("## Section\n\n" + "Content here. " * 60 + "\n\n") * 6)
    before = session.n_concepts()
    session.handle_slash(f"/ingest {doc}")
    assert session.n_concepts() > before
    # The session reloaded the bundle: the new concept is answerable.
    assert session.bundle.get("big/section") is not None


# ---------------------------------------------------------------------------
# answering: extractive mode
# ---------------------------------------------------------------------------


def test_extractive_answer_lists_concepts(session: ChatSession) -> None:
    text = session.answer("authentication")
    assert "api/auth" in text
    assert "Authentication" in text
    assert session.last_concepts, "expected follow-up context recorded"


def test_extractive_answer_honest_when_no_hits(session: ChatSession) -> None:
    text = session.answer("zzz-no-such-word")
    assert "couldn't find anything" in text
    assert session.last_concepts == []


# ---------------------------------------------------------------------------
# answering: LLM mode
# ---------------------------------------------------------------------------


def _llm_session(bundle_dir: Path, backend: LLMBackend) -> ChatSession:
    console = Console(file=io.StringIO(), width=100)
    return ChatSession(
        Bundle.load(bundle_dir), bundle_dir, backend=backend, console=console
    )


def test_llm_answer_grounded_and_cited(bundle_dir: Path) -> None:
    backend = FakeBackend(["Use a Bearer token. [api/auth]"])
    session = _llm_session(bundle_dir, backend)
    session.answer("how do I authenticate?")
    prompt = backend.seen[0]
    assert prompt[0]["role"] == "system"
    user_msg = prompt[-1]["content"]
    assert "api/auth" in user_msg  # retrieved context fed to the model
    assert "Bearer token" in user_msg
    out = session.console.file.getvalue()
    assert "Sources:" in out
    assert "[api/auth]" in out


def test_llm_answer_history_feeds_followups(bundle_dir: Path) -> None:
    backend = FakeBackend(["first", "second"])
    session = _llm_session(bundle_dir, backend)
    session.answer("authentication")
    session.answer("rate limits")
    second_prompt = backend.seen[1]
    roles = [m["role"] for m in second_prompt]
    assert roles.count("user") >= 2 and "assistant" in roles


def test_followup_falls_back_to_recent_context(bundle_dir: Path) -> None:
    """A follow-up matching nothing new reuses the previous question's concepts."""
    backend = FakeBackend(["Use a Bearer token. [api/auth]", "It goes in the header. [api/auth]"])
    session = _llm_session(bundle_dir, backend)
    session.answer("authentication")
    session.answer("aur iska source kya hai")  # Roman Urdu: matches nothing
    out = session.console.file.getvalue()
    assert "previous question's context" in out
    followup_prompt = backend.seen[1][-1]["content"]
    assert "api/auth" in followup_prompt


def test_citations_validated_against_bundle(bundle_dir: Path) -> None:
    """Hallucinated [made/up] citations are de-bracketed, never presented."""
    backend = FakeBackend(["Tokens go in the header [api/auth] and also [made/up]."])
    session = _llm_session(bundle_dir, backend)
    text = session.answer("authentication")
    assert "[api/auth]" in text
    assert "[made/up]" not in text
    assert "made/up" in text  # de-bracketed, not dropped silently
    sources_line = text.split("Sources:")[-1]
    assert "made/up" not in sources_line


def test_llm_error_falls_back_to_extractive(bundle_dir: Path) -> None:
    class BrokenBackend(LLMBackend):
        name = "broken"

        def chat(self, messages, *, temperature=0.0, max_tokens=4096) -> str:
            raise LLMResponseError("boom")

    session = _llm_session(bundle_dir, BrokenBackend("x"))
    text = session.answer("authentication")
    assert "api/auth" in text  # extractive table shown instead
    assert "hiccup" in session.console.file.getvalue()


# ---------------------------------------------------------------------------
# backend resolution
# ---------------------------------------------------------------------------


def test_resolve_chat_backend_no_llm() -> None:
    assert resolve_chat_backend(no_llm=True) is None


def test_resolve_chat_backend_unreachable_means_extractive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import okfsmith.extract.llm as llm_mod

    monkeypatch.setattr(llm_mod, "is_ollama_reachable", lambda *a, **k: False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # resolve_backend raises LLMUnavailableError when Ollama is unreachable
    # and no key is set → chat degrades to extractive mode, never raises.
    assert resolve_chat_backend() is None


# ---------------------------------------------------------------------------
# REPL loop: EOF / Ctrl-C / piped stdin
# ---------------------------------------------------------------------------


def _run_with_inputs(session: ChatSession, inputs: list) -> int:
    it = iter(inputs)

    def fake_input(prompt: str) -> str:
        item = next(it)
        if isinstance(item, BaseException):
            raise item
        return item

    return session.run(input_fn=fake_input)


def test_eof_exits_cleanly(session: ChatSession) -> None:
    code = _run_with_inputs(session, [EOFError()])
    assert code == 0
    assert "Goodbye" in _out(session)


def test_ctrl_c_cancels_input_and_session_survives(
    session: ChatSession, capsys: pytest.CaptureFixture
) -> None:
    code = _run_with_inputs(
        session, [KeyboardInterrupt(), "/list", "/exit"]
    )
    assert code == 0
    out = _out(session)
    assert "cancelled" in out
    # /list delegates to the CLI command (real stdout): the session survived.
    assert "api/auth" in capsys.readouterr().out


def test_ctrl_c_during_answer_does_not_kill_session(
    bundle_dir: Path,
) -> None:
    class FlakyBackend(FakeBackend):
        def chat(self, messages, *, temperature=0.0, max_tokens=4096) -> str:
            raise KeyboardInterrupt()

    session = _llm_session(bundle_dir, FlakyBackend())
    code = _run_with_inputs(session, ["authentication", "/exit"])
    assert code == 0
    assert "Cancelled." in session.console.file.getvalue()


def test_blank_lines_ignored(session: ChatSession) -> None:
    code = _run_with_inputs(session, ["", "   ", "/exit"])
    assert code == 0


def test_piped_stdin_integration(bundle_dir: Path, tmp_path: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive the real Typer command via piped stdin, like a shell user."""
    monkeypatch.setenv("OKFSMITH_HISTORY_FILE", str(tmp_path / "hist"))
    result = runner.invoke(
        app, ["chat", str(bundle_dir), "--no-llm"], input="/list\n/exit\n"
    )
    assert result.exit_code == 0, result.output
    assert "okfsmith chat" in result.output
    assert "api/auth" in result.output
    assert "Goodbye" in result.output


def test_piped_stdin_eof_without_exit(bundle_dir: Path, tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl-D (immediate EOF) exits 0 with a goodbye line."""
    monkeypatch.setenv("OKFSMITH_HISTORY_FILE", str(tmp_path / "hist"))
    result = runner.invoke(app, ["chat", str(bundle_dir), "--no-llm"], input="")
    assert result.exit_code == 0, result.output
    assert "Goodbye" in result.output


def test_model_and_no_llm_conflict(bundle_dir: Path) -> None:
    result = runner.invoke(
        app, ["chat", str(bundle_dir), "--model", "x", "--no-llm"]
    )
    assert result.exit_code == 2


def test_chat_requires_a_bundle(tmp_path: Path) -> None:
    result = runner.invoke(app, ["chat", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "bundle-not-found" in result.output or "not exist" in result.output


def test_chat_help(bundle_dir: Path) -> None:
    result = runner.invoke(app, ["chat", "--help"])
    assert result.exit_code == 0
    assert "natural language" in result.output


# ---------------------------------------------------------------------------
# startup banner UI (Qwen Code / Claude Code / Antigravity CLI aesthetic)
# ---------------------------------------------------------------------------


def test_banner_renders_ascii_logo_and_tips(session: ChatSession) -> None:
    session._print_banner()
    out = _out(session)
    rows = banner_rows()
    assert len(rows) == 5
    assert max(len(r) for r in rows) <= 80  # fits narrow terminals
    assert rows[0] in out  # plain ASCII when captured
    assert "Tips for getting started:" in out
    assert "1. Ask questions about your documents." in out
    assert "/help" in out
    assert "/ingest <path>" in out


def test_banner_shows_version_and_bundle_info(session: ChatSession) -> None:
    session._print_banner()
    out = _out(session)
    assert f"okfsmith chat v{__version__}" in out
    assert "kb" in out
    assert "3 concepts" in out
    assert "extractive mode" in out  # no backend in this fixture


def test_banner_info_line_with_llm_backend(bundle_dir: Path) -> None:
    session = _llm_session(bundle_dir, FakeBackend())
    session._print_banner()
    out = session.console.file.getvalue()
    assert "fake · fake-model" in out
    # extractive-mode notice must not appear when a backend is present
    assert "no LLM reachable" not in out


def test_banner_no_ansi_when_not_tty(session: ChatSession) -> None:
    session._print_banner()
    assert "\x1b[" not in _out(session)


def test_banner_gradient_on_tty_and_no_color_fallback(
    bundle_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")  # deterministic, not env-dependent
    console = Console(file=io.StringIO(), width=100, force_terminal=True)
    session = ChatSession(
        Bundle.load(bundle_dir), bundle_dir, backend=None, console=console
    )
    session._print_banner()
    assert "\x1b[" in session.console.file.getvalue()  # gradient ANSI emitted

    monkeypatch.setenv("NO_COLOR", "1")
    console2 = Console(file=io.StringIO(), width=100, force_terminal=True)
    session2 = ChatSession(
        Bundle.load(bundle_dir), bundle_dir, backend=None, console=console2
    )
    session2._print_banner()
    out2 = session2.console.file.getvalue()
    assert "\x1b[" not in out2  # NO_COLOR kills the gradient...
    assert banner_rows()[0] in out2  # ...but the plain ASCII logo remains


def test_prompt_plain_when_piped(session: ChatSession) -> None:
    assert session.prompt == "kb › "


def test_prompt_styled_on_tty(
    bundle_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")  # deterministic, not env-dependent
    console = Console(file=io.StringIO(), width=100, force_terminal=True)
    session = ChatSession(
        Bundle.load(bundle_dir), bundle_dir, backend=None, console=console
    )
    styled = session.prompt
    assert "\x1b[" in styled
    assert "kb" in styled and "›" in styled


def test_extractive_answer_has_marker(session: ChatSession) -> None:
    session.answer("authentication")
    assert "✦" in _out(session)


def test_llm_answer_has_marker(bundle_dir: Path) -> None:
    session = _llm_session(bundle_dir, FakeBackend(["canned [api/auth]"]))
    session.answer("authentication")
    assert "✦" in session.console.file.getvalue()
