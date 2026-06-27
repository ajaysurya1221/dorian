# Dorian Claim Warrants for Claude Code

A one-command Claude Code integration that turns the **checkable** facts in a
coding agent's change summary into deterministic Dorian `.warrant` receipts —
**claim warrants** — that revoke when later code makes one false. Token-free, in
your own trusted repo.

> **The model drafts. Dorian proves.** The skill (and the optional hook) only
> *draft* a change note and a `claims.json`. Sealing requires `dorian verify` to
> run each claim's deterministic checker and pass — **no model runs at check
> time, ever.** A claim is a **DRAFT — not verified until Dorian verify passes.**

## What this is

- A project-local Claude Code **skill** at
  `.claude/skills/dorian-claim-warrants/SKILL.md`, invoked as
  **`/dorian-claim-warrants`**. It reads your git diff and the agent's summary,
  drafts `docs/changes/<slug>.md` + `docs/changes/<slug>.claims.json` for the
  checkable subset (config values, signatures/defaults, constants, file/symbol
  references), and prints the exact `dorian verify` command.
- An **opt-in, reminder-only** Stop hook (`--with-hook`) that nudges Claude to
  create claim warrants at the end of a coding turn. It never blocks and never
  runs Dorian.
- Review-first settings examples.

## What this is not

- **Not** an LLM judge — no model runs at check time.
- **Not** a semantic verifier of the whole summary — it warrants only the claims
  written down, and cannot catch a lie of omission.
- **Not** a sandbox — `C4 pytest:` and `C5 shell:` checkers execute code; use it
  in **trusted repos** only.
- **Not** a replacement for tests, SAST, CI, code review, or human judgment.
- **Not** "Agent Receipts" — that protocol audits agent *actions*; Dorian warrants
  *claim truth*. See [`CLAIM_WARRANTS_VS_AGENT_RECEIPTS.md`](CLAIM_WARRANTS_VS_AGENT_RECEIPTS.md).

## Install

```bash
pip install dorian-vwp                       # or: uv tool install dorian-vwp
cd your-trusted-repo
dorian claude-code install-claim-warrants    # add --with-hook for the reminder hook
```

This scaffolds (idempotent; never overwrites without `--force`, `--dry-run` to preview):

```
.claude/skills/dorian-claim-warrants/   SKILL.md, README.md, examples/, templates/, reference/
.claude/settings.dorian-claim-warrants.review-first.example.json
.claude/settings.dorian-claim-warrants.trusted-local.example.json
.claude/hooks/dorian_claim_warrants_stop.py   (only with --with-hook; not auto-enabled)
```

Flags: `--force`, `--dry-run`, `--with-hook`, `--no-hook` (default), `--settings-only`,
`--print-next-steps`, `--target PATH`.

> **Restart Claude Code** after the first install — a *new* top-level skills
> directory registers only at startup. Then `/dorian-claim-warrants` appears.

## Invoke

After a coding change:

```
/dorian-claim-warrants
```

The skill drafts the change note and claims, then either prints the verify command
(review-first) or runs it (trusted-local).

## Review-first flow (default)

The skill drafts `docs/changes/<slug>.md` and `docs/changes/<slug>.claims.json`,
labels them **DRAFT — not verified**, and prints:

```bash
dorian verify docs/changes/<slug>.md --claims docs/changes/<slug>.claims.json \
  --strength-gate=fail --binding-gate=warn
```

You review the claims (they are executable input), then run it. Only an exit-0
`dorian verify` seals the `.warrant`.

## Trusted-local optional flow

If you trust the repo and have reviewed how the skill drafts claims, copy
`.claude/settings.dorian-claim-warrants.trusted-local.example.json` into your
`.claude/settings.json` to pre-allow `dorian verify`/`revalidate`. The skill will
then run verify itself — and report the real exit code, never claiming "verified"
unless Dorian actually sealed a warrant.

## Optional Stop hook

`dorian claude-code install-claim-warrants --with-hook` scaffolds
`.claude/hooks/dorian_claim_warrants_stop.py`. It is **off until you register it**
under `hooks.Stop` in your project `.claude/settings.json`:

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

It returns a soft `additionalContext` reminder only — never a block, so it cannot
loop. It no-ops on non-Stop events, on `stop_hook_active`, outside a git repo, when
no relevant code/config changed, when claim-warrant artifacts already exist in the
diff, or when the final message says nothing changed. It never runs `dorian verify`
or tests, never writes files, and never executes project code (its only side effect
is a read-only `git status`). Suppress it for a turn with
`DORIAN_CLAIM_WARRANTS_SKIP=1`.

## Checker selection guide

Match the checker to the claim's `kind` (truth axis). Full map in the bundled
`reference/checker-selection.md`. Quick guide:

| The summary says… | `kind` | checker `program` |
|---|---|---|
| package/config value | `quantity`/`fact` | `config-value:pyproject.toml:project.requires-python:">=3.11"` |
| a Python signature/defaults | `reference` | `py-signature:m.py::f::a, b=1 -> int` |
| a Python constant's value | `quantity` | `py-const:m.py::TIMEOUT::30` |
| symbol/path exists | `reference` | `symbol:m.py::X` / `path:pkg/p.py` |
| an anchored value | `quantity` | `regex:m.py::TIMEOUT\s*=\s*30\b` |
| a real behavior (safe test) | `behavior` | `pytest:tests/test_x.py::T` (RUNS the test) |

`--strength-gate=fail` refuses to seal a load-bearing **behavior** claim backed only
by existence, or a **quantity** value backed only by a bare existence check.

## Good vs bad claims

**Good** (specific, falsifiable): `config-value:` / `py-signature:` / `py-const:`
for no-test facts; `pytest:` for a real behavior. **Bad** (leave as prose): "cleaner",
"faster", "refactored", "updated docs", a behavior backed only by `symbol:`, a
quantity backed only by existence. See the bundled `examples/bad-claims.md`.

## Security / trust boundary

`dorian verify`/`revalidate` execute checker programs; `C4 pytest:`/`C5 shell:`
execute code. Treat an agent-emitted `claims.json` like agent-emitted code: review
it before running, and only in a **trusted** repo. In semi-trusted contexts add
`--deny-exec` (fail-closed, **not a sandbox**). Full boundary:
[`SECURITY_BOUNDARY.md`](SECURITY_BOUNDARY.md).

## Troubleshooting

- **`/dorian-claim-warrants` doesn't appear** → restart Claude Code (new skills dir
  registers at startup).
- **`dorian verify` exits 4** → a load-bearing claim is false or its checker can't
  run. Fix the claim or the code; never fake a checker.
- **`dorian verify` exits 5 (ERRORED)** → environment missing (e.g. no `pytest`).
  Fail-closed; resolve the environment.
- **The skill won't run tools** → a checked-in project skill needs the workspace
  trust dialog accepted first.

## How to commit artifacts

Commit `docs/changes/<slug>.md`, `docs/changes/<slug>.claims.json`, and — once
sealed — `docs/changes/<slug>.md.warrant`, alongside your change.

## How the GitHub Action revalidates later

On every later PR, the Dorian Action runs `dorian revalidate --since <base>` and
re-checks only the affected claims. A broken load-bearing claim folds the warrant to
`REVOKED` (exit 4) and blocks the PR, naming the claim — deterministically and
token-free. See [`action/README.md`](../action/README.md); for semi-trusted
contributors add `checker_trust: base` + `deny_exec: true`.
