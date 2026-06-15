"""Deterministic Python structural comparisons over the stdlib `ast` (no execution).

Backs the C3 structural subgrammars `py-signature:` and `py-const:`. Both parse the
target file's AST and compare *structure* / *literal values*, so they are tolerant
of formatting (whitespace, quote style, integer base) and cannot be satisfied by a
mention in a comment, docstring, or dead string literal — the documented weak-verdict
ceiling of `symbol:`/`string:`/`regex:`.

Each entry point returns ``(verdict, detail)`` where ``verdict`` is ``"PASS"`` /
``"FAIL"`` / ``"ERROR"`` (the caller maps to ``CheckResult``). The split mirrors the
checker contract exactly:
- **FAIL** — a real drift: the function/constant is gone, or its signature/value no
  longer matches the claim.
- **ERROR** — the checker could not run: an unparseable target, a malformed program,
  or a non-literal constant whose value cannot be compared. ERROR is never a vacuous
  PASS and never a false FAIL.

This module imports only ``ast``; it neither imports nor executes the target.
"""

from __future__ import annotations

import ast
import io
import tokenize

# ast.parse on a pathological (but importable) file can blow these without a
# SyntaxError; treat them as "could not run", never as drift.
_PARSE_ERRORS = (SyntaxError, ValueError, RecursionError, MemoryError)

_SCOPE_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def code_only_python(text: str) -> str | None:
    """Return `text` with comments and docstrings blanked to spaces (line count and
    column offsets preserved), or None if it is not parseable Python.

    Real string literals — a route path in a dict key, a call argument, a decorator
    argument — are KEPT: only ``#`` comments and bare-string docstring statements are
    removed. This is what makes `code:` reject a fact that survives only in a comment
    or docstring while still matching the same fact in actual code.
    """
    tree = _parse(text)
    if tree is None:
        return None
    buf = [list(line) for line in text.split("\n")]

    def blank(sl: int, sc: int, el: int, ec: int) -> None:
        """Blank the half-open span (sl,sc)..(el,ec) to spaces. Lines 1-based, cols 0-based."""
        for ln in range(sl, el + 1):
            if ln - 1 >= len(buf):
                break
            row = buf[ln - 1]
            lo = sc if ln == sl else 0
            hi = ec if ln == el else len(row)
            for i in range(lo, min(hi, len(row))):
                row[i] = " "

    # Docstrings: the first body statement of a module/class/function that is a bare string
    # OR f-string expression. Blank by the NODE's span (not the whole line), so a real string
    # literal co-located on the docstring's physical line is preserved; an f-string docstring
    # (ast.JoinedStr) is blanked just like a plain one.
    for node in ast.walk(tree):
        if not isinstance(node, _SCOPE_NODES):
            continue
        body = getattr(node, "body", None)
        if not (isinstance(body, list) and body and isinstance(body[0], ast.Expr)):
            continue
        val = body[0].value
        is_doc = (isinstance(val, ast.Constant) and isinstance(val.value, str)) or isinstance(
            val, ast.JoinedStr
        )
        if is_doc and val.end_lineno is not None and val.end_col_offset is not None:
            blank(val.lineno, val.col_offset, val.end_lineno, val.end_col_offset)

    # Comments: char-accurate via tokenize.
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                blank(tok.start[0], tok.start[1], tok.end[0], tok.end[1])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass  # ast parsed cleanly; a tokenizer hiccup leaves best-effort blanking
    return "\n".join("".join(row) for row in buf)


def _parse(text: str) -> ast.Module | None:
    try:
        return ast.parse(text)
    except _PARSE_ERRORS:
        return None


def _find_def(tree: ast.Module, qualname: str) -> ast.AST | None:
    """Resolve a dotted qualname (``A.method``) to its def node, last definition
    winning (runtime rebinding semantics). Descends ClassDef/FunctionDef bodies."""
    node: ast.AST = tree
    parts = qualname.split(".")
    for part in parts:
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            return None
        match: ast.AST | None = None
        for child in body:
            if (
                isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                and child.name == part
            ):
                match = child  # last wins
        if match is None:
            return None
        node = match
    return node


