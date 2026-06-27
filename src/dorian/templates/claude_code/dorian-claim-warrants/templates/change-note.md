# Change note — <slug>

> Drafted by the `/dorian-claim-warrants` skill. **DRAFT — not verified until
> `dorian verify` exits 0 and writes a `.warrant`.** The model drafts; Dorian
> proves. No model runs at check time.

## Summary

<One short, honest paragraph of what changed — the same human summary the agent
gave. Prose only; nothing here is a warrant.>

## Checkable claims included

These are the statements a deterministic Dorian checker can falsify. Each maps to
a claim in `<slug>.claims.json`:

- `<claim-id>`: <the specific fact> — `<C3/C4/C5 program>`

## Non-checkable claims intentionally excluded

Statements from the summary that no deterministic checker can falsify, so they are
**left as prose, not warranted** (this honesty is the point):

- "<e.g. 'the code is cleaner / faster / more maintainable'>" — opinion, not checkable
- "<e.g. a performance/security claim with no falsifying check>" — excluded

## Verification command

```bash
dorian verify docs/changes/<slug>.md \
  --claims docs/changes/<slug>.claims.json \
  --strength-gate=fail --binding-gate=warn
```

## Trust boundary

The `/dorian-claim-warrants` skill only **drafts** these files. Sealing requires
`dorian verify` to run each claim's deterministic checker and pass — a false claim
is refused, not sealed. Dorian is **not a sandbox**: `C4 pytest:` and `C5 shell:`
checkers execute code, so this runs in **trusted repos** only. Later,
`dorian revalidate --since <base>` flips a broken claim to `REVOKED` (exit 4).
