# Change: Dorian Loop Guard

Dorian Loop Guard adds a deterministic, token-free **steering layer for AI coding loops**
on top of `revalidate`: `dorian loop preflight` re-checks the warrants a change touched and
returns a CONTINUE / REPAIR / ESCALATE decision; `dorian loop prompt` renders it for the
next agent iteration; `dorian loop install` scaffolds the `/dorian-loop-guard` Claude Code
skill. No model runs at check time; not a sandbox; trusted repos only.

This is the dogfood change note. The checkable facts below are warranted by Dorian itself.

## Checkable claims (warranted)

- `loop-engine` — the engine entry point `preflight` exists in `src/dorian/loop.py`.
- `loop-cli` — `cli.py` wires the nested `loop` subcommand (`_add_loop_parser`).
- `loop-handler` — `commands.py` dispatches it (`cmd_loop`).
- `loop-guard-doc` / `loop-alignment-doc` — the two Loop Guard docs exist.
- `loop-skill` — the `/dorian-loop-guard` skill template ships.
- `zero-runtime-deps` — `pyproject.toml` still declares zero runtime dependencies.
- `readme-loops-section` — the README has a "Using dorian inside AI coding loops" section.
- `docs-not-a-sandbox` / `docs-does-not-stop-loop` — the docs keep the boundary honest:
  not a sandbox, and Dorian does not stop the loop by default (REVOKED → repair/escalate,
  not an automatic halt).

## Intentionally NOT warranted (prose, not checkable)

"Loop Guard is the right reframe", "keeps loops on track", "useful product surface" — these
are judgments, not deterministically falsifiable facts, so they are left as prose.

## Verify

```bash
dorian verify docs/changes/dorian-loop-guard.md \
  --claims docs/changes/dorian-loop-guard.claims.json \
  --strength-gate=fail --binding-gate=warn
```

The sealed `docs/changes/dorian-loop-guard.md.warrant` is produced by running the command
above (born-verifiable: it refuses to seal anything already false). `tests/test_loop_guard_dogfood.py`
runs this exact verify→preflight flow in a temp copy and proves a mutated fact flips the
loop decision from CONTINUE to REPAIR.

Trust boundary: the model drafted this note; Dorian verifies the claims deterministically
and token-free; not a sandbox; trusted repo only.
