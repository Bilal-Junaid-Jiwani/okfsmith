"""Interactive chat REPL over an OKF bundle (Claude Code / Gemini CLI style).

Ask questions in natural language; okfsmith retrieves the relevant concepts
and answers with citations. With an LLM backend (local Ollama by default)
answers are synthesized and grounded; without one the REPL stays useful in
*extractive mode*, showing the keyword-matched concepts themselves.

Slash commands expose bundle operations inline (``/help`` lists them).
The Typer command itself lives in :mod:`okfsmith.cli.commands`; this module
is the REPL engine so it can be driven programmatically (and tested) without
a terminal.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from okfsmith import __version__
from okfsmith.core.bundle import Bundle, Concept
from okfsmith.core.spec import trust_tier
from okfsmith.extract.llm import (
    LLMBackend,
    LLMError,
    LLMUnavailableError,
    key_status,
    resolve_backend,
)

try:
    import readline  # noqa: F401  (stdlib; absent on Windows without pyreadline)
except ImportError:  # pragma: no cover
    readline = None  # type: ignore[assignment]

#: Env var overriding where REPL line history is persisted (tests use this).
HISTORY_FILE_ENV_VAR = "OKFSMITH_HISTORY_FILE"

#: Default persistent history location.
DEFAULT_HISTORY_FILE = Path.home() / ".okfsmith" / "history"

#: How many top concepts feed an answer.
TOP_K = 5

#: How many recent turns (user+assistant pairs count as two) stay in LLM context.
HISTORY_TURNS = 6

#: Max body characters per concept stuffed into the LLM context window.
CONTEXT_BODY_CHARS = 1500

#: ``[concept/id]`` citations the model emits; validated against the bundle.
_CITATION_RE = re.compile(r"\[([A-Za-z0-9_][A-Za-z0-9_./-]*)\]")

SYSTEM_PROMPT = """\
You are okfsmith chat, answering questions about the user's OKF knowledge bundle.
Rules you must follow:
- Answer ONLY from the Context concepts below. Every factual claim carries a
  citation like [concept/id] pointing at the concept it came from.
- If the context does not contain the answer, say so plainly and suggest what
  to ingest or search — never invent facts, ids, or citations.
