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
import json
import tomllib
from pathlib import Path

from dorian import gitio
from dorian.bindings import _tokens
from dorian.model import Claim

_MAX_FILE_BYTES = 1 << 20  # skip files > 1 MiB (mirrors bindings); parsing them is wasteful
_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# config-key index: stdlib-parseable formats only. YAML is deliberately excluded —
# parsing it needs a third-party dep and dorian's core has zero runtime deps.
_CONFIG_SUFFIXES = (".toml", ".json")
_MIN_KEY_LEN = 4  # mirror bindings._MIN_IDENT: shorter keys are noise

# Common PEP 621 / packaging / generic config keys are ordinary English words that appear
# in claim prose constantly. Binding the config file every time one is mentioned is noise —
# and worse, it can pull a restricted config file (e.g. pyproject.toml) into the scope-linted
# read-set and newly refuse a previously-clean seal. So the config axis (like the symbol
# axis's _BACKTICK_STOPWORDS) skips these common keys; specific keys (max_workers, new_login)
# still bind. Found by adversarial review: a backticked `dependencies` made verify exit 6.
_CONFIG_KEY_STOPWORDS = frozenset(
    {
        "name",
        "version",
        "description",
        "readme",
        "license",
        "authors",
        "maintainers",
        "keywords",
        "classifiers",
        "dependencies",
        "scripts",
        "urls",
        "homepage",
        "repository",
        "documentation",
        "changelog",
        "requires",
        "optional",
        "project",
        "build",
        "tool",
        "include",
        "exclude",
        "packages",
        "source",
        "target",
        "default",
        "type",
        "format",
        "title",
        "summary",
        "value",
        "values",
        "enabled",
        "disabled",
        "options",
        "settings",
        "config",
        "email",
        "data",
        "files",
        "module",
        "modules",
        "dependency",
        "group",
        "groups",
        "extras",
    }
)


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


def _module_candidate_files(module: str, tracked: set[str]) -> list[str]:
    """Tracked .py files whose repo-relative path matches a dotted MODULE by path tail
    (so 'pkg.cli' matches 'pkg/cli.py', 'src/pkg/cli.py', or 'pkg/cli/__init__.py'). A
    pure string match — it never imports, executes, or consults sys.path."""
    tail = module.replace(".", "/")
    wants = (tail + ".py", tail + "/__init__.py")
    return sorted(f for f in tracked if any(f == w or f.endswith("/" + w) for w in wants))