def _find_assign(tree: ast.Module, qualname: str) -> ast.expr | None:
    """Resolve a dotted constant name (``C.LIMIT``) to its assigned RHS value node,
    last assignment winning. Walks into ClassDef containers for the dotted prefix."""
    parts = qualname.split(".")
    *containers, name = parts
    if not name:
        return None
    node: ast.AST = tree
    for part in containers:
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            return None
        match: ast.ClassDef | None = None
        for child in body:
            if isinstance(child, ast.ClassDef) and child.name == part:
                match = child
        if match is None:
            return None
        node = match
    body = getattr(node, "body", None)
    if not isinstance(body, list):
        return None
    found: ast.expr | None = None
    for stmt in body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    found = stmt.value
        elif (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == name
            and stmt.value is not None
        ):
            found = stmt.value
    return found


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict]:
    """Normalized parameter list: name + kind, plus annotation/default source reprs
    (via ast.unparse, so spacing/quote style/int base are canonical)."""
    a = fn.args
    out: list[dict] = []
    pos = a.posonlyargs + a.args
    dmap = {
        arg.arg: ast.unparse(d)
        for arg, d in zip(pos[len(pos) - len(a.defaults) :], a.defaults, strict=False)
    }
    kwd = {
        arg.arg: ast.unparse(d)
        for arg, d in zip(a.kwonlyargs, a.kw_defaults, strict=False)
        if d is not None
    }

    def emit(args: list[ast.arg], kind: str, defaults: dict[str, str]) -> None:
        for arg in args:
            out.append(
                {
                    "name": arg.arg,
                    "kind": kind,
                    "annotation": ast.unparse(arg.annotation) if arg.annotation else None,
                    "default": defaults.get(arg.arg),
                }
            )

    emit(a.posonlyargs, "posonly", dmap)
    emit(a.args, "arg", dmap)
    if a.vararg:
        out.append(
            {
                "name": a.vararg.arg,
                "kind": "vararg",
                "annotation": ast.unparse(a.vararg.annotation) if a.vararg.annotation else None,
                "default": None,
            }
        )
    emit(a.kwonlyargs, "kwonly", kwd)
    if a.kwarg:
        out.append(
            {
                "name": a.kwarg.arg,
                "kind": "kwarg",
                "annotation": ast.unparse(a.kwarg.annotation) if a.kwarg.annotation else None,
                "default": None,
            }
        )
    return out


def _compare_params(expected: list[dict], actual: list[dict]) -> str | None:
    """Compare names/kinds/order always; annotations and defaults ONLY where the
    expected spec provided them (so a names-only spec ignores annotations)."""
    if len(expected) != len(actual):
        return f"param count {len(actual)} != expected {len(expected)}"
    for e, a in zip(expected, actual, strict=True):
        if e["name"] != a["name"] or e["kind"] != a["kind"]:
            return f"param {a['name']!r} ({a['kind']}) != expected {e['name']!r} ({e['kind']})"
        if e["annotation"] is not None and e["annotation"] != a["annotation"]:
            return (
                f"annotation of {e['name']!r}: {a['annotation']!r} != expected {e['annotation']!r}"
            )
        if e["default"] is not None and e["default"] != a["default"]:
            return f"default of {e['name']!r}: {a['default']!r} != expected {e['default']!r}"
    return None


