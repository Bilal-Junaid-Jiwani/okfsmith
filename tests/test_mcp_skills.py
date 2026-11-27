"""Tests for serving the bundled okfsmith-build skill over MCP.

Skills over MCP (SEP-2640, ``io.modelcontextprotocol/skills``): the server
publishes the skill via ``skills/list`` / ``skills/get`` plus ``skill://``
resources, so a client that implements the extension (Claude Code >=
2.1.331, protocol 2026-07-28 or later) discovers the bundle-building
playbook at connect time instead of needing it copied into its own skill
directory. Exercised over FastMCP's in-memory client — no live transport
is needed.

Requires the ``mcp`` extra (fastmcp >= 4.2, which ships the skills
provider). If it is not installed, the tests skip with a clear reason —
the same pattern as tests/test_mcp.py.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

fastmcp = pytest.importorskip("fastmcp", reason="mcp extra not installed")
pytest.importorskip(
    "fastmcp.skills.provider", reason="fastmcp < 4.2 has no skills provider"
)

from fastmcp import Client  # noqa: E402
from fastmcp.skills.client import SkillsClientExtension  # noqa: E402
from mcp.shared.exceptions import MCPError  # noqa: E402

from okfsmith.mcp_server.server import build_server  # noqa: E402
from okfsmith.mcp_server.skills import (  # noqa: E402
    BUNDLED_SKILL_URI,
    attach_bundled_skills,
    bundled_skills_root,
)

FIXTURE_BUNDLE = Path(__file__).resolve().parent.parent / ".contract" / "fixtures" / "valid"


def _skill_dir() -> Path:
    """The skill as shipped in the package — the single source of truth.

    Resolved through the same function the server uses, so these tests pin
    the served content to the files the server actually reads.
    """
    root = bundled_skills_root()
    assert root is not None, "bundled skills missing from the installed package"
    return root / "okfsmith-build"


def _skill_files() -> dict[str, bytes]:
    skill_dir = _skill_dir()
    return {
        p.relative_to(skill_dir).as_posix(): p.read_bytes()
        for p in sorted(skill_dir.rglob("*"))
        if p.is_file()
    }


def _run(coro):
    return asyncio.run(coro)


async def _list_skills(server):
    async with Client(server, extensions=[SkillsClientExtension()]) as client:
        return await client.list_skills()


def test_bundled_skills_root_resolves():
    root = bundled_skills_root()
    assert root is not None and root.is_dir()
    assert (root / "okfsmith-build" / "SKILL.md").is_file()


def test_server_discover_declares_skills_extension():
    async def check():
        server = build_server(FIXTURE_BUNDLE)
        async with Client(server, extensions=[SkillsClientExtension()]) as client:
            caps = client.server_capabilities
            assert caps is not None
            # The extension declaration is what tells a client it may call
            # skills/list and skills/get; resources is required alongside.
            assert "io.modelcontextprotocol/skills" in (caps.extensions or {})
            assert caps.resources is not None

    _run(check())


def test_skills_list_returns_bundled_skill():
    async def check():
        server = build_server(FIXTURE_BUNDLE)
        skills = await _list_skills(server)
        assert len(skills) == 1
        skill = skills[0]
        assert skill.uri == BUNDLED_SKILL_URI
        assert skill.frontmatter.name == "okfsmith-build"
        assert "okfsmith" in skill.frontmatter.description
        # Frontmatter passes through verbatim: the listing is the registry.
        assert skill.frontmatter.root["name"] == "okfsmith-build"

    _run(check())


def test_skills_list_manifest_matches_files_on_disk():
    """Every file is listed exactly once, with its real digest and size.

    A host verifies what it later reads against this manifest, so a stale
    or partial listing is a security-relevant bug, not a cosmetic one.
    """
    files = _skill_files()
    assert files, "bundled skill has no files"
    # The skill stays well inside the extension's per-skill limits.
    assert len(files) <= 512
    assert sum(len(b) for b in files.values()) <= 16_777_216

    async def check():
        server = build_server(FIXTURE_BUNDLE)
        skills = await _list_skills(server)
        assert isinstance(skills[0].resources, list)
        listed = {r.uri: r for r in skills[0].resources}
        assert len(listed) == len(files)
        for rel, content in files.items():
            uri = f"skill://okfsmith-build/{rel}"
            assert uri in listed, f"missing from manifest: {uri}"
            assert listed[uri].digest == "sha256:" + hashlib.sha256(content).hexdigest()
            assert listed[uri].size == len(content)

    _run(check())


def test_skills_get_by_uri_and_unknown_uri_errors():
    async def check():
        server = build_server(FIXTURE_BUNDLE)
        async with Client(server, extensions=[SkillsClientExtension()]) as client:
            skill = await client.get_skill(BUNDLED_SKILL_URI)
            assert skill.uri == BUNDLED_SKILL_URI
            assert skill.frontmatter.name == "okfsmith-build"
            with pytest.raises(MCPError, match="Unknown skill URI"):
                await client.get_skill("skill://no-such-skill/SKILL.md")

    _run(check())


def test_skill_files_readable_as_resources():
    files = _skill_files()

    async def check():
        server = build_server(FIXTURE_BUNDLE)
        async with Client(server, extensions=[SkillsClientExtension()]) as client:
            listed = await client.list_resources()
            uris = {r.uri for r in listed}
            for rel in files:
                assert f"skill://okfsmith-build/{rel}" in uris
            # resources/read serves the exact bytes the manifest digests.
            for rel, content in files.items():
                uri = f"skill://okfsmith-build/{rel}"
                got = await client.read_resource(uri)
                assert len(got) == 1
                assert got[0].text.encode("utf-8") == content
            with pytest.raises(MCPError, match="Resource not found"):
                await client.read_resource("skill://okfsmith-build/nope.md")

    _run(check())


def test_skills_served_in_read_only_mode():
    """Skill files are read-only content: served in read-only mode too."""
    async def check():
        server = build_server(FIXTURE_BUNDLE, read_only=True)
        skills = await _list_skills(server)
        assert [s.uri for s in skills] == [BUNDLED_SKILL_URI]

    _run(check())


def test_skills_served_with_writes_allowed():
    async def check():
        server = build_server(FIXTURE_BUNDLE, allow_writes=True)
        skills = await _list_skills(server)
        assert [s.uri for s in skills] == [BUNDLED_SKILL_URI]

    _run(check())


def test_missing_skills_root_degrades_gracefully(monkeypatch):
    """No skill directory (stripped install) must not take the server down."""
    import okfsmith.mcp_server.skills as skills_mod

    monkeypatch.setattr(skills_mod, "bundled_skills_root", lambda: None)
    server = build_server(FIXTURE_BUNDLE)
    assert attach_bundled_skills(server) is False
    # The nine read tools still register and the server still builds.
    registered = _run(server._list_tools())
    assert len(registered) == 9


def test_pycache_bytecode_is_not_served_as_skill_content(tmp_path, monkeypatch):
    """pip byte-compiles validate.py at install time; the .pyc is not content.

    An installed package carries ``scripts/__pycache__/validate.*.pyc``
    next to the skill's own ``validate.py``. It varies by Python version
    and install, so serving it would make the published manifest differ
    between installs — the served skill must be the authored skill.
    """
    import shutil

    import okfsmith.mcp_server.skills as skills_mod

    root = tmp_path / "skills"
    shutil.copytree(_skill_dir(), root / "okfsmith-build")
    pycache = root / "okfsmith-build" / "scripts" / "__pycache__"
    pycache.mkdir()
    (pycache / "validate.cpython-312.pyc").write_bytes(b"fake bytecode")
    monkeypatch.setattr(skills_mod, "bundled_skills_root", lambda: root)

    async def check():
        server = build_server(FIXTURE_BUNDLE)
        skills = await _list_skills(server)
        assert len(skills) == 1
        uris = {r.uri for r in skills[0].resources}
        assert len(uris) == 5
        assert not any("__pycache__" in uri for uri in uris)

    _run(check())
