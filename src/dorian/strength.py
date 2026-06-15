"""Checker-strength and claim-risk diagnostics — make TRUTH strength visible.

The protocol keeps two questions apart (``docs/VALIDATION_HONESTY.md``):
- **Trigger coverage** — WHEN a claim is re-checked (binding; ``bindings.py``).
- **Truth strength** — WHETHER a checker can actually FALSIFY the claim (here).

A green seal says every backed claim held at seal time; it does NOT say the checker
is strong enough to catch a future drift. This module scores that second axis:

1. classify each checker's truth strength (``existence`` < ``raw_text`` <
   ``semantic_text`` < ``snapshot`` < ``data`` < ``structural`` < ``behavioral``;
   ``shell_executable`` is opaque), and the strongest backing per claim;
2. flag an ``adequacy_mismatch`` when the claim's ``kind`` needs more than its
   checkers provide (a ``behavior`` claim with only an existence/text checker; a
   ``quantity`` claim with only an existence checker);
3. run an advisory C4 test-adequacy lint (a bound pytest node with no assertions, or
   only a constant assertion, passes vacuously);
4. roll those into a per-claim ``risk`` level (``high``/``medium``/``low``).

It is purely advisory and deterministic: it never executes a checker, never changes
a verdict, trust state, or exit code, and reports repo-relative facts only. C4
adequacy parses the test file's AST (read-only); it never runs the test.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from dorian import pyast
from dorian.model import CheckerSpec, Claim
from dorian.policy import executable_kind

# Truth-strength rank (higher = can falsify more). `shell_executable` is opaque —
# it may be strong or vacuous — so it is ranked low and flagged, never trusted as
# the strongest backing on reputation alone.
_RANK = {
    "unbacked": 0,
    "shell_executable": 1,
    "existence": 2,
    "raw_text": 3,
    "semantic_text": 4,
    "snapshot": 5,
    "data": 6,
    "structural": 7,
    "behavioral": 8,
}

_C3_STRENGTH = {
    "path": "existence",
    "symbol": "existence",
    "string": "raw_text",
    "regex": "raw_text",
    "code": "semantic_text",
    "py-signature": "structural",
    "py-const": "structural",
}

# claim kinds and the WEAK strengths that under-verify them
_WEAK_FOR_BEHAVIOR = {"existence", "raw_text", "semantic_text", "snapshot", "data"}


def checker_strength(spec: CheckerSpec) -> str:
    """Classify a single checker's truth strength (see module docstring)."""
    if spec.type == "C1":
        return "snapshot"  # exact span-hash: snapshot-grade content match
    if spec.type == "C4":
        return "behavioral"
    if spec.type == "C5":
        form = spec.program.partition(":")[0]
        if form == "shell":
            return "shell_executable"
        if form == "snapshot":
            return "snapshot"
        return "data"  # rowcount/schema/nullrate/domain/freshness/reconcile
    if spec.type == "C3":
        return _C3_STRENGTH.get(spec.program.partition(":")[0], "raw_text")
    return "raw_text"  # unknown checker type: conservative


def claim_strength(claim: Claim) -> str:
    """The strongest backing across a claim's checkers; ``unbacked`` if none."""
    if not claim.checkers:
        return "unbacked"
    return max((checker_strength(s) for s in claim.checkers), key=lambda s: _RANK.get(s, 0))


def c4_adequacy(repo: Path, spec: CheckerSpec) -> list[str]:
    """Advisory: does a C4 ``pytest:`` node actually assert anything? Parses the test
    file's AST (no execution). Returns at most one note. Silent (``[]``) when the
    node cannot be located statically (the checker itself reports ``test_gone``) or
    when assertions / assertion helpers / ``pytest.raises`` are present."""
    prefix, _, nodeid = spec.program.partition(":")
    if prefix != "pytest":
        return []
    file, _, rest = nodeid.partition("::")
    if not file.strip() or not rest.strip():
        return []  # whole-file node or malformed: not the linter's call
    path = repo / file.strip()
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    tree = pyast._parse(text)
    if tree is None:
        return []
    fn = pyast._find_def(tree, rest.strip().replace("::", "."))
    if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
        return []  # not found by static walk: do not guess
    asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
    if asserts:
        if all(isinstance(a.test, ast.Constant) and bool(a.test.value) for a in asserts):
            return [f"c4_adequacy: {rest.strip()} asserts only a constant (vacuous)"]
        return []
    if _has_assertion_helper(fn):
        return []
    return [f"c4_adequacy: {rest.strip()} has no assertions (may pass vacuously; low confidence)"]


