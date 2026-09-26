# Install

## Requirements

- Python 3.10 or newer
- `pip` (or `pipx` / `uvx` for isolated installs)

## From PyPI

```bash
pip install okfsmith
```

Optional extras (install only what you need):

```bash
pip install "okfsmith[office]"   # DOCX / PPTX / XLSX via MarkItDown
pip install "okfsmith[mcp]"      # serve bundles over MCP (FastMCP)
pip install "okfsmith[ocr]"      # Docling OCR sidecar for scanned PDFs
pip install "okfsmith[test]"     # pytest, for running the test suite
```

Isolated installs:

```bash
pipx install "okfsmith[office,mcp]"
uvx --with "okfsmith[office]" okfsmith -- --help
```

## Check your setup

```bash
okfsmith doctor
```

`doctor` reports each dependency, extra, Ollama reachability, and temp-dir
writability as OK / MISSING / WARN. A missing extra tells you the exact
`pip install "okfsmith[<extra>]"` command to fix it.

## Shell completion

Static scripts ship in `completions/` (also in the sdist):

```bash
# bash — add to ~/.bashrc
source /path/to/okfsmith/completions/okfsmith.bash

# zsh — add to ~/.zshrc
source /path/to/okfsmith/completions/okfsmith.zsh

# fish — add to ~/.config/fish/config.fish
source /path/to/okfsmith/completions/okfsmith.fish
```

Or generate on the fly, or install permanently:

```bash
eval "$(okfsmith --show-completion bash)"   # bash/zsh/fish
okfsmith --install-completion               # writes to your shell rc file
```

## Uninstall

```bash
pip uninstall okfsmith
# or: pipx uninstall okfsmith
```

Uninstalling never touches your bundles — they are plain directories of
markdown.
