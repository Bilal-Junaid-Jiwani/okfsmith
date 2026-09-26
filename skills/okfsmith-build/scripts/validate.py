#!/usr/bin/env python3
"""Standalone OKF v0.2 bundle validator for the okfsmith-build skill.

Runs from the skill directory alone — no installed dependencies, stdlib only.

Preferred path: if the ``okfsmith`` package is importable and exposes
``okfsmith.validate.check``, that engine is used (thin wrapper). Otherwise a
built-in minimal fallback enforces exactly the §11 conformance rules as error
checks E001–E004:

  E001  non-reserved .md file without a parseable YAML frontmatter block (§11.1)
  E002  frontmatter is not a mapping, or ``type`` missing/empty (§11.2)
  E003  ``index.md`` frontmatter violation (§11.3/§8/§12)
  E004  ``log.md`` with a ``## `` heading that is not a valid YYYY-MM-DD date

The fallback emits errors only (no advisory warnings); a bundle with errors
is non-conformant, otherwise it is conformant. Broken links, missing indexes,
unknown types/keys, and missing optional fields are never errors (spec §11).

Machine-readable JSON goes to stdout; exit code is 0 when conformant,
1 when errors were found, 2 on usage/IO failure.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Optional full engine: okfsmith.validate.check (if the package is installed)
# ---------------------------------------------------------------------------

def _try_full_engine(bundle_root: Path):
    """Return findings from the okfsmith package, or None if unavailable.

    Expected contract: ``okfsmith.validate.check(root)`` returns either a
    dict with ``errors``/``warnings`` lists, or a list of finding dicts
    (each with ``code``, ``file``, ``message``, ``spec`` and a severity).
    Anything else is treated as unavailable and the fallback runs instead.
    """
    try:
        from okfsmith.validate import check  # type: ignore
    except Exception:
        return None
    try:
        result = check(str(bundle_root))
    except Exception:
        return None
    errors: list[dict] = []
    warnings: list[dict] = []
    if isinstance(result, dict):
        errors = list(result.get("errors", []) or [])
        warnings = list(result.get("warnings", []) or [])
    elif isinstance(result, (list, tuple)):
        for f in result:
            if isinstance(f, dict) and f.get("code"):
                (errors if str(f.get("severity", "error")).startswith("err")
                 else warnings).append(f)
    else:
        return None
    return {"engine": "okfsmith.validate", "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# Minimal stdlib-only fallback: §11 hard rules E001–E004
# ---------------------------------------------------------------------------

class _YamlError(ValueError):
    """Raised when the frontmatter block is not parseable as YAML."""


def _split_key_value(line: str):
    """Split ``key: value`` on the first colon outside quotes/flow brackets.

    Returns ``(key, value)`` or None when the line is not a mapping entry.
    """
    depth = 0
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote is not None:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            if depth == 0:
                raise _YamlError("unbalanced flow bracket")
            depth -= 1
        elif ch == ":" and depth == 0:
            rest = line[i + 1 :]
            if rest == "" or rest[0] in " \t":
                return line[:i].strip(), rest.strip()
        i += 1
    return None


def _unquote(scalar: str):
    """Interpret a YAML scalar: quoted strings, nulls, else raw text."""
    s = scalar.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        inner = s[1:-1]
        if s[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    if s in ("", "~", "null", "Null", "NULL"):
        return None
    return s


def _child_indent(lines: list[str], pos: int, parent: int) -> int | None:
    """Indent of the first content line after ``pos`` (None if none)."""
    while pos < len(lines):
        raw = lines[pos]
        if raw.strip() and not raw.strip().startswith("#"):
            cur = len(raw) - len(raw.lstrip(" "))
            if "\t" in raw[:cur]:
                raise _YamlError("tab indentation is not allowed")
            return cur
        pos += 1
    return None


def _parse_block(lines: list[str], pos: int, indent: int):
    """Parse one block node starting at ``pos``; return (value, new_pos)."""
    value = None
    is_map: bool | None = None
    while pos < len(lines):
        raw = lines[pos]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            pos += 1
            continue
        cur = len(raw) - len(raw.lstrip(" "))
        if "\t" in raw[:cur]:
            raise _YamlError("tab indentation is not allowed")
        if cur < indent:
            break
        if cur > indent:
            raise _YamlError("unexpected indentation")
        if stripped.startswith("- ") or stripped == "-":
            if is_map:
                raise _YamlError("sequence item inside mapping")
            is_map = False
            item = stripped[1:].strip()
            seq = value if isinstance(value, list) else []
            if not item:
                child_indent = _child_indent(lines, pos + 1, indent)
                if child_indent is None or child_indent <= indent:
                    seq.append(None)
                    pos += 1
                else:
                    child, pos = _parse_block(lines, pos + 1, child_indent)
                    seq.append(child)
                value = seq
                continue
            item_kv = _split_key_value(item)
            if item_kv is None:
                # Plain scalar item; more-indented lines after it are an error.
                seq.append(_unquote(item))
                value = seq
                pos += 1
                continue
            # `- key: value` starts a mapping node; absorb deeper lines.
            node: dict = {}
            ikey, ival = item_kv
            if not ikey or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*",
                                            ikey):
                raise _YamlError(f"invalid key: {ikey!r}")
            node[ikey] = _unquote(ival) if ival else None
            child_indent = _child_indent(lines, pos + 1, indent)
            pos += 1
            if child_indent is not None and child_indent > indent:
                rest, pos = _parse_block(lines, pos, child_indent)
                if isinstance(rest, dict):
                    node.update(rest)
                elif rest is not None:
                    raise _YamlError("mixed sequence item content")
            seq.append(node)
            value = seq
            continue
        kv = _split_key_value(stripped)
        if kv is None:
            raise _YamlError(f"not a mapping entry: {stripped!r}")
        if is_map is False:
            raise _YamlError("mapping entry inside sequence")
        is_map = True
        key, val = kv
        if not key or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", key):
            raise _YamlError(f"invalid key: {key!r}")
        mapping = value if isinstance(value, dict) else {}
        if val in ("|", ">", "|+", "|-", ">+", ">-"):
            # Block scalar: consume the more-indented lines opaquely.
            child_indent = _child_indent(lines, pos + 1, indent)
            pos += 1
            buf = []
            while pos < len(lines):
                nxt = lines[pos]
                nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                if nxt.strip() and (child_indent is None
                                    or nxt_indent < child_indent):
                    break
                buf.append(nxt)
                pos += 1
            mapping[key] = "\n".join(buf)
            value = mapping
            continue
        if val == "":
            child_indent = _child_indent(lines, pos + 1, indent)
            if child_indent is None or child_indent <= indent:
                mapping[key] = None
                pos += 1
            else:
                child, pos = _parse_block(lines, pos + 1, child_indent)
                mapping[key] = child
            value = mapping
            continue
        mapping[key] = _unquote(val)
        value = mapping
        pos += 1
    return value, pos


def _parse_frontmatter_yaml(block: str):
    """Parse a frontmatter block; raise _YamlError on failure."""
    lines = block.splitlines()
    value, pos = _parse_block(lines, 0, 0)
    # Trailing garbage after a completed node is a parse error.
    while pos < len(lines):
        if lines[pos].strip() and not lines[pos].strip().startswith("#"):
            raise _YamlError("trailing content after frontmatter node")
        pos += 1
    return value


def _extract_block(text: str):
    """Return the frontmatter block text, or None when absent."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


_DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})$")


def _check_bundle(bundle_root: Path) -> tuple[list[dict], list[dict]]:
    errors: list[dict] = []
    warnings: list[dict] = []

    def err(code: str, rel: str, message: str, spec: str):
        errors.append(
            {"code": code, "file": rel, "message": message, "spec": spec}
        )

    md_files = sorted(
        p for p in bundle_root.rglob("*.md") if p.is_file()
    )
    for path in md_files:
        rel = path.relative_to(bundle_root).as_posix()
        name = path.name
        is_reserved = name in ("index.md", "log.md")  # case-sensitive, §3.1
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            err("E001", rel, f"cannot read file: {exc}", "§11.1")
            continue
        block = _extract_block(text)

        if is_reserved and name == "log.md":
            # E004: every `## ` heading must be a valid ISO calendar date.
            for line in text.splitlines():
                m = _DATE_RE.match(line)
                if line.startswith("## "):
                    if not m:
                        err("E004", rel,
                            f"log heading is not ISO YYYY-MM-DD: {line!r}",
                            "§9")
                        break
                    try:
                        datetime.date.fromisoformat(m.group(1))
                    except ValueError:
                        err("E004", rel,
                            f"log heading is not a valid calendar date: {line!r}",
                            "§9")
                        break
            continue

        if is_reserved and name == "index.md":
            # E003: frontmatter rules for index files (§8/§12).
            if block is not None:
                try:
                    data = _parse_frontmatter_yaml(block)
                except _YamlError as exc:
                    err("E003", rel,
                        f"index.md frontmatter does not parse: {exc}", "§8")
                    continue
                keys = set(data.keys()) if isinstance(data, dict) else None
                if path.parent == bundle_root:
                    if keys != {"okf_version"}:
                        err("E003", rel,
                            "bundle-root index.md frontmatter may carry "
                            "`okf_version` only", "§12")
                else:
                    err("E003", rel,
                        "non-root index.md must not carry frontmatter", "§8")
            continue

        # Concept document: §11 rules 1 and 2.
        if block is None:
            err("E001", rel, "no frontmatter block", "§11.1")
            continue
        try:
            data = _parse_frontmatter_yaml(block)
        except _YamlError as exc:
            err("E001", rel, f"frontmatter YAML does not parse: {exc}", "§4.1")
            continue
        if not isinstance(data, dict):
            err("E002", rel, "frontmatter is not a YAML mapping", "§11.2")
            continue
        ftype = data.get("type")
        # Non-string scalars are accepted and coerced (§4.1, locked A18);
        # only missing/null/empty/whitespace-only is an error.
        if ftype is None or (isinstance(ftype, str) and not ftype.strip()):
            missing = "type" not in data
            err("E002", rel,
                "frontmatter `type` is missing" if missing
                else "frontmatter `type` is empty",
                "§11.2")
    return errors, warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an OKF v0.2 bundle (errors E001–E004 per §11)."
    )
    parser.add_argument("bundle", help="path to the bundle root directory")
    args = parser.parse_args(argv)

    root = Path(args.bundle)
    if not root.is_dir():
        print(json.dumps({"error": f"not a directory: {args.bundle}"}),
              file=sys.stderr)
        return 2

    full = _try_full_engine(root)
    if full is None:
        errors, warnings = _check_bundle(root)
        full = {"engine": "minimal-fallback", "errors": errors,
                "warnings": warnings}

    report = {
        "bundle": str(root),
        "engine": full["engine"],
        "conformant": not full["errors"],
        "errors": full["errors"],
        "warnings": full["warnings"],
    }
    print(json.dumps(report, indent=2, sort_keys=False))
    return 0 if not full["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
