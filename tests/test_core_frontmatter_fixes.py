"""Regression tests for frontmatter QA fixes: C4, C9, H4, M24, L22, M28."""

import datetime
import time

from okfsmith.core.frontmatter import parse_frontmatter, serialize_frontmatter

# --- C4: non-mapping / invalid YAML frontmatter is preserved, not dropped ---


def test_c4_list_frontmatter_kept_as_body():
    raw = "---\n- just\n- a\n- list\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert data == {}
    assert body == raw  # the whole text is kept, frontmatter lines included


def test_c4_scalar_frontmatter_kept_as_body():
    raw = "---\njust a string\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert data == {} and body == raw


def test_c4_invalid_yaml_kept_as_body():
    # Tab-indented YAML is invalid; the lines must survive, not be dropped.
    raw = "---\n\tkey: v\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert data == {} and body == raw


def test_c4_load_resave_does_not_delete_frontmatter_lines():
    raw = "---\n- a\n- b\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    resaved = serialize_frontmatter(data, body)
    assert "- a\n" in resaved and "- b\n" in resaved
    # And the resaved document is a stable fixed point: re-parsing it keeps
    # the original lines intact instead of degrading further.
    data2, body2 = parse_frontmatter(resaved)
    resaved2 = serialize_frontmatter(data2, body2)
    assert "- a\n" in resaved2 and "- b\n" in resaved2


def test_c4_empty_frontmatter_still_parses_to_empty_mapping():
    data, body = parse_frontmatter("---\n---\nbody\n")
    assert data == {} and body == "body\n"


def test_c4_mapping_roundtrip_unaffected():
    fm = {"type": "Note", "title": "T"}
    data, body = parse_frontmatter(serialize_frontmatter(fm, "body\n"))
    assert data == fm and body == "body\n"


# --- C9: impossible timestamps degrade to strings, never a crash ---
#
# The lenient timestamp loader (core.frontmatter.lenient_safe_load) keeps the
# mapping parseable when a date is typo'd: the bad scalar becomes a plain
# string so downstream checks (e.g. validator W016) can report it precisely
# instead of the whole block becoming unparseable (E001).


def test_c9_bad_month_no_crash():
    raw = "---\ntype: Note\nstale_after: 2026-13-99\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert data == {"type": "Note", "stale_after": "2026-13-99"} and body == "body\n"


def test_c9_impossible_day_no_crash():
    raw = "---\nd: 2026-02-30\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert data == {"d": "2026-02-30"} and body == "body\n"


def test_c9_valid_timestamp_still_parses():
    data, body = parse_frontmatter("---\nd: 2026-02-28\n---\nbody\n")
    assert data == {"d": datetime.date(2026, 2, 28)} and body == "body\n"


# --- H4: pathological nesting -> unparseable, never a RecursionError ---


def test_h4_deeply_nested_yaml_no_recursion_error():
    raw = "---\ntitle: T\nk: " + "[" * 900 + "x\n---\n"
    data, body = parse_frontmatter(raw)  # must not raise RecursionError
    assert data == {} and body == raw


def test_h4_balanced_deep_nesting_no_recursion_error():
    raw = "---\nk: " + "[" * 800 + "]" * 800 + "\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert data == {} and body == raw


# --- M24: '---' inside an indented block scalar does not end frontmatter ---


def test_m24_block_scalar_containing_fence_line():
    raw = "---\ndescription: |\n  line one\n  ---\n  line two\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert data == {"description": "line one\n---\nline two\n"}
    assert body == "body\n"


def test_m24_folded_scalar_containing_fence_line():
    raw = "---\ndescription: >\n  line one\n  ---\n  line two\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert body == "body\n"
    assert "---" in data["description"]


def test_m24_indented_fence_alone_is_not_a_closing_fence():
    # The only '---' candidate is indented, so there is no valid closing
    # fence: the whole text is kept as the body (never silently dropped).
    raw = "---\ntitle: x\n  ---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert data == {} and body == raw


def test_m24_serialized_block_scalar_roundtrips():
    fm = {"description": "line one\n---\nline two"}
    data, body = parse_frontmatter(serialize_frontmatter(fm, "body\n"))
    assert data == fm and body == "body\n"


# --- L22: leading BOM is stripped, frontmatter still detected ---


def test_l22_bom_prefixed_frontmatter_parses():
    data, body = parse_frontmatter("\ufeff---\ntitle: x\n---\nbody\n")
    assert data == {"title": "x"} and body == "body\n"


def test_l22_bom_without_frontmatter():
    data, body = parse_frontmatter("\ufeff# hello\n")
    assert data == {} and body == "# hello\n"


def test_l22_bom_does_not_break_reserialize():
    raw = "\ufeff---\ntitle: x\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert serialize_frontmatter(data, body) == "---\ntitle: x\n---\nbody\n"


# --- Existing guarantees still hold ---


def test_missing_fences_keep_whole_text():
    raw = "---\ntitle: x\nbody without closing fence\n"
    data, body = parse_frontmatter(raw)
    assert data == {} and body == raw


def test_no_frontmatter_keeps_whole_text():
    raw = "# just a heading\n"
    data, body = parse_frontmatter(raw)
    assert data == {} and body == raw


# --- M28: size guard on frontmatter (DoS-adjacent slowness) ---


def test_m28_huge_key_count_frontmatter_refused_fast():
    # QA repro shape: a 200k-key mapping took ~66 s to parse; the guard must
    # refuse it quickly instead, keeping the whole text as the body.
    raw = "---\n" + "".join(f"k{i:06d}: v\n" for i in range(200_000)) + "---\nbody\n"
    start = time.perf_counter()
    data, body = parse_frontmatter(raw)
    elapsed = time.perf_counter() - start
    assert data == {} and body == raw
    assert elapsed < 10  # was ~66 s before the guard


def test_m28_huge_char_count_frontmatter_refused():
    raw = "---\nkey: " + "x" * 1_000_001 + "\n---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert data == {} and body == raw


def test_m28_reasonable_frontmatter_still_parses():
    raw = "---\n" + "".join(f"k{i}: v\n" for i in range(1000)) + "---\nbody\n"
    data, body = parse_frontmatter(raw)
    assert len(data) == 1000 and body == "body\n"
