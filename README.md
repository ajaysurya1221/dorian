<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/dorian-hero.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/dorian-hero-light.png">
  <img src="docs/assets/dorian-hero-light.png" alt="dorian — hold AI agents to what they said they did" width="720">
</picture>

# dorian

**Hold AI agents to what they said they did.**

*The summary still reads perfectly. Its portrait doesn't.*

<p>
  <a href="#getting-started"><img src="https://img.shields.io/badge/Quickstart-2ea44f?style=for-the-badge" alt="Quickstart"></a>
  <a href="#the-60-second-aha"><img src="https://img.shields.io/badge/Demo-1f6feb?style=for-the-badge" alt="Demo"></a>
  <a href="action/README.md"><img src="https://img.shields.io/badge/GitHub_Action-6e40c9?style=for-the-badge" alt="GitHub Action"></a>
</p>

<p>
  <a href="https://github.com/ajaysurya1221/dorian/actions/workflows/ci.yml"><img src="https://github.com/ajaysurya1221/dorian/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="Apache-2.0">
  <img src="https://img.shields.io/badge/status-v0.7-orange" alt="v0.7">
</p>

</div>

An AI agent says it *added rate-limiting to `/login`, set the timeout to 30s, and updated every
caller.* Some of that is already false; the rest goes false on the next commit — and CI stays green
the whole time. `dorian` turns each checkable claim into a deterministic, token-free check that holds
now and is re-checked on every future change, so a confident summary doesn't quietly become a lie.

## Table of contents

