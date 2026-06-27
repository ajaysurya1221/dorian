# Dorian claim warrants — Claude Code skill bundle

Installed by `dorian claude-code install-claim-warrants`. Contents:

```
dorian-claim-warrants/
  SKILL.md          the skill (invoked as /dorian-claim-warrants)
  README.md         this file
  examples/         good-claims.json, bad-claims.md, final-message-example.md
  templates/        change-note.md, claims.json skeletons the skill fills in
  reference/        checker-selection.md, safety-boundary.md
```

## What it does

After a coding change, invoke **`/dorian-claim-warrants`**. The skill reads your
git diff and the agent's summary, drafts `docs/changes/<slug>.md` and
`docs/changes/<slug>.claims.json` for the **checkable** facts (config values,
signatures, constants, references), and prints the exact `dorian verify` command.

**The model only drafts. `dorian verify` proves it** — deterministically and
token-free. A claim is a **DRAFT — not verified until Dorian verify passes**. Dorian
is **not a sandbox**; run it in **trusted repo**s only.

```bash
dorian verify docs/changes/<slug>.md --claims docs/changes/<slug>.claims.json \
  --strength-gate=fail --binding-gate=warn
```

Commit the resulting `.warrant`. Later, `dorian revalidate --since <base>` flips a
broken claim to `REVOKED` (exit 4).

> **Skill not showing as `/dorian-claim-warrants`?** Claude Code only registers a
> *new* top-level skills directory at startup — restart Claude Code (or start a new
> session) after the first install.

## Optional reminder hook (opt-in)

`dorian claude-code install-claim-warrants --with-hook` also scaffolds
`.claude/hooks/dorian_claim_warrants_stop.py` — a **reminder-only** Stop hook. It is
**off until you register it**. To enable, add to your project `.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command",
        "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/dorian_claim_warrants_stop.py\"" } ] }
    ]
  }
}
```

The hook only nudges (`additionalContext`); it never blocks, never runs `dorian
verify` or tests, never writes files, and never executes project code. Suppress it
for a turn with `DORIAN_CLAIM_WARRANTS_SKIP=1`.

## Settings examples

`.claude/settings.dorian-claim-warrants.review-first.example.json` pre-allows only
inspection commands (`status`, `bindings`, `bind-suggest`). The `trusted-local`
variant additionally pre-allows `verify`/`revalidate` — use it only when you trust
the local repo and review agent-emitted `claims.json` before running it. Merge the
snippet you want into your own `.claude/settings.json`; the installer never edits it
for you.
