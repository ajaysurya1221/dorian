"""Deterministic, zero-model C3 claim SUGGESTIONS for a Python file.

The C3 counterpart to `datachecks.suggest` (which does C5 data checks). It
proposes born-verifiable claims for a repo-relative `.py` file:

- `symbol:<file>::<name>` for every non-private top-level `def`/`class`
  (skipped, loudly, when the name is defined in more than one tracked file —
  the binding would be ambiguous).
- `py-const:<file>::<NAME>::<literal>` for every non-private module-level
  assignment whose right-hand side is a simple Python literal.

Every candidate is RUN against the current source and only the ones that PASS
are emitted, so the fragment seals unmodified. Output is a reviewable
`{"claims": [...]}` fragment to paste into claims.json — never applied
automatically, and `load_bearing` defaults to false.

These are SCAFFOLDING, not proof of behavior: a `symbol:`/`py-const:` claim
re-checks existence/value, not behavior — a gutted function body keeps a
`symbol:` claim green (see docs/WRITING_GOOD_CLAIMS.md). Review every
suggestion and pair behavior claims with a C4 `pytest:` or C5 check.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from dorian import gitio, symbol_index
from dorian.checkers.base import CheckContext, Verdict, run_checker
from dorian.model import CheckerSpec, Claim

# bool is a subclass of int; type(None) covers the literal None
_LITERAL_TYPES = (int, float, str, bool, type(None))


def _claim(cid: str, text: str, kind: str, program: str, path: str) -> dict[str, Any]:
    return {
        "id": cid,
        "text": text,
        "kind": kind,
        "load_bearing": False,
        "checkers": [{"type": "C3", "program": program, "watch": [path]}],
    }


def _passes(repo: Path, program: str) -> bool:
    """Run a candidate C3 checker against current source; True iff it PASSES."""
    spec = CheckerSpec(type="C3", program=program)
    claim = Claim(id="_probe", text="", kind="reference", load_bearing=False, checkers=(spec,))
    return run_checker(CheckContext(repo=repo, claim=claim), 0).verdict is Verdict.PASS


def suggest(repo: Path, path: str) -> dict[str, Any]:
    """Return {"claims": [...], "skipped": [...]} of born-verifiable C3 suggestions
    for the repo-relative Python file `path`. Deterministic; no model."""
    if not path.endswith(".py"):
        raise ValueError(f"suggest-claims supports Python files (.py), got: {path}")
    p = repo / path
    if not p.is_file():
        raise ValueError(f"missing file: {path}")
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise ValueError(f"unparseable python: {path}: {exc}") from None

    try:
        definers: dict[str, tuple[str, ...]] | None = symbol_index.python_symbol_definers(repo)
    except gitio.GitError:
        definers = None  # not a git checkout: skip cross-file ambiguity filtering

    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name
            if name.startswith("_"):
                continue
            files = definers.get(name, ()) if definers is not None else ()
            if len(files) > 1:  # ambiguous definer: binding would be unreliable, skip loudly
                skipped.append(
                    {"name": name, "reason": "ambiguous_symbol", "definers": list(files)}
                )
                continue
            candidates.append(
                _claim(
                    f"{name}-defined",
                    f"`{name}` is defined in `{path}`.",
                    "reference",
                    f"symbol:{path}::{name}",
                    path,
                )
            )
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            cname = node.targets[0].id
            if cname.startswith("_"):
                continue
            try:
                val = ast.literal_eval(node.value)
            except (ValueError, SyntaxError, TypeError):
                continue  # non-literal RHS (a call, name, container expr): not a constant value
            if not isinstance(val, _LITERAL_TYPES):
                continue  # conservative: skip containers (list/dict/tuple/set)
            candidates.append(
                _claim(
                    f"{cname}-value",
                    f"`{cname}` in `{path}` equals `{val!r}`.",
                    "quantity",
                    f"py-const:{path}::{cname}::{val!r}",
                    path,
                )
            )

    claims: list[dict[str, Any]] = []
    for c in candidates:  # born-verifiable: emit only suggestions that pass now
        if _passes(repo, c["checkers"][0]["program"]):
            claims.append(c)
        else:
            skipped.append({"name": c["id"], "reason": "did_not_pass"})
    return {"claims": claims, "skipped": skipped}