- [The 60-second aha](#the-60-second-aha)
- [We ran this on dorian itself](#we-ran-this-on-dorian-itself)
- [About](#about)
- [Who verifies the verifier?](#who-verifies-the-verifier)
- [Why not just watch files?](#why-not-just-watch-files)
- [How it works](#how-it-works)
- [What gets committed](#what-gets-committed)
- [Getting started](#getting-started)
- [Writing claims an agent can be held to](#writing-claims-an-agent-can-be-held-to)
- [Command surface](#command-surface)
- [Claim extraction is frozen](#claim-extraction-is-frozen)
- [What dorian is not](#what-dorian-is-not)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## The 60-second aha

An agent finishes a change and emits the claims it just made — a `claims.json` next to the work,
each claim bound to a read-only deterministic checker:

```json
{
  "claims": [
    { "id": "login-ratelimit-added", "text": "Rate limiting guards the /login route.",
      "kind": "behavior", "load_bearing": true,
      "checkers": [{ "type": "C3", "program": "symbol:src/api/auth.py::rate_limit" }] },
    { "id": "login-timeout-30s", "text": "The login request timeout is 30 seconds.",
      "kind": "quantity", "load_bearing": true,
      "checkers": [{ "type": "C3", "program": "regex:src/api/config.py::LOGIN_TIMEOUT\\s*=\\s*30\\b" }] }
  ]
}
```

`dorian verify` binds each claim to its checker, auto-captures the files those checkers read, and
seals a `.warrant` — but only because every claim holds against the **real, current** code:

```text
$ dorian verify docs/changes/login.md --claims claims.json
sha256:7920c71b5a6a9c8e2b53e401c78db88af9a30c7a2f5f2f8063d7d40809866102
verified 2/2 claim(s) against current sources -> docs/changes/login.md.warrant
# exit 0 — born verifiable: had any claim been false now, the seal is refused (exit 4) and nothing is written
```

Weeks later a refactor renames `rate_limit` and drops the timeout to 10. `docs/changes/login.md` is
untouched, so git, the diff, and CI all stay silent. `dorian revalidate` re-checks **only the two
claims whose files changed** — deterministically, with zero model tokens — and is not silent:

```text
$ dorian revalidate --since main~20
checked 2 candidate claim(s)
BROKEN    sha256:7920c71b5a6a9c8e login-ratelimit-added  C3: symbol_missing
BROKEN    sha256:7920c71b5a6a9c8e login-timeout-30s  C3: regex_missing
fold      sha256:7920c71b5a6a9c8e WARRANTED -> REVOKED
# exit 4 — a load-bearing claim is now false
```

The summary still reads perfectly. Its portrait flipped to **REVOKED** — and every artifact whose
warrant was built on it is flagged `recalled`, so nobody builds on a claim that silently went false.

## We ran this on dorian itself

The `verify` and `revalidate` output above is exactly what dorian prints, shown for an illustrative
`/login` change. The mechanism is no mock-up — we ran it on **dorian's own repository**: `dorian
verify` sealed five true claims about dorian's code (e.g. that `cmd_verify`
and `referenced_paths` exist) — `verified 5/5 claim(s)`, exit 0 — and then renaming a symbol one of
those claims named made `dorian revalidate` flag exactly that claim `BROKEN` and fold the warrant to
`REVOKED` (exit 4), leaving the other four `VERIFIED`. That was a throwaway demo on a real repo — not
a committed artifact and not a benchmark figure — but it is proof the mechanism catches a real break
on real code, for zero model tokens.

## About

An AI agent writes the code and then a confident account of what it did — a PR description, a commit
message, a design note: *"added rate-limiting to `/login`," "the timeout is 30 seconds now," "updated
all callers," "schema bumped to 1.3."* Some of those claims are wrong the moment they're written;
others are true today and go silently false on the next edit. Either way the summary keeps reading
perfectly, the diff looks plausible, and CI is green — so nobody finds out.

That is *The Picture of Dorian Gray*, inverted: the summary is Dorian's ever-youthful portrait,
untouched while the code rots beneath it. `dorian` gives that summary a **portrait in the attic**.
For each checkable claim, you (or your agent) emit a `claims.json` binding the claim to a read-only
deterministic **checker** — C1 (span), C3 (path / symbol / string / regex), C4 (pytest), or C5 (typed
data) — and run `dorian verify`. It auto-captures the files each checker reads, runs every one against
the real current sources, and seals a content-addressed `.warrant` sidecar next to the artifact. It is
**born verifiable**: the seal happens only if every backed claim holds (exit 0), and is refused —
writing nothing — if any claim is already false (exit 4).

From then on, when sources change, `dorian revalidate` re-checks only the claims whose watched files
drifted — deterministically, with **zero model tokens** — and folds the warrant to REVOKED the instant
a claim stops being true, naming the exact claim that broke and recalling every downstream artifact
built on it. The artifact stays pristine; the `.warrant` is where the rot shows.

It is **local-first** (a CLI and a git repo, nothing else), **git-native** (sidecars are committed
beside the artifacts they warrant), and has **zero runtime dependencies**.

## Who verifies the verifier?

As models get cheaper and write more of the code, the confident summary is the easy part — the scarce
thing is cheap, deterministic ground truth that holds *without* a model. `dorian` runs zero model
tokens at check time precisely so it can't be obsoleted by the model it is checking: the one thing a
smarter, cheaper LLM still can't be is its own trustworthy external verifier (LLMs are
[empirically often worse at verifying than at solving](https://arxiv.org/abs/2402.08115)). So an
independent, deterministic, token-free checker tends to get **more** valuable the more code agents
write, not less. That is a tendency, stated as a tendency — but it is why dorian is built around a
checker the model can't talk its way past, rather than another model in the loop.

## Why not just watch files?

A file watcher alarms whenever any supporting file changes — but support files are touched constantly
by refactors, formatting, and adjacent features, and most of those changes don't falsify anything the
artifact says. (Re-reading the diff with another model has the opposite problem: it burns tokens on
every PR and still can't reliably verify itself.) `dorian` checks **claims, not files**: an alarm
means a specific sentence stopped being true.

On the v0.7.0 large controlled-mutation benchmark — 240 (artifact, mutation) pairs over six invented,
synthetic fixture domains (Python/CSV/JSON/YAML/package-metadata/SQL), 16 warranted artifacts, 53
claims, with **known-truth** labels (each label is a mechanical consequence of the edit, not a review
judgment) — claim-level revalidation flagged broken claims at precision **0.93** / recall **0.93**,
versus three file-change watchers all at recall 1.00 but precision **0.34** (naive), **0.56**
(path-scope), and **0.59** (line-aware). That is an **11.6x false-positive reduction** versus the
path-scope watcher (58 → 5 false alarms) and **10.4x** versus the stronger line-aware watcher (52 → 5)
— at a recall cost from substring-scan misses the benchmark records honestly. (The baselines hit recall
1.00 by construction here; the meaningful axis is their precision.)

These numbers describe a synthetic fixture suite, not your repository, and are not a universal
performance claim. See [`docs/BENCHMARK_v0.7.0.md`](docs/BENCHMARK_v0.7.0.md) (protocol:
[`docs/BENCHMARK_PROTOCOL_v0.7.0.md`](docs/BENCHMARK_PROTOCOL_v0.7.0.md)); reproduce with
`dorian bench large-mutation`, and measure your own repos with the harness in `bench/`.

## How it works

1. **Write `claims.json`** — your agent emits it as it works, or you write it by hand
   (see [`docs/AGENT_CLAIMS.md`](docs/AGENT_CLAIMS.md)).
2. **`dorian verify`** — one shot: auto-capture the read-set from each claim's checker, then seal.
   Every checker must pass at seal time, so warrants are born verifiable.
3. **`dorian revalidate`** when sources change — only claims whose watched files drifted are
   re-checked, with zero model tokens.
4. **Inspect** — broken claims, trust-state transitions, the audit trail, and the blast radius of
   downstream artifacts.

```bash
# the one-shot loop: emit claims.json, then verify it against the current code
dorian verify docs/changes/login.md --claims claims.json

# later, after the repo changed
dorian revalidate --since main~20

# inspect
dorian status docs/changes/login.md
dorian blast docs/changes/login.md
dorian report --audit
```

For a C1 *span* claim (a quoted slice of the artifact itself), the read-set can't be derived from the
claim, so use the lower-level two-step instead: `dorian capture` to build the read-set, then
`dorian seal`.

## What gets committed

- the artifact (e.g. `docs/changes/login.md`),
- its `.warrant` sidecar (`docs/changes/login.md.warrant`),
- optional config in `pyproject.toml` (e.g. restricted-path scopes).

**Sidecars are the source of truth.** The SQLite index under `.warrant/` is a local, derived cache —
rebuildable at any time with `dorian sync` — and is never committed.

## Getting started

The distribution is `dorian-vwp`; the import and CLI are `dorian`. The first PyPI release is on the
roadmap — until it lands, install from source:

```bash
pip install 'dorian-vwp @ git+https://github.com/ajaysurya1221/dorian.git'

# extras
pip install 'dorian-vwp[data] @ git+https://github.com/ajaysurya1221/dorian.git'     # + duckdb for parquet data claims
pip install 'dorian-vwp[extract] @ git+https://github.com/ajaysurya1221/dorian.git'  # + anthropic for LLM claim drafting (frozen/experimental)
```

After the first PyPI release:

```bash
pip install dorian-vwp             # core, zero runtime dependencies
pip install 'dorian-vwp[data]'     # + duckdb for parquet data claims
pip install 'dorian-vwp[extract]'  # + anthropic for LLM claim drafting (frozen/experimental)
```

Then run `dorian verify <artifact> --claims claims.json` on one change. For CI, add the composite
[GitHub Action](action/README.md) — it revalidates the claims a pull request touches and posts a
sticky PR comment. **Read its
[security notes](action/README.md#security-checker-execution-and-untrusted-pull-requests) first:**
checker specs in `.warrant` files are *executable* (C4 runs `pytest`, C5 `shell:` runs a command), so
the Action is currently recommended for trusted/internal repositories, not for public repos taking
forked PRs.

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

## Writing claims an agent can be held to

A warrant is worth only what its checkers actually catch. The full authoring contract — the
`claims.json` shape, the four checker families, and the three false-confidence rules (**back** every
load-bearing claim, **bind** the file that would change if the claim went false, **prefer**
shape-tolerant checks like `regex:`/`symbol:`/typed-C5 over brittle `string:`) — lives in
[`docs/AGENT_CLAIMS.md`](docs/AGENT_CLAIMS.md). Checker program grammars (C1 span, C3
path/symbol/string/regex, C4 `pytest:<nodeid>`, C5 typed data) are documented in
[`spec/checkers.md`](spec/checkers.md).

> **Checker programs are executable.** `dorian verify` *runs* every checker at seal time. C3 and typed
> C5 only inspect files, but C4 (`pytest:`) and C5 `shell:` execute code — review an agent-emitted
> `claims.json` exactly as you would review agent-emitted code, and never run `verify` on claims from
> an untrusted source.

## Command surface

The core loop is `verify` (auto-capture the read-set, run every checker, seal the `.warrant`) →
`revalidate` (re-check only what changed). `capture` + `seal` are the lower-level path for C1 span
claims.

- `dorian verify <artifact> --claims claims.json` — the one-shot agent-claims entry point:
  auto-derive the read-set from each C3/C4/C5 checker, then seal (born-verifiable). C1 span claims
  use `dorian capture` + `dorian seal` instead.
- `dorian blast <path|warrant-id> [--max-depth N]` — downstream warrants reachable through the
  derives graph. When `revalidate` newly breaks a claim, every downstream warrant gets a `recalled`
  event: a flag only — downstream is never re-checked and its states are untouched. Re-seal with
  `seal --supersede <old-id>` so downstream warrants sealed against the old id stay reachable.
- `dorian bindings <artifact>` — binding-quality diagnostics (unbacked, single-file, short-literal,
  unwatched-mention). Informational, never a gate; output carries file paths only, never matched
  content.
- `dorian suggest-data-checks <path> [--columns ...] [--out f]` — born-verifiable C5 checker
  suggestions from a data file's current state, for review and pasting into a claim's `checkers` list.
- `dorian report --audit` — the full event log as `dorian-audit-v1` JSONL, byte-identical across
  runs; checker details truncated to 160 chars to bound source-content carryover.
- `dorian revalidate --format md|json` — `md` is the PR-comment body posted by the
  [GitHub Action](action/) (`action/action.yml`, composite, no third-party actions).
- `dorian seal --no-quotes` — content-free sidecars: anchor line numbers stay, quotes are dropped
  (the warrant id changes accordingly).
- Seal-time scope lint: `[tool.dorian.scopes] restricted = [globs]` in the *target* repo's
  pyproject.toml refuses to seal read-sets touching restricted paths (exit 6); `--allow-restricted`
  overrides and is receipted in the sealed event. (It restricts which files a claim may *name*, not
  what an executed checker may read or write — it is not a sandbox.)
- `dorian bench large-mutation` — the v0.7.0 controlled-mutation benchmark (numbers-only aggregate +
  stratified summary; [`docs/BENCHMARK_v0.7.0.md`](docs/BENCHMARK_v0.7.0.md)). `dorian bench mutation`
  is the earlier, smaller benchmark; `dorian bench churn` measures extraction stability.

Exit codes: `0` ok/TRUSTED · `2` usage/infra (incl. a C1 or C5 `shell:` claim handed to `verify`) ·
`3` DEGRADED · `4` REVOKED/integrity · `5` ERRORED-only (checkers could not run — never conflated with
broken) · `6` scope violation.

## Claim extraction is frozen

`--extract` drafts claims with an LLM from a blank file. It still works but is **frozen and
experimental** — it failed its stability gate twice, and the supported, recommended path is now an
agent (or you) emitting `claims.json` directly and running `dorian verify`. See
[`docs/AGENT_CLAIMS.md`](docs/AGENT_CLAIMS.md); treat any extracted claims as drafts for review, never
stable warrant inputs.

## What dorian is not

Not an LLM judge. Not an eval framework. Not a doc generator. Not a framework for running AI tools.
Not a SaaS, a dashboard, or an AI-governance platform. Not a token-burning re-scanner that re-reads
your repo on every PR. It is a small, deterministic CLI that tells you whether stated claims are
**true against the source** — never whether the code is *good* — and makes acceptance of AI-generated
work perishable, so you find out when it expired.

## Roadmap

- **Real catches on real repos** — the dogfood above made the loop usable; next is using it daily and
  recording the breaks it catches that would otherwise have shipped.
- **Closing the binding gap** — today a claim's checker can miss the file that actually defines its
  fact, letting a warrant read TRUSTED while reality drifted; a symbol→defining-file index is the next
  correctness investment ([`docs/NEXT_ALGORITHMIC_BETS.md`](docs/NEXT_ALGORITHMIC_BETS.md)).
- **A public benchmark on real repositories** — extending the synthetic mechanism demonstration to
  frozen public-repo SHAs with manual claims and reproducible known-truth labels
  ([`docs/SOLO_VALIDATION_LADDER.md`](docs/SOLO_VALIDATION_LADDER.md)).
- **Tagged release and PyPI trusted publishing.**

Non-goals stay non-goals: no servers, no dashboards, no hosted control plane, no model at check time.
Local-first is the design center.

## Contributing

```bash
git clone https://github.com/ajaysurya1221/dorian.git
cd dorian
make install   # uv sync
make lint      # ruff check + format check
make test      # pytest
```

Issues and small, focused PRs are welcome. Please keep changes surgical, match the existing style, and
include tests. Benchmark contributions must contain aggregate numbers only — never private repository
content.

## License

Apache-2.0. Protocol: VWP (Validity Warrant Protocol), spec in [`spec/`](spec/).

## Contact

- Issues and discussions: [github.com/ajaysurya1221/dorian](https://github.com/ajaysurya1221/dorian)
- Author: Ajay Surya Senthilrajan ([@ajaysurya1221](https://github.com/ajaysurya1221))
