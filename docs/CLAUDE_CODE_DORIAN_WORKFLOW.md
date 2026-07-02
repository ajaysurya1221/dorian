# Claude Code + Dorian — turn your agent's summary into claim warrants

> A practical workflow for Claude Code / Codex / Cursor users. When the agent finishes a change, it
> ends with a summary of specific claims. This is how to make the **checkable** subset into deterministic
> git **claim warrants** (receipts for checkable claims) that fail later if the code drifts — token-free,
> in a trusted repo.

> **One-command Claude Code setup.** `dorian claude-code install-claim-warrants` scaffolds a
> `/dorian-claim-warrants` skill (and an opt-in reminder hook) that drafts the change note + `claims.json`
> for you, then prints the `dorian verify` command. The model drafts; Dorian proves. See
> [`DORIAN_CLAIM_WARRANTS_CLAUDE_CODE_SKILL.md`](DORIAN_CLAIM_WARRANTS_CLAUDE_CODE_SKILL.md). The manual
> loop below is the same thing by hand.

## The loop

1. The agent makes the change and writes its normal summary / PR description.
2. The agent emits a small `claims.json` for **only the checkable** statements in that summary.
3. `dorian verify <change-note> --claims claims.json --strength-gate=fail` seals a `.warrant` sidecar
   (born-verifiable: it refuses to seal anything that is already false).
4. Commit the `.warrant` alongside the change.
5. On every later PR, the GitHub Action runs `dorian revalidate --since <base>`; if a later edit broke a
   sealed claim, the warrant folds to **REVOKED** (exit 4) and the Action blocks — naming the claim.

> **Claim warrants are not only post-change receipts — they are loop memory.** In an autonomous
> coding loop, the warrants you seal here become the deterministic facts the *next* iteration
> revalidates: `dorian loop preflight` re-checks them before each step and returns
> **CONTINUE / REPAIR / ESCALATE** so a stale assumption surfaces as a steering signal instead of
> rotting silently. Same mechanism, pointed forward. See
> [`DORIAN_LOOP_GUARD.md`](DORIAN_LOOP_GUARD.md) and the `/dorian-loop-guard` skill.

## How the agent should write claims

Pick the **checker whose strength matches the claim** (the truth axis). Each claim is
`{id, text, kind, load_bearing, checkers:[{type, program}]}`.

| The summary says… | kind | checker (`program`) |
|---|---|---|
| "function `f` exists in `m.py`" | reference | `C3` `symbol:m.py::f` |
| "`f`'s signature/defaults are `(a, b=1) -> int`" | reference | `C3` `py-signature:m.py::f::a, b=1 -> int` |
| "the constant `TIMEOUT` is `30`" | quantity | `C3` `py-const:m.py::TIMEOUT::30` |
| "`requires-python` is `>=3.11`" / a config default | quantity | `C3` `config-value:pyproject.toml:project.requires-python:">=3.11"` |
| "the string/route `"/admin"` is present in `r.py`" | reference | `C3` `string:r.py::/admin` or `regex:` / `code:` |
| "behavior B holds (covered by test T)" | behavior | `C4` `pytest:tests/test_x.py::T` |
| "the data file has ≥N rows / column C / freshness" | quantity/fact | `C5` `rowcount:`/`schema:`/`freshness:` |

Rule of thumb: a **behavior** claim needs a `C4` test (or it is under-verified); a **quantity** claim
needs a value-pinning checker (`py-const`/`config-value`/anchored `regex`/typed `C5`), not a bare
existence check. `--strength-gate=fail` enforces exactly this for load-bearing claims.

## Good vs bad claims

**Good (checkable, specific, falsifiable):**
- `py-signature:src/auth.py::verify_token::token, algo="RS256" -> bool`
- `config-value:pyproject.toml:project.requires-python:">=3.11"`
- `pytest:tests/test_auth.py::test_rs256_roundtrip` for "RS256 tokens verify"

**Bad (do not seal these — they are prose, not receipts):**
- "the code is cleaner / more maintainable / more performant" (not checkable)
- "this is a big improvement" (opinion)
- a **behavior** claim backed only by `symbol:` (exists ≠ behaves — `--strength-gate=fail` refuses it)
- vague "updated the docs" with no specific anchor

## Running Dorian

```bash
# one-shot: auto-capture the read-set from the claims, run checkers, seal
dorian verify dorian-change-note.md --claims claims.json --strength-gate=fail --binding-gate=warn

# later, on a PR:
dorian revalidate --since origin/main      # REVOKED (exit 4) if a sealed claim broke
dorian status                              # trust state of every warranted artifact
```

`dorian init` scaffolds a starter `claims.json`, a change note, and a `.github/workflows/dorian.yml`.

## GitHub Action

```yaml
- uses: ajaysurya1221/dorian/action@v1.4.0
  with:
    fail_on: revoked        # block the PR when a sealed claim breaks
    # for semi-trusted contributors, also: checker_source: base  + deny_exec: true
```

It posts a customer-readable PR comment (`Blocked/Passed/Errored`, the claim that changed, the affected
`.warrant`). The check is deterministic and token-free.

## What to avoid

- Don't seal marketing/opinion claims — only checkable facts.
- Don't use Dorian as a sandbox: `C4 pytest:` and `C5 shell:` execute code; use it in **trusted** repos,
  and for semi-trusted contributors combine `checker_source: base` + `deny_exec: true` (see
  [`SECURITY_BOUNDARY.md`](SECURITY_BOUNDARY.md)).
- Don't read a weak-binding or weak-strength warning as "the claim is false" — it means low coverage/
  confidence; strengthen the watch or the checker.

## Recommended Claude Code final-message template

End a coding turn with both a human summary and a machine block:

```
### What I changed
<human summary>

### Checkable receipts (dorian)
I emit claims.json with these load-bearing, checker-backed claims:
- <id>: <text>  — <C3/C4/C5 program>
(only statements a deterministic checker can falsify; prose is excluded)
Run: dorian verify <change-note> --claims claims.json --strength-gate=fail
```

This keeps the agent honest at the moment of maximum context, and leaves a receipt that fails later if
the code drifts — without spending a single token to re-check.