- The user may ask follow-ups ("tell me more", "what is its source", "aur detail
  do"); resolve pronouns against the recent conversation.
- Be concise. Reply in the user's language. Use markdown.
"""


def _history_file() -> Path:
    override = os.environ.get(HISTORY_FILE_ENV_VAR)
    return Path(override) if override else DEFAULT_HISTORY_FILE


# ---------------------------------------------------------------------------
# startup banner — Qwen Code / Claude Code / Antigravity CLI aesthetic
# ---------------------------------------------------------------------------

#: 5-row block-letter glyphs for the OKFSMITH startup logo.
_BANNER_GLYPHS: dict[str, list[str]] = {
    "O": [" ███ ", "█   █", "█   █", "█   █", " ███ "],
    "K": ["█   █", "█  █ ", "███  ", "█  █ ", "█   █"],
    "F": ["█████", "█    ", "████ ", "█    ", "█    "],
    "S": [" ████", "█    ", " ███ ", "    █", "████ "],
    "M": ["█   █", "██ ██", "█ █ █", "█   █", "█   █"],
    "I": ["█████", "  █  ", "  █  ", "  █  ", "█████"],
    "T": ["█████", "  █  ", "  █  ", "  █  ", "  █  "],
    "H": ["█   █", "█   █", "█████", "█   █", "█   █"],
}

#: Gradient anchors for the logo: yellow → orange → magenta (Qwen-style).
_GRADIENT_STOPS = ((255, 214, 10), (255, 123, 0), (255, 46, 158))

#: Accent color for the prompt chevron and answer markers.
ACCENT = "#ff7b00"

#: Marker printed before answers (Qwen-style), kept subtle.
ANSWER_MARKER = "✦"


def _color_enabled(console: Console) -> bool:
    """True only on a real terminal without NO_COLOR.

    Piped or captured output (tests, scripts) always gets plain ASCII so it
    stays deterministic and grep-friendly.
    """
    if os.environ.get("NO_COLOR"):
        return False
    return bool(console.is_terminal)


def print_styled(console: Console, styled: str) -> None:
    """Print rich-markup *styled* on a tty, plain text otherwise.

    Guarantees zero ANSI escapes in piped / NO_COLOR output (rich alone
    keeps ``dim``/``bold`` attributes under NO_COLOR, which would still
    pollute scripts and logs).
    """
    if _color_enabled(console):
        console.print(styled)
    else:
        # highlight=False: rich auto-highlights numbers/URLs in plain
        # strings, which would still emit ANSI on a terminal console.
        console.print(Text.from_markup(styled).plain, highlight=False)


def _gradient_color(x: int, width: int) -> str:
    """Hex color for logo column *x* along the yellow→orange→magenta ramp."""
    t = x / max(width - 1, 1)
    if t < 0.5:
        a, b, u = _GRADIENT_STOPS[0], _GRADIENT_STOPS[1], t * 2
    else:
        a, b, u = _GRADIENT_STOPS[1], _GRADIENT_STOPS[2], (t - 0.5) * 2
    r = round(a[0] + (b[0] - a[0]) * u)
    g = round(a[1] + (b[1] - a[1]) * u)
    bl = round(a[2] + (b[2] - a[2]) * u)
    return f"#{r:02x}{g:02x}{bl:02x}"


def banner_rows() -> list[str]:
    """The plain-ASCII rows of the OKFSMITH logo (no color codes)."""
    return [
        " ".join(_BANNER_GLYPHS[ch][i] for ch in "OKFSMITH") for i in range(5)
    ]


def print_banner_logo(console: Console) -> None:
    """Print the OKFSMITH logo; gradient on a tty, plain ASCII otherwise."""
    rows = banner_rows()
    width = max(len(r) for r in rows)
    color = _color_enabled(console)
    text = Text()
    for ri, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != " " and color:
                text.append(ch, style=_gradient_color(x, width))
            else:
                text.append(ch)
        if ri < len(rows) - 1:
            text.append("\n")
    console.print(text)


def _snippet(text: str, width: int = 300) -> str:
    """First meaningful chunk of *text*, whitespace-collapsed and truncated."""
    for line in text.splitlines():
        line = " ".join(line.split())
        if line and not line.startswith("#"):
            return line if len(line) <= width else line[: width - 1] + "…"
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= width else collapsed[: width - 1] + "…"


def _concept_sources(concept: Concept) -> list[str]:
    sources = concept.frontmatter.get("sources") or []
    if isinstance(sources, str):
        sources = [sources]
    return [str(s) for s in sources if str(s).strip()]


def resolve_chat_backend(
    *,
    model: str | None = None,
    provider: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    no_llm: bool = False,
) -> LLMBackend | None:
    """Pick the chat backend, or ``None`` for extractive mode.

    - ``no_llm=True`` → ``None`` (extractive mode, by choice).
    - Otherwise the standard :func:`resolve_backend` selection (explicit
      provider/base/key → env → Ollama → legacy ``OPENAI_API_KEY``).
    - :class:`LLMUnavailableError` → ``None``: chat always starts, LLM or not.
    - :class:`LLMError` for *configuration* mistakes (unknown provider) is
      **not** swallowed — a typo'd ``--provider`` must fail loudly, not
      silently degrade to extractive mode.
    """
    if no_llm:
        return None
    try:
        return resolve_backend(
            model=model, provider=provider, api_base=api_base, api_key=api_key
        )
    except LLMUnavailableError:
        return None
    except Exception as exc:
        if isinstance(exc, LLMError):
            raise
        return None


def _backend_status_line(backend: LLMBackend | None) -> str:
    if backend is None:
        return (
            "[yellow]extractive mode[/yellow] — no LLM reachable. Answers are "
            "keyword-matched concept excerpts. Start Ollama, set "
            "OKFSMITH_API_KEY + OKFSMITH_PROVIDER, or pass --provider, for "
            "generative answers."
        )
    provider = escape(getattr(backend, "provider", backend.name))
    has_key = bool(getattr(backend, "has_key", False))
    return (
        f"[green]{provider}[/green] · model {escape(backend.model)} · "
        f"key {key_status('x' if has_key else None)}"
    )


class ChatSession:
    """One interactive chat session over a loaded bundle."""

    def __init__(
        self,
        bundle: Bundle,
        bundle_root: Path,
        *,
        backend: LLMBackend | None = None,
        model: str | None = None,
        provider: str | None = None,
        api_base: str | None = None,
        api_key: str | None = None,
        console: Console | None = None,
    ) -> None:
        self.bundle = bundle
        self.bundle_root = bundle_root
        self.backend = backend
        self.model = model or (backend.model if backend is not None else None)
        #: Explicit LLM routing, re-applied by /ingest so a chat started with
        #: --provider/--api-base/--api-key ingests with the same backend.
        #: The raw key lives here only in memory, never on disk (the backend
        #: holds it too — same process, same lifetime).
        self.llm_provider = provider
        self.llm_api_base = api_base
        self.llm_api_key = api_key
        self.console = console or Console()
        #: Recent (role, content) turns fed back to the LLM as context.
        self.history: list[dict] = []
        #: Concepts behind the latest answer — follow-up fallback context.
        self.last_concepts: list[Concept] = []

    # -- session plumbing -------------------------------------------------
    @property
    def bundle_label(self) -> str:
        return self.bundle_root.name or str(self.bundle_root)

    @property
    def prompt(self) -> str:
        # Styled on a real terminal (colored bundle name + accent chevron);
        # plain text when piped/captured so output stays deterministic.
        if _color_enabled(self.console):
            with self.console.capture() as cap:
                self.console.print(
                    f"[cyan]{escape(self.bundle_label)}[/cyan]"
                    f" [bold {ACCENT}]›[/] ",
                    end="",
                )
            return cap.get()
        return f"{self.bundle_label} › "

    def n_concepts(self) -> int:
        return sum(1 for _ in self.bundle.iter_concepts())

    def reload_bundle(self) -> None:
        """Re-read the bundle from disk (after /ingest adds concepts)."""
        self.bundle = Bundle.load(self.bundle_root)

    def _backend_info(self) -> str:
        """Compact ``provider · model`` (or ``extractive mode``) for the
        Antigravity-style info line under the logo."""
        if self.backend is None:
            return "extractive mode"
        provider = escape(getattr(self.backend, "provider", self.backend.name))
        return f"{provider} · {escape(self.backend.model)}"

    def _print_banner(self) -> None:
        c = self.console
        print_banner_logo(c)
        print_styled(c, f"[dim]okfsmith chat v{escape(__version__)}[/dim]")
        print_styled(
            c,
            f"Bundle: [cyan]{escape(self.bundle_label)}[/cyan] "
            f"([cyan]{self.n_concepts()} concepts[/cyan]) · {self._backend_info()}",
        )
        if self.backend is None:
            print_styled(
                c,
                "[dim]Extractive mode — no LLM reachable. Answers are "
                "keyword-matched excerpts. Start Ollama, set OKFSMITH_API_KEY "
                "+ OKFSMITH_PROVIDER, or pass --provider, for generative "
                "answers.[/dim]",
            )
        c.print()
        print_styled(c, "[bold]Tips for getting started:[/bold]")
        print_styled(c, "  [dim]1.[/dim] Ask questions about your documents.")
        print_styled(c, "  [dim]2.[/dim] Type [cyan]/help[/cyan] for chat commands.")
        print_styled(
            c,
            "  [dim]3.[/dim] Type [cyan]/ingest <path>[/cyan] to add more "
            "documents.",
        )
        c.print()

    def _setup_readline(self) -> None:
        if readline is None:  # pragma: no cover
            return
        try:
            hist = _history_file()
            hist.parent.mkdir(parents=True, exist_ok=True)
            if hist.exists():
                readline.read_history_file(str(hist))
            readline.set_history_length(500)
            readline.set_completer(_slash_completer)
            readline.parse_and_bind("tab: complete")
        except OSError:
            pass

    def _save_history(self) -> None:
        if readline is None:  # pragma: no cover
            return
        try:
            readline.write_history_file(str(_history_file()))
        except OSError:
            pass

    # -- answering --------------------------------------------------------
    def answer(self, question: str) -> str:
        """Answer *question*; returns the text shown (useful for tests)."""
        from okfsmith.mcp_server.server import rank_concepts

        hits = rank_concepts(self.bundle, question, TOP_K)
        fallback = False
        if not hits and self.last_concepts:
            # Follow-up ("tell me more", "uska source kya hai"): the new
            # question matches nothing, so resolve against recent context.
            hits = [(0, c) for c in self.last_concepts[:TOP_K]]
            fallback = True
        concepts = [c for _, c in hits]
        if not concepts:
            msg = (
                f"I couldn't find anything in '{self.bundle_label}' about that. "
                "Try /search with broader keywords, /list to browse, or "
                "/ingest to add the missing material."
            )
            self.console.print(f"[yellow]{escape(msg)}[/yellow]")
            return msg
        if fallback:
            self.console.print(
                "[dim](no new matches — answering from the previous question's "
                "context)[/dim]"
            )
        if self.backend is None:
            return self._answer_extractive(question, concepts)
        return self._answer_llm(question, concepts)

    def _context_block(self, concept: Concept) -> str:
        fm = concept.frontmatter
        body = concept.body.strip()
        if len(body) > CONTEXT_BODY_CHARS:
            body = body[: CONTEXT_BODY_CHARS - 1] + "…"
        return (
            f"[{concept.id}]\n"
            f"title: {fm.get('title', concept.id)}\n"
            f"type: {fm.get('type', '?')} · trust: {trust_tier(fm)}\n"
            f"{body}"
        )

    def _answer_llm(self, question: str, concepts: list[Concept]) -> str:
        context = "\n\n---\n\n".join(self._context_block(c) for c in concepts)
        messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + self.history[-HISTORY_TURNS:]
            + [
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                }
            ]
        )
        assert self.backend is not None
        try:
            with self.console.status("[cyan]thinking…[/cyan]", spinner="dots"):
                text = self.backend.chat(messages, temperature=0.2)
        except (LLMError, Exception) as exc:  # noqa: BLE001 — never die mid-chat
            self.console.print(
                f"[yellow]LLM hiccup ({escape(str(exc))}) — "
                "showing extractive matches instead.[/yellow]"
            )
            return self._answer_extractive(question, concepts)
        text = self._validate_citations(text, concepts)
        print_styled(self.console, f"[dim {ACCENT}]{ANSWER_MARKER}[/]")
        self.console.print(Markdown(text))
        self._record_turn(question, concepts, text)
        return text

    def _validate_citations(self, text: str, concepts: list[Concept]) -> str:
        """Keep only citations that name real bundle concepts.

        A model that invents ``[made/up]`` must never have it presented as a
        source: unknown ids are de-bracketed in the text, and the Sources
        footer lists only ids that exist in the bundle.
        """
        valid_ids = {c.id for c in self.bundle.iter_concepts()}
        cited: list[str] = []

        def _fix(match: re.Match) -> str:
            cid = match.group(1)
            if cid in valid_ids:
                if cid not in cited:
                    cited.append(cid)
                return match.group(0)
            return cid  # de-bracket hallucinated citations

        text = _CITATION_RE.sub(_fix, text)
        if cited:
            text = text.rstrip() + "\n\n*Sources: " + ", ".join(
                f"[{c}]" for c in cited
            ) + "*"
        return text

    def _answer_extractive(self, question: str, concepts: list[Concept]) -> str:
        table = Table(
            title=Text.from_markup(
                f"[{ACCENT}]{ANSWER_MARKER}[/] Matches for: {escape(question)}"
            )
        )
        table.add_column("Concept", no_wrap=True, overflow="fold")
        table.add_column("Trust tier")
        table.add_column("Excerpt")
        shown: list[str] = []
        for concept in concepts:
            fm = concept.frontmatter
            title = str(fm.get("title") or concept.id)
            excerpt = _snippet(
                str(fm.get("description") or "") or concept.body
            )
            cell = escape(excerpt)
            sources = _concept_sources(concept)
            if sources:
                cell += f"  [dim](sources: {len(sources)})[/dim]"
            table.add_row(
                f"[bold]{escape(concept.id)}[/bold]\n{escape(title)}",
                escape(trust_tier(fm)),
                cell,
            )
            shown.append(f"{concept.id} — {title}")
        self.console.print(table)
        self.console.print(
            "[dim]Extractive mode: excerpts above, no generative summary. "
            "Use /read <id> for the full concept.[/dim]"
        )
        self._record_turn(question, concepts, "\n".join(shown))
        return "\n".join(shown)

    def _record_turn(
        self, question: str, concepts: list[Concept], answer_text: str
    ) -> None:
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": answer_text})
        self.last_concepts = list(concepts)

    # -- slash commands ---------------------------------------------------
    def handle_slash(self, line: str) -> str | None:
        """Handle a ``/command`` line. Returns ``"exit"`` to quit the REPL."""
        name, _, arg = line[1:].strip().partition(" ")
        name, arg = name.lower(), arg.strip()
        handler = _SLASH.get(name)
        if handler is None:
            self.console.print(
                f"[yellow]Unknown command '/{escape(name)}'.[/yellow] "
                "Type [bold]/help[/bold] to see available commands."
            )
            return None
        return handler(self, arg)

    # -- main loop ----------------------------------------------------------
    def run(self, input_fn: Callable[[str], str] | None = None) -> int:
        """Run the REPL until /exit or EOF. Returns the process exit code."""
        self._print_banner()
        self._setup_readline()
        read = input_fn if input_fn is not None else (lambda p: input(p))
        while True:
            try:
                line = read(self.prompt)
            except EOFError:
                break  # Ctrl-D: goodbye below
            except KeyboardInterrupt:
                # Ctrl-C cancels the current input line; the session survives.
                self.console.print()
                self.console.print(
                    "[dim]Input cancelled — type /exit to quit.[/dim]"
                )
                continue
            if not line.strip():
                continue
            try:
                if line.strip().startswith("/"):
                    if self.handle_slash(line.strip()) == "exit":
                        break
                else:
                    self.answer(line.strip())
            except KeyboardInterrupt:
                self.console.print("\n[dim]Cancelled.[/dim]")
            except EOFError:
                break
        self._save_history()
        self.console.print("[dim]Goodbye — your bundle is untouched.[/dim]")
        return 0


# ---------------------------------------------------------------------------
# slash command implementations
# ---------------------------------------------------------------------------


def _needs_arg(session: ChatSession, arg: str, usage: str) -> bool:
    if arg:
        return False
    session.console.print(f"[yellow]Usage:[/yellow] {usage}")
    return True


def _run_cli(session: ChatSession, fn, *args, **kwargs) -> None:
    """Call a Typer command function directly; failed commands print their
    own ``error [CODE]`` and exit — catch that so the REPL survives."""
    import typer

    try:
        fn(*args, **kwargs)
    except typer.Exit:
        pass


def _slash_help(session: ChatSession, _arg: str) -> None:
    table = Table(title="Chat commands")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("What it does")
    for name, _fn, blurb in _SLASH_HELP:
        table.add_row(f"/{name}", blurb)
    session.console.print(table)
    session.console.print(
        "[dim]Anything else you type is a question about the bundle.[/dim]"
    )


def _slash_ingest(session: ChatSession, arg: str) -> None:
    if _needs_arg(session, arg, "/ingest <file-or-dir> [--recursive]"):
        return
    from okfsmith.cli import commands as _cmd

    parts = arg.split()
    recursive = False
    if "--recursive" in parts:
        recursive = True
        parts.remove("--recursive")
    if not parts:
        session.console.print("[yellow]Usage:[/yellow] /ingest <file-or-dir> [--recursive]")
        return
    _run_cli(
        session,
        _cmd.ingest,
        session.bundle_root,
        [Path(p) for p in parts],
        model=session.model,
        provider=session.llm_provider,
        api_base=session.llm_api_base,
        api_key=session.llm_api_key,
        no_llm=session.backend is None,
        recursive=recursive,
        quiet=False,
        dry_run=False,
    )
    session.reload_bundle()
    session.console.print(
        f"[dim]Bundle reloaded — {session.n_concepts()} concepts now.[/dim]"
    )


def _slash_list(session: ChatSession, _arg: str) -> None:
    from okfsmith.cli import commands as _cmd

    # Pass every option explicitly: calling a Typer command function
    # directly leaves OptionInfo sentinels in place of unset options.
    _run_cli(
        session,
        _cmd.list_concepts,
        session.bundle_root,
        None,
        None,
        _cmd.ValidateFormat.text,
    )


def _slash_read(session: ChatSession, arg: str) -> None:
    if _needs_arg(session, arg, "/read <concept-id>"):
        return
    from okfsmith.cli import commands as _cmd

    _run_cli(
        session, _cmd.read, session.bundle_root, arg, _cmd.ValidateFormat.text
    )


def _slash_search(session: ChatSession, arg: str) -> None:
    if _needs_arg(session, arg, "/search <keywords>"):
        return
    from okfsmith.mcp_server.server import BundleTools, rank_concepts

    hits = rank_concepts(session.bundle, arg, 10)
    if not hits:
        session.console.print(
            f"[yellow]No concepts match {escape(arg)!r}.[/yellow]"
        )
        return
    tools = BundleTools(session.bundle)
    session.console.print(Markdown(tools.search(arg, limit=10)))


def _slash_validate(session: ChatSession, _arg: str) -> None:
    from okfsmith.cli import commands as _cmd

    _run_cli(
        session, _cmd.validate, session.bundle_root, False, _cmd.ValidateFormat.text
    )


def _slash_graph(session: ChatSession, _arg: str) -> None:
    from okfsmith.cli import commands as _cmd

    _run_cli(
        session, _cmd.graph, session.bundle_root, _cmd.GraphFormat.text, None
    )


def _slash_doctor(session: ChatSession, _arg: str) -> None:
    from okfsmith.cli import commands as _cmd

    _run_cli(session, _cmd.doctor)


def _slash_model(session: ChatSession, arg: str) -> None:
    if not arg:
        if session.backend is None:
            session.console.print(
                "[yellow]No LLM backend[/yellow] (extractive mode). "
                "Start Ollama, set OKFSMITH_API_KEY + OKFSMITH_PROVIDER "
                "(e.g. openrouter, groq, mistral, deepseek, together, "
                "fireworks, agentrouter, xai, gemini), or: /model provider groq"
            )
        else:
            backend = session.backend
            base = escape(getattr(backend, "base_url", "?") or "?")
            has_key = bool(getattr(backend, "has_key", False))
            session.console.print(
                f"Backend: [green]{escape(getattr(backend, 'provider', backend.name))}[/green]\n"
                f"  base URL: {base}\n"
                f"  model: {escape(backend.model)}\n"
                f"  api key: {key_status('x' if has_key else None)}\n"
                "[dim]Switch model: /model <name> · switch provider: "
                "/model provider <name>[/dim]"
            )
        return
    parts = arg.split()
    if parts[0].lower() == "provider":
        if len(parts) < 2:
            session.console.print(
                "[yellow]Usage:[/yellow] /model provider <name> "
                "(groq, mistral, deepseek, openrouter, together, xai, "
                "gemini, openai, ollama)"
            )
            return
        name = parts[1].lower()
        session.llm_provider = name
        # LLMError (unknown provider) propagates: a typo must fail loudly,
        # not silently degrade to extractive mode.
        session.backend = resolve_chat_backend(
            model=session.model,
            provider=name,
            api_base=session.llm_api_base,
            api_key=session.llm_api_key,
        )
        session.console.print(
            f"Switched provider to {escape(name)} — "
            f"{_backend_status_line(session.backend)}"
        )
        return
    session.model = arg
    session.backend = resolve_chat_backend(
        model=arg,
        provider=session.llm_provider,
        api_base=session.llm_api_base,
        api_key=session.llm_api_key,
    )
    session.console.print(
        f"Switched model to {escape(arg)} — {_backend_status_line(session.backend)}"
    )


def _slash_clear(session: ChatSession, _arg: str) -> None:
    session.history.clear()
    session.last_concepts.clear()
    session.console.clear()
    session.console.print(
        "[dim]Screen and conversation history cleared "
        "(line-editing history kept).[/dim]"
    )


def _slash_exit(session: ChatSession, _arg: str) -> str:
    return "exit"


_SLASH: dict[str, Callable[[ChatSession, str], str | None]] = {
    "help": _slash_help,
    "ingest": _slash_ingest,
    "list": _slash_list,
    "read": _slash_read,
    "search": _slash_search,
    "validate": _slash_validate,
    "graph": _slash_graph,
    "doctor": _slash_doctor,
    "model": _slash_model,
    "clear": _slash_clear,
    "exit": _slash_exit,
    "quit": _slash_exit,
}

_SLASH_HELP: list[tuple[str, Callable, str]] = [
    ("help", _slash_help, "Show this table."),
    ("ingest <path> [--recursive]", _slash_ingest, "Ingest a file or directory into the bundle."),
    ("list", _slash_list, "List concepts in the bundle."),
    ("read <id>", _slash_read, "Print a concept in full."),
    ("search <keywords>", _slash_search, "Keyword-search concepts."),
    ("validate", _slash_validate, "Validate the bundle against OKF v0.2."),
    ("graph", _slash_graph, "Show the concept link graph."),
    ("doctor", _slash_doctor, "Check the environment."),
    ("model [name | provider <name>]", _slash_model, "Show or switch the LLM backend/model/provider."),
    ("clear", _slash_clear, "Clear the screen and conversation history."),
    ("exit", _slash_exit, "Leave the chat (/quit works too)."),
]


def _slash_completer(text: str, state: int) -> str | None:
    """readline tab-completion for slash commands."""
    if readline is None:  # pragma: no cover
        return None
    buf = readline.get_line_buffer()
    if not buf.startswith("/"):
        return None
    options = ["/" + name for name in _SLASH if ("/" + name).startswith(buf)]
    return options[state] if state < len(options) else None


# ---------------------------------------------------------------------------
# entry point (called by the Typer command in okfsmith.cli.commands)
# ---------------------------------------------------------------------------


def run_chat(
    bundle_root: Path,
    *,
    model: str | None,
    no_llm: bool,
    provider: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> int:
    """Load the bundle, resolve the backend, and run the REPL."""
    bundle = Bundle.load(bundle_root)
    # Unknown providers fail loudly here (LLMError), not inside the REPL.
    backend = resolve_chat_backend(
        model=model, provider=provider, api_base=api_base, api_key=api_key,
        no_llm=no_llm,
    )
    session = ChatSession(
        bundle,
        bundle_root,
        backend=backend,
        model=model,
        provider=provider,
        api_base=api_base,
        api_key=api_key,
    )
    return session.run()
