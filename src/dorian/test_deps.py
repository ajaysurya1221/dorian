"""Deterministic C4 test-import dependency binding (stdlib ``ast`` only).

A C4 ``pytest:<nodeid>`` checker proves behavior WHEN IT RUNS, but the watch
``seal._derive_watch`` derives for it is only the nodeid's test file. If the
implementation file the test exercises changes and the claim text names no
uniquely indexed symbol/config key, ``revalidate`` can skip the claim entirely
even though an adequate behavior checker exists — a re-check TRIGGER gap (the
silent revalidation skip), not a truth-check failure.

This module statically resolves the repo-local Python files a test file imports
and ``c4_dependency_watch_paths`` maps each claim to the implementation files its
C4 test imports. ``verify`` / ``rebind`` add those to the claim's watch + read-set
(``seal`` keeps the truth decision in the checker), so a source edit re-runs the
existing C4 checker. A file change is a re-check TRIGGER, never a BROKEN: whether
the claim breaks is still decided by the test result.

Read-only and conservative by construction, mirroring ``symbol_index``:

- stdlib ``ast`` only — never imports application modules, executes setup code,
  mutates ``sys.path``, inspects installed packages, or touches the network;
- only TRACKED ``.py`` files are parsed and resolved; a stdlib import is skipped
  outright via the interpreter's module-name table, and a third-party import resolves
  to nothing UNLESS the repo happens to contain a file whose path tail matches the
  module name — a bounded, conservative false re-check TRIGGER, never a false BROKEN
  (the C4 test still decides truth);
- an import that resolves to EXACTLY ONE tracked file is bound; zero or more than
  one (ambiguous tail match) is skipped, because a wrong watch is a false-BROKEN
  risk and a false BROKEN is what gets the tool suppressed;
- syntax errors, symlinked / unreadable / oversized files, a non-git repo, an
  untracked test file, and relative imports that climb above the repo root all degrade
  to a partial result or ``()`` — the resolver is never the reason a seal fails;
- content-free: only repo-relative paths are produced, never source text.

``revalidate`` never calls this — the wider watch set is baked into the sealed
sidecar at verify/rebind time (the permanent "revalidate stays symbol/import
blind" design constraint).
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from dorian import gitio
from dorian.model import CheckerSpec, Claim

_MAX_FILE_BYTES = 1 << 20  # skip files > 1 MiB (mirrors symbol_index / bindings)

# Top-level names of THIS interpreter's standard library. An ABSOLUTE import whose first
# dotted component is a stdlib module (`import json`, `from os import path`) is never
# repo-local, so it is skipped before any path-tail match — otherwise a tracked repo file
# that happens to share the basename (e.g. `pkg/json.py`) would be a false re-check
# trigger. Read-only interpreter data: no import, no `sys.path`, no package introspection.
# Relative imports are repo-local by construction and are never checked against this set.
_STDLIB_TOP = frozenset(sys.stdlib_module_names)


def _is_stdlib_absolute(module: str) -> bool:
    """True when an absolute module's top-level package is a stdlib module."""
    return module.split(".", 1)[0] in _STDLIB_TOP


def python_import_dependencies(repo: Path, file: str, *, max_depth: int = 1) -> tuple[str, ...]:
    """The sorted, unique repo-relative tracked ``.py`` files statically imported by
    ``file`` (a repo-relative tracked test file), to ``max_depth`` import hops.

    Pure and read-only: no execution, no ``sys.path`` mutation, no application
    imports. Returns ``()`` for a non-git repo, an untracked/oversized/unreadable
    or unparseable ``file``, or when nothing repo-local resolves; the file itself is
    never listed. ``max_depth=1`` (the default and first-release setting) resolves
    only the test file's direct imports.
    """
    repo = repo.resolve()
    try:
        tracked = set(gitio.ls_files(repo))
    except gitio.GitError:
        return ()  # not a git checkout: no tracked-file set to resolve against
    return _resolve_imports(repo, file, tracked, max_depth)


