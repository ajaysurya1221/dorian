"""Tests for dorian.goals — human-authored Goal records and the `dorian goal` CLI.

Task 3 scope only: the durable Goal record + add/show CLI. It must NOT decide whether a
goal is complete and must not be wired into the verdict path (coverage_diff is Task 4).
"""

import json
from pathlib import Path

import pytest

from dorian import cli, commands, goals


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def _make_goal(**over):
    base = dict(
        goal_id="g-1",
        title="Add idempotency",
        statement="add idempotency keys to POST /orders",
        policy_ref="default-assist",
        scope=("src/payments/**",),
        deny_paths=("infra/*",),
        base_ref="main~1",
        coverage_contract={"min_strength_load_bearing": "structural"},
    )
    base.update(over)
    return goals.Goal(**base)


def test_goal_roundtrip(tmp_path):
    g = _make_goal()
    goals.save(tmp_path, g)
    loaded = goals.load(tmp_path, "g-1")
    assert loaded == g  # frozen dataclass value equality
    assert loaded.schema_version == goals.SCHEMA_VERSION
    assert loaded.statement == "add idempotency keys to POST /orders"
    assert loaded.scope == ("src/payments/**",)
    assert loaded.policy_ref == "default-assist"


def test_goal_saved_to_expected_sidecar_path(tmp_path):
    p = goals.save(tmp_path, _make_goal())
    assert p == (tmp_path / ".dorian/goals/g-1.goal.json").resolve()
    assert p.exists()


def test_goal_payload_deterministic_and_sorted(tmp_path):
    g = _make_goal()
    b1 = goals.save(tmp_path, g).read_bytes()
    b2 = goals.save(tmp_path, g).read_bytes()
    assert b1 == b2  # same record -> identical bytes
    text = b1.decode("utf-8")
    assert text.index('"base_ref"') < text.index('"goal_id"') < text.index('"statement"')


def test_schema_version_present_and_unsupported_rejected(tmp_path):
    goals.save(tmp_path, _make_goal())
    sidecar = tmp_path / ".dorian/goals/g-1.goal.json"
    data = json.loads(sidecar.read_text())
    assert data["schema_version"] == goals.SCHEMA_VERSION
    data["schema_version"] = 999
    sidecar.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        goals.load(tmp_path, "g-1")


def test_malformed_record_rejected(tmp_path):
    sidecar = tmp_path / ".dorian/goals/g-1.goal.json"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("{ not json")
    with pytest.raises(ValueError):
        goals.load(tmp_path, "g-1")


def test_base_ref_required_and_preserved(tmp_path):
    goals.save(tmp_path, _make_goal(base_ref="release/v2"))
    assert goals.load(tmp_path, "g-1").base_ref == "release/v2"
    data = json.loads((tmp_path / ".dorian/goals/g-1.goal.json").read_text())
    assert "base_ref" in data


def test_statement_and_scope_preserved_exactly(tmp_path):
    g = _make_goal(statement="exact human words; preserved verbatim", scope=("a/**", "b/**"))
    goals.save(tmp_path, g)
    loaded = goals.load(tmp_path, "g-1")
    assert loaded.statement == "exact human words; preserved verbatim"
    assert loaded.scope == ("a/**", "b/**")


def test_path_escape_refused_via_save(tmp_path):
    # goal_path is .dorian/goals/<id>.goal.json (2 levels deep) -> need 3+ ../ to escape
    with pytest.raises(ValueError):
        goals.save(tmp_path, _make_goal(goal_id="../../../escape"))


def test_cli_goal_add_creates_record(tmp_path, capsys):
    rc = commands.cmd_goal(
        _ns(
            "--repo",
            str(tmp_path),
            "goal",
            "add",
            "--id",
            "g-1",
            "--title",
            "Add idempotency",
            "--statement",
            "do X",
            "--base-ref",
            "HEAD",
            "--scope",
            "src/**",
            "--deny-path",
            "infra/*",
            "--policy-ref",
            "default-assist",
            "--min-strength",
            "structural",
        )
    )
    assert rc == 0
    assert "g-1" in capsys.readouterr().out
    g = goals.load(tmp_path, "g-1")
    assert g.title == "Add idempotency"
    assert g.scope == ("src/**",)
    assert g.deny_paths == ("infra/*",)
    assert g.base_ref == "HEAD"
    assert g.coverage_contract == {"min_strength_load_bearing": "structural"}


