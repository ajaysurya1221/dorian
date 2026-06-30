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
