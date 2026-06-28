"""Loop preflight: the deterministic CONTINUE / REPAIR / ESCALATE decision packet.

Reuses the shared fixture repo and the 4 demo claims from test_revalidate (_sealed):
  c1  load-bearing  C1 span over src/auth.py   (relocates on rename, never breaks here)
  c2  load-bearing  C5 shell  TIMEOUT == 30     (breaks when src/config.py drifts)
  c3  NON-load-bearing  C3 string /v1/login     (breaks when the route is removed)
  c4  NON-load-bearing  C5 rowcount             (untouched here)

So a config edit breaks exactly one LOAD-BEARING claim; a routes edit breaks exactly one
NON-load-bearing claim; --deny-shell makes the C5 shell ERROR instead of run.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import CONFIG_PY, ROUTES_PY, write
from dorian import cli, commands, gitio
from test_revalidate import _sealed


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def _preflight(capsys, repo: Path, base: str, *extra: str) -> tuple[int, dict]:
    rc = commands.cmd_loop(
        _ns("--repo", str(repo), "loop", "preflight", "--since", base, "--format", "json", *extra)
    )
    return rc, json.loads(capsys.readouterr().out)


def _break_config(repo: Path) -> None:
    write(repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))


def _break_route(repo: Path) -> None:
    write(repo, "src/routes.py", ROUTES_PY.replace('    "/v1/login": "auth.login",\n', ""))


# --- continue --------------------------------------------------------------------


def test_clean_change_continues(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)  # nothing changed since HEAD
    rc, data = _preflight(capsys, fixture_repo, base)
    assert rc == 0
    assert data["decision"] == "continue"
    assert data["candidates"] == 0
    assert data["broken_claims"] == []
    assert data["human_escalation"]["required"] is False


# --- repair (load-bearing break) -------------------------------------------------


def test_load_bearing_break_repairs(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)
    rc, data = _preflight(capsys, fixture_repo, base, "--policy", "assist")
    assert rc == 0  # default --fail-on never: preflight does not stop the loop by itself
    assert data["decision"] == "repair"
    (c2,) = [b for b in data["broken_claims"] if b["claim_id"] == "c2"]
    assert c2["load_bearing"] is True
    assert c2["verdict"] == "BROKEN"
    assert c2["suggested_next_step"] == "repair_code"
    assert c2["trust_state"] == "REVOKED"
    assert c2["checker"] == "C5"  # checker type captured separately
    assert not c2["evidence"].startswith("C5:")  # and not doubled into the evidence text
    assert data["trust_summary"]["revoked"] == 1
    assert data["human_escalation"]["required"] is False


def test_fail_on_repair_and_escalate_gates(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)
    # decision is "repair": --fail-on repair trips the gate (exit 4); escalate does not
    rc_repair, _ = _preflight(capsys, fixture_repo, base, "--fail-on", "repair")
    assert rc_repair == 4
    rc_esc, data = _preflight(capsys, fixture_repo, base, "--fail-on", "escalate")
    assert rc_esc == 0
    assert data["decision"] == "repair"


# --- degraded (non-load-bearing break) depends on policy -------------------------


def test_non_load_bearing_break_continues_under_assist(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_route(fixture_repo)
    rc, data = _preflight(capsys, fixture_repo, base, "--policy", "assist")
    assert rc == 0
    assert data["decision"] == "continue"
    (c3,) = [b for b in data["broken_claims"] if b["claim_id"] == "c3"]
    assert c3["load_bearing"] is False
    assert data["trust_summary"]["degraded"] == 1


def test_non_load_bearing_break_repairs_under_cautious(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_route(fixture_repo)
    rc, data = _preflight(capsys, fixture_repo, base, "--policy", "cautious")
    assert data["decision"] == "repair"
    assert rc == 0


# --- escalate: ERRORED checker ---------------------------------------------------


def test_errored_checker_escalates(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)  # makes c2 a candidate
    _, data = _preflight(capsys, fixture_repo, base, "--deny-shell")
    assert data["decision"] == "escalate"
    (c2,) = [b for b in data["broken_claims"] if b["claim_id"] == "c2"]
    assert c2["verdict"] == "ERRORED"
    assert c2["suggested_next_step"] == "fix_environment"
    assert data["human_escalation"]["required"] is True
    rc_gate, _ = _preflight(capsys, fixture_repo, base, "--deny-shell", "--fail-on", "escalate")
    assert rc_gate == 4


# --- escalate: repair-attempt cap ------------------------------------------------


def test_repair_cap_escalates(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)
    _, data = _preflight(capsys, fixture_repo, base, "--max-repairs", "2", "--repair-attempts", "2")
    assert data["decision"] == "escalate"
    assert data["repair"] == {"attempts": 2, "max": 2}
    assert "infinite-fix" in data["reason"]


def test_cap_does_not_stop_non_load_bearing_under_assist(fixture_repo: Path, capsys) -> None:
    """A stale repair counter must NOT cap-escalate a non-load-bearing-only break that
    assist would otherwise `continue` past — don't stop the loop unnecessarily."""
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_route(fixture_repo)  # non-load-bearing c3 only
    _, data = _preflight(
        capsys,
        fixture_repo,
        base,
        "--policy",
        "assist",
        "--max-repairs",
        "1",
        "--repair-attempts",
        "5",
    )
    assert data["decision"] == "continue"


