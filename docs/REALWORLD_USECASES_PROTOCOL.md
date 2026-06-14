# Real-world use-case reproductions — protocol

How the public cases in [`REALWORLD_USECASES.md`](REALWORLD_USECASES.md) were
chosen, reproduced, and labelled. The goal is honest, scoped evidence: dorian
**solves this controlled reproduction of a public problem class**, never "dorian
solves real-world drift."

## Discovery (network, one-time)

Public problems were collected by web search across five categories — stale
README/API docs, AI-authored PR descriptions that go stale, security/config
drift, route/OpenAPI/CLI-help drift, and test-coverage claims — and screened for:

- **public + citable** (a real GitHub issue/PR/advisory or widely-cited post);
- **still open / unresolved / a recurring class as of 2026-06-14** (a merged fix
  found ⇒ demoted to a negative or a recurring-class exhibit);
- **maps to dorian's lifecycle model** (a fact a deterministic checker can watch);
- **hermetically reproducible without copying proprietary content**.

Discovery may use the network; the committed reproductions do **not**. There is no
`--fetch` mode — every reproduction is a synthetic, offline fixture.

## Reproduction (offline, hermetic)

Each public issue is the **design template only**; the fixture is invented and
public-safe. A reproduction builds a tiny git repo, seals a claim with a
deterministic checker (born-verifiable: seal is refused if the claim is already
false), applies the real-world **drift** as one commit, and runs
`dorian revalidate`. No external repo source is copied; no private path, secret, or
timestamp is committed.

## Labelling (derived, never asserted)

The label is **derived from dorian's actual revalidate behavior** and cross-checked
against the case's frozen expectation — a mislabel raises rather than passing:

| label | requires |
|---|---|
| `solved` | hermetic + mechanically checkable, and dorian folds the claim **BROKEN** (not merely re-checks it) |
| `partial` | dorian **re-checks** the claim (trigger fired) but its checker cannot prove the semantic fact, so it stays **VERIFIED** — the trigger-vs-truth ceiling |
| `not_solved` | dorian misses the change, or it cannot be made deterministic/hermetic; documented from public sources, not reproduced |
| `cannot_test` | needs private content, unsafe exploitation, network-by-default, or nonmechanical judgment |

A case is **never** `solved` because a watched file changed — only because a
checker that EXERCISES the fact folded it BROKEN. The `partial` cases exist
precisely to make the ceiling visible: a rename is caught (existence breaks) while
a same-name behavior/type change is missed (existence still passes).

## Wording

Allowed: "dorian solves this controlled reproduction of a public problem class",
"partially addresses this case by re-checking the trigger", "does not yet solve
this case because the checker does not exercise the semantic fact", "a public-case
reproduction, not a blanket real-world result". Forbidden: proven, validated,
universal, real-world validated, guaranteed, semantic proof, production-ready,
fully solves stale docs / agent claim drift.

## Reproduce

```bash
dorian bench realworld-usecases
```
