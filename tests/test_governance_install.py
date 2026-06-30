"""Tests for `dorian governance install` — scaffolds the Claude Code governance adapter
(the two host hooks + settings example + docs) via the shared build_plan/apply machinery.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import dorian
from dorian import cli, commands

VETO_HOOK = (
    Path(dorian.__file__).parent
    / "templates/claude_code/dorian-governance/hooks/dorian_preflight_veto.py"
)

VETO = ".claude/hooks/dorian_preflight_veto.py"
STOP = ".claude/hooks/dorian_loop_preflight.py"
SETTINGS = ".claude/settings.dorian-governance.example.json"
README = ".claude/dorian-governance/README.md"
MODES = ".claude/dorian-governance/reference/enforcement-modes.md"


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def _install(capsys, repo, *extra: str):
    rc = commands.cmd_governance(
        _ns("--repo", str(repo), "--json", "governance", "install", *extra)
    )
    return rc, json.loads(capsys.readouterr().out)


def test_install_writes_hooks_settings_and_docs(tmp_path, capsys):
    rc, data = _install(capsys, tmp_path)
    assert rc == 0
    for f in (VETO, STOP, SETTINGS, README, MODES):
        assert (tmp_path / f).is_file(), f
    assert VETO in data["created"] and STOP in data["created"]


def test_veto_hook_fails_closed_and_owns_exit_2(tmp_path, capsys):
    _install(capsys, tmp_path)
    veto = (tmp_path / VETO).read_text(encoding="utf-8")
    assert "return 2" in veto  # the exit-2 tool-block veto lives in the HOST hook
    assert "strict" in veto  # fail-closed under unattended/godmode
    assert "FAIL CLOSED" in veto.upper()


def test_subagentstop_hook_shells_dorian_gate_and_emits_host_output(tmp_path, capsys):
    _install(capsys, tmp_path)
    stop = (tmp_path / STOP).read_text(encoding="utf-8")
    assert "gate" in stop  # reuses the pure `dorian gate` emitter
    assert "hookSpecificOutput" in stop  # host-side mapping lives in the hook, not in core
    assert "created_at_epoch" in stop  # runner stamps freshness (wall-clock lives here)


def test_install_idempotent_without_force(tmp_path, capsys):
    _install(capsys, tmp_path)
    (tmp_path / VETO).write_text("edited by user\n", encoding="utf-8")
    rc, data = _install(capsys, tmp_path)
    assert rc == 0
    assert VETO in data["skipped"]
    assert data["created"] == []
    assert (tmp_path / VETO).read_text(encoding="utf-8") == "edited by user\n"  # not clobbered


def test_install_force_overwrites(tmp_path, capsys):
    _install(capsys, tmp_path)
    (tmp_path / VETO).write_text("stale\n", encoding="utf-8")
    rc, data = _install(capsys, tmp_path, "--force")
    assert rc == 0
    assert VETO in data["overwritten"]
    assert "return 2" in (tmp_path / VETO).read_text(encoding="utf-8")


def test_install_dry_run_writes_nothing(tmp_path, capsys):
    rc, data = _install(capsys, tmp_path, "--dry-run")
    assert rc == 0
    assert data["dry_run"] is True
    assert VETO in data["created"]  # planned
    assert not (tmp_path / VETO).exists()  # but not written


# --- functional veto-hook tests (execute the host hook as a subprocess) ----------------


def _subprocess_cwd(tmp_path) -> str:
    out = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _run_veto(tmp_path, *, tool='{"tool_input": {"file_path": "src/x.py"}}', packet=None, env=None):
    if packet is not None:
        (tmp_path / ".dorian/local").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".dorian/local/last-decision.json").write_text(
            json.dumps(packet), encoding="utf-8"
        )
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("DORIAN_")}
    full_env.update(env or {})
    r = subprocess.run(
        [sys.executable, str(VETO_HOOK)],
        cwd=tmp_path,
        input=tool,
        capture_output=True,
        text=True,
        env=full_env,
    )
    return r.returncode


def _fresh_packet(tmp_path, *, decision, sensitive=False, base="HEAD"):
    return {
        "decision": decision,
        "created_at_epoch": int(time.time()),
        "repo_root": _subprocess_cwd(tmp_path),  # matches the veto's os.getcwd() default
        "base_ref": base,
        "nonce": "",
        "broken_claims": [{"sensitive": sensitive}],
        "human_escalation": {"reason": "needs a human"},
    }


def test_veto_strict_fresh_continue_allowed_with_default_identity(tmp_path):
    # regression for the identity-default blocker: strict + fresh + matching CONTINUE -> allow
    pkt = _fresh_packet(tmp_path, decision="continue")
    rc = _run_veto(tmp_path, packet=pkt, env={"DORIAN_POLICY": "unattended", "DORIAN_BASE": "HEAD"})
    assert rc == 0


def test_veto_strict_escalate_blocks(tmp_path):
    pkt = _fresh_packet(tmp_path, decision="escalate")
    rc = _run_veto(tmp_path, packet=pkt, env={"DORIAN_POLICY": "unattended", "DORIAN_BASE": "HEAD"})
    assert rc == 2


def test_veto_strict_missing_packet_fails_closed(tmp_path):
    rc = _run_veto(
        tmp_path, packet=None, env={"DORIAN_POLICY": "unattended", "DORIAN_BASE": "HEAD"}
    )
    assert rc == 2


def test_veto_strict_stale_packet_fails_closed(tmp_path):
    pkt = _fresh_packet(tmp_path, decision="continue")
    pkt["created_at_epoch"] = int(time.time()) - 100_000  # well past the freshness window
    rc = _run_veto(tmp_path, packet=pkt, env={"DORIAN_POLICY": "unattended", "DORIAN_BASE": "HEAD"})
    assert rc == 2


def test_veto_attended_missing_packet_fails_open(tmp_path):
    rc = _run_veto(tmp_path, packet=None, env={"DORIAN_POLICY": "assist"})
    assert rc == 0  # a human is present; don't trap the agent


def test_veto_attended_escalate_nonsensitive_allows(tmp_path):
    pkt = _fresh_packet(tmp_path, decision="escalate", sensitive=False)
    rc = _run_veto(tmp_path, packet=pkt, env={"DORIAN_POLICY": "assist", "DORIAN_BASE": "HEAD"})
    assert rc == 0


def test_veto_escalate_on_sensitive_path_blocks_even_when_attended(tmp_path):
    pkt = _fresh_packet(tmp_path, decision="escalate", sensitive=True)
    rc = _run_veto(tmp_path, packet=pkt, env={"DORIAN_POLICY": "assist", "DORIAN_BASE": "HEAD"})
    assert rc == 2
