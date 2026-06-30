"""Determinism firewall: prove no model/provider/network/UI dependency is reachable
from Dorian's deterministic verification (verdict) path.

This is a *regression guard*, not a product subsystem. Non-Negotiable #1 ("no LLM/model
in the verification path") and #3 ("zero core runtime dependencies") are enforced by
construction today; this test makes them enforceable in CI rather than by convention.

How it works: starting from the deterministic-core seed modules, it statically walks the
``dorian.*`` import graph with the stdlib ``ast`` module (it never imports project code,
runs no checker, and touches no network), collecting every *external* (non-``dorian``)
import root reachable from that closure. Only **module-level** (import-time) imports are
followed — function-local imports are the project's sanctioned way to keep the core import
surface clean for optional deps (see ``_module_level_import_nodes``). The test fails if any
reachable root is on the forbidden list. stdlib modules (e.g. ``json``, ``subprocess``,
``urllib.parse``) are allowed — only model SDKs, network clients, agent frameworks, and
TUI/UI libraries are forbidden, because none of those belong on a token-free, local-only
verdict path.
"""

from __future__ import annotations

import ast
import pathlib
import tempfile

PKG = "dorian"
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / PKG

# The deterministic-core seeds: warrant model, checker execution, sealing, revalidation,
# fold/verdict logic, execution policy, loop decision classification, plus the storage,
# git, and claim-parsing modules the verdict path hard-depends on. The walker follows
# dorian.* edges transitively from here, so modules these reach (e.g. blast, pyast,
# _regex_worker, cli, claude_code) are guarded too — the seed list is a floor, not a cap.
VERDICT_SEEDS = [
    "model",
    "checkers",
    "seal",
    "revalidate",
    "fold",
    "policy",
    "loop",
    "store",
    "gitio",
    "claims_io",
]

# Forbidden top-level import roots on the verdict path. Model/provider SDKs, agent
# frameworks, network clients, and TUI/UI libraries. NB: stdlib ``urllib`` is allowed
# (used as ``urllib.parse``); the third-party ``urllib3`` is not.
FORBIDDEN = {
    # model / provider SDKs
    "anthropic",
    "openai",
    "google",
    "genai",
    "cohere",
    # agent / orchestration frameworks
    "langchain",
    "langgraph",
    "autogen",
    "semantic_kernel",
    "crewai",
    "llama_index",
    "mcp",
    # network clients
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "websockets",
    # TUI / UI libraries
    "textual",
    "rich",
    "urwid",
    "blessed",
    "prompt_toolkit",
}

# Deterministic-core utility modules that are NOT on the verdict path (so they do not belong
# in VERDICT_SEEDS) but must still stay stdlib-only. Guarded so a core write/helper module
# cannot silently introduce a model/network/UI dependency. Add new such helpers here.
CORE_UTILITY_SEEDS = ["sidecars", "goals"]


def _module_path(modname: str, src: pathlib.Path) -> pathlib.Path | None:
    """Resolve a dorian submodule name (``"loop"`` or ``"checkers.base"``) to a file.

    Returns the module file, the package ``__init__.py``, or ``None`` if the name does not
    resolve to a file/package (e.g. it is a symbol re-exported from a package ``__init__``).
    """
    rel = modname.replace(".", "/")
    f = src / (rel + ".py")
    if f.exists():
        return f
    init = src / rel / "__init__.py"
    if init.exists():
        return init
    return None


def _module_level_import_nodes(tree: ast.Module) -> list[ast.stmt]:
    """Import/ImportFrom nodes that execute at MODULE LOAD time — i.e. not inside a
    function body. Imports nested in top-level ``if``/``try``/``with``/``class`` blocks
    count (they run at import); imports inside ``def``/``async def`` do NOT.

    This is deliberate: Dorian's own convention is to hide optional or heavy dependencies
    behind *function-local* imports (e.g. ``anthropic`` in ``extract.py``, the lazy
    ``bindings``/``strength`` imports in ``seal.py``) precisely so the module import
    surface stays clean and the core installs with zero runtime dependencies. NN1 is about
    what loads when you ``import`` a verdict module, so the firewall scans the import-time
    surface. A function-local optional import is the sanctioned escape hatch — and it is
    backstopped in depth by the empty ``[project].dependencies`` (a function-local
    ``import anthropic`` would simply ``ImportError`` in a clean core install)."""
    nodes: list[ast.stmt] = []

    def visit(parent: ast.AST) -> None:
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue  # do not descend into function bodies
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                nodes.append(child)
            visit(child)

    visit(tree)
    return nodes