def _resolve_imports(repo: Path, file: str, tracked: set[str], max_depth: int) -> tuple[str, ...]:
    """Core resolver over a PRE-BUILT tracked-file set, so a multi-claim caller
    (``c4_dependency_watch_paths``) builds the set once per verify/rebind rather than
    once per test file. Same result as ``python_import_dependencies``: ``()`` when the
    file is untracked; the file itself is never listed."""
    if file not in tracked:
        return ()  # parse only TRACKED .py files (per spec); also blocks `..`/abs paths
    out: set[str] = set()
    seen: set[str] = {file}
    frontier = [file]
    depth = 0
    while frontier and depth < max_depth:
        nxt: list[str] = []
        for rel in frontier:
            for dep in _imports_of_file(repo, rel, tracked):
                if dep not in seen:
                    seen.add(dep)
                    out.add(dep)
                    nxt.append(dep)
        frontier = nxt
        depth += 1
    return tuple(sorted(out))


def _imports_of_file(repo: Path, rel: str, tracked: set[str]) -> list[str]:
    """Repo-local tracked ``.py`` files the single file ``rel`` imports (one hop).
    Unreadable / oversized / unparseable / pathological files yield ``[]`` — never
    raise, so one bad tracked file cannot break the whole resolution."""
    path = repo / rel
    try:
        # skip symlinks: a tracked symlink-to-.py can point OUTSIDE the repo, and following
        # it would ast.parse out-of-repo bytes (is_file()/stat() resolve the link target).
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            return []
        tree = ast.parse(path.read_bytes())  # bytes: honour the PEP 263 coding cookie
    except (OSError, SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    deps: set[str] = set()
    file_dir_parts = rel.split("/")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_stdlib_absolute(alias.name):
                    _add_if_unique(_module_files(alias.name, tracked), deps)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                _resolve_relative(node, file_dir_parts, tracked, deps)
            else:
                _resolve_absolute(node, tracked, deps)
    return sorted(deps)


def _resolve_absolute(node: ast.ImportFrom, tracked: set[str], deps: set[str]) -> None:
    """``from pkg.mod import a, b`` (level 0): bind the module ``pkg.mod`` and, for
    each imported name, the candidate submodule ``pkg.mod.<name>`` — each only when it
    resolves to exactly one tracked file (a name may be an attribute OR a submodule;
    we cannot tell without importing, so consider both, conservatively). A stdlib
    ``from`` target (``from os.path import join``) is skipped, like ``import`` above."""
    if not node.module or _is_stdlib_absolute(node.module):
        return
    _add_if_unique(_module_files(node.module, tracked), deps)
    for alias in node.names:
        if alias.name != "*":
            _add_if_unique(_module_files(f"{node.module}.{alias.name}", tracked), deps)


def _resolve_relative(
    node: ast.ImportFrom, file_dir_parts: list[str], tracked: set[str], deps: set[str]
) -> None:
    """``from . import x`` / ``from .mod import y`` / ``from ..pkg import z``: resolve
    against the importing file's package, derived from its path (no ``sys.path``). A
    relative import that climbs above the repo root is skipped. Candidate paths are
    EXACT (relative imports resolve to a precise location), bound only when exactly
    one of ``x.py`` / ``x/__init__.py`` is tracked."""
    up = node.level - 1
    if up > len(file_dir_parts):
        return  # climbs above the repo root: unresolvable here
    base = file_dir_parts[: len(file_dir_parts) - up]
    if node.module:
        target = [*base, *node.module.split(".")]
        _add_if_unique(_exact_tracked(_module_path_candidates(target), tracked), deps)
        for alias in node.names:
            if alias.name != "*":
                cands = _module_path_candidates([*target, alias.name])
                _add_if_unique(_exact_tracked(cands, tracked), deps)
    else:  # from . import names -> the package __init__ plus each submodule
        _add_if_unique(_exact_tracked(["/".join([*base, "__init__.py"])], tracked), deps)
        for alias in node.names:
            if alias.name != "*":
                cands = _module_path_candidates([*base, alias.name])
                _add_if_unique(_exact_tracked(cands, tracked), deps)


def _module_files(module: str, tracked: set[str]) -> list[str]:
    """Tracked ``.py`` files whose repo-relative path matches a dotted ABSOLUTE module
    by path tail (so ``pkg.cli`` matches ``pkg/cli.py``, ``src/pkg/cli.py``, or
    ``pkg/cli/__init__.py``). A pure string match — never imports, executes, or
    consults ``sys.path``; mirrors ``symbol_index._module_candidate_files``."""
    tail = module.replace(".", "/")
    wants = (tail + ".py", tail + "/__init__.py")
    return sorted(f for f in tracked if any(f == w or f.endswith("/" + w) for w in wants))


def _module_path_candidates(parts: list[str]) -> list[str]:
    """EXACT repo-relative candidate paths for a relative-import target (no tail
    match): ``a/b.py`` and ``a/b/__init__.py``."""
    stem = "/".join(parts)
    return [stem + ".py", stem + "/__init__.py"]


def _exact_tracked(candidates: Iterable[str], tracked: set[str]) -> list[str]:
    return sorted({c for c in candidates if c in tracked})


def _add_if_unique(files: list[str], deps: set[str]) -> None:
    """Bind only an UNAMBIGUOUS resolution: exactly one tracked file. Zero or more
    than one is skipped (a wrong watch is a false-BROKEN risk)."""
    if len(files) == 1:
        deps.add(files[0])


def _c4_test_file(spec: CheckerSpec) -> str | None:
    """The nodeid's file part of a C4 ``pytest:<nodeid>`` checker, else ``None``.
    Mirrors ``seal._derive_watch`` so the derived test-file watch and the
    import-derived watches resolve from the same nodeid parse."""
    if spec.type != "C4":
        return None
    prefix, sep, nodeid = spec.program.partition(":")
    if prefix != "pytest" or not sep:
        return None
    file = nodeid.partition("::")[0].strip()
    return file or None


def c4_dependency_watch_paths(
    repo: Path, claims: Sequence[Claim], *, max_depth: int = 1
) -> dict[str, tuple[str, ...]]:
    """claim id -> the sorted repo-local implementation files its C4 ``pytest:`` test
    files statically import. Claims with no C4 checker (or whose tests import nothing
    repo-local) are omitted. Each distinct test file is parsed at most once. Additive
    and trigger-only — a resolved file is a re-check trigger; the C4 test still decides
    truth when it runs."""
    repo = repo.resolve()
    # build the tracked-file set ONCE per call (not once per claim/test file): a pure
    # function of the repo tree, threaded into every resolution below. A non-git repo
    # self-degrades to {} exactly as the symbol helpers do.
    try:
        tracked = set(gitio.ls_files(repo))
    except gitio.GitError:
        return {}
    cache: dict[str, tuple[str, ...]] = {}
    out: dict[str, tuple[str, ...]] = {}
    for claim in claims:
        paths: set[str] = set()
        for spec in claim.checkers:
            tf = _c4_test_file(spec)
            if tf is None:
                continue
            if tf not in cache:
                cache[tf] = _resolve_imports(repo, tf, tracked, max_depth)
            paths.update(cache[tf])
        if paths:
            out[claim.id] = tuple(sorted(paths))
    return out


def merge_watch_maps(*maps: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    """Union per-claim watch maps (claim id -> paths), sorted and deduped. Mirrors
    ``symbol_index.claim_watch_paths``' own merge so the combined ``extra_watch`` is
    byte-identical regardless of source order."""
    merged: dict[str, set[str]] = {}
    for m in maps:
        for cid, paths in m.items():
            merged.setdefault(cid, set()).update(paths)
    return {cid: tuple(sorted(paths)) for cid, paths in merged.items()}