def pyproject_script_definers(
    repo: Path, definers: dict[str, tuple[str, ...]] | None = None
) -> dict[str, tuple[str, ...]]:
    """Console-script name (from [project.scripts] / [project.gui-scripts] in
    pyproject.toml) -> the single tracked .py file that defines its `module:function`
    target. Unambiguous by construction (TOML keys are unique; the target is one
    module:function); a target whose module/function does not resolve to a tracked def
    is skipped. {} when there is no pyproject, no scripts, or it is malformed.
    """
    pp = repo / "pyproject.toml"
    if not pp.is_file():
        return {}
    try:
        data = tomllib.loads(pp.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return {}
    project = data.get("project")
    if not isinstance(project, dict):
        return {}
    entries: dict[str, str] = {}
    for table in ("scripts", "gui-scripts"):
        t = project.get(table)
        if isinstance(t, dict):
            for k, v in t.items():
                if isinstance(k, str) and isinstance(v, str):
                    entries[k] = v
    if not entries:
        return {}
    if definers is None:
        definers = python_symbol_definers(repo)
    try:
        tracked = set(gitio.ls_files(repo))
    except gitio.GitError:
        return {}  # not a git checkout: no tracked-file set to resolve script targets against
    out: dict[str, tuple[str, ...]] = {}
    for name, target in entries.items():
        module, sep, func = target.partition(":")
        if not module or not sep or not func:
            continue
        func_name = func.split(".", 1)[0]  # 'obj.attr' -> 'obj'; usually a bare function name
        candidates = _module_candidate_files(module, tracked)
        confirmed = [f for f in candidates if f in definers.get(func_name, ())]
        if len(confirmed) == 1:
            out[name] = (confirmed[0],)
    return out


def claim_symbol_watch_paths(
    repo: Path,
    claims: list[Claim],
    definers: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, tuple[str, ...]]:
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
    if definers is None:
        try:
            definers = python_symbol_definers(repo)
        except gitio.GitError:
            return {}
    index = definers
    scripts = pyproject_script_definers(repo, index)  # console-script name -> target file
    out: dict[str, tuple[str, ...]] = {}
    for claim in claims:
        paths: set[str] = set()
        for token in claim_tokens.get(claim.id, ()):
            files = index.get(token)
            if files is not None and len(files) == 1:
                paths.add(files[0])
            elif token in scripts:
                paths.add(scripts[token][0])
        if paths:
            out[claim.id] = tuple(sorted(paths))
    return out


def _walk_keys(obj: object):
    """Yield every string dict-key in a nested TOML/JSON structure (recursively)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


def config_key_index(repo: Path) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    """(key -> sorted tracked .toml/.json files defining it, sorted unparseable files).

    Keys shorter than _MIN_KEY_LEN are dropped as noise. A supported config file that
    fails to parse is returned in the second element — a LOUD diagnostic, never a
    silent skip that would hide a missed binding. YAML is not indexed (no runtime dep).
    """
    repo = repo.resolve()
    keys: dict[str, set[str]] = {}
    unparseable: list[str] = []
    try:
        tracked = gitio.ls_files(repo)
    except gitio.GitError:
        return ({}, ())  # not a git checkout: degrade to no index (never blocks)
    for rel in tracked:
        if not rel.endswith(_CONFIG_SUFFIXES):
            continue
        path = repo / rel
        try:
            if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
                continue
            raw = path.read_text(encoding="utf-8")
            data = tomllib.loads(raw) if rel.endswith(".toml") else json.loads(raw)
        except (
            OSError,
            UnicodeDecodeError,
            tomllib.TOMLDecodeError,
            json.JSONDecodeError,
            RecursionError,
        ):
            unparseable.append(rel)
            continue
        for key in _walk_keys(data):
            if len(key) >= _MIN_KEY_LEN:
                keys.setdefault(key, set()).add(rel)
    return ({k: tuple(sorted(v)) for k, v in sorted(keys.items())}, tuple(sorted(unparseable)))


def claim_config_watch_paths(
    repo: Path,
    claims: list[Claim],
    config_index: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """claim id -> the config file(s) to add to its watch set: for every identifier-shaped
    token in the claim text that is a config key defined in EXACTLY ONE tracked .toml/.json.
    Ambiguous keys (>1 file) are skipped (see ambiguous_config_mentions). Additive and
    trigger-only — a config change re-checks the claim; the checker still decides truth."""
    claim_tokens = {c.id: _tokens(c.text) for c in claims if isinstance(c.text, str)}
    if not any(claim_tokens.values()):
        return {}
    index = config_index if config_index is not None else config_key_index(repo)[0]
    out: dict[str, tuple[str, ...]] = {}
    for claim in claims:
        paths: set[str] = set()
        for token in claim_tokens.get(claim.id, ()):
            if token.lower() in _CONFIG_KEY_STOPWORDS:
                continue  # common config word: prose, not a key to bind (over-binding/scope)
            files = index.get(token)
            if files is not None and len(files) == 1:
                paths.add(files[0])
        if paths:
            out[claim.id] = tuple(sorted(paths))
    return out


def claim_watch_paths(
    repo: Path,
    claims: list[Claim],
    definers: dict[str, tuple[str, ...]] | None = None,
    config_index: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """All deterministic re-check watches dorian binds per claim: Python symbol-definer
    files + pyproject console scripts (claim_symbol_watch_paths) UNION config-key files
    (claim_config_watch_paths). Union, sorted, deduped. Conservative and additive — it
    only ever widens the re-check trigger set; it never proves a claim true."""
    merged: dict[str, set[str]] = {}
    for source in (
        claim_symbol_watch_paths(repo, claims, definers),
        claim_config_watch_paths(repo, claims, config_index),
    ):
        for cid, paths in source.items():
            merged.setdefault(cid, set()).update(paths)
    return {cid: tuple(sorted(paths)) for cid, paths in merged.items()}


def ambiguous_config_mentions(
    repo: Path,
    claims: list[Claim],
    config_index: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, dict[str, tuple[str, ...]]]:
    """claim id -> {config key: defining files} for keys a LOAD-BEARING claim mentions
    that are defined in MORE THAN ONE tracked config file — the ambiguous case binding
    skips. Lets verify/bind-suggest surface the skip rather than guess. {} if none."""
    index = config_index if config_index is not None else config_key_index(repo)[0]
    out: dict[str, dict[str, tuple[str, ...]]] = {}
    for claim in claims:
        if not claim.load_bearing or not isinstance(claim.text, str):
            continue
        ambiguous = {
            tok: index[tok]
            for tok in _tokens(claim.text)
            if tok.lower() not in _CONFIG_KEY_STOPWORDS and len(index.get(tok, ())) > 1
        }
        if ambiguous:
            out[claim.id] = ambiguous
    return out


def ambiguous_symbol_mentions(
    repo: Path,
    claims: list[Claim],
    definers: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, dict[str, tuple[str, ...]]]:
    """claim id -> {symbol: defining files} for symbols a LOAD-BEARING claim's text
    mentions that are defined in MORE THAN ONE tracked file — the ambiguous case the
    binding fix intentionally skips (a definer is unknowable, so binding one would be
    false precision). Lets `verify` / `bindings` surface that skip loudly and reviewably
    instead of hiding it; it never adds a watch. {} on a non-git repo.
    """
    if definers is None:
        try:
            index = python_symbol_definers(repo)
        except gitio.GitError:
            return {}
    else:
        index = definers
    out: dict[str, dict[str, tuple[str, ...]]] = {}
    for claim in claims:
        if not claim.load_bearing or not isinstance(claim.text, str):
            continue
        ambiguous = {tok: index[tok] for tok in _tokens(claim.text) if len(index.get(tok, ())) > 1}
        if ambiguous:
            out[claim.id] = ambiguous
    return out
