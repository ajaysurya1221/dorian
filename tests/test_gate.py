"""Tests for `dorian gate` — a host-mappable preflight body.

`dorian gate` reuses the existing Loop Guard preflight and emits ONLY Dorian contract exit
codes (0, or 4 under --fail-on). It NEVER uses exit 2 as a REPAIR/ESCALATE veto — exit 2 is
reserved for malformed input / usage. The host-hook exit-2 veto mapping belongs to a later
task, not to this command. The loop preflight path is exercised end-to-end by the existing
loop tests; here we stub `_run_loop_preflight` to prove the gate's wiring deterministically.
"""

import io
import json

from dorian import cli, commands


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def _packet(decision: str) -> dict:
    # minimal but field-shaped like LoopDecision.to_dict()
    return {
        "schema_version": 1,
        "decision": decision,
        "reason": f"stub {decision}",
        "policy": "assist",
        "notes": [],
    }


def _run_gate(monkeypatch, tmp_path, *, decision, fail_on=None, stdin='{"tool_input": {}}'):
    monkeypatch.setattr(commands.sys, "stdin", io.StringIO(stdin))
    monkeypatch.setattr(commands, "_run_loop_preflight", lambda args: (_packet(decision), 0))
    argv = ["--repo", str(tmp_path), "gate", "--since", "HEAD"]
    if fail_on is not None:
        argv += ["--fail-on", fail_on]
    return commands.cmd_gate(_ns(*argv))


# --- output + reuse --------------------------------------------------------------------


def test_gate_prints_loopdecision_json_and_reuses_preflight(tmp_path, monkeypatch, capsys):
    rc = _run_gate(monkeypatch, tmp_path, decision="continue")
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["decision"] == "continue"
    assert "reason" in payload  # the real LoopDecision packet, not a host-hook shape
    assert rc == 0


# --- default exit codes: a decision NEVER blocks by itself ------------------------------


def test_gate_continue_default_exit_0(tmp_path, monkeypatch):
    assert _run_gate(monkeypatch, tmp_path, decision="continue") == 0


def test_gate_repair_default_exit_0(tmp_path, monkeypatch):
    assert _run_gate(monkeypatch, tmp_path, decision="repair") == 0


def test_gate_escalate_default_exit_0(tmp_path, monkeypatch):
    assert _run_gate(monkeypatch, tmp_path, decision="escalate") == 0


# --- --fail-on opts into a hard exit 4 (never 2) ---------------------------------------


def test_gate_escalate_fail_on_escalate_exit_4(tmp_path, monkeypatch):
    assert _run_gate(monkeypatch, tmp_path, decision="escalate", fail_on="escalate") == 4


def test_gate_repair_fail_on_repair_exit_4(tmp_path, monkeypatch):
    assert _run_gate(monkeypatch, tmp_path, decision="repair", fail_on="repair") == 4


def test_gate_escalate_fail_on_repair_exit_4(tmp_path, monkeypatch):
    # repair threshold means "repair or worse"
    assert _run_gate(monkeypatch, tmp_path, decision="escalate", fail_on="repair") == 4


def test_gate_continue_fail_on_escalate_exit_0(tmp_path, monkeypatch):
    assert _run_gate(monkeypatch, tmp_path, decision="continue", fail_on="escalate") == 0


def test_gate_repair_fail_on_escalate_exit_0(tmp_path, monkeypatch):
    # repair is below the escalate threshold -> not blocked
    assert _run_gate(monkeypatch, tmp_path, decision="repair", fail_on="escalate") == 0


def test_no_valid_decision_path_returns_2(tmp_path, monkeypatch):
    for decision in ("continue", "repair", "escalate"):
        for fail_on in (None, "never", "repair", "escalate"):
            rc = _run_gate(monkeypatch, tmp_path, decision=decision, fail_on=fail_on)
            assert rc in (0, 4), f"{decision}/{fail_on} -> {rc}; valid decisions must never be 2"


# --- malformed stdin: usage error, NOT a policy veto -----------------------------------


def test_malformed_stdin_json_is_usage_error_not_a_veto(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(commands.sys, "stdin", io.StringIO("{ not json"))

    def _must_not_run(args):
        raise AssertionError("preflight must not run on malformed stdin")

    monkeypatch.setattr(commands, "_run_loop_preflight", _must_not_run)
    rc = commands.cmd_gate(_ns("--repo", str(tmp_path), "gate", "--since", "HEAD"))
    out = capsys.readouterr().out
    assert rc == 2  # EXIT_USAGE — malformed input, explicitly NOT a REPAIR/ESCALATE veto
    assert out.strip() == ""  # no fake LoopDecision packet printed


# --- preflight errors pass through with existing fail-closed semantics ------------------


def test_gate_passes_through_preflight_usage_error(tmp_path, monkeypatch):
    monkeypatch.setattr(commands.sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(commands, "_run_loop_preflight", lambda args: (None, 2))
    rc = commands.cmd_gate(_ns("--repo", str(tmp_path), "gate", "--since", "HEAD"))
    assert rc == 2  # propagated usage error (e.g. bad ref), not invented


def test_gate_passes_through_preflight_sidecar_error(tmp_path, monkeypatch):
    monkeypatch.setattr(commands.sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(commands, "_run_loop_preflight", lambda args: (None, 4))
    rc = commands.cmd_gate(_ns("--repo", str(tmp_path), "gate", "--since", "HEAD"))
    assert rc == 4  # fail-closed evidence (corrupt sidecar), existing loop semantics


# --- host-hook boundary: gate is NOT the Claude Code hook ------------------------------


def test_gate_emits_no_host_hook_json_and_writes_no_files(tmp_path, monkeypatch, capsys):
    rc = _run_gate(monkeypatch, tmp_path, decision="escalate", fail_on="escalate")
    out = capsys.readouterr().out
    assert "hookSpecificOutput" not in out
    assert "PreToolUse" not in out
    assert "additionalContext" not in out
    assert not (tmp_path / ".claude").exists()  # gate creates no hook files
    assert rc == 4