def _has_assertion_helper(fn: ast.AST) -> bool:
    """unittest ``self.assert*`` calls or a ``pytest.raises`` / bare ``raises`` context
    count as assertions for the adequacy lint (conservative: avoid false warnings)."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Attribute) and node.attr.startswith("assert"):
            return True
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "raises":
                return True
            if isinstance(f, ast.Name) and f.id == "raises":
                return True
    return False


def adequacy_notes(repo: Path, claim: Claim) -> list[str]:
    """Kind-vs-strength mismatches plus C4 adequacy notes for one claim."""
    if not claim.checkers:
        return []
    notes: list[str] = []
    strongest = claim_strength(claim)
    behavioral_backed = any(checker_strength(s) == "behavioral" for s in claim.checkers)
    if claim.kind == "behavior" and not behavioral_backed and strongest in _WEAK_FOR_BEHAVIOR:
        notes.append(
            f"adequacy_mismatch: 'behavior' claim backed only by {strongest}"
            " — only a C4 pytest checker proves behavior"
        )
    if claim.kind == "quantity" and all(checker_strength(s) == "existence" for s in claim.checkers):
        notes.append(
            "adequacy_mismatch: 'quantity' claim backed only by an existence checker"
            " — use py-const:/anchored regex:/typed C5 to verify the value"
        )
    for spec in claim.checkers:
        if spec.type == "C4":
            notes.extend(c4_adequacy(repo, spec))
    return notes


def claim_risk(
    claim: Claim, flags: Sequence[str], adequacy: Sequence[str]
) -> tuple[str, list[str]]:
    """Roll strength + binding flags + adequacy into a level + reasons. Deterministic.
    Non-load-bearing claims never score ``high`` (a soft claim is the author's call)."""
    reasons: list[str] = []
    level = "low"
    if not claim.checkers:
        reasons.append("unbacked")
        level = "high" if claim.load_bearing else "low"
    else:
        strongest = claim_strength(claim)
        if adequacy:
            reasons.append("adequacy_mismatch")
            if claim.load_bearing:
                level = "high" if strongest in ("existence", "raw_text") else "medium"
    high_binding = {
        "short-literal",
        "ambiguous-mention",
        "trigger-only-symbol",
        "unwatched-mention",
    }
    for f in flags:
        if f in high_binding:
            reasons.append(f"binding:{f}")
            if claim.load_bearing and level == "low":
                level = "medium"
    return level, reasons


def analyze(
    repo: Path,
    claims: Sequence[Claim],
    flags_by_id: dict[str, Sequence[str]] | None = None,
) -> list[dict]:
    """Per-claim strength/risk diagnostics, in claim order. ``flags_by_id`` (from
    ``bindings.analyze``) feeds binding-flag risk reasons when available."""
    flags_by_id = flags_by_id or {}
    out: list[dict] = []
    for c in claims:
        adequacy = adequacy_notes(repo, c)
        level, reasons = claim_risk(c, flags_by_id.get(c.id, ()), adequacy)
        out.append(
            {
                "claim_id": c.id,
                "kind": c.kind,
                "load_bearing": c.load_bearing,
                "strength": claim_strength(c),
                "executes": sorted({k for s in c.checkers if (k := executable_kind(s))}),
                "adequacy": adequacy,
                "risk": level,
                "reasons": reasons,
            }
        )
    return out


def summary_line(diags: list[dict]) -> str:
    """One deterministic line: risk-level counts. For CLI summaries."""
    counts = {"high": 0, "medium": 0, "low": 0}
    for d in diags:
        counts[d["risk"]] = counts.get(d["risk"], 0) + 1
    return f"claim-risk: {counts['high']} high, {counts['medium']} medium, {counts['low']} low"
