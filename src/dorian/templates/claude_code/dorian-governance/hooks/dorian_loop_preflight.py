"""Claude Code SubagentStop hook for the Dorian governance adapter.

After each sub-agent turn it runs the deterministic Dorian gate (`dorian gate`, which emits
only contract codes 0/4 and a JSON decision packet), stamps run identity + wall-clock
freshness onto the packet, and writes it to the ephemeral, gitignored
.dorian/local/last-decision.json for the PreToolUse veto to read. It returns the steer as a
soft `additionalContext` nudge and never blocks at SubagentStop. Stdlib only; it fails open so
a hook error can never break the turn. The wall-clock and nonce live ONLY here, never in
Dorian core (which stays a pure, time-free, randomness-free emitter).

Wire it by exporting DORIAN_BASE (the loop's base ref) before launching the agent; optionally
DORIAN_POLICY, DORIAN_SCOPE (comma-separated globs), DORIAN_REPO_ROOT, DORIAN_NONCE.
"""

import json
import os
import subprocess
import sys
import time


def main() -> int:
    base = os.environ.get("DORIAN_BASE")
    if not base:
        return 0  # no loop window configured -> stay silent
    cmd = [
        "dorian",
        "gate",
        "--since",
        base,
        "--policy",
        os.environ.get("DORIAN_POLICY", "assist"),
        "--state-file",
        ".dorian/local/loop-state.json",
    ]
    for glob in filter(None, os.environ.get("DORIAN_SCOPE", "").split(",")):
        cmd += ["--scope", glob]
    try:
        out = subprocess.run(
            cmd, input="{}", capture_output=True, text=True, timeout=600, check=False
        )
    except Exception:
        return 0  # a hook must never break the turn
    if out.returncode not in (0, 4):
        return 0
    try:
        packet = json.loads(out.stdout)
    except Exception:
        return 0
    # The RUNNER stamps identity + freshness; wall-clock / nonce live only here.
    packet["created_at_epoch"] = int(time.time())
    packet["repo_root"] = os.environ.get("DORIAN_REPO_ROOT", os.getcwd())
    packet["base_ref"] = base
    packet["nonce"] = os.environ.get("DORIAN_NONCE", "")
    try:
        os.makedirs(".dorian/local", exist_ok=True)
        with open(".dorian/local/last-decision.json", "w", encoding="utf-8") as fh:
            json.dump(packet, fh)
    except Exception:
        return 0
    nudge = packet.get("loop_instruction") or packet.get("reason", "")
    print(
        json.dumps(
            {"hookSpecificOutput": {"hookEventName": "SubagentStop", "additionalContext": nudge}}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
