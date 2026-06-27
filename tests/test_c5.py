"""Acceptance matrix for the C5 reconciliation checker (typed data-claim grammar).

Each typed form must PASS on the intact fixture data/lots.csv and FAIL on a
seeded violation; infrastructure problems (timeout, missing engine) are ERROR.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from dorian.checkers.base import CheckContext, CheckResult, Verdict, run_checker
from dorian.model import CheckerSpec, Claim, ReadSetEntry, lf_normalize, sha256_hex

LOTS = "data/lots.csv"


def run_c5(
    repo: Path,
    program: str,
    *,
    expect: str = "exit:0",
    timeout_s: int = 30,
    supports: tuple[ReadSetEntry, ...] = (),
    rename_map: dict[str, str] | None = None,
) -> CheckResult:
    spec = CheckerSpec(type="C5", program=program, expect=expect, timeout_s=timeout_s)
    claim = Claim(id="cl1", text="data claim", kind="quantity", load_bearing=True, checkers=(spec,))
    ctx = CheckContext(
        repo=repo, claim=claim, supports=list(supports), rename_map=dict(rename_map or {})
    )
    return run_checker(ctx, 0)


def append_row(repo: Path, row: str = "L005,delft,open,2026-01-05\n") -> None:
    p = repo / LOTS
    p.write_text(p.read_text() + row)


# --- rowcount ------------------------------------------------------------------


def test_rowcount_pass(fixture_repo):
    assert run_c5(fixture_repo, f"rowcount:{LOTS}::== 4").verdict is Verdict.PASS


def test_rowcount_fail_after_appended_row(fixture_repo):
    append_row(fixture_repo)
    res = run_c5(fixture_repo, f"rowcount:{LOTS}::== 4")
    assert res.verdict is Verdict.FAIL
    assert "5" in res.detail and "4" in res.detail  # observed vs expected


def test_rowcount_other_ops(fixture_repo):
    assert run_c5(fixture_repo, f"rowcount:{LOTS}::>= 4").verdict is Verdict.PASS
    assert run_c5(fixture_repo, f"rowcount:{LOTS}::!= 4").verdict is Verdict.FAIL
    assert run_c5(fixture_repo, f"rowcount:{LOTS}::< 10").verdict is Verdict.PASS


# --- schema --------------------------------------------------------------------


def test_schema_pass_order_insensitive(fixture_repo):
    res = run_c5(fixture_repo, f"schema:{LOTS}::status,lot_id,loaded_at,site")
    assert res.verdict is Verdict.PASS


def test_schema_fail_renamed_column(fixture_repo):
    p = fixture_repo / LOTS
    p.write_text(p.read_text().replace("lot_id,site,status", "lot_id,location,status"))
    res = run_c5(fixture_repo, f"schema:{LOTS}::lot_id,site,status,loaded_at")
    assert res.verdict is Verdict.FAIL
    assert "site" in res.detail


# --- nullrate ------------------------------------------------------------------


def test_nullrate_pass(fixture_repo):
    assert run_c5(fixture_repo, f"nullrate:{LOTS}::site::<= 0.0").verdict is Verdict.PASS


def test_nullrate_fail_blanked_cell(fixture_repo):
    p = fixture_repo / LOTS
    p.write_text(p.read_text().replace("L002,berlin,", "L002,,"))
    res = run_c5(fixture_repo, f"nullrate:{LOTS}::site::<= 0.0")
    assert res.verdict is Verdict.FAIL
    assert "0.25" in res.detail


def test_nullrate_on_dropped_column_is_fail_column_missing(fixture_repo):
    p = fixture_repo / LOTS
    p.write_text(p.read_text().replace("lot_id,site,status", "lot_id,location,status"))
    res = run_c5(fixture_repo, f"nullrate:{LOTS}::site::<= 0.0")
    assert res.verdict is Verdict.FAIL
    assert "column_missing" in res.detail


# --- domain --------------------------------------------------------------------


def test_domain_pass(fixture_repo):
    res = run_c5(fixture_repo, f"domain:{LOTS}::status::{{open,closed}}")
    assert res.verdict is Verdict.PASS


def test_domain_fail_new_value(fixture_repo):
    append_row(fixture_repo, "L005,delft,pending,2026-01-05\n")
    res = run_c5(fixture_repo, f"domain:{LOTS}::status::{{open,closed}}")
    assert res.verdict is Verdict.FAIL
    assert "pending" in res.detail


# --- freshness -----------------------------------------------------------------


def test_freshness_pass(fixture_repo):
    res = run_c5(fixture_repo, f"freshness:{LOTS}::loaded_at::>= 2026-01-04")
    assert res.verdict is Verdict.PASS


def test_freshness_fail(fixture_repo):
    res = run_c5(fixture_repo, f"freshness:{LOTS}::loaded_at::>= 2027-01-01")
    assert res.verdict is Verdict.FAIL
    assert "2026-01-04" in res.detail


def test_freshness_all_null_column_is_fail(fixture_repo):
    p = fixture_repo / LOTS
    text = p.read_text()
    for day in ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"):
        text = text.replace(day, "")
    p.write_text(text)
    res = run_c5(fixture_repo, f"freshness:{LOTS}::loaded_at::>= 2026-01-01")
    assert res.verdict is Verdict.FAIL
    assert "no values" in res.detail


# --- zero-row datasets (vacuous truth guard) ------------------------------------


def _empty_lots(repo: Path) -> None:
    (repo / LOTS).write_text("lot_id,site,status,loaded_at\n")  # header only, 0 rows


def test_empty_dataset_no_rows_fails_nullrate(fixture_repo):
    _empty_lots(fixture_repo)
    res = run_c5(fixture_repo, f"nullrate:{LOTS}::site::<= 1.0")
    assert res.verdict is Verdict.FAIL
    assert "no_rows" in res.detail


def test_empty_dataset_no_rows_fails_domain(fixture_repo):
    _empty_lots(fixture_repo)
    res = run_c5(fixture_repo, f"domain:{LOTS}::status::{{open,closed}}")
    assert res.verdict is Verdict.FAIL
    assert "no_rows" in res.detail


def test_empty_dataset_no_rows_fails_freshness(fixture_repo):
    _empty_lots(fixture_repo)
    res = run_c5(fixture_repo, f"freshness:{LOTS}::loaded_at::>= 2020-01-01")
    assert res.verdict is Verdict.FAIL
    assert "no_rows" in res.detail


# --- snapshot ------------------------------------------------------------------


def _lots_entry(repo: Path) -> ReadSetEntry:
    h = sha256_hex(lf_normalize((repo / LOTS).read_bytes()))
    return ReadSetEntry(id="r1", uri=LOTS, selector=None, hash=h, version=None)


def test_snapshot_pass(fixture_repo):
    entry = _lots_entry(fixture_repo)
    res = run_c5(fixture_repo, f"snapshot:{LOTS}", supports=(entry,))
    assert res.verdict is Verdict.PASS


def test_snapshot_fail_after_modification(fixture_repo):
    entry = _lots_entry(fixture_repo)
    append_row(fixture_repo)
    res = run_c5(fixture_repo, f"snapshot:{LOTS}", supports=(entry,))
    assert res.verdict is Verdict.FAIL


def test_snapshot_error_without_support_entry(fixture_repo):
    res = run_c5(fixture_repo, f"snapshot:{LOTS}", supports=())
    assert res.verdict is Verdict.ERROR
    assert "no_support_entry" in res.detail


# --- reconcile -----------------------------------------------------------------


def _make_lots_db(repo: Path) -> None:
    con = sqlite3.connect(repo / "data" / "lots.db")
    con.execute("CREATE TABLE lots (lot_id TEXT)")
    con.executemany("INSERT INTO lots VALUES (?)", [("L001",), ("L002",), ("L003",), ("L004",)])
    con.commit()
    con.close()


RECONCILE = f"reconcile:csv:{LOTS}~~sqlite:data/lots.db::SELECT COUNT(*) FROM lots"


def test_reconcile_pass(fixture_repo):
    _make_lots_db(fixture_repo)
    assert run_c5(fixture_repo, RECONCILE).verdict is Verdict.PASS


def test_reconcile_fail_after_csv_drift(fixture_repo):
    _make_lots_db(fixture_repo)
    append_row(fixture_repo)
    res = run_c5(fixture_repo, RECONCILE)
    assert res.verdict is Verdict.FAIL
    assert "5" in res.detail and "4" in res.detail


def test_reconcile_sqlite_bad_query_is_error_bad_program(fixture_repo):
    _make_lots_db(fixture_repo)
    prog = f"reconcile:csv:{LOTS}~~sqlite:data/lots.db::SELECT * FROM nonexistent"
    res = run_c5(fixture_repo, prog)
    assert res.verdict is Verdict.ERROR
    assert "bad_program" in res.detail


def test_reconcile_sqlite_attach_write_escape_is_blocked(fixture_repo):
    _make_lots_db(fixture_repo)
    evil = fixture_repo.parent / "evil.db"
    prog = f"reconcile:csv:{LOTS}~~sqlite:data/lots.db::ATTACH 'file:{evil}?mode=rwc' AS e"
    res = run_c5(fixture_repo, prog)
    assert res.verdict is Verdict.ERROR
    assert not evil.exists()  # read-only contract: no file created outside the repo


def test_reconcile_sqlite_pathological_query_is_error_quickly(fixture_repo, monkeypatch):
    """A recursive CTE is permitted by the read-only authorizer (SQLITE_RECURSIVE is a
    read op) and runs unbounded, so without a per-query bound it hangs the process even
    under --deny-exec (typed C5 is deliberately not deny-exec-gated; only shell: is). The
    progress-handler deadline must ERROR(query_timeout) quickly — never PASS/FAIL, never
    hang. The cap is patched tiny so the test is fast and default-independent."""
    import time as _time

    from dorian.checkers import c5_data as c5_mod

    _make_lots_db(fixture_repo)
    monkeypatch.setattr(c5_mod, "_SQLITE_QUERY_TIMEOUT_S", 0.5)
    cte = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c"
    prog = f"reconcile:csv:{LOTS}~~sqlite:data/lots.db::{cte}"

    start = _time.monotonic()
    res = run_c5(fixture_repo, prog)
    elapsed = _time.monotonic() - start

    assert res.verdict is Verdict.ERROR
    assert "query_timeout" in res.detail
    assert elapsed < 10, "per-query timeout did not bound the recursive CTE"


# --- shell ---------------------------------------------------------------------

GREP_TIMEOUT = 'shell:grep -Eq "TIMEOUT *= *30" src/config.py'


def _break_timeout(repo: Path) -> None:
    p = repo / "src" / "config.py"
    p.write_text(p.read_text().replace("TIMEOUT = 30", "TIMEOUT = 10"))


def test_shell_exit_pass_then_fail(fixture_repo):
    assert run_c5(fixture_repo, GREP_TIMEOUT).verdict is Verdict.PASS
    _break_timeout(fixture_repo)
    assert run_c5(fixture_repo, GREP_TIMEOUT).verdict is Verdict.FAIL


def test_shell_regex_pass_then_fail(fixture_repo):
    prog, exp = "shell:cat src/config.py", r"regex:TIMEOUT *= *30"
    assert run_c5(fixture_repo, prog, expect=exp).verdict is Verdict.PASS
    _break_timeout(fixture_repo)
    assert run_c5(fixture_repo, prog, expect=exp).verdict is Verdict.FAIL


def test_shell_eq_pass_then_fail(fixture_repo):
    assert run_c5(fixture_repo, "shell:printf hello", expect="eq:hello").verdict is Verdict.PASS
    assert run_c5(fixture_repo, "shell:printf hello", expect="eq:world").verdict is Verdict.FAIL


def test_shell_timeout_is_error(fixture_repo):
    res = run_c5(fixture_repo, "shell:sleep 2", timeout_s=1)
    assert res.verdict is Verdict.ERROR


# --- engines / infrastructure --------------------------------------------------


def test_parquet_without_duckdb_is_engine_missing(fixture_repo, monkeypatch):
    (fixture_repo / "data" / "lots.parquet").write_bytes(b"PAR1")
    monkeypatch.setitem(sys.modules, "duckdb", None)  # force ImportError on import
    res = run_c5(fixture_repo, "rowcount:data/lots.parquet::== 4")
    assert res.verdict is Verdict.ERROR
    assert "engine_missing" in res.detail


def test_missing_data_file_is_fail_file_gone(fixture_repo):
    (fixture_repo / LOTS).unlink()
    res = run_c5(fixture_repo, f"rowcount:{LOTS}::== 4")
    assert res.verdict is Verdict.FAIL
    assert "file_gone" in res.detail


def test_malformed_programs_are_error_bad_program(fixture_repo):
    for prog in (
        f"rowcount:{LOTS}::~ 4",  # bad comparator
        f"rowcount:{LOTS}::== four",  # non-integer bound
        f"frobnicate:{LOTS}",  # unknown form
        f"nullrate:{LOTS}::site",  # missing comparator part
        "reconcile:csv:data/lots.csv",  # missing ~~ side
    ):
        res = run_c5(fixture_repo, prog)
        assert res.verdict is Verdict.ERROR, prog
        assert "bad_program" in res.detail, prog


def test_path_escaping_repo_is_error_bad_program(fixture_repo):
    outside = fixture_repo.parent / "secret.csv"
    outside.write_text("a\n1\n")
    res = run_c5(fixture_repo, "rowcount:../secret.csv::== 1")
    assert res.verdict is Verdict.ERROR
    assert "bad_program" in res.detail


def test_reconcile_side_escaping_repo_is_error_bad_program(fixture_repo):
    outside = fixture_repo.parent / "secret.csv"
    outside.write_text("a\n1\n")
    res = run_c5(fixture_repo, f"reconcile:csv:../secret.csv~~csv:{LOTS}")
    assert res.verdict is Verdict.ERROR
    assert "bad_program" in res.detail


def test_paths_resolve_through_rename_map(fixture_repo):
    (fixture_repo / LOTS).rename(fixture_repo / "data" / "lots_v2.csv")
    res = run_c5(
        fixture_repo,
        f"rowcount:{LOTS}::== 4",
        rename_map={LOTS: "data/lots_v2.csv"},
    )
    assert res.verdict is Verdict.PASS


# --- freshness false-PASS regression (non-date values, invalid bound) -----------


def test_freshness_nondate_value_is_fail_not_false_pass(fixture_repo):
    # a non-date value lexicographically sorts ABOVE any real date; the old string
    # `max(values) >= bound` returned PASS on garbage. It must now FAIL, never PASS,
    # even against a far-future bound the real data could not satisfy.
    append_row(fixture_repo, "L099,delft,open,zzzz\n")
    res = run_c5(fixture_repo, f"freshness:{LOTS}::loaded_at::>= 2099-01-01")
    assert res.verdict is Verdict.FAIL
    assert "non-date" in res.detail


def test_freshness_invalid_bound_is_error(fixture_repo):
    res = run_c5(fixture_repo, f"freshness:{LOTS}::loaded_at::>= notadate")
    assert res.verdict is Verdict.ERROR
    assert "bad_program" in res.detail


# --- C5 shell expect hardening (ReDoS + unbounded output) ------------------------


def test_shell_expect_regex_catastrophic_is_error_not_hang(fixture_repo):
    # a catastrophic-backtracking expect-regex against adversarial stdout must be
    # bounded by the same spawned-worker timeout C3 uses — ERROR, never a hang.
    prog = "shell:printf '" + "a" * 40 + "b'"
    res = run_c5(fixture_repo, prog, expect="regex:(a+)+$", timeout_s=1)
    assert res.verdict is Verdict.ERROR
    assert "regex" in res.detail.lower()


def test_shell_expect_eq_mismatch_bounds_observed_output(fixture_repo):
    # a shell command can print a huge/sensitive stdout; the eq-mismatch detail must
    # be bounded so it cannot bloat or leak the full output through the renderers.
    prog = "shell:printf '" + "X" * 300 + "'"
    res = run_c5(fixture_repo, prog, expect="eq:NOPE")
    assert res.verdict is Verdict.FAIL
    assert "X" * 200 in res.detail and "X" * 201 not in res.detail
