# Validation honesty

What dorian's evidence does and does not support, stated once so no benchmark or
demo can be read as more than it is. This is the contract every results doc and
README claim must stay inside.

## The two layers (never collapse them)

dorian's job splits into two independent questions. A benchmark must report them
separately; a number for one is not a number for the other.

| Layer | Question | Metric | A win means |
|---|---|---|---|
| **Trigger / selection** | When a watched source changes, is the affected claim re-checked? | selection recall (and precision vs. a baseline watcher) | the right claims are *considered* — not that any fact was proven |
| **Truth / alarm** | Given the claim is re-checked, does the checker correctly say true/false? | alarm precision, false-positive rate, false-negative rate | a verdict is *correct* — only as strong as the checker backing the claim |

A claim can be perfectly triggered and still carry no truth signal (e.g. a
`symbol:` checker re-runs on the defining file but cannot see a behavior change —
only a `pytest:` checker would). That gap is the **trigger-vs-truth ceiling**;
it is a property to report, not a bug to hide.

## Vocabulary

Use these; avoid the words in the "instead of" column.

| Say | Instead of |
|---|---|
| reproducible on this suite | proven / validated |
| scoped reproduction | works on real repos |
| mechanism evidence | semantic proof |
| trigger-layer improvement | better detection (unqualified) |
| truth-layer limitation | (silence about the gap) |
| weak-binding warning | false claim (weak binding is confidence, not falsity) |
| trusted/internal workflow | safe for public fork PRs |

## What a passing benchmark can and cannot claim

**Can:** the mechanism reproduces on the named inputs; on this suite, selection
recall / alarm precision were *X*; against baseline *B* on these inputs, dorian
had fewer false re-checks.

**Cannot:** dorian works on real repos in general; the numbers transfer to your
codebase; the tool is "validated"; users will adopt it; a weak-binding warning
means a claim is false.

## Synthetic vs. real

- **Synthetic** fixtures (controlled-mutation, binding-lifecycle) are *designed*
  inputs: they isolate a mechanism and let it be measured cleanly, but their
  distribution is invented. Label them synthetic, every time.
- **Offline public-case reproductions** ([REALWORLD_USECASES.md](REALWORLD_USECASES.md))
  reproduce a public problem *class*, not a blanket real-world result.
- **Public-repo micro-benchmark** ([PUBLIC_BENCHMARK_PROTOCOL.md](PUBLIC_BENCHMARK_PROTOCOL.md))
  is reproducibility on a handful of frozen SHAs — hermetic reproduction, not
  broad validation.

## Hermetic reproduction ≠ broad validation

Byte-identical reproduction on frozen inputs proves the *process* is
deterministic and inspectable. It says nothing about coverage of the space of
real changes. Both are worth having; only the first is something dorian can
currently demonstrate, and it must be named as such.

## The one rule

If you cannot name the specific false statement a result rules out, the result
is not evidence — it is decoration. Do not ship it as proof.
