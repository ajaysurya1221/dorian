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

## Discovery catalog (≥12 public problems, 5 categories)

This is the discovery breadth behind the report — so the five report cases read as
a *selection*, not a cherry-pick. **Counts (kept distinct):** ≥12 public problems
screened across 5 categories; **5 carried into the report** =
[`REALWORLD_USECASES.md`](REALWORLD_USECASES.md) — **3 hermetic reproductions** +
**2 documented boundary cases**. The report summary's `candidate_count = 5` counts
those report cases, not the discovery total. The **Expected fit** column is an
*assessment* of how dorian would fare; it is **verified only for the ★ rows** (the
report cases) — a non-★ "solved" means *expected to solve if reproduced*, never a
verified result. Statuses are as of 2026-06-14; no proprietary content is copied.

| # | category | source | status | problem class | dorian fit (help · risk) | in report | expected fit |
|---|---|---|---|---|---|---|---|
| 1 | docs-drift | [Proxyfan#978](https://github.com/Proxyfan/Proxyfan/issues/978) | open | config file renamed, docs keep the legacy name | help: C3 string on the loader · risk: legacy name is legit in a migration shim | ★ | solved |
| 2 | docs-drift | [Effect-TS#1378](https://github.com/Effect-TS/effect-smol/issues/1378) | open | v4 API renames + same-name return-type drift | help: C3 symbol existence catches renames · risk: a behavior/type change under the same name is unseen | ★ | partial |
| 3 | docs-drift | [pymoveit2#110](https://github.com/AndrejOrsula/pymoveit2/issues/110) | open | README launch-file rename | help: C3 path · risk: file is in a sibling package + the README was already fixed | ★ | not_solved |
| 4 | docs-drift | [godot-proposals#3902](https://github.com/godotengine/godot-proposals/issues/3902) | recurring-class | engine-wide 4.0 renames break copied tutorial code | help: C3 symbol/path · risk: cross-repo external docs are out of local scope | | partial |
| 5 | agent-claim-drift | [community#187863](https://github.com/orgs/community/discussions/187863) | open | Copilot agent overwrites the PR description each run | help: bind the change's claims to code facts · risk: prose-only claims are unbindable | | partial |
| 6 | agent-claim-drift | [github.blog changelog](https://github.blog/changelog/2022-08-23-new-options-for-controlling-the-default-commit-message-when-merging-a-pull-request/) | recurring-class | squash-merge freezes an AI PR body into the commit message | help: bind described facts to checkers · risk: dorian does not warrant commit-message prose | | not_solved |
| 7 | security/config-drift | [grafana#110811](https://github.com/grafana/grafana/issues/110811) | open | `InsecureSkipVerify: true` disables TLS verification | help: C3 regex anchored to the secure value · risk: proves the source value, not runtime TLS | ★ | solved |
| 8 | security/config-drift | [SafeLine#1229](https://github.com/chaitin/SafeLine/issues/1229) | open | `NO_AUTH` env var bypasses the auth middleware | help: C3 string/regex on the guard · risk: the env-gated runtime path is not exercised | | partial |
| 9 | security/config-drift | [Django DEBUG (Acunetix)](https://www.acunetix.com/vulnerabilities/web/django-debug-mode-enabled/) | recurring-class | `DEBUG=True` shipped to production | help: C3 regex anchored to `DEBUG = False` · risk: per-env config, not the committed default alone | | partial |
| 10 | route/schema/cli-drift | [metasploit#21503](https://github.com/rapid7/metasploit-framework/issues/21503) | open | msfvenom docs cite flags absent from the arg parser | help: C3 string/symbol on the parser file · risk: needs the canonical parser file bound | | partial |
| 11 | route/schema/cli-drift | [trailbase#211](https://github.com/trailbaseio/trailbase/issues/211) | open | OpenAPI spec status codes diverge from the handlers | help: C3 on the spec/handler · risk: response behavior needs a test, not existence | | partial |
| 12 | test-coverage-drift | [rails#26546](https://github.com/rails/rails/issues/26546) | unresolved | a zero-assertion test reports as passing | help: C4 runs the test · risk: a gutted, assertion-free test still exits 0 (the ceiling) | ★ | not_solved |

Not every candidate is reproduced, and not every candidate is solved — most are
`partial` or `not_solved` once you ask whether a checker actually *exercises* the
fact. That is the honest shape of the trigger-vs-truth ceiling at real-world scale.

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
