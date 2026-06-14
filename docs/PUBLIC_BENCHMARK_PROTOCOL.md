# Public micro-benchmark protocol (pre-registration)

**Status: protocol only — no results are published in this document.** This is the next rung of
[`SOLO_VALIDATION_LADDER.md`](SOLO_VALIDATION_LADDER.md): moving from invented synthetic fixtures
(the [v0.7.0 controlled-mutation benchmark](BENCHMARK_v0.7.0.md) and the
[binding-lifecycle benchmark](BENCHMARK_BINDING_LIFECYCLE.md)) and offline reproductions of public
problem *classes* ([`REALWORLD_USECASES.md`](REALWORLD_USECASES.md)) to a small, fully reproducible
benchmark on **real public repositories at frozen commit SHAs**.

This protocol is committed *before* any results, so the design can't be tuned to flatter an outcome.
Results, when produced, go in a separate `BENCHMARK_PUBLIC_REPOS.md` that cites this protocol.

## 1. What this proves — and what it does not

This benchmark is **reproducibility evidence on a handful of public repositories**: that anyone can
clone the named repos at the named SHAs, run the named commands, and reproduce the reported
trigger/selection and truth/alarm numbers byte-for-byte. It is explicitly **not** a broad real-world
performance claim, not evidence that dorian "works on real repos" in general, and not a measure of
willingness to adopt. A pass means *the mechanism reproduces on these inputs*, nothing wider.

## 2. Repositories (public, frozen)

Two genuinely public, permissively licensed repositories, pinned at frozen SHAs:

| repo | URL | frozen SHA | why |
|---|---|---|---|
| httpx | https://github.com/encode/httpx | `d4961b9f8e7f00b654dbdbf200562bd273f598c7` | a widely used Python HTTP client; rich symbols, config constants, and a real test suite |
| click | https://github.com/pallets/click | `5df10013f7ed8bad94da1e82d58e3711eec1afb3` | a widely used CLI library; stable public API surface for symbol/path claims |

Both SHAs are pinned in the committed public manifest
(`bench/public/repos.public.json`). Private or local development clones, including the author's
internal `genai-core` experiments, are **excluded from this protocol and must never be cited as
public evidence**; published results use only the public repos above.

## 3. Claims — manual only

Claims are **authored by hand** (or reviewed agent-emitted), never produced by `--extract` (frozen).
Each claim names a real fact about the repo at its frozen SHA — a public symbol that exists, a config
value, a path, a passing test — bound to the shape-tolerant checker that would catch its falsification
(`symbol:`/`regex:`/`path:`/typed `C5`/`pytest:`), per [`AGENT_CLAIMS.md`](AGENT_CLAIMS.md). The claim
set and its checkers are committed alongside the manifest; the count and ids are fixed before any run.

## 4. Two measurement layers, reported separately

Following the binding-lifecycle protocol, the two layers are **never merged into one score**:

- **Trigger / selection layer** — *did `revalidate` re-check the claims it should, given which files
  changed between two SHAs?* Metrics: selection precision and recall against a mechanically-derived
  "should re-check" label (a claim should be re-checked iff a changed path intersects its watch set).
  Baselines: the naive file watcher, the checker-path watcher, and dorian's bound candidate set.
- **Truth / alarm layer** — *of the claims it re-checked, did it fold BROKEN exactly the ones whose
  fact actually changed?* Metrics: alarm precision and recall against a mechanically-derived "should
  alarm" label. `ERRORED` (checker could not run) is reported as a third bucket and is **never**
  counted as an alarm.

The "should re-check" set is a superset of the "should alarm" set; reporting them separately keeps the
trigger-vs-truth ceiling visible (a watched file changing widens *re-checking*, never *truth*).

## 5. The reproducibility manifest

Published results must ship a manifest sufficient to reproduce them with no hidden state. Required
fields per (repo, artifact):

- repository URL and frozen SHA (base), and the SHA(s) the mutation/diff is measured against;
- the artifact path and its committed `claims.json` (claim ids + checker programs);
- the exact `dorian` command(s) to reproduce, including flags;
- tool versions: `dorian --version`, Python version, and any extra (`duckdb` for C5 data claims);
- **expected vs. measured kept separate**: the pre-registered expectation and the observed run are
  distinct columns, so a mismatch is visible rather than silently overwritten.

## 6. Pre-registration discipline

1. Commit this protocol and the claim set + manifest *before* running.
2. Run the benchmark; capture raw machine output.
3. Publish results in a separate doc that cites this protocol; never edit measured numbers to match
   the expectation — record the mismatch.

## 7. Reproduce (once a harness lands)

A `dorian bench public-repos` subcommand is **not yet implemented** — see
[`bench/public/README.md`](../bench/public/README.md) for the scaffold and
[`bench/public/repos.public.json`](../bench/public/repos.public.json) for the committed public
manifest. Until the harness lands, this document is the pre-registered design. If `bench/real/` is
used locally, it is local-only and gitignored: clones and worktrees there are never committed, never
linted, and never public evidence.

## 8. Wording (results docs)

Allowed: "reproduces on these public repos at these SHAs", "selection recall X / alarm precision Y on
the pinned set", "reproducibility evidence, not a real-world performance claim". **Forbidden:**
proven, validated, real-world validated, universal, guaranteed, production-ready, production-grade,
semantic proof, "works on real repos", "fully solves" anything. Benchmark contributions carry
aggregate numbers only — never private repository content.