def test_cap_stops_non_load_bearing_under_cautious(fixture_repo: Path, capsys) -> None:
    """cautious DOES repair non-load-bearing breaks, so the cap applies to them there."""
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_route(fixture_repo)
    _, data = _preflight(
        capsys,
        fixture_repo,
        base,
        "--policy",
        "cautious",
        "--max-repairs",
        "1",
        "--repair-attempts",
        "5",
    )
    assert data["decision"] == "escalate"


# --- escalate: scope over-reach / unattended needs scope / sensitive path --------


def test_out_of_scope_break_escalates(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)  # bound to src/config.py
    _, data_out = _preflight(capsys, fixture_repo, base, "--scope", "docs/**")
    assert data_out["decision"] == "escalate"
    _, data_in = _preflight(capsys, fixture_repo, base, "--scope", "src/**")
    assert data_in["decision"] == "repair"


def test_cautious_scope_escalates_out_of_lane_non_load_bearing(fixture_repo: Path, capsys) -> None:
    """cautious repairs non-load-bearing breaks, so one outside --scope over-reaches -> escalate."""
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_route(fixture_repo)  # non-load-bearing c3, bound to src/routes.py
    _, data = _preflight(capsys, fixture_repo, base, "--policy", "cautious", "--scope", "docs/**")
    assert data["decision"] == "escalate"


def test_repair_instruction_excludes_out_of_scope_files(fixture_repo: Path, capsys) -> None:
    """An in-scope load-bearing repair must never tell the agent to touch an out-of-scope file."""
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)  # load-bearing c2, src/config.py (in scope)
    _break_route(fixture_repo)  # non-load-bearing c3, src/routes.py (out of scope)
    _, data = _preflight(
        capsys, fixture_repo, base, "--policy", "assist", "--scope", "src/config.py"
    )
    assert data["decision"] == "repair"
    assert "src/config.py" in data["loop_instruction"]
    assert "src/routes.py" not in data["loop_instruction"]


def test_repair_warns_when_cap_tracking_absent(fixture_repo: Path, capsys) -> None:
    """On a repair with no --repair-attempts/--state-file, the packet says the cap is inactive."""
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)
    _, data = _preflight(capsys, fixture_repo, base, "--policy", "assist")
    assert data["decision"] == "repair"
    assert any("infinite-fix cap inactive" in n for n in data["notes"])


def test_unattended_requires_scope(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)
    _, no_scope = _preflight(capsys, fixture_repo, base, "--policy", "unattended")
    assert no_scope["decision"] == "escalate"
    _, scoped = _preflight(
        capsys, fixture_repo, base, "--policy", "unattended", "--scope", "src/**"
    )
    assert scoped["decision"] == "repair"


def test_sensitive_denylisted_path_escalates(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)
    _, data = _preflight(capsys, fixture_repo, base, "--deny-path", "src/config.py")
    assert data["decision"] == "escalate"
    (c2,) = [b for b in data["broken_claims"] if b["claim_id"] == "c2"]
    assert c2["sensitive"] is True
    assert c2["suggested_next_step"] == "escalate"


# --- packet shape ----------------------------------------------------------------


def test_packet_shape(fixture_repo: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)
    _, d = _preflight(capsys, fixture_repo, base)
    assert d["schema_version"] == 1
    assert d["decision"] in ("continue", "repair", "escalate")
    assert set(d["trust_summary"]) == {"trusted", "warranted", "degraded", "revoked", "errored"}
    assert set(d["repair"]) == {"attempts", "max"}
    assert set(d["human_escalation"]) == {"required", "reason", "message"}
    assert d["loop_instruction"]
    assert d["sensitive_globs"]  # built-in set is echoed, never hidden
    b = d["broken_claims"][0]
    for key in (
        "artifact",
        "warrant",
        "claim_id",
        "text",
        "kind",
        "load_bearing",
        "verdict",
        "trust_state",
        "checker",
        "evidence",
        "paths",
        "sensitive",
        "in_scope",
        "suggested_next_step",
    ):
        assert key in b


def test_cli_main_dispatches_loop_preflight(fixture_repo: Path, capsys) -> None:
    """Full top-level dispatch: cli.main(argv) -> commands.cmd_loop -> preflight."""
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    rc = cli.main(
        ["--repo", str(fixture_repo), "loop", "preflight", "--since", base, "--format", "json"]
    )
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "continue"


def test_requires_since_or_changed_paths(fixture_repo: Path, capsys) -> None:
    rc = commands.cmd_loop(_ns("--repo", str(fixture_repo), "loop", "preflight"))
    assert rc == 2
    assert "exactly one of" in capsys.readouterr().err


def test_state_file_repair_attempts(fixture_repo: Path, tmp_path: Path, capsys) -> None:
    _sealed(fixture_repo)
    base = gitio.head_ref(fixture_repo)
    _break_config(fixture_repo)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"repair_attempts": 3}))
    _, data = _preflight(
        capsys, fixture_repo, base, "--max-repairs", "3", "--state-file", str(state)
    )
    assert data["decision"] == "escalate"  # 3 >= 3 -> cap
    assert data["repair"]["attempts"] == 3
