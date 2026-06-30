"""Manifest for the Claude Code governance adapter (host hooks that enforce loop decisions).

Scaffolded by ``dorian governance install`` through the shared ``claude_code.build_plan`` /
``apply`` machinery — exactly like ``dorian loop install``. Stdlib only; the templates are inert
package data. This is ONE concrete Claude Code adapter; no generic provider abstraction is
introduced until a second concrete adapter exists.
"""

from __future__ import annotations

from dorian.claude_code import _Template

HOOKS_DIR = ".claude/hooks"
BUNDLE_DIR = ".claude/dorian-governance"

# Install all three groups by default — the hooks are the whole point of the adapter
# (claude_code's DEFAULT_GROUPS omits "hook", so governance install passes this set).
DEFAULT_GROUPS = frozenset({"skill", "settings", "hook"})

GOVERNANCE_MANIFEST: tuple[_Template, ...] = (
    _Template(
        "dorian-governance/hooks/dorian_preflight_veto.py",
        f"{HOOKS_DIR}/dorian_preflight_veto.py",
        "hook",
        "PreToolUse veto (exit 2 on standing escalate; fails closed under strict modes)",
    ),
    _Template(
        "dorian-governance/hooks/dorian_loop_preflight.py",
        f"{HOOKS_DIR}/dorian_loop_preflight.py",
        "hook",
        "SubagentStop: run `dorian gate`, stamp freshness, write the runtime packet",
    ),
    _Template(
        "dorian-governance/settings.dorian-governance.example.json",
        ".claude/settings.dorian-governance.example.json",
        "settings",
        "example wiring for both hooks (merge into .claude/settings.json)",
    ),
    _Template(
        "dorian-governance/README.md",
        f"{BUNDLE_DIR}/README.md",
        "skill",
        "what the adapter does, the env vars it reads, the trust boundary",
    ),
    _Template(
        "dorian-governance/reference/enforcement-modes.md",
        f"{BUNDLE_DIR}/reference/enforcement-modes.md",
        "skill",
        "fail-open vs fail-closed by policy mode, and the freshness window",
    ),
)
