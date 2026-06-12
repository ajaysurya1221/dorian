"""Audit export: `report --audit` emits the full event log as dorian-audit-v1 JSONL.

The export is local history (stored event times are allowed) but must add no new
timestamp, leak no source content, and keep a stable one-line-per-event schema.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import ROUTES_PY, commit_all, git, write
from dorian import cli, commands, gitio, store
from dorian.capture.manual import parse_manual
from dorian.model import CheckerSpec, Claim
from dorian.revalidate import revalidate
from dorian.seal import seal_artifact

# a distinctive source string planted inside a sealed span: it must never
# surface in the export (checker details are codes, causes are paths)
SENTINEL = "XK_AUDIT_SENTINEL_b7e2_never_in_export"

AUDIT_KEYS = {"schema", "seq", "at", "actor", "kind", "warrant_id", "claim_id", "cause"}
BARE_KINDS = {"sealed", "synced", "recalled"}


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def _export(capsys, repo: Path, *extra: str) -> list[str]:
    """Run `report --audit` through the CLI handler; return raw stdout lines."""
    rc = commands.cmd_report(_ns("--repo", str(repo), "report", "--audit", *extra))
    out = capsys.readouterr().out
    assert rc == 0
    return out.splitlines()


def _seal_tamper_revalidate(repo: Path) -> None:
    """The audit corpus: seal two checked claims, break both spans, revalidate."""
    git(repo, "config", "user.name", "dorian-test")
    write(repo, "src/notes.py", f'NOTE = "{SENTINEL}"\n')
    commit_all(repo, "plant sentinel span")
    readset = parse_manual(["src/notes.py:L1-1", "src/routes.py"], repo)
    claims = [
        Claim(
            id="c1",
            text="The note constant lives in src/notes.py.",
            kind="fact",
            load_bearing=True,
            supports=("rs-0",),
            checkers=(CheckerSpec(type="C1", program="rs-0"),),
        ),
        Claim(
            id="c2",
            text="Login is served at /v1/login.",
            kind="reference",
            load_bearing=False,
            supports=("rs-1",),
            checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
        ),
    ]
    base = gitio.head_ref(repo)
    seal_artifact(repo, "docs/design.md", readset, claims)
    write(repo, "src/notes.py", 'NOTE = "rewritten"\n')
    write(repo, "src/routes.py", ROUTES_PY.replace('    "/v1/login": "auth.login",\n', ""))
    commit_all(repo, "drift: rewrite sentinel span, drop login route")
    revalidate(repo, since=base)


def test_audit_golden_shape(fixture_repo: Path, capsys) -> None:
    _seal_tamper_revalidate(fixture_repo)
    lines = _export(capsys, fixture_repo)
    assert lines
    events = []
    for line in lines:
        ev = json.loads(line)  # every line is standalone JSON
        # one event per line, stable rendering: sorted keys, no indent
        assert line == json.dumps(ev, sort_keys=True)
        assert set(ev) == AUDIT_KEYS
        assert ev["schema"] == "dorian-audit-v1"
        assert isinstance(ev["seq"], int)
        assert ev["at"]  # stored event time, emitted as stored
        assert ev["actor"]  # non-empty on every line
        assert ev["warrant_id"]
        assert ev["claim_id"] is None or isinstance(ev["claim_id"], str)
        assert ev["cause"] is None or isinstance(ev["cause"], dict)  # parsed, not a string
        assert ev["kind"] in BARE_KINDS or ev["kind"].startswith(("claim.", "fold."))
        events.append(ev)

    seqs = [ev["seq"] for ev in events]
    assert seqs == sorted(set(seqs))  # strictly increasing

    kinds = [ev["kind"] for ev in events]
    assert "sealed" in kinds
    assert kinds.count("claim.stale") == 2
    assert kinds.count("claim.broken") == 2
    assert any(k.startswith("fold.") for k in kinds)

    # stale causes are parsed JSON carrying changed *paths*, never content
    stale_causes = [ev["cause"] for ev in events if ev["kind"] == "claim.stale"]
    assert {tuple(c["changed"]) for c in stale_causes} == {
        ("src/notes.py",),
        ("src/routes.py",),
    }


def test_audit_never_leaks_source_content(fixture_repo: Path, capsys) -> None:
    _seal_tamper_revalidate(fixture_repo)
    out = "\n".join(_export(capsys, fixture_repo))
    assert SENTINEL not in out
    # the span break surfaces as a checker code, not as span text
    assert "span_changed_or_removed" in out
    assert "string_missing" in out


def test_audit_export_is_deterministic(fixture_repo: Path, capsys) -> None:
    """Two exports of the same store are byte-identical: no new timestamps."""
    _seal_tamper_revalidate(fixture_repo)
    assert _export(capsys, fixture_repo) == _export(capsys, fixture_repo)


def test_audit_since_filter(fixture_repo: Path, capsys) -> None:
    _seal_tamper_revalidate(fixture_repo)
    conn = store.connect(fixture_repo)
    try:  # plant an ancient event: full export must include it, --since must not
        conn.execute(
            "INSERT INTO event (warrant_id, claim_id, actor, kind, cause, at)"
            " VALUES ('w-ancient', NULL, 'tester', 'recalled', NULL, '2000-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()
    full = [json.loads(line) for line in _export(capsys, fixture_repo)]
    assert "recalled" in [ev["kind"] for ev in full]  # no --since => FULL history
    recent = [json.loads(line) for line in _export(capsys, fixture_repo, "--since", "24h")]
    assert "recalled" not in [ev["kind"] for ev in recent]
    assert len(recent) == len(full) - 1


def test_audit_empty_store_zero_lines(fixture_repo: Path, capsys) -> None:
    rc = commands.cmd_report(_ns("--repo", str(fixture_repo), "report", "--audit"))
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


def test_audit_bad_since_is_usage(fixture_repo: Path, capsys) -> None:
    args = _ns("--repo", str(fixture_repo), "report", "--audit", "--since", "soon")
    rc = commands.cmd_report(args)
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    assert "dorian report:" in captured.err
    assert len(captured.err.splitlines()) == 1


def test_audit_truncates_long_cause_detail(fixture_repo: Path, capsys) -> None:
    """C5 details can embed observed data values; the export caps the carryover."""
    conn = store.connect(fixture_repo)
    try:
        store.append_event(
            conn,
            warrant_id="w-x",
            actor="tester",
            kind="claim.broken",
            cause={"detail": "v" * 500, "other": "kept"},
        )
    finally:
        conn.close()
    (line,) = _export(capsys, fixture_repo)
    ev = json.loads(line)
    assert ev["cause"]["detail"] == "v" * 160
    assert ev["cause"]["other"] == "kept"


def test_plain_report_still_defaults_to_7d(fixture_repo: Path, capsys) -> None:
    """--since stays optional for the digest path (default window unchanged)."""
    rc = commands.cmd_report(_ns("--repo", str(fixture_repo), "report"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "(7d)" in out
