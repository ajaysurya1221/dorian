"""Loop-guard template packaging: every manifest template resolves via package data.

The non-slow checks here run in an editable checkout (importlib.resources over the
source tree); the slow installed-wheel check lives in test_packaging.py and proves the
same files ship in a built wheel and resolve from an installed package.
"""

from __future__ import annotations

from dorian import claude_code, loop


def test_every_loop_template_is_readable_package_data() -> None:
    for t in loop.LOOP_MANIFEST:
        assert claude_code._read_template(t.src), f"empty/missing loop template: {t.src}"


def test_loop_manifest_groups_and_dests() -> None:
    assert {t.group for t in loop.LOOP_MANIFEST} <= set(loop.GROUPS)
    assert "skill" in loop.DEFAULT_GROUPS
    assert len(loop.DEFAULT_GROUPS) == 1
    for t in loop.LOOP_MANIFEST:
        if t.group == "skill":
            assert t.dest.startswith(".claude/skills/dorian-loop-guard/")


def test_skill_frontmatter_and_boundary_phrases() -> None:
    text = claude_code._read_template("dorian-loop-guard/SKILL.md")
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    for key in ("name:", "description:", "when_to_use:"):
        assert key in frontmatter
    assert "/dorian-loop-guard" in text
    for phrase in ("not a sandbox", "token-free", "steering signal", "not an LLM judge"):
        assert phrase in text


def test_loop_decisions_reference_documents_the_table() -> None:
    text = claude_code._read_template("dorian-loop-guard/reference/loop-decisions.md")
    for phrase in ("continue", "repair", "escalate", "cautious", "assist", "unattended"):
        assert phrase in text
