"""Serve the bundled ``okfsmith-build`` skill over the MCP Skills extension.

Anthropic's Skills over MCP (public beta, 24 November 2026; SEP-2640,
``io.modelcontextprotocol/skills``) lets an MCP server publish Agent Skills
alongside its tools: a client discovers them with ``skills/list``, fetches
one with ``skills/get``, and reads its files with ``resources/read`` under
``skill://`` URIs. FastMCP >= 4.2 implements the extension natively; the
bundled skill is loaded with ``fastmcp.skills.Skill`` and served through a
``SkillCatalogProvider``, which is what declares the extension in
``server/discover``.

The skill lives in the package at ``okfsmith/skills/okfsmith-build/`` so it
ships inside the wheel — a server installed from PyPI serves the same skill
a source checkout does. Skill files are read-only content, so the provider
is attached in every mode (read-only default and ``--allow-writes`` alike).

If the skill directory is missing (a stripped install), the installed
FastMCP predates the skills provider, or the bundled skill fails Agent
Skills validation, the server starts without skills and logs a warning —
skill serving must never take the bundle server down.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: URI of the bundled skill's ``SKILL.md``, per the Skills extension mapping.
BUNDLED_SKILL_URI = "skill://okfsmith-build/SKILL.md"


def bundled_skills_root() -> Path | None:
    """Directory holding the skill folders shipped with the package.

    Returns ``None`` when the package carries no skills (a stripped
    install) so the caller can skip skill serving.
    """
    root = Path(__file__).resolve().parent.parent / "skills"
    return root if root.is_dir() else None


def _is_skill_content(path: str) -> bool:
    """True when *path* (relative to a skill folder) is skill content.

    pip byte-compiles ``.py`` files at install time, so an installed
    package carries ``scripts/__pycache__/validate.*.pyc`` next to the
    skill's own ``validate.py``. That bytecode is not skill content: it
    varies by Python version and install, so serving it would make the
    published manifest differ between installs. Drop it (and any other
    ``__pycache__`` entry) so the served skill is identical everywhere.
    """
    return "__pycache__" not in Path(path).parts


def attach_bundled_skills(server: Any) -> bool:
    """Attach the bundled skills to *server*; True when serving them.

    Returns False (and logs a warning) when the skill directory is
    missing, the installed FastMCP has no skills provider, or no valid
    bundled skill is found — the caller keeps a working server either way.
    """
    root = bundled_skills_root()
    if root is None:
        logger.warning(
            "okfsmith skills not found in the installed package; "
            "serving the MCP server without the okfsmith-build skill"
        )
        return False
    try:
        from fastmcp.skills import Skill
        from fastmcp.skills.provider import SkillCatalogProvider
    except ImportError:
        logger.warning(
            "Installed fastmcp predates the MCP Skills provider "
            "(needs fastmcp>=4.2); serving the MCP server without "
            "the okfsmith-build skill"
        )
        return False
    skills = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not (folder / "SKILL.md").is_file():
            continue
        try:
            skill = Skill.from_directory(folder)
        except (ValueError, OSError) as exc:
            # Our own bundled skill failed Agent Skills validation — a
            # bug, but the bundle server must still start.
            logger.warning(
                "Skipping invalid bundled skill %s (%s); serving the "
                "MCP server without it",
                folder.name,
                exc,
            )
            continue
        content = {
            path: blob
            for path, blob in skill.files.items()
            if _is_skill_content(path)
        }
        skills.append(Skill.from_files(content))
    if not skills:
        logger.warning(
            "No valid bundled skills found; serving the MCP server "
            "without the okfsmith-build skill"
        )
        return False
    server.add_provider(SkillCatalogProvider(skills))
    return True
