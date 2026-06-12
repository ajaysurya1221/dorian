"""Structured data-check suggestion generator: emit C5-compatible checkers.

suggest() derives born-verifiable CheckerSpec-shaped dicts from the CURRENT
state of a data file: every suggested program PASSes the real C5 checker at
generation time. Suggestions are exactly that — a human reviews them and
pastes the keepers into a claim's "checkers" list in claims.json; nothing
here touches warrant state. The snapshot:<path> suggestion additionally needs
the claim to supports-bind the data file's read-set entry to run; seal
auto-binds that entry when the read-set has a whole-file entry for the path
(capture the data file into the read-set), so the pasted fragment seals as-is.

Grammar discipline: programs are emitted ONLY in forms c5_data.py's parser
accepts. csv/parquet use the typed forms (rowcount/schema/nullrate/domain/
freshness/snapshot); the schema grammar is plain column names (no col:type
pairs), so types are never emitted. c5_data has no typed-form support for
sqlite — its only sqlite grammar is reconcile's `sqlite:<db>::<SELECT ...>`
side — so sqlite suggestions are reconcile programs (plus snapshot). The C5
read-only authorizer denies pragma table-valued functions, so sqlite gets no
schema-presence suggestion.

Representability guard: emitted programs must survive the real C5 parser, so a
column whose NAME contains ',' (re-split by the schema grammar), '::' (changes
the program's part count), or a control character (< 0x20, corrupts the
one-line program) is deterministically skipped for the schema/nullrate/domain/
freshness forms; rowcount and snapshot are column-free and unaffected. Domain
VALUES get the same control-character guard on top of _domain_safe.

Input errors (missing/unsupported/unreadable files, unknown requested
columns) raise ValueError; the CLI maps that to a one-line stderr + exit 2.
"""

from __future__ import annotations

import csv
import re
import sqlite3
from datetime import date
from pathlib import Path

# reuse the checker's own loader and null predicate so suggestions are
# computed by the same code that will later check them
from dorian.checkers.c5_data import _is_null, _load_table

_MAX_DOMAIN_VALUES = 12
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def suggest(repo: Path, path: str, columns: list[str] | None = None) -> list[dict]:
    """C5 CheckerSpec-shaped suggestions for a repo-relative data file."""
    p = repo / path
    if not p.is_file():
        raise ValueError(f"missing data file: {path}")
    suffix = p.suffix
    if suffix in (".csv", ".parquet"):
        return _table_suggestions(path, *_load(p), columns)
    if suffix in (".sqlite", ".db"):
        return _sqlite_suggestions(p, path, columns)
    raise ValueError(f"unsupported data file extension: {path} (.csv, .sqlite/.db, .parquet)")


def _spec(program: str, path: str) -> dict:
    return {"type": "C5", "program": program, "watch": [path]}


def _load(p: Path) -> tuple[list[str], list[dict]]:
    if p.suffix == ".parquet":
        try:
            import duckdb  # noqa: F401
        except ImportError:
            raise ValueError("parquet needs duckdb: pip install dorian-vwp[data]") from None
        try:
            return _load_table(p)
        except Exception as exc:  # duckdb error types live in the optional extra
            raise ValueError(f"unreadable parquet: {exc}") from None
    try:
        return _load_table(p)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"unreadable csv: {exc}") from None


def _requested(cols: list[str], columns: list[str] | None) -> list[str]:
    """Requested columns in file order; unknown names are caller errors."""
    if columns is None:
        return cols
    unknown = sorted(set(columns) - set(cols))
    if unknown:
        raise ValueError(f"unknown column(s): {', '.join(unknown)}")
    return [c for c in cols if c in columns]


