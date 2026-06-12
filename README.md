<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/dorian-hero.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/dorian-hero-light.png">
  <img src="docs/assets/dorian-hero-light.png" alt="dorian — validity warrants for AI-generated work" width="720">
</picture>

# dorian

**Validity warrants for AI-generated work.**

*Your doc still looks perfect. Its portrait doesn't.*

<p>
  <a href="#getting-started"><img src="https://img.shields.io/badge/Quickstart-2ea44f?style=for-the-badge" alt="Quickstart"></a>
  <a href="#a-60-second-example"><img src="https://img.shields.io/badge/Demo-1f6feb?style=for-the-badge" alt="Demo"></a>
  <a href="action/README.md"><img src="https://img.shields.io/badge/GitHub_Action-6e40c9?style=for-the-badge" alt="GitHub Action"></a>
</p>

<p>
  <a href="https://github.com/ajaysurya1221/dorian/actions/workflows/ci.yml"><img src="https://github.com/ajaysurya1221/dorian/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="Apache-2.0">
  <img src="https://img.shields.io/badge/status-v0.1-orange" alt="v0.1">
</p>

</div>

## Table of contents

- [About](#about)
- [A 60-second example](#a-60-second-example)
- [Why not just watch files?](#why-not-just-watch-files)
- [How it works](#how-it-works)
- [What gets committed](#what-gets-committed)
- [Getting started](#getting-started)
- [Command surface](#command-surface)
- [Claim extraction is experimental](#claim-extraction-is-experimental)
- [What dorian is not](#what-dorian-is-not)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## About

When an AI agent writes a document — a design doc, a plan, a report, a summary — it may be
correct today. Later, the code, data, prompt, schema, or API it described changes. The
document still looks fine. CI is green. But one of its claims is now false, and nothing
tells you.

`dorian` attaches a `.warrant` sidecar to every AI-generated artifact. The sidecar records:

- **what the producing run read** (a content-hashed read-set),
- **what the artifact claims** (each important claim restated atomically),
- **how each claim can be re-checked later** (an executable, read-only checker per claim).

When sources change, `dorian revalidate` re-checks only the affected claims —
deterministically, with **zero model tokens** — and reports exactly which claim is now
broken, which artifact's trust state changed, and what downstream work inherited the
damage.

The name is *The Picture of Dorian Gray*, inverted: the document stays pristine while
reality drifts, and the `.warrant` is the portrait in the attic that shows the true state.

It is **local-first** (a CLI and a git repo, nothing else), **git-native** (sidecars are
committed next to the artifacts they warrant), and **privacy-conscious** (content-free
sidecar mode, redaction-aware reports). It is useful for generated docs, plans, reports,
prompt changelogs, and data-dependent artifacts.

## A 60-second example

A generated design doc ships with a warrant covering three claims (a committed,
fictional version of this doc lives at
[`examples/demo-repo/docs/design.md`](examples/demo-repo/docs/design.md)):

| claim | text |
|---|---|
| `c-02` | The default request timeout is 30 seconds. |
| `c-07` | Login is served at `/v1/login`. |
| `c-11` | The report schema is version 1.1. |

Weeks later, a refactor PR changes the timeout to 10, removes `/v1/login`, and bumps the
schema to 1.3. The doc itself is untouched, so normal git tooling and CI stay silent.

`dorian revalidate` is not silent (illustrative output):

```text
docs/design.md: WARRANTED -> REVOKED
  c-02  BROKEN  C3: regex_missing (TIMEOUT *= *30)
  c-07  BROKEN  C3: string_missing (/v1/login)
  c-11  BROKEN  C5: schema version mismatch
recalled downstream: docs/rollout-plan.md (depth 1)
```

The trust state moves to REVOKED, and every artifact derived from this doc gets a
`recalled` flag so nobody builds on a broken claim without knowing.

## Why not just watch files?

A file watcher alarms whenever any supporting file changes. But support files are touched
constantly — refactors, formatting, comments, adjacent features — and most of those
changes don't falsify anything the artifact says. `dorian` checks **claims**, not just
files: an alarm means a specific sentence stopped being true.

In the owner-checked v0.0 real-history gate, claim-level revalidation reduced
false-positive staleness alarms **32.40×** versus file-hash watching at **0.89 recall**
(556 artifact-commit pairs over three repositories; blind model-panel labels with a
72-pair human spot-check, recommendation PASS). Raw private benchmark artifacts remain
local-only; public summaries are aggregate-only. Labels are model-adjudicated with a
human spot-check, not fully human-labeled — methodology, confidence intervals, and
caveats are in [`docs/KILL_REPORT_v0.0.md`](docs/KILL_REPORT_v0.0.md).

This is one measured result on specific repositories, not a universal performance claim.
Measure your own repos with the harness in `bench/`. Fully public proof is still in
progress: the next evidence step is a small reproducible public benchmark (frozen public
repos, manual claims, owner labels), per
[`docs/SOLO_VALIDATION_LADDER.md`](docs/SOLO_VALIDATION_LADDER.md).

## How it works

1. **Capture** what the AI read — from a Claude Code session transcript or manual specs.
2. **Seal** the generated artifact into a `.warrant` — every checker must pass at seal
   time, so warrants are born verifiable.
3. **Revalidate** when sources change — only claims whose watched files drifted are
   re-checked.
4. **Report** broken claims, trust-state transitions, the audit trail, and the blast
   radius of downstream artifacts.

```bash
# 1. capture the read-set (or: dorian capture --transcript session.jsonl)
dorian capture --manual src/auth.py --manual src/config.py:L1-40 --out rs.json

# 2. write claims.json (or draft with --extract, then review), then seal
dorian seal docs/design.md --readset rs.json --claims claims.json

# 3. later, after the repo changed
dorian revalidate --since main~20

# 4. inspect
dorian status docs/design.md
dorian blast docs/design.md
dorian report --audit
```

## What gets committed

- the generated artifact (e.g. `docs/design.md`),
- its `.warrant` sidecar (`docs/design.md.warrant`),
- optional config in `pyproject.toml` (e.g. restricted-path scopes).

**Sidecars are the source of truth.** The SQLite index under `.warrant/` is a local,
derived cache — rebuildable at any time with `dorian sync` — and is never committed.

## Getting started

The distribution is `dorian-vwp`; the import and CLI are `dorian`. The first PyPI
release is on the roadmap — until it lands, install from source:

```bash
pip install 'dorian-vwp @ git+https://github.com/ajaysurya1221/dorian.git'

# extras
pip install 'dorian-vwp[data] @ git+https://github.com/ajaysurya1221/dorian.git'     # + duckdb for parquet data claims
pip install 'dorian-vwp[extract] @ git+https://github.com/ajaysurya1221/dorian.git'  # + anthropic for LLM claim drafting (experimental)
```

After the first PyPI release:

```bash
pip install dorian-vwp             # core, zero runtime dependencies
pip install 'dorian-vwp[data]'     # + duckdb for parquet data claims
pip install 'dorian-vwp[extract]'  # + anthropic for LLM claim drafting (experimental)
```

Then run the four-step loop above on one artifact. For CI, add the composite
[GitHub Action](action/README.md) — it revalidates the claims a pull request touches and
posts a sticky PR comment. Read its
[security notes](action/README.md#security-checker-execution-and-untrusted-pull-requests)
first: checker specs in `.warrant` files are executable, so the Action is currently
recommended for trusted/internal repositories, not for public repos taking forked PRs:

```yaml
name: dorian
on: [pull_request]

permissions:
  contents: read
  pull-requests: write

jobs:
  revalidate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with: { fetch-depth: 0 }   # revalidate diffs against the PR base sha
      - uses: ajaysurya1221/dorian/action@main
        with:
          fail_on: revoked
          # until the PyPI release, install from source:
          install: 'dorian-vwp @ git+https://github.com/ajaysurya1221/dorian.git'
```

## Command surface

The core loop is `capture` (read-set) → `seal` (run every checker, write the `.warrant`
sidecar) → `revalidate` (re-check only what changed). Checker program grammars (C1 span,
C3 path/symbol/string/regex, C4 `pytest:<nodeid>`, C5 typed data forms) are documented in
[`spec/checkers.md`](spec/checkers.md).

- `dorian blast <path|warrant-id> [--max-depth N]` — downstream warrants reachable
  through the derives graph. When `revalidate` newly breaks a claim, every downstream
  warrant gets a `recalled` event: a flag only — downstream is never re-checked and its
  states are untouched. Re-seal with `seal --supersede <old-id>` so downstream warrants
  that were sealed against the old id stay reachable in the derives graph.
- `dorian bindings <artifact>` — binding-quality diagnostics (unbacked, single-file,
  short-literal, unwatched-mention). Informational, never a gate; output carries file
  paths only, never matched content.
- `dorian suggest-data-checks <path> [--columns ...] [--out f]` — born-verifiable C5
  checker suggestions from a data file's current state, for human review and pasting
  into a claim's `checkers` list in claims.json. Never applied automatically.
- `dorian report --audit` — the full event log as `dorian-audit-v1` JSONL,
  byte-identical across runs; checker details truncated to 160 chars to bound
  source-content carryover.
- `dorian revalidate --format md|json` — `md` is the PR-comment body posted by the
  [GitHub Action](action/) (`action/action.yml`, composite, no third-party actions);
  its details get the same 160-char carryover bound as the audit export.
- `dorian seal --no-quotes` — content-free sidecars: anchor line numbers stay, quotes
  are dropped (the warrant id changes accordingly).
- Seal-time scope lint: `[tool.dorian.scopes] restricted = [globs]` in the *target*
  repo's pyproject.toml refuses to seal read-sets touching restricted paths (exit 6);
  `--allow-restricted` overrides and is receipted in the sealed event.
- `dorian bench public-summary` — the private-content-free benchmark summary; the
  other bench subcommands (`make-owner-review` / `merge-owner-review` /
  `owner-metrics` / `churn`) are documented in
  [`docs/OWNER_SPOTCHECK.md`](docs/OWNER_SPOTCHECK.md).

Exit codes: `0` ok/TRUSTED · `2` usage/infra · `3` DEGRADED · `4` REVOKED/integrity ·
`5` ERRORED-only (checkers could not run — never conflated with broken) · `6` scope
violation.

## Claim extraction is experimental

`--extract` drafts claims with an LLM so you don't start from a blank `claims.json`.
It is **experimental, and measurably so**: the first compliant churn measurement
(temperature 0, forced tool call, 3 re-runs on a real document) failed its stability
gate — mean exact Jaccard distance 0.49 and fuzzy 0.21 against the < 0.20 gate. The
model extracts a stable *number* of claims but a different *selection* each run.

Treat extracted claims as **drafts for human review, not stable warrant inputs**: always
review and edit `claims.json` before sealing. Measure your own documents with
`dorian bench churn` (the committed demo doc `examples/demo-repo/docs/design.md` works as
a target). Prompt hardening to lift this gate is on the roadmap.

## What dorian is not

Not a doc generator. Not an LLM drift *scanner* (no model re-reads your repo on every
PR). Not an eval framework. Not an agent framework. Not a SaaS, a dashboard, or an
AI-governance platform. It is a small, deterministic CLI that makes acceptance of
AI-generated work perishable — and tells you when it expired.

Related boundaries: agent receipt systems record agent actions; agent governance
toolkits govern agent execution. `dorian` warrants generated artifacts *after they
exist* and revalidates their claims over time.

## Roadmap

- **A public micro-benchmark** — frozen public repos, manual claims, owner labels, fully
  publishable artifacts ([`docs/SOLO_VALIDATION_LADDER.md`](docs/SOLO_VALIDATION_LADDER.md)).
- **Extraction-prompt hardening** and churn re-measurement on more documents — the
  documented path to promoting `--extract` beyond experimental.
- **Checker calibration** informed by the benchmark's measured failure modes (binding
  misses and over-tight string literals).
- **A polished example repo** with a scripted demo PR.
- **Tagged release and PyPI trusted publishing.**

Non-goals stay non-goals: no servers, no dashboards, no hosted control plane.
Local-first is the design center.

## Contributing

```bash
git clone https://github.com/ajaysurya1221/dorian.git
cd dorian
make install   # uv sync
make lint      # ruff check + format check
make test      # pytest
```

Issues and small, focused PRs are welcome. Please keep changes surgical, match the
existing style, and include tests. Benchmark contributions must contain aggregate
numbers only — never private repository content.

## License

Apache-2.0. Protocol: VWP (Validity Warrant Protocol), spec in [`spec/`](spec/).

## Contact

- Issues and discussions: [github.com/ajaysurya1221/dorian](https://github.com/ajaysurya1221/dorian)
- Author: Ajay Surya Senthilrajan ([@ajaysurya1221](https://github.com/ajaysurya1221))
