"""Regression tests for C10: ``trust_tier`` must never raise on malformed ``verified``.

A hand-written ``verified: yes`` (scalar bool/str/int frontmatter value) used
to crash every agent-facing path with ``TypeError: 'bool' object is not
iterable`` (a bare string iterated char-by-char and misreported
``machine-confirmed``). These tests pin the defensive coercion: scalar /
missing / malformed ``verified`` resolves to a sane tier and never raises.
"""

import pytest

from okfsmith.core import spec
from okfsmith.core.frontmatter import parse_frontmatter
from okfsmith.core.spec import trust_tier

UNVERIFIED = spec.UNVERIFIED
MACHINE_CONFIRMED = spec.MACHINE_CONFIRMED
HUMAN_REVIEWED = spec.HUMAN_REVIEWED


@pytest.mark.parametrize(
    "value",
    [
        True,  # verified: yes
        False,  # verified: no
        "yes",
        "no",
        "machine",
        "human:alice",  # a bare actor string carries no structured entry info
        5,
        0,
        3.14,
    ],
)
def test_scalar_verified_never_raises_and_is_unverified(value):
    tier = trust_tier({"verified": value})
    assert tier == UNVERIFIED


def test_string_verified_no_longer_misreports_machine_confirmed():
    # Before the fix, "yes" iterated char-by-char and returned
    # MACHINE_CONFIRMED; it carries no actor info, so it is unverified.
    assert trust_tier({"verified": "yes"}) == UNVERIFIED


def test_missing_verified_is_unverified():
    assert trust_tier({}) == UNVERIFIED
    assert trust_tier({"type": "Note"}) == UNVERIFIED
    assert trust_tier({"verified": None}) == UNVERIFIED
    assert trust_tier({"verified": []}) == UNVERIFIED


@pytest.mark.parametrize(
    "value",
    [
        {"weird": 1},  # mapping without a "by" key
        {"by": 123},  # non-string actor
        {"by": None},
        {"by": ["human:alice"]},  # non-string actor container
        {"by": ""},
    ],
)
def test_malformed_verified_dict_never_raises(value):
    assert trust_tier({"verified": value}) == MACHINE_CONFIRMED


def test_malformed_verified_dict_with_human_actor():
    assert trust_tier({"verified": {"by": "human:alice"}}) == HUMAN_REVIEWED


def test_list_with_scalar_entries_never_raises():
    assert trust_tier({"verified": [True, "x", None, 7]}) == MACHINE_CONFIRMED
    assert (
        trust_tier({"verified": [True, {"by": "human:alice"}]}) == HUMAN_REVIEWED
    )


def test_verified_entry_happy_path_unchanged():
    # Pinned semantics from the existing suite (test_core_smoke).
    assert trust_tier({"verified": {"by": "process:nightly"}}) == MACHINE_CONFIRMED
    assert (
        trust_tier({"verified": [{"by": "process:nightly"}, {"by": "human:ada"}]})
        == HUMAN_REVIEWED
    )
    assert (
        trust_tier({"verified": {"by": "human:ada", "at": "2026-01-01"}})
        == HUMAN_REVIEWED
    )


def test_qa_repro_yaml_verified_yes_does_not_raise():
    # The exact QA C10 shape: hand-written YAML ``verified: yes``.
    frontmatter, _body = parse_frontmatter("---\ntitle: T\nverified: yes\n---\nbody\n")
    assert frontmatter["verified"] is True
    assert trust_tier(frontmatter) == UNVERIFIED
