# Contributing

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest
```

## Ground rules

- **No fabricated claims.** Never add benchmarks, scores, stars, downloads,
  testimonials, or adoption numbers that weren't measured. Docs examples must
  come from real command output.
- **Tests for behavior changes.** CLI contract changes go in
  `tests/test_cli.py`; security fixes get a regression test in
  `tests/test_security.py`; viewer changes get one in `tests/test_viz.py`.
- **Stable errors.** New expected failures need a stable `error [CODE]:`
  code, a hint, and exit 1 (exit 2 for usage errors). Never let a traceback
  reach the user.
- **No secrets.** Never commit API keys, tokens, or credentials. `.gitignore`
  already excludes `.env`, `*.pem`, `*.key`, and `*secret*` patterns.
- **Keep the CLI grammar.** The bundle is the first positional argument
  everywhere. README and docs must match the real CLI exactly.
- **Conventional commits**: `feat:`, `fix:`, `docs:`, `test:`, `chore:`,
  `refactor:`, `security:`.

## Release process

1. Bump `__version__` in `src/okfsmith/__init__.py` (single source).
2. Update `CHANGELOG.md`.
3. Full test suite green, `python -m build`, `twine check`.
4. Publish to PyPI, verify the project page and artifacts, mirror to GitHub.
