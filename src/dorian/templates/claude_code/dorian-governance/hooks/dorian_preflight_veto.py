"""Claude Code PreToolUse veto for the Dorian governance adapter.

Blocks a mutating tool call when Dorian's last loop decision is ESCALATE. This host hook —
not `dorian gate` — is where the exit-2 tool-blocking veto lives (Dorian's own commands only
ever emit contract codes 0/4). It FAILS CLOSED under strict modes (unattended / godmode) and
on a stale, mismatched, or missing decision packet; it fails OPEN in attended modes so a human
at the keyboard is never trapped. Stdlib only. It reads the ephemeral packet the SubagentStop
hook wrote to .dorian/local/last-decision.json — it is not a sandbox.

Env: DORIAN_POLICY (cautious|assist|unattended), DORIAN_EFFORT (godmode => strict),
DORIAN_REPO_ROOT, DORIAN_BASE, DORIAN_NONCE (must match the stamped packet under strict mode).
"""

import json
import os
import sys
import time

FRESH_SECONDS = 900  # a decision packet older than this is treated as stale


def main() -> int:
    mode = os.environ.get("DORIAN_POLICY", "assist")
    strict = mode == "unattended" or os.environ.get("DORIAN_EFFORT") == "godmode"
    try:
        tool = json.load(sys.stdin)
        path = (tool.get("tool_input") or {}).get("file_path", "")
    except Exception:
        return 2 if strict else 0  # malformed tool input: blocked under strict modes
    try:
        with open(".dorian/local/last-decision.json", encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        if strict:  # FAIL CLOSED: no fresh packet under unattended / godmode
            sys.stderr.write("Dorian VETO: no fresh decision packet under strict mode.")
            return 2
        return 0  # attended: a human is present, do not trap the agent
    stale = (time.time() - d.get("created_at_epoch", 0)) > FRESH_SECONDS
    # Defaults MUST match how the SubagentStop hook stamps the packet (os.getcwd() and ""),
    # or an unset DORIAN_REPO_ROOT/DORIAN_NONCE would false-mismatch and block every tool.
    mismatch = (
        d.get("repo_root") != os.environ.get("DORIAN_REPO_ROOT", os.getcwd())
        or d.get("base_ref") != os.environ.get("DORIAN_BASE")
        or d.get("nonce") != os.environ.get("DORIAN_NONCE", "")
    )
    if strict and (stale or mismatch):
        sys.stderr.write("Dorian VETO: stale or mismatched decision packet under strict mode.")
        return 2
    sensitive = any(b.get("sensitive") for b in d.get("broken_claims", []))
    if d.get("decision") == "escalate" and (strict or sensitive or not path):
        reason = d.get("human_escalation", {}).get("reason", "escalate")
        sys.stderr.write("Dorian VETO: " + reason)
        return 2  # exit-2 tool-block lives HERE in the host hook, never in `dorian gate`
    return 0


if __name__ == "__main__":
    sys.exit(main())
