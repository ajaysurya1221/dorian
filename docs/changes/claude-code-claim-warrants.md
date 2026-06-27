# Change note — Dorian Claim Warrants for Claude Code (v1.3.0)

Adds a one-command Claude Code integration: `dorian claude-code
install-claim-warrants` scaffolds a project-local `/dorian-claim-warrants` skill
(and an opt-in, reminder-only Stop hook) that **drafts** claim warrants for the
checkable facts a coding agent says it changed. `dorian verify` then **proves**
them deterministically — no model is ever added to the verification path, and the
core stays zero-dependency.

This note is dogfooded: the load-bearing facts the feature relies on are sealed in
[`claude-code-claim-warrants.claims.json`](claude-code-claim-warrants.claims.json)
under `--strength-gate=fail --binding-gate=warn`.

## Checkable claims included

- The CLI exposes `claude-code install-claim-warrants` (parser + handler).
- The packaged skill template ships in source package data.
- The hook template handles `stop_hook_active` and uses `additionalContext`.
- The docs state the hook is reminder-only, that the model drafts and Dorian
  verifies, that Dorian is not a sandbox, and compare claim warrants to Agent
  Receipts.
- `pyproject.toml` keeps a zero-dependency runtime core.
- The integration's documented command uses `--strength-gate=fail`.

## Non-checkable claims intentionally excluded

- "This makes Dorian easier to adopt" — outcome claim, not deterministically
  checkable.
- "The skill drafts good claims" — quality judgment; only `dorian verify` decides
  truth, and the skill's drafting is model-assisted at authoring time.

## Verification command

```bash
dorian verify docs/changes/claude-code-claim-warrants.md \
  --claims docs/changes/claude-code-claim-warrants.claims.json \
  --strength-gate=fail --binding-gate=warn
```

## Trust boundary

The skill (and hook) only draft. Sealing requires `dorian verify` to run each
deterministic checker and pass. Dorian is **not a sandbox** — `C4`/`C5` checkers
execute code; trusted repos only.