def _scan(path: pathlib.Path, src: pathlib.Path) -> tuple[set[str], set[str]]:
    """Return ``(internal_submodules, external_roots)`` imported at MODULE LEVEL by one file.

    ``internal_submodules`` are dorian-relative dotted names (``"checkers.base"``);
    ``external_roots`` are top-level non-dorian package roots (``"json"``, ``"anthropic"``).
    Handles absolute (``from dorian import x`` / ``from dorian.a.b import y`` / ``import
    dorian.x``) and, defensively, relative imports (``from . import x``) even though the
    current core uses only absolute imports. Function-local imports are intentionally
    ignored (see ``_module_level_import_nodes``).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    internal: set[str] = set()
    external: set[str] = set()
    # dorian-relative package of this file, e.g. checkers/base.py -> ["checkers"]
    rel_parts = path.relative_to(src).with_suffix("").parts
    pkg_parts = list(rel_parts[:-1])

    for node in _module_level_import_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == PKG:
                    if len(parts) > 1:
                        internal.add(".".join(parts[1:]))  # import dorian.a.b -> a.b
                else:
                    external.add(parts[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # relative import: resolve against this file's package position
                drop = node.level - 1
                base = pkg_parts[: len(pkg_parts) - drop] if drop else pkg_parts
                tail = node.module.split(".") if node.module else []
                mod_parts = [*base, *tail]
                if mod_parts:
                    internal.add(".".join(mod_parts))
                for alias in node.names:
                    internal.add(".".join([*mod_parts, alias.name]) if mod_parts else alias.name)
                continue
            parts = (node.module or "").split(".")
            if parts[0] == PKG:
                if len(parts) > 1:
                    internal.add(".".join(parts[1:]))  # from dorian.a.b import x -> a.b
                else:
                    # from dorian import gitio, store -> {gitio, store}. NB: a bare
                    # `import dorian` (handled above) and `from dorian import *` are not
                    # followed — the core uses neither; a future star-import into a verdict
                    # module would be a known blind spot to close if it ever appears.
                    for alias in node.names:
                        internal.add(alias.name)
            elif parts[0]:
                external.add(parts[0])
    return internal, external


def external_imports(seeds: list[str], src: pathlib.Path = SRC) -> dict[str, list[str]]:
    """Map each external import root reachable from ``seeds`` to the sorted list of source
    files (relative to ``src``) that import it. Follows dorian.* edges transitively."""
    if not src.is_dir():
        # Fail loudly instead of passing vacuously if the core source tree is missing or
        # the repo layout changed — a silent empty result would defeat the guard.
        raise FileNotFoundError(f"deterministic-core source tree not found: {src}")
    seen: set[str] = set()
    stack: list[str] = list(seeds)
    sites: dict[str, set[str]] = {}

    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        path = _module_path(name, src)
        if path is None:
            # Not a file/package (e.g. a symbol re-exported from a package __init__,
            # or a bare package dir without __init__). Expand a dir if one exists.
            d = src / name.replace(".", "/")
            if d.is_dir():
                for f in sorted(d.rglob("*.py")):
                    _absorb(f, src, sites, stack, seen)
            continue
        targets = [path]
        if path.name == "__init__.py":
            # a package seed: scan every module in the package, not just __init__
            targets += [p for p in sorted(path.parent.rglob("*.py")) if p != path]
        for t in targets:
            _absorb(t, src, sites, stack, seen)

    return {root: sorted(files) for root, files in sorted(sites.items())}


def _absorb(
    f: pathlib.Path,
    src: pathlib.Path,
    sites: dict[str, set[str]],
    stack: list[str],
    seen: set[str],
) -> None:
    internal, external = _scan(f, src)
    rel = f.relative_to(src).as_posix()
    for root in external:
        sites.setdefault(root, set()).add(rel)
    stack.extend(m for m in internal if m not in seen)


def test_no_model_or_network_on_verdict_path():
    """The deterministic verdict path imports nothing model/network/UI-shaped."""
    reachable = external_imports(VERDICT_SEEDS)
    offenders = {root: files for root, files in reachable.items() if root in FORBIDDEN}
    assert not offenders, (
        "Forbidden import(s) reachable from Dorian's deterministic verdict path "
        f"(seeds={VERDICT_SEEDS}):\n"
        + "\n".join(
            f"  - {root!r} imported by: {', '.join(files)}" for root, files in offenders.items()
        )
        + "\nThe verification path must stay model-free, network-free, and UI-free "
        "(Non-Negotiable #1, zero-dependency core). Move the dependency OUT of core "
        "(into extract/adapters/pane) or behind a function-local optional import."
    )


def test_firewall_detects_planted_forbidden_imports():
    """Negative control: the walker catches a forbidden import — directly AND through a
    transitive dorian.* edge — so a future violation cannot pass silently. Uses a synthetic
    source tree (no production code is edited, no fragile re-import of this test module)."""
    with tempfile.TemporaryDirectory() as tmp:
        fake = pathlib.Path(tmp) / "dorian"
        fake.mkdir()
        # loop imports a forbidden root directly, and pulls in store via a dorian.* edge
        (fake / "loop.py").write_text(
            "import anthropic\nfrom dorian import store\nimport json\n", encoding="utf-8"
        )
        # store (reached transitively) imports another forbidden root
        (fake / "store.py").write_text("from openai import OpenAI\n", encoding="utf-8")

        reachable = external_imports(["loop"], src=fake)

        assert "anthropic" in reachable, "direct forbidden import not detected"
        assert "openai" in reachable, "transitive forbidden import (loop -> store) not detected"
        assert reachable["anthropic"] == ["loop.py"]
        assert reachable["openai"] == ["store.py"]
        assert set(reachable) & FORBIDDEN == {"anthropic", "openai"}
        # stdlib imports are recorded but are NOT forbidden
        assert "json" in reachable and "json" not in FORBIDDEN


def test_core_utility_modules_stay_stdlib_only():
    """`dorian.sidecars` and `dorian.goals` are deterministic-core helpers — not on the
    verdict path (so not in VERDICT_SEEDS), but they must also stay stdlib-only. Guard them
    explicitly so a core helper cannot silently introduce a model/network/UI dependency, and
    confirm each is actually scanned (not an unguarded orphan)."""
    reachable = external_imports(CORE_UTILITY_SEEDS)
    scanned = {f for files in reachable.values() for f in files}
    for mod in CORE_UTILITY_SEEDS:
        assert f"{mod}.py" in scanned, f"dorian.{mod} not scanned — orphan core module?"
    offenders = sorted(set(reachable) & FORBIDDEN)
    assert not offenders, f"forbidden import in core utility module(s): {offenders}"