def test_cli_goal_show_displays_record(tmp_path, capsys):
    commands.cmd_goal(
        _ns(
            "--repo",
            str(tmp_path),
            "goal",
            "add",
            "--id",
            "g-1",
            "--title",
            "T",
            "--base-ref",
            "HEAD",
        )
    )
    capsys.readouterr()  # clear add output
    rc = commands.cmd_goal(_ns("--repo", str(tmp_path), "goal", "show", "--id", "g-1"))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["goal_id"] == "g-1"
    assert payload["title"] == "T"


def test_cli_goal_show_missing_record_is_usage_error(tmp_path):
    rc = commands.cmd_goal(_ns("--repo", str(tmp_path), "goal", "show", "--id", "nope"))
    assert rc == 2  # EXIT_USAGE — clear error, not a crash


def test_goals_not_wired_into_verdict_path():
    """goals.py imports only sidecars + stdlib; no verdict module imports goals — so the
    goal record can never feed verdict/completion/continuation logic."""
    gmod = Path(goals.__file__)
    src = gmod.read_text(encoding="utf-8")
    for forbidden in (
        "import revalidate",
        "dorian.revalidate",
        "dorian.loop",
        "_decide",
        "dorian.fold",
        "dorian.seal",
        "dorian.checkers",
        "dorian.policy",
    ):
        assert forbidden not in src, f"goals.py must not touch verdict logic: {forbidden!r}"
    pkg = gmod.parent
    for mod in ("loop.py", "revalidate.py", "fold.py", "seal.py", "policy.py"):
        text = (pkg / mod).read_text(encoding="utf-8")
        assert "goals" not in text.replace("# ", ""), f"{mod} must not reference goals"


# --- Task 4: deterministic goal<->claim coverage diff (pure function) -----------------


def test_coverage_uncovered_in_scope_without_warrant():
    g = _make_goal(scope=("src/**",))
    res = goals.coverage_diff(g, ["src/a.py"], [])
    assert res == {"covered": [], "uncovered": ["src/a.py"]}


def test_coverage_covered_exact_warrant():
    g = _make_goal(scope=("src/**",))
    res = goals.coverage_diff(g, ["src/a.py"], ["src/a.py"])
    assert res == {"covered": ["src/a.py"], "uncovered": []}


def test_coverage_out_of_scope_path_ignored():
    g = _make_goal(scope=("src/**",))
    res = goals.coverage_diff(g, ["docs/readme.md", "src/a.py"], [])
    assert res == {"covered": [], "uncovered": ["src/a.py"]}  # docs/ neither covered nor uncovered


def test_coverage_sorted_and_deduped():
    g = _make_goal(scope=("src/**",))
    res = goals.coverage_diff(g, ["src/b.py", "src/a.py", "src/a.py"], ["src/a.py"])
    assert res["covered"] == ["src/a.py"]  # deduped
    assert res["uncovered"] == ["src/b.py"]  # sorted, deduped


def test_coverage_empty_scope_means_all_changed_paths_in_scope():
    g = _make_goal(scope=())
    res = goals.coverage_diff(g, ["anywhere/x.py"], [])
    assert res["uncovered"] == ["anywhere/x.py"]


def test_coverage_normalizes_paths():
    g = _make_goal(scope=("src/**",))
    # "./src/a.py" normalizes to "src/a.py" and matches the warrant "src/a.py"
    res = goals.coverage_diff(g, ["./src/a.py"], ["src/a.py"])
    assert res == {"covered": ["src/a.py"], "uncovered": []}


def test_coverage_absolute_path_does_not_false_match_scope():
    g = _make_goal(scope=("src/**",))
    res = goals.coverage_diff(g, ["/etc/passwd"], [])
    assert res == {"covered": [], "uncovered": []}  # absolute -> out of "src/**" scope -> ignored


