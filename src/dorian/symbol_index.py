"""Deterministic Python symbol -> defining-file index (stdlib `ast` only).

Widens the set of source changes that RE-CHECK a claim: a change to the file
that defines a symbol the claim text mentions now makes the claim a revalidation
candidate, even when no checker named that file. This closes the *silent-skip*
class from docs/NEXT_ALGORITHMIC_BETS.md #1 — where a claim about a symbol
watched only the file its checker named, so a change to the file that actually
defines the symbol never triggered revalidation at all.

It widens the re-check TRIGGER set, not the checks themselves: whether a
re-check turns into a BROKEN verdict still depends on the claim's checkers — a
checker that exercises the symbol (e.g. a `pytest:` that imports it) breaks; a
checker that only inspects an unrelated file re-runs and passes. So this narrows
the false-confidence gap by surfacing the claim for re-check; it does not by
itself verify the symbol.

Conservative by construction: only identifier-shaped tokens (the same
backtick / snake_case / CamelCase extraction `bindings` uses) that resolve to
EXACTLY ONE defining file are bound; an ambiguous symbol (defined in more than
one file) is left unwatched, because a wrong watch is a false-BROKEN risk and a
false BROKEN is what gets the tool suppressed. Content-free: only repo-relative
paths are produced, never source text. `revalidate` never calls this — the
better watch set is baked into the sealed sidecar at verify time.
"""

from __future__ import annotations

import ast
from pathlib import Path

from dorian import gitio
from dorian.bindings import _tokens
from dorian.model import Claim

_MAX_FILE_BYTES = 1 << 20  # skip files > 1 MiB (mirrors bindings); parsing them is wasteful
_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def python_symbol_definers(repo: Path) -> dict[str, tuple[str, ...]]:
    """Symbol name -> the sorted, unique git-tracked `.py` files that define it
    as a function, async function, or class. Unreadable, oversized, or
    unparseable files — including a syntactically valid one whose pathological
    AST blows the recursion/memory limit on parse or walk — are skipped, so the
    index is never the reason a seal or revalidation fails. Raises gitio.GitError
    only if `repo` is not a git checkout (the caller `claim_symbol_watch_paths`
    degrades that to a no-op).
    """
    repo = repo.resolve()
    definers: dict[str, set[str]] = {}
    for rel in gitio.ls_files(repo):
        if not rel.endswith(".py"):
            continue
        path = repo / rel
        try:
            if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
                continue
            tree = ast.parse(path.read_bytes())  # bytes: ast honours the PEP 263 coding cookie
            names = [n.name for n in ast.walk(tree) if isinstance(n, _DEF_NODES)]
        except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
            continue  # unreadable / invalid / pathological python: skip, never fail the index
        for name in names:
            definers.setdefault(name, set()).add(rel)
    return {name: tuple(sorted(files)) for name, files in sorted(definers.items())}


def claim_symbol_watch_paths(repo: Path, claims: list[Claim]) -> dict[str, tuple[str, ...]]:
    """claim id -> the sorted, unique defining files to add to that claim's watch
    set: for every identifier-shaped token in the claim text that names a symbol
    defined in EXACTLY ONE file. Claims mentioning no such symbol are omitted
    (callers add nothing for them).

    Non-fatal and additive: a non-string `claim.text` (malformed agent JSON)
    contributes nothing, a non-git repo yields {}, and the per-file AST index is
    built only when some claim actually contains an identifier-shaped token — so
    the common no-symbol case pays no file I/O or parsing at all.
    """
    claim_tokens = {
        claim.id: _tokens(claim.text) for claim in claims if isinstance(claim.text, str)
    }
    if not any(claim_tokens.values()):
        return {}
    try:
        index = python_symbol_definers(repo)
    except gitio.GitError:
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for claim in claims:
        paths: set[str] = set()
        for token in claim_tokens.get(claim.id, ()):
            files = index.get(token)
            if files is not None and len(files) == 1:
                paths.add(files[0])
        if paths:
            out[claim.id] = tuple(sorted(paths))
    return out
