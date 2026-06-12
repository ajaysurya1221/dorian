"""Born-verifiable data-check suggestions (datachecks.suggest + CLI wiring).

Every suggested program must PASS the real C5 checker against the exact data
state it was derived from; seeded drift must flip the matching suggestion to
FAIL. Suggestions are emitted ONLY in grammar c5_data.py's parser accepts.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dorian import datachecks
from dorian.capture.manual import parse_manual
from dorian.checkers.base import CheckContext, CheckResult, Verdict, run_checker
from dorian.cli import main
from dorian.model import CheckerSpec, Claim, ReadSetEntry, lf_normalize, sha256_hex
from dorian.seal import SealError, seal_artifact

LOTS = "data/lots.csv"


def run_all(repo: Path, path: str, suggestions: list[dict]) -> dict[str, CheckResult]:
    """Execute every suggestion through the real C5 checker; verdicts by program."""
    specs = tuple(CheckerSpec.from_dict(s) for s in suggestions)
    entry = ReadSetEntry(
        id="r1",
        uri=path,
        selector=None,
        hash=sha256_hex(lf_normalize((repo / path).read_bytes())),
        version=None,
    )
    claim = Claim(
        id="cl1",
        text="data claim",
        kind="quantity",
        load_bearing=True,
        supports=("r1",),
        checkers=specs,
    )
    ctx = CheckContext(repo=repo, claim=claim, supports=[entry])
    return {specs[i].program: run_checker(ctx, i) for i in range(len(specs))}


def run_one(repo: Path, path: str, suggestion: dict) -> CheckResult:
    return next(iter(run_all(repo, path, [suggestion]).values()))


def by_program(suggestions: list[dict]) -> dict[str, dict]:
    return {s["program"]: s for s in suggestions}


# --- csv: born-verifiable suggestions --------------------------------------------


def test_csv_suggestions_cover_expected_forms(fixture_repo):
    programs = [s["program"] for s in datachecks.suggest(fixture_repo, LOTS)]
    assert f"rowcount:{LOTS}::== 4" in programs
    assert f"schema:{LOTS}::lot_id,site,status,loaded_at" in programs
    assert f"domain:{LOTS}::status::{{closed,open}}" in programs
    assert f"freshness:{LOTS}::loaded_at::>= 2026-01-04" in programs
    assert f"snapshot:{LOTS}" in programs


def test_csv_suggestions_are_c5_shaped(fixture_repo):
    for s in datachecks.suggest(fixture_repo, LOTS):
        assert s["type"] == "C5"
        assert s["watch"] == [LOTS]


def test_csv_every_suggestion_passes_the_real_checker(fixture_repo):
    suggestions = datachecks.suggest(fixture_repo, LOTS)
    results = run_all(fixture_repo, LOTS, suggestions)
    bad = {p: r for p, r in results.items() if r.verdict is not Verdict.PASS}
    assert not bad, bad


def test_csv_null_free_columns_get_nullrate_zero(fixture_repo):
    programs = [s["program"] for s in datachecks.suggest(fixture_repo, LOTS)]
    for col in ("lot_id", "site", "status", "loaded_at"):
        assert f"nullrate:{LOTS}::{col}::<= 0.0" in programs


def test_csv_nullrate_bound_rounds_up_and_passes(fixture_repo):
    # 1 null of 3 rows: 0.3333... must round UP to 0.3334 (born-verifiable bound)
    (fixture_repo / "data" / "q.csv").write_text("a,b\n1,x\n,y\n3,z\n")
    suggestions = datachecks.suggest(fixture_repo, "data/q.csv")
    progs = by_program(suggestions)
    program = "nullrate:data/q.csv::a::<= 0.3334"
    assert program in progs
    assert run_one(fixture_repo, "data/q.csv", progs[program]).verdict is Verdict.PASS


def test_csv_column_with_nulls_gets_no_domain_suggestion(fixture_repo):
    # C5 domain observes the raw cell set (nulls included as ''), so a domain
    # suggestion on a null-bearing column could never be born-verifiable
    (fixture_repo / "data" / "q.csv").write_text("a,b\n1,x\n,y\n3,z\n")
    programs = [s["program"] for s in datachecks.suggest(fixture_repo, "data/q.csv")]
    assert not any(p.startswith("domain:data/q.csv::a") for p in programs)
    assert "domain:data/q.csv::b::{x,y,z}" in programs


def test_csv_high_cardinality_column_gets_no_domain(fixture_repo):
    rows = "".join(f"v{i},k\n" for i in range(13))
    (fixture_repo / "data" / "wide.csv").write_text("a,b\n" + rows)
    programs = [s["program"] for s in datachecks.suggest(fixture_repo, "data/wide.csv")]
    assert not any(p.startswith("domain:data/wide.csv::a") for p in programs)
    assert "domain:data/wide.csv::b::{k}" in programs


# --- csv: representability guard (programs must survive the real C5 parser) ------


def test_newline_bearing_domain_value_skips_domain_and_all_pass(fixture_repo):
    # a quoted CSV cell legally embeds a newline; emitted in a {...} domain it
    # would be bad_program at birth (the domain grammar is single-line)
    (fixture_repo / "data" / "nl.csv").write_text('a,b\n"x\ny",k\n"x\ny",k\n')
    suggestions = datachecks.suggest(fixture_repo, "data/nl.csv")
    programs = [s["program"] for s in suggestions]
    assert not any(p.startswith("domain:data/nl.csv::a") for p in programs)
    assert "domain:data/nl.csv::b::{k}" in programs
    results = run_all(fixture_repo, "data/nl.csv", suggestions)
    bad = {p: r for p, r in results.items() if r.verdict is not Verdict.PASS}
    assert not bad, bad


def test_comma_bearing_column_name_skipped_and_all_pass(fixture_repo):
    # 'a,x' in the schema list would re-split into phantom columns and FAIL at birth
    (fixture_repo / "data" / "comma.csv").write_text('"a,x",b\n1,2\n')
    suggestions = datachecks.suggest(fixture_repo, "data/comma.csv")
    programs = [s["program"] for s in suggestions]
    assert "schema:data/comma.csv::b" in programs
    assert not any("a,x" in p for p in programs)
    results = run_all(fixture_repo, "data/comma.csv", suggestions)
    bad = {p: r for p, r in results.items() if r.verdict is not Verdict.PASS}
    assert not bad, bad


def test_double_colon_column_name_skipped_and_all_pass(fixture_repo):
    # 'a::x' changes the '::' part count and would ERROR at birth
    (fixture_repo / "data" / "colons.csv").write_text("a::x,b\n1,2\n")
    suggestions = datachecks.suggest(fixture_repo, "data/colons.csv")
    programs = [s["program"] for s in suggestions]
    assert "schema:data/colons.csv::b" in programs
    assert not any("a::x" in p for p in programs)
    results = run_all(fixture_repo, "data/colons.csv", suggestions)
    bad = {p: r for p, r in results.items() if r.verdict is not Verdict.PASS}
    assert not bad, bad


# --- csv: seeded violations flip the matching suggestion to FAIL -----------------


def test_dropped_row_fails_rowcount(fixture_repo):
    progs = by_program(datachecks.suggest(fixture_repo, LOTS))
    p = fixture_repo / LOTS
    p.write_text("".join(p.read_text().splitlines(keepends=True)[:-1]))  # drop a row
    res = run_one(fixture_repo, LOTS, progs[f"rowcount:{LOTS}::== 4"])
    assert res.verdict is Verdict.FAIL


def test_nulled_cell_fails_nullrate(fixture_repo):
    progs = by_program(datachecks.suggest(fixture_repo, LOTS))
    p = fixture_repo / LOTS
    p.write_text(p.read_text().replace("L002,berlin,", "L002,,"))
    res = run_one(fixture_repo, LOTS, progs[f"nullrate:{LOTS}::site::<= 0.0"])
    assert res.verdict is Verdict.FAIL


def test_out_of_domain_value_fails_domain(fixture_repo):
    progs = by_program(datachecks.suggest(fixture_repo, LOTS))
    p = fixture_repo / LOTS
    p.write_text(p.read_text() + "L005,delft,pending,2026-01-05\n")
    res = run_one(fixture_repo, LOTS, progs[f"domain:{LOTS}::status::{{closed,open}}"])
    assert res.verdict is Verdict.FAIL


# --- the advertised round trip: paste the fragment into claims.json, seal --------


def test_pasted_suggestions_seal_without_prewired_supports(fixture_repo):
    """Regression: the advertised round trip (suggest -> review -> paste into a
    claim's "checkers" list -> seal) once ERRORED at seal on the snapshot
    suggestion (no_support_entry) unless the claim ALSO supports-bound the data
    file's read-set entry — a requirement neither the fragment nor the help
    mentioned. Seal now auto-binds the whole-file entry for the snapshot path."""
    suggestions = datachecks.suggest(fixture_repo, LOTS)
    claim = Claim(
        id="d-csv",
        text="the lots dataset matches its captured state",
        kind="quantity",
        load_bearing=False,
        checkers=tuple(CheckerSpec.from_dict(s) for s in suggestions),  # verbatim paste
    )
    rs = parse_manual([LOTS], fixture_repo)  # data file captured in the read-set
    w = seal_artifact(fixture_repo, "docs/design.md", rs, [claim])
    assert (fixture_repo / "docs/design.md.warrant").is_file()
    assert rs.entries[0].id in w.claims[0].supports  # auto-bound for snapshot:<path>


def test_snapshot_without_readset_entry_refuses_with_remedy(fixture_repo):
    """When the read-set has NO entry for the snapshot path, the seal still
    refuses (born-verifiable) — but the error now names the remedy."""
    claim = Claim(
        id="d-csv",
        text="the lots dataset matches its captured state",
        kind="quantity",
        load_bearing=False,
        checkers=(CheckerSpec(type="C5", program=f"snapshot:{LOTS}", watch=(LOTS,)),),
    )
    rs = parse_manual(["src/auth.py"], fixture_repo)  # data file NOT captured
    with pytest.raises(SealError, match="supports-bind"):
        seal_artifact(fixture_repo, "docs/design.md", rs, [claim])
    assert not (fixture_repo / "docs/design.md.warrant").exists()


# --- sqlite: reconcile-form programs (the only sqlite grammar c5_data accepts) ---


def _make_db(repo: Path) -> str:
    con = sqlite3.connect(repo / "data" / "lots.db")
    con.execute("CREATE TABLE lots (lot_id TEXT, site TEXT, status TEXT, loaded_at TEXT)")
    con.executemany(
        "INSERT INTO lots VALUES (?,?,?,?)",
        [
            ("L001", "athens", "open", "2026-01-01"),
            ("L002", None, "closed", "2026-01-02"),
            ("L003", "athens", "open", "2026-01-03"),
            ("L004", "cairo", "open", "2026-01-04"),
        ],
    )
    con.commit()
    con.close()
    return "data/lots.db"


def test_sqlite_suggestions_are_accepted_and_pass(fixture_repo):
    db = _make_db(fixture_repo)
    suggestions = datachecks.suggest(fixture_repo, db)
    programs = [s["program"] for s in suggestions]
    rowcount = f'reconcile:sqlite:{db}::SELECT COUNT(*) FROM "lots"~~sqlite:{db}::SELECT 4'
    assert rowcount in programs
    assert f"snapshot:{db}" in programs
    # only grammar c5_data accepts for sqlite: reconcile sides (plus snapshot)
    assert all(p.startswith(("reconcile:sqlite:", "snapshot:")) for p in programs)
    results = run_all(fixture_repo, db, suggestions)
    bad = {p: r for p, r in results.items() if r.verdict is not Verdict.PASS}
    assert not bad, bad


def test_sqlite_inserted_row_fails_rowcount(fixture_repo):
    db = _make_db(fixture_repo)
    progs = by_program(datachecks.suggest(fixture_repo, db))
    rowcount = f'reconcile:sqlite:{db}::SELECT COUNT(*) FROM "lots"~~sqlite:{db}::SELECT 4'
    con = sqlite3.connect(fixture_repo / db)
    con.execute("INSERT INTO lots VALUES ('L005','delft','open','2026-01-05')")
    con.commit()
    con.close()
    assert run_one(fixture_repo, db, progs[rowcount]).verdict is Verdict.FAIL


def test_sqlite_out_of_domain_value_fails_domain(fixture_repo):
    db = _make_db(fixture_repo)
    progs = by_program(datachecks.suggest(fixture_repo, db))
    domain = next(p for p in progs if "NOT IN" in p and '"status"' in p)
    con = sqlite3.connect(fixture_repo / db)
    con.execute("UPDATE lots SET status = 'pending' WHERE lot_id = 'L001'")
    con.commit()
    con.close()
    assert run_one(fixture_repo, db, progs[domain]).verdict is Verdict.FAIL


# --- parquet (optional duckdb engine) ---------------------------------------------


def test_parquet_suggestions_pass(fixture_repo):
    duckdb = pytest.importorskip("duckdb")
    src = (fixture_repo / LOTS).as_posix()
    dst = (fixture_repo / "data" / "lots.parquet").as_posix()
    con = duckdb.connect()
    con.execute(f"COPY (SELECT * FROM read_csv_auto('{src}')) TO '{dst}' (FORMAT PARQUET)")
    con.close()
    suggestions = datachecks.suggest(fixture_repo, "data/lots.parquet")
    programs = [s["program"] for s in suggestions]
    assert "rowcount:data/lots.parquet::== 4" in programs
    results = run_all(fixture_repo, "data/lots.parquet", suggestions)
    bad = {p: r for p, r in results.items() if r.verdict is not Verdict.PASS}
    assert not bad, bad


# --- column filtering -------------------------------------------------------------


def test_columns_filter_limits_column_suggestions(fixture_repo):
    programs = [s["program"] for s in datachecks.suggest(fixture_repo, LOTS, columns=["status"])]
    assert f"nullrate:{LOTS}::status::<= 0.0" in programs
    assert not any("::site::" in p for p in programs)
    assert not any("::loaded_at::" in p for p in programs)
    # table-level suggestions are not column-filtered
    assert f"rowcount:{LOTS}::== 4" in programs
    assert f"schema:{LOTS}::lot_id,site,status,loaded_at" in programs
    assert f"snapshot:{LOTS}" in programs


def test_unknown_requested_column_is_a_value_error(fixture_repo):
    with pytest.raises(ValueError):
        datachecks.suggest(fixture_repo, LOTS, columns=["nope"])


# --- input errors -----------------------------------------------------------------


def test_unsupported_extension_raises_value_error(fixture_repo):
    with pytest.raises(ValueError):
        datachecks.suggest(fixture_repo, "docs/design.md")


def test_missing_file_raises_value_error(fixture_repo):
    with pytest.raises(ValueError):
        datachecks.suggest(fixture_repo, "data/nope.csv")


# --- CLI: dorian suggest-data-checks ----------------------------------------------


def cli(repo: Path, *argv: str) -> int:
    return main(["--repo", str(repo), *argv])


def test_cli_prints_json_fragment_and_writes_out(fixture_repo, tmp_path, capsys):
    out = tmp_path / "suggested.json"
    rc = cli(fixture_repo, "suggest-data-checks", LOTS, "--out", str(out))
    assert rc == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert list(payload) == ["checkers"]
    assert payload["checkers"]
    assert all(c["type"] == "C5" for c in payload["checkers"])
    assert out.read_text() == stdout


def test_cli_output_is_deterministic(fixture_repo, capsys):
    assert cli(fixture_repo, "suggest-data-checks", LOTS) == 0
    first = capsys.readouterr().out
    assert cli(fixture_repo, "suggest-data-checks", LOTS) == 0
    assert capsys.readouterr().out == first


def test_cli_columns_flag(fixture_repo, capsys):
    rc = cli(fixture_repo, "suggest-data-checks", LOTS, "--columns", "status,loaded_at")
    assert rc == 0
    programs = [c["program"] for c in json.loads(capsys.readouterr().out)["checkers"]]
    assert any("::status::" in p for p in programs)
    assert any("::loaded_at::" in p for p in programs)
    assert not any("::site::" in p for p in programs)


def test_cli_out_into_missing_directory_exits_2(fixture_repo, tmp_path, capsys):
    # an unwritable --out is a usage error: one-line stderr + exit 2, no traceback
    out = tmp_path / "no_such_dir" / "suggested.json"
    rc = cli(fixture_repo, "suggest-data-checks", LOTS, "--out", str(out))
    assert rc == 2
    err = capsys.readouterr().err
    assert err.strip() and "\n" not in err.strip()  # one-line stderr


def test_cli_unsupported_extension_exits_2(fixture_repo, capsys):
    assert cli(fixture_repo, "suggest-data-checks", "docs/design.md") == 2
    err = capsys.readouterr().err
    assert err.strip() and "\n" not in err.strip()  # one-line stderr


def test_cli_missing_file_exits_2(fixture_repo, capsys):
    assert cli(fixture_repo, "suggest-data-checks", "data/nope.csv") == 2
    assert capsys.readouterr().err.strip()
