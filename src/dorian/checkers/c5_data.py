"""C5 reconciliation checker: typed data-claim grammar (first-class data governance).

Program forms (separator '::'):
  rowcount:<path>::<op><int>             schema:<path>::col1,col2,...
  nullrate:<path>::<col>::<op><float>    domain:<path>::<col>::{v1,v2,...}
  freshness:<path>::<col>::>= <ISO-date> snapshot:<path>
  reconcile:<sideA>~~<sideB>             shell:<command>   (judged by spec.expect)

Shell programs are opaque commands judged only by spec.expect; shape-tolerant
matching (reformat-survivable facts) belongs to the typed forms above and to
C3's regex: grammar.

Verdict semantics: FAIL means the data no longer supports the claim; checker
infrastructure problems (timeout, missing engine, bad program) are ERROR.
Vacuous-truth guard: nullrate/domain/freshness FAIL with 'no_rows' on a
zero-row dataset — an empty dataset cannot support a data claim.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

from dorian.checkers import registry
from dorian.checkers.base import CheckContext, CheckResult, Verdict, resolve_path, run_readonly
from dorian.model import CheckerSpec, lf_normalize, sha256_hex


class _BadProgram(Exception):
    pass


class _FileGone(Exception):
    pass


class _EngineMissing(Exception):
    pass


class _ColumnGone(Exception):
    pass


_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}

_CMP_RE = re.compile(r"^(==|!=|>=|<=|>|<)\s*(\S+)$")
_FRESHNESS_RE = re.compile(r"^>=\s*(\S+)$")
_DOMAIN_RE = re.compile(r"^\{(.*)\}$")


def _parts(rest: str, n: int, form: str) -> list[str]:
    parts = rest.split("::")
    if len(parts) != n:
        raise _BadProgram(f"{form} expects {n} '::'-separated parts, got {len(parts)}")
    return parts


def _parse_cmp(s: str, conv: type) -> tuple[str, int | float]:
    m = _CMP_RE.match(s.strip())
    if not m:
        raise _BadProgram(f"bad comparator: {s!r}")
    try:
        return m.group(1), conv(m.group(2))
    except ValueError:
        raise _BadProgram(f"bad comparator bound: {s!r}") from None


def _data_path(ctx: CheckContext, uri: str) -> Path:
    p = resolve_path(ctx, uri)
    if not p.resolve().is_relative_to(ctx.repo.resolve()):  # same guard as C3
        raise _BadProgram(f"path escapes repo: {uri!r}")
    if not p.is_file():
        raise _FileGone(uri)
    return p


def _load_table(path: Path) -> tuple[list[str], list[dict]]:
    """(columns, rows-as-dicts). csv via stdlib; .parquet via optional duckdb."""
    if path.suffix == ".parquet":
        try:
            import duckdb
        except ImportError:
            raise _EngineMissing from None
        con = duckdb.connect()
        try:
            rel = con.execute("SELECT * FROM read_parquet(?)", [str(path)])
            cols = [d[0] for d in rel.description]
            return cols, [dict(zip(cols, row, strict=True)) for row in rel.fetchall()]
        finally:
            con.close()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _column(cols: list[str], rows: list[dict], column: str) -> list:
    if column not in cols:
        raise _ColumnGone(column)
    return [r.get(column) for r in rows]


def _is_null(v: object) -> bool:
    return v is None or str(v).strip() == ""


# --- typed forms ---------------------------------------------------------------


def _rowcount(ctx: CheckContext, rest: str) -> CheckResult:
    uri, cmp_s = _parts(rest, 2, "rowcount")
    op, bound = _parse_cmp(cmp_s, int)
    _, rows = _load_table(_data_path(ctx, uri))
    n = len(rows)
    if _OPS[op](n, bound):
        return CheckResult(Verdict.PASS, detail=f"rowcount {n} {op} {bound}")
    return CheckResult(Verdict.FAIL, detail=f"rowcount observed={n} expected {op} {bound}")


def _schema(ctx: CheckContext, rest: str) -> CheckResult:
    uri, cols_s = _parts(rest, 2, "schema")
    wanted = {c.strip() for c in cols_s.split(",") if c.strip()}
    if not wanted:
        raise _BadProgram("schema needs at least one column")
    cols, _ = _load_table(_data_path(ctx, uri))
    missing = sorted(wanted - set(cols))
    if not missing:
        return CheckResult(Verdict.PASS, detail=f"all columns present: {sorted(wanted)}")
    return CheckResult(Verdict.FAIL, detail=f"missing columns {missing}, observed {cols}")


def _nullrate(ctx: CheckContext, rest: str) -> CheckResult:
    uri, column, cmp_s = _parts(rest, 3, "nullrate")
    op, bound = _parse_cmp(cmp_s, float)
    cols, rows = _load_table(_data_path(ctx, uri))
    if not rows:
        return CheckResult(Verdict.FAIL, detail=f"no_rows: {uri} is empty")
    values = _column(cols, rows, column)
    rate = sum(1 for v in values if _is_null(v)) / len(values)
    if _OPS[op](rate, bound):
        return CheckResult(Verdict.PASS, detail=f"nullrate({column}) {rate:.4g} {op} {bound}")
    return CheckResult(
        Verdict.FAIL, detail=f"nullrate({column}) observed={rate:.4g} expected {op} {bound}"
    )


def _domain(ctx: CheckContext, rest: str) -> CheckResult:
    uri, column, set_s = _parts(rest, 3, "domain")
    m = _DOMAIN_RE.match(set_s.strip())
    if not m:
        raise _BadProgram(f"domain expects {{v1,v2,...}}, got {set_s!r}")
    allowed = {v.strip() for v in m.group(1).split(",") if v.strip()}
    cols, rows = _load_table(_data_path(ctx, uri))
    if not rows:
        return CheckResult(Verdict.FAIL, detail=f"no_rows: {uri} is empty")
    observed = {str(v) for v in _column(cols, rows, column)}
    bad = sorted(observed - allowed)
    if not bad:
        return CheckResult(Verdict.PASS, detail=f"{column} values within {sorted(allowed)}")
    return CheckResult(
        Verdict.FAIL, detail=f"{column} values {bad} outside domain {sorted(allowed)}"
    )


def _freshness(ctx: CheckContext, rest: str) -> CheckResult:
    uri, column, bound_s = _parts(rest, 3, "freshness")
    m = _FRESHNESS_RE.match(bound_s.strip())
    if not m:
        raise _BadProgram(f"freshness expects '>= <ISO-date>', got {bound_s!r}")
    bound = m.group(1)
    cols, rows = _load_table(_data_path(ctx, uri))
    if not rows:
        return CheckResult(Verdict.FAIL, detail=f"no_rows: {uri} is empty")
    values = [str(v).strip() for v in _column(cols, rows, column) if not _is_null(v)]
    if not values:
        return CheckResult(Verdict.FAIL, detail=f"no values in column {column}")
    newest = max(values)
    if newest >= bound:
        return CheckResult(Verdict.PASS, detail=f"max({column})={newest} >= {bound}")
    return CheckResult(Verdict.FAIL, detail=f"max({column}) observed={newest} expected >= {bound}")


def _snapshot(ctx: CheckContext, rest: str) -> CheckResult:
    uri = rest.strip()
    if not uri:
        raise _BadProgram("snapshot needs a data path")
    entry = next((e for e in ctx.supports if e.uri == uri), None)
    if entry is None:
        return CheckResult(
            Verdict.ERROR,
            detail=(
                f"no_support_entry: {uri}"
                " (the claim must supports-bind a read-set entry for this path;"
                " seal auto-binds it when the read-set has a whole-file entry)"
            ),
        )
    observed = sha256_hex(lf_normalize(_data_path(ctx, uri).read_bytes()))
    if observed == entry.hash:
        return CheckResult(Verdict.PASS, detail=f"snapshot matches {entry.hash}")
    return CheckResult(Verdict.FAIL, detail=f"snapshot observed={observed} expected={entry.hash}")


# mode=ro only protects the main database; the authorizer blocks write escapes
# (e.g. ATTACH 'file:...?mode=rwc') so the program stays read-only end to end.
_SQLITE_READ_OPS = frozenset(
    {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
)


def _deny_non_read(op: int, *_: object) -> int:
    return sqlite3.SQLITE_OK if op in _SQLITE_READ_OPS else sqlite3.SQLITE_DENY


def _reconcile_side(ctx: CheckContext, side: str) -> int:
    engine, _, body = side.strip().partition(":")
    if engine == "csv":
        _, rows = _load_table(_data_path(ctx, body))
        return len(rows)
    if engine == "sqlite":
        db_uri, sep, query = body.partition("::")
        if not sep or not query.strip():
            raise _BadProgram(f"sqlite side expects '<db-path>::<SELECT query>', got {side!r}")
        path = _data_path(ctx, db_uri)
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            con.set_authorizer(_deny_non_read)
            row = con.execute(query).fetchone()
        except sqlite3.Error as exc:
            raise _BadProgram(f"sqlite query failed: {exc}") from None
        finally:
            con.close()
        if row is None:
            raise _BadProgram(f"sqlite query returned no rows: {query!r}")
        return row[0]
    raise _BadProgram(f"unknown reconcile engine: {engine!r}")


def _reconcile(ctx: CheckContext, rest: str) -> CheckResult:
    if "~~" not in rest:
        raise _BadProgram("reconcile expects '<sideA>~~<sideB>'")
    a_s, b_s = rest.split("~~", 1)
    a, b = _reconcile_side(ctx, a_s), _reconcile_side(ctx, b_s)
    if a == b:
        return CheckResult(Verdict.PASS, detail=f"reconciled: {a} == {b}")
    return CheckResult(
        Verdict.FAIL, detail=f"reconcile mismatch: {a_s.strip()}={a} {b_s.strip()}={b}"
    )


# --- shell ---------------------------------------------------------------------


def _shell(ctx: CheckContext, spec: CheckerSpec, cmd: str) -> CheckResult:
    if not cmd.strip():
        raise _BadProgram("empty shell command")
    rc, out, err = run_readonly(cmd, cwd=ctx.repo, timeout_s=spec.timeout_s, shell=True)
    if rc is None:  # timeout or spawn failure: infra, never FAIL
        return CheckResult(Verdict.ERROR, detail=f"shell did not complete: {err.strip()}")
    mode, _, arg = spec.expect.partition(":")
    if spec.expect == "exit:0":
        if rc == 0:
            return CheckResult(Verdict.PASS, detail="exit 0")
        return CheckResult(Verdict.FAIL, detail=f"exit code {rc}: {err.strip()[:200]}")
    if mode == "regex":
        try:
            pattern = re.compile(arg)
        except re.error as exc:
            raise _BadProgram(f"bad regex {arg!r}: {exc}") from None
        if pattern.search(out):
            return CheckResult(Verdict.PASS, detail=f"stdout matched {arg!r}")
        return CheckResult(Verdict.FAIL, detail=f"regex {arg!r} not found in stdout")
    if mode == "eq":
        if out.strip() == arg:
            return CheckResult(Verdict.PASS, detail=f"stdout == {arg!r}")
        return CheckResult(Verdict.FAIL, detail=f"stdout observed={out.strip()!r} expected={arg!r}")
    raise _BadProgram(f"unknown expect: {spec.expect!r}")


# --- dispatch ------------------------------------------------------------------

_FORMS = {
    "rowcount": _rowcount,
    "schema": _schema,
    "nullrate": _nullrate,
    "domain": _domain,
    "freshness": _freshness,
    "snapshot": _snapshot,
    "reconcile": _reconcile,
}


def check(ctx: CheckContext, spec: CheckerSpec) -> CheckResult:
    form, sep, rest = spec.program.partition(":")
    try:
        if form == "shell":
            return _shell(ctx, spec, rest)
        handler = _FORMS.get(form)
        if handler is None or not sep:
            raise _BadProgram(f"unknown program form: {spec.program!r}")
        return handler(ctx, rest)
    except _BadProgram as exc:
        return CheckResult(Verdict.ERROR, detail=f"bad_program: {exc}")
    except _EngineMissing:
        return CheckResult(Verdict.ERROR, detail="engine_missing: pip install dorian-vwp[data]")
    except _FileGone as exc:
        return CheckResult(Verdict.FAIL, detail=f"file_gone: {exc}")
    except _ColumnGone as exc:
        return CheckResult(Verdict.FAIL, detail=f"column_missing: {exc}")


registry.register("C5", check)
