# Release decision artifacts — dorian 1.0.0

The 1.0.0 decision is produced by `bench/release_state.py` from a specific
checkout or tag. Commit-specific JSON and Markdown output must be generated into
an ignored release artifact directory such as `.release/rc2-evidence/`; do not
commit a file that claims to contain its own final evaluated commit.

For the current RC baseline:

```bash
uv run python bench/release_state.py \
  --target 1.0.0 \
  --rc-tag v1.0.0rc2 \
  --json --strict \
  --out .release/rc2-evidence/release_state.json \
  --decision-out .release/rc2-evidence/RELEASE_DECISION_1_0.md
```

The generated decision document records:

- evaluated commit
- source version
- current RC tag
- `features_after_rc`
- S0-S10 state evidence
- final state-machine decision

See `docs/RELEASE_GATE_1_0.md` for the full state table and decision rules.