def check_signature(text: str, needle: str) -> tuple[str, str]:
    """``needle`` is ``<qualname>::<sigspec>``. ``sigspec`` is the parameter list as
    written inside ``def f(...)`` (optionally ``-> ret``, optionally a leading
    ``async``). Compares names/kinds/order always; annotations, defaults, the return
    annotation, and async-ness only when the spec states them."""
    qualname, sep, spec = needle.partition("::")
    qualname, spec = qualname.strip(), spec.strip()
    if not sep or not qualname:
        return ("ERROR", "bad_program: py-signature needs <qualname>::<sigspec>")

    async_required = False
    if spec == "async" or spec.startswith("async "):
        async_required = True
        spec = spec[len("async") :].strip()
    if " -> " in spec:
        param_src, ret = spec.split(" -> ", 1)
        arrow = f" -> {ret.strip()}"
    else:
        param_src, arrow = spec, ""
    try:
        probe = ast.parse(f"def __dorian_probe__({param_src}){arrow}: pass")
    except _PARSE_ERRORS:
        return ("ERROR", f"bad_program: cannot parse expected signature {spec!r}")
    pfn = probe.body[0]
    if not isinstance(pfn, ast.FunctionDef):
        return ("ERROR", f"bad_program: cannot parse expected signature {spec!r}")

    tree = _parse(text)
    if tree is None:
        return ("ERROR", "target_unparseable: not parseable python")
    fn = _find_def(tree, qualname)
    if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
        return ("FAIL", f"function_missing: {qualname}")

    if async_required and not isinstance(fn, ast.AsyncFunctionDef):
        return ("FAIL", f"signature_mismatch: {qualname} is not async")
    # normalization/comparison can hit RecursionError/MemoryError on a pathological
    # (but parseable) signature, e.g. a deeply nested annotation — honor pyast's own
    # ERROR contract here rather than relying on the run_checker safety net.
    try:
        mismatch = _compare_params(_params(pfn), _params(fn))
        if mismatch:
            return ("FAIL", f"signature_mismatch: {qualname}: {mismatch}")
        if arrow:
            want_ret = ast.unparse(pfn.returns) if pfn.returns else None
            got_ret = ast.unparse(fn.returns) if fn.returns else None
            if want_ret != got_ret:
                return (
                    "FAIL",
                    f"signature_mismatch: {qualname}: return {got_ret!r} != {want_ret!r}",
                )
    except _PARSE_ERRORS:
        return ("ERROR", f"signature_uncomparable: {qualname} has a pathological signature")
    return ("PASS", f"signature ok: {qualname}")


def check_const(text: str, needle: str) -> tuple[str, str]:
    """``needle`` is ``<qualname>::<literal>``. Compares the assignment's literal
    VALUE (via ``ast.literal_eval``), so quote style / int base / spacing are
    tolerated and a comment/docstring mention cannot pass. A non-literal RHS ERRORs
    (the value cannot be determined), never a vacuous PASS."""
    qualname, sep, expected = needle.partition("::")
    qualname, expected = qualname.strip(), expected.strip()
    if not sep or not qualname:
        return ("ERROR", "bad_program: py-const needs <qualname>::<value>")
    if not expected:
        return ("ERROR", "bad_program: py-const needs an expected value")
    try:
        want = ast.literal_eval(expected)
    except _PARSE_ERRORS:
        return ("ERROR", f"bad_program: expected value is not a python literal: {expected!r}")

    tree = _parse(text)
    if tree is None:
        return ("ERROR", "target_unparseable: not parseable python")
    rhs = _find_assign(tree, qualname)
    if rhs is None:
        return ("FAIL", f"const_missing: {qualname}")
    try:
        got = ast.literal_eval(rhs)
    except _PARSE_ERRORS:
        return ("ERROR", f"non_literal: {qualname} is not a literal constant")
    # value AND type must match: Python `==` conflates 30/30.0, 1/True, 0/False, so a
    # type-only drift (a bool flag becoming an int, an int becoming a float) would wrongly
    # PASS the tier sold as the strong value verifier. Compare type first.
    if type(got) is type(want) and got == want:
        return ("PASS", f"const ok: {qualname} == {expected}")
    return ("FAIL", f"const_value_mismatch: {qualname} != {expected}")
