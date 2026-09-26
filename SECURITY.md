# Security policy

## Reporting a vulnerability

Open a GitHub issue at
<https://github.com/Bilal-Junaid-Jiwani/okfsmith/issues> or contact the
maintainer privately. Please do not open public issues for vulnerabilities
that are being actively exploited — give us a chance to fix first.

## What we protect

- **Supply chain**: pinned dependency floors for known CVEs (see
  `pyproject.toml` comments, e.g. the markitdown floor for CVE-2025-11849
  and CVE-2025-64512).
- **Path safety**: link targets are contained inside the bundle root;
  zip extraction is ZipSlip-safe with member-count and size caps;
  `Bundle.load` skips symlinks; subdir traversal is rejected.
- **Output safety**: untrusted text (parser exceptions, concept titles,
  file paths) is escaped before reaching terminal or HTML output.
- **Secrets**: API keys are read from environment variables only, redacted
  from logs and error output, and never committed (see `.gitignore`).

## Known non-goals

okfsmith is a local-first CLI. It does not sandbox LLM backends, and the
MCP server trusts the local bundle directory it is pointed at. Do not serve
untrusted bundles over a network transport without your own access controls.
