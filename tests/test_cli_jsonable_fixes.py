"""Regression tests for H13: ``read --format json`` on non-JSON-native frontmatter.

``_jsonable`` must convert ``bytes`` (e.g. ``!!binary`` YAML tags, which
PyYAML loads as ``bytes``) instead of letting ``json.dumps`` raise
``TypeError: Object of type bytes is not JSON serializable``.
"""

from __future__ import annotations

import base64
import datetime
import json
from pathlib import Path

from typer.testing import CliRunner

from okfsmith.cli.app import app
from okfsmith.cli.commands import _jsonable

runner = CliRunner()


def test_jsonable_bytes_utf8_decodes_to_str() -> None:
    assert _jsonable(b"hello") == "hello"


def test_jsonable_bytes_non_utf8_becomes_base64_marker() -> None:
    raw = b"\xff\xfe\xfd"
    out = _jsonable(raw)
    assert out == {"$binary": base64.b64encode(raw).decode("ascii")}
    json.dumps(out)  # the whole point: must be JSON-serializable


def test_jsonable_bytearray() -> None:
    assert _jsonable(bytearray(b"abc")) == "abc"


def test_jsonable_bytes_dict_key() -> None:
    assert _jsonable({b"k": b"v"}) == {"k": "v"}


def test_jsonable_datetime_still_iso() -> None:
    assert _jsonable(datetime.date(2026, 1, 2)) == "2026-01-02"


def test_jsonable_nested_bytes_json_roundtrip() -> None:
    payload = {"fm": {"blob": b"\x89PNG", "tags": [b"a"]}, "n": 1}
    json.dumps(_jsonable(payload))


def _write_bundle(tmp_path: Path, text: str) -> Path:
    bundle = tmp_path / "kb"
    bundle.mkdir()
    (bundle / "index.md").write_text("# Index\n", encoding="utf-8")
    (bundle / "weird.md").write_text(text, encoding="utf-8")
    return bundle


def test_read_json_binary_frontmatter_no_crash(tmp_path: Path) -> None:
    # QA H13 repro: ``!!binary`` bytes in frontmatter (UTF-8-decodable).
    bundle = _write_bundle(
        tmp_path, '---\ntitle: W\nblob: !!binary "aGVsbG8="\n---\n\nBody\n'
    )
    result = runner.invoke(app, ["read", str(bundle), "weird", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    payload = json.loads(result.output)
    assert payload["frontmatter"]["blob"] == "hello"


def test_read_json_nonutf8_binary_frontmatter_no_crash(tmp_path: Path) -> None:
    # Non-UTF-8 bytes must not crash either; they become a $binary marker.
    bundle = _write_bundle(tmp_path, "---\ntitle: T\ndata: !!binary |-\n  //79\n---\nbody\n")
    result = runner.invoke(app, ["read", str(bundle), "weird", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    payload = json.loads(result.output)
    assert set(payload["frontmatter"]["data"]) == {"$binary"}