def _nullrate_bound(nulls: int, total: int) -> str:
    """Observed null rate rounded UP to 4 decimals (integer math, no float)."""
    if nulls == 0:
        return "0.0"
    k = -((-nulls * 10000) // total)  # ceil(nulls/total * 10000)
    return f"{k // 10000}.{k % 10000:04d}"


def _control_free(s: str) -> bool:
    """No control characters (< 0x20): embedded newlines/tabs are legal in
    quoted CSV but would corrupt a one-line C5 program."""
    return all(ord(ch) >= 0x20 for ch in s)


def _col_safe(name: str) -> bool:
    """Column NAME representable in the typed column grammars: survives the
    '::' program split and the schema form's comma re-split (module docstring:
    representability guard)."""
    return "," not in name and "::" not in name and _control_free(name)


def _domain_safe(value: str) -> bool:
    """Representable in the C5 domain grammar: survives `{v1,v2,...}` parsing
    (which strips values), the '::' program split, and one-line emission."""
    return (
        value == value.strip()
        and value != ""
        and "::" not in value
        and not any(ch in value for ch in ",{}")
        and _control_free(value)
    )


def _domain_values(values: list) -> list[str] | None:
    """Sorted domain set, or None when no born-verifiable domain exists. The
    checker observes the raw cell set (nulls included, as ''/None strings),
    so null-bearing columns can never pass a domain of their values."""
    if any(_is_null(v) for v in values):
        return None
    distinct = {str(v) for v in values}
    if not 0 < len(distinct) <= _MAX_DOMAIN_VALUES:
        return None
    if not all(_domain_safe(v) for v in distinct):
        return None
    return sorted(distinct)


def _freshness_bound(values: list) -> str | None:
    """Max observed ISO date, or None unless every non-null value is one."""
    dates = [str(v).strip() for v in values if not _is_null(v)]
    if not dates:
        return None
    for d in dates:
        if not _ISO_DATE_RE.fullmatch(d):
            return None
        try:
            date.fromisoformat(d)
        except ValueError:
            return None
    return max(dates)


def _table_suggestions(
    path: str, cols: list[str], rows: list[dict], columns: list[str] | None
) -> list[dict]:
    requested = _requested(cols, columns)
    out = [_spec(f"rowcount:{path}::== {len(rows)}", path)]
    safe_cols = [c for c in cols if _col_safe(c)]  # representability guard
    if safe_cols:
        out.append(_spec(f"schema:{path}::{','.join(safe_cols)}", path))
    if rows:  # zero-row data FAILs every column form (vacuous-truth guard)
        per_column = {c: [r.get(c) for r in rows] for c in requested if _col_safe(c)}
        for c, values in per_column.items():
            nulls = sum(1 for v in values if _is_null(v))
            bound = _nullrate_bound(nulls, len(values))
            out.append(_spec(f"nullrate:{path}::{c}::<= {bound}", path))
        for c, values in per_column.items():
            domain = _domain_values(values)
            if domain is not None:
                out.append(_spec(f"domain:{path}::{c}::{{{','.join(domain)}}}", path))
        for c, values in per_column.items():
            newest = _freshness_bound(values)
            if newest is not None:
                out.append(_spec(f"freshness:{path}::{c}::>= {newest}", path))
    out.append(_spec(f"snapshot:{path}", path))
    return out


# --- sqlite (reconcile grammar) ---------------------------------------------------


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_literal(v: object) -> str | None:
    """SQL literal for a domain value; None when not representable."""
    if isinstance(v, str):
        lit = "'" + v.replace("'", "''") + "'"
    elif isinstance(v, int | float) and not isinstance(v, bool):
        lit = repr(v)
    else:
        return None
    return None if "~~" in lit else lit  # '~~' would split the reconcile sides


def _reconcile(path: str, query: str, expected: str) -> str:
    return f"reconcile:sqlite:{path}::{query}~~sqlite:{path}::SELECT {expected}"


def _sqlite_table_suggestions(
    path: str, table: str, n_rows: int, per_column: dict[str, list]
) -> list[dict]:
    t = _ident(table)
    out = [_spec(_reconcile(path, f"SELECT COUNT(*) FROM {t}", str(n_rows)), path)]
    if n_rows == 0:
        return out
    for c, values in per_column.items():
        # nulls*10000 <= bound*total in integer SQL, so SQLite recomputes the
        # exact comparison the bound was derived from (born-verifiable)
        nulls = sum(1 for v in values if v is None)
        k = 0 if nulls == 0 else -((-nulls * 10000) // len(values))
        query = (
            f"SELECT SUM(CASE WHEN {_ident(c)} IS NULL THEN 1 ELSE 0 END) * 10000"
            f" <= {k} * COUNT(*) FROM {t}"
        )
        out.append(_spec(_reconcile(path, query, "1"), path))
    for c, values in per_column.items():
        distinct = sorted({v for v in values if v is not None}, key=str)
        if not 0 < len(distinct) <= _MAX_DOMAIN_VALUES:
            continue
        literals = [_sql_literal(v) for v in distinct]
        if None in literals:
            continue
        # NULL NOT IN (...) is NULL, so nulls never count as out-of-domain
        query = f"SELECT COUNT(*) FROM {t} WHERE {_ident(c)} NOT IN ({','.join(literals)})"
        out.append(_spec(_reconcile(path, query, "0"), path))
    for c, values in per_column.items():
        present = [v for v in values if v is not None]
        if not present or not all(isinstance(v, str) for v in present):
            continue
        newest = _freshness_bound(present)
        if newest is None:
            continue
        query = f"SELECT MAX({_ident(c)}) >= '{newest}' FROM {t}"
        out.append(_spec(_reconcile(path, query, "1"), path))
    return out


def _sqlite_suggestions(p: Path, path: str, columns: list[str] | None) -> list[dict]:
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            tables = [
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                    " AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
                if "~~" not in r[0]
            ]
            out: list[dict] = []
            seen_cols: set[str] = set()
            for table in tables:
                cur = con.execute(f"SELECT * FROM {_ident(table)}")
                names = [d[0] for d in cur.description]
                rows = cur.fetchall()
                cols = [c for c in names if "~~" not in c]
                seen_cols.update(cols)
                per_column = {
                    c: [row[names.index(c)] for row in rows]
                    for c in cols
                    if columns is None or c in columns
                }
                out.extend(_sqlite_table_suggestions(path, table, len(rows), per_column))
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise ValueError(f"unreadable sqlite database: {exc}") from None
    if columns is not None:
        unknown = sorted(set(columns) - seen_cols)
        if unknown:
            raise ValueError(f"unknown column(s): {', '.join(unknown)}")
    out.append(_spec(f"snapshot:{path}", path))
    return out
