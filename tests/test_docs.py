"""Docs/spec regressions from the ring-1 hostile review.

The repo's published surface must track the code: the warrant schema's checker
enum once lagged the C4 checker (a valid C4 sidecar was invalid against the
repo's own spec), model.py pointed at a spec/checkers.md that did not exist, and
README documented none of the ring-1 commands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

from dorian.model import CheckerType

ROOT = Path(__file__).resolve().parent.parent


def test_schema_checker_enum_matches_model() -> None:
    """Regression: the enum was ["C1", "C3", "C5"] after ring 1 added C4."""
    schema = json.loads((ROOT / "spec" / "warrant.schema.json").read_text(encoding="utf-8"))
    claims = schema["properties"]["warrant"]["properties"]["claims"]
    enum = claims["items"]["properties"]["checkers"]["items"]["properties"]["type"]["enum"]
    assert sorted(enum) == sorted(get_args(CheckerType))


def test_checker_grammar_reference_exists_and_covers_every_grammar() -> None:
    """model.py's CheckerSpec points at spec/checkers.md; it was dangling since
    the kernel. It must exist and document every program grammar."""
    text = (ROOT / "spec" / "checkers.md").read_text(encoding="utf-8")
    for needle in (
        "pytest:",  # C4
        "path:",  # C3 forms
        "symbol:",
        "string:",
        "regex:",
        "rowcount:",  # C5 typed forms
        "schema:",
        "nullrate:",
        "domain:",
        "freshness:",
        "snapshot:",
        "reconcile:",
        "shell:",
        "catastrophic backtracking",  # documented C3 regex residual risk
        "near-miss",
    ):
        assert needle in text, f"spec/checkers.md must document {needle!r}"


def test_readme_documents_the_ring1_surface() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for needle in (
        "dorian blast",
        "recalled",
        "--supersede",
        "dorian bindings",
        "suggest-data-checks",
        "--audit",
        "--format md",
        "--no-quotes",
        "[tool.dorian.scopes]",
        "--allow-restricted",
        "action/",
        "bench mutation",
        "bench large-mutation",
        "spec/checkers.md",
        "docs/AGENT_CLAIMS.md",
    ):
        assert needle in text, f"README must mention {needle!r}"
    # the user-facing exit-code contract (previously only in cli.py's docstring)
    assert "Exit codes" in text
    for code in ("`0`", "`2`", "`3`", "`4`", "`5`", "`6`"):
        assert code in text, f"README exit-code contract must include {code}"