def test_coverage_ignores_statement_and_coverage_contract():
    a = _make_goal(scope=("src/**",), statement="alpha", coverage_contract={})
    b = _make_goal(
        scope=("src/**",),
        statement="totally different prose",
        coverage_contract={"min_strength_load_bearing": "behavioral"},
    )
    changed, warranted = ["src/a.py"], []
    assert goals.coverage_diff(a, changed, warranted) == goals.coverage_diff(b, changed, warranted)


# --- Task 4: `dorian goal check` CLI (I/O boundaries stubbed for determinism) ----------


def _seed_goal(tmp_path, scope="src/**"):
    commands.cmd_goal(
        _ns(
            "--repo",
            str(tmp_path),
            "goal",
            "add",
            "--id",
            "g-1",
            "--title",
            "T",
            "--base-ref",
            "HEAD",
            "--scope",
            scope,
        )
    )


class _FakeConn:
    def close(self):
        pass


def _stub_io(monkeypatch, *, changed, warranted):
    monkeypatch.setattr(commands.gitio, "changed_paths", lambda repo, since: (list(changed), {}))
    monkeypatch.setattr(commands.store, "connect", lambda repo: _FakeConn())
    monkeypatch.setattr(commands.store, "sync", lambda repo, conn: None)
    monkeypatch.setattr(
        commands.store, "get_warrants", lambda conn: [{"artifact_uri": p} for p in warranted]
    )


def test_cli_goal_check_prints_json_and_exits_ok_without_flag(tmp_path, monkeypatch, capsys):
    _seed_goal(tmp_path)
    capsys.readouterr()
    _stub_io(monkeypatch, changed=["src/a.py"], warranted=[])
    rc = commands.cmd_goal(
        _ns("--repo", str(tmp_path), "goal", "check", "--id", "g-1", "--since", "HEAD")
    )
    out = json.loads(capsys.readouterr().out)
    assert out == {"covered": [], "uncovered": ["src/a.py"]}
    assert rc == 0  # uncovered exists but no --fail-on-uncovered -> EXIT_OK


def test_cli_goal_check_fail_on_uncovered_returns_4(tmp_path, monkeypatch, capsys):
    _seed_goal(tmp_path)
    capsys.readouterr()
    _stub_io(monkeypatch, changed=["src/a.py"], warranted=[])
    rc = commands.cmd_goal(
        _ns(
            "--repo",
            str(tmp_path),
            "goal",
            "check",
            "--id",
            "g-1",
            "--since",
            "HEAD",
            "--fail-on-uncovered",
        )
    )
    assert rc == 4  # EXIT_REVOKED — a refusal, NOT a false claim


def test_cli_goal_check_covered_passes_under_fail_flag(tmp_path, monkeypatch, capsys):
    _seed_goal(tmp_path)
    capsys.readouterr()
    _stub_io(monkeypatch, changed=["src/a.py"], warranted=["src/a.py"])
    rc = commands.cmd_goal(
        _ns(
            "--repo",
            str(tmp_path),
            "goal",
            "check",
            "--id",
            "g-1",
            "--since",
            "HEAD",
            "--fail-on-uncovered",
        )
    )
    out = json.loads(capsys.readouterr().out)
    assert out == {"covered": ["src/a.py"], "uncovered": []}
    assert rc == 0


def test_cli_goal_check_missing_goal_is_usage_error(tmp_path):
    rc = commands.cmd_goal(
        _ns("--repo", str(tmp_path), "goal", "check", "--id", "nope", "--since", "HEAD")
    )
    assert rc == 2  # EXIT_USAGE


def test_cli_goal_check_bad_ref_is_usage_error(tmp_path, monkeypatch):
    _seed_goal(tmp_path)

    def _boom(repo, since):
        raise commands.gitio.GitError("bad revision: " + since)

    monkeypatch.setattr(commands.gitio, "changed_paths", _boom)
    rc = commands.cmd_goal(
        _ns("--repo", str(tmp_path), "goal", "check", "--id", "g-1", "--since", "nope")
    )
    assert rc == 2  # EXIT_USAGE — a bad ref is infra/usage, not a verdict
