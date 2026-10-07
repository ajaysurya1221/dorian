<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/dorian-hero.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/dorian-hero-light.png">
  <img src="docs/assets/dorian-hero-light.png" alt="dorian — hold AI agents to what they said they did" width="720">
</picture>

# dorian

**Hold AI agents to what they said they did.**

<p>
  <a href="#install"><img src="https://img.shields.io/badge/Quickstart-2ea44f?style=for-the-badge" alt="Quickstart"></a>
  <a href="#try-it"><img src="https://img.shields.io/badge/Demo-1f6feb?style=for-the-badge" alt="Demo"></a>
  <a href="action/README.md"><img src="https://img.shields.io/badge/GitHub_Action-6e40c9?style=for-the-badge" alt="GitHub Action"></a>
</p>

<p>
  <a href="https://github.com/ajaysurya1221/dorian/actions/workflows/ci.yml"><img src="https://github.com/ajaysurya1221/dorian/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="Apache-2.0">
  <a href="https://github.com/ajaysurya1221/dorian/releases/latest"><img src="https://img.shields.io/github/v/release/ajaysurya1221/dorian?label=release&color=blue" alt="Latest release"></a>
</p>

</div>

`dorian` turns explicit claims about a code change into executable checks and stores their results
in a `.warrant` beside the code. Later revalidation reruns affected checks and revokes warrants when
those checks fail. Verification makes no model calls (**zero model tokens at check time**); its
strength depends on the claims, checkers and trusted execution environment. Its question is:
**"Does the code still satisfy this recorded claim?"**

The agent (or you) writes a `claims.json` of checkable claims about a change — "`handler()` lives in
`app.py`", "the login timeout is 30 seconds", "`test_login_ratelimit` passes". `dorian verify` runs
each claim's checker against the code and seals the results in a git-committed `.warrant` sidecar. On
each later commit, `dorian revalidate` re-runs only the checks whose watched files changed and flips
the warrant to **REVOKED** when a load-bearing claim's check fails, naming the claim. It ships as a
CLI, a GitHub Action, and Claude Code hooks, with **zero runtime dependencies**.


## Try it

A self-contained run in a throwaway directory, with its own virtual environment and a command-local
Git identity, so it needs no prior install and no global Git configuration. The demo repository and virtual environment stay in the temporary directory. (A black-box test pins the commands and their exit codes.)

```bash
tmp=$(mktemp -d)
cd "$tmp"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install dorian-vwp==1.4.0
git init -q
printf '.venv/\n' > .gitignore

printf 'def handler():\n    return 200\n' > app.py
printf '# change note\n\n`handler()` lives in app.py.\n' > note.md
git add app.py note.md .gitignore
git -c user.name=Demo -c user.email=demo@example.invalid \
  -c commit.gpgsign=false commit -q -m "app + note"

cat > claims.json <<'JSON'
{"claims": [
  {"id": "handler-exists", "text": "handler() lives in app.py.",
   "kind": "reference", "load_bearing": true,
   "checkers": [{"type": "C3", "program": "symbol:app.py::handler"}]}
]}
JSON

dorian verify note.md --claims claims.json     # -> verified 1/1 claim(s)  (exit 0)

# now a refactor renames the function the note claims exists:
printf 'def renamed():\n    return 200\n' > app.py
dorian revalidate --since HEAD                 # -> handler-exists BROKEN; WARRANTED -> REVOKED  (exit 4)
```

`note.md` never changed, but the warrant flips to REVOKED and names the claim whose check failed.
`python3` must be 3.11 or newer. For other ways to install, see [Install](#install).

## What it checks and what it does not

A claim is bound to one of four checker families: **C1** (a quoted span of the artifact itself),
**C3** (a path, symbol, string, or regex in a file, plus the structural `py-signature:` /
`py-const:` / `code:` / `config-value:` forms), **C4** (a `pytest:` node id), or **C5** (typed data
checks on CSV/parquet files, or a `shell:` command). C1, C3, and typed C5 only read files; C4 and C5
`shell:` execute code (see [Security](#security-claims-are-executable-input)). `verify` is
*born-verifiable*: it seals only if every claim holds right now (exit 0) and writes nothing
otherwise (exit 4). A warrant is born **WARRANTED** and folds on each `revalidate` to **TRUSTED**,
**DEGRADED**, **REVOKED**, or **UNKNOWN** (a checker could not run — never counted as broken, never
silently green).

The honest limits:

- **Binding is a re-check trigger, not a behavior proof.** When a claim names a symbol, dorian also
  watches the file that defines it, so an edit there re-checks the claim — but the checker still
  decides truth. A watched file changing never makes a claim BROKEN by itself: binding is trigger
  coverage, **not** behavior proof. Ambiguity is skipped, not guessed — a symbol defined in more than
  one file is left unwatched. Details: [`docs/BINDING.md`](docs/BINDING.md).
- **The gutted-body ceiling.** If a function keeps its name but its behavior changes, an existence
  check (`symbol:`) fires the re-check and passes. Only a behavior checker (a `pytest:` test) on the
  same edit catches it. `--strength-gate` flags load-bearing claims backed only by existence checks.
- It reports whether stated claims are **true against the source** — never whether the code is
  *good*. Not an LLM judge, not an eval framework, not a sandbox.
  Full list: [What dorian is not](docs/OVERVIEW.md#what-dorian-is-not).

## Security: claims are executable input

`dorian verify` *runs* every checker. C1, C3, and typed C5 only read files, but **C4 (`pytest:`) and
C5 `shell:` execute code** — so a `claims.json` or a `.warrant` is executable input. Treat an
agent-emitted `claims.json` like agent-emitted code: review it, and never run `verify` on claims from
an untrusted source. dorian is built for **trusted, internal repositories** — not public CI
taking forked pull requests by default. When you cannot trust the claims, `--deny-exec` (env
`DORIAN_DENY_EXEC=1`) makes the executable families ERROR instead of running (fail-closed, never a
silent pass), and `checker_trust: base` runs only base-approved checker specs on fork PRs. Neither is
a sandbox. See [SECURITY.md](SECURITY.md) and [`docs/SECURITY_BOUNDARY.md`](docs/SECURITY_BOUNDARY.md).

## Install

The PyPI distribution is `dorian-vwp`; the import and CLI are `dorian`. Python 3.11+, zero runtime
dependencies, trusted publishing (latest: **`v1.4.0`**).

```bash
pip install dorian-vwp             # core
pip install 'dorian-vwp[data]'     # + duckdb for parquet data claims
pip install 'dorian-vwp[extract]'  # + anthropic for LLM claim drafting (frozen/experimental)
```

`dorian init` scaffolds a born-verifiable starter `claims.json`, its change note, and a workflow
file, so the first `dorian verify` seals green:

```bash
cd your-repo
dorian init
dorian verify dorian-change-note.md --claims claims.json   # seals the warrant — exit 0
```

## GitHub Action

The composite [Action](action/README.md) revalidates the claims a pull request touches and posts a
sticky PR comment; with `fail_on: revoked`, a broken load-bearing claim blocks the PR. Read its
[security notes](action/README.md#security-checker-execution-and-untrusted-pull-requests) first.

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
        with:
          fetch-depth: 0             # revalidate diffs against the PR base sha
          persist-credentials: false # the Action only reads the diff + posts via GITHUB_TOKEN
      - uses: ajaysurya1221/dorian/action@v1.4.0
        with:
          fail_on: revoked
          # install defaults to the published PyPI package (dorian-vwp); pin a
          # version or set a git source spec to install unreleased changes
```

## Using dorian with Claude Code

One command scaffolds a project-local skill: `dorian claude-code install-claim-warrants`. After a
change, `/dorian-claim-warrants` drafts the change note + `claims.json` for the checkable facts the
agent claimed and prints the verify command. **The model drafts; deterministic checkers evaluate the
specified claims.** Review the drafted `claims.json` before running `verify`: C4 and C5 `shell:`
checkers execute code ([Security](#security-claims-are-executable-input)). On later PRs,
`dorian revalidate --since <base>` re-runs the affected checks and revokes a warrant when a
load-bearing check fails. Add `--with-hook` for an opt-in, reminder-only Stop hook. Paste-ready
prompt, runnable example pack, and `settings.json` sample:
[`docs/USE_WITH_CLAUDE_CODE.md`](docs/USE_WITH_CLAUDE_CODE.md) and
[`examples/claude-code/`](examples/claude-code/).

Using dorian inside AI coding loops: `dorian loop preflight --since <base>` re-checks the warrants a
change touched before each iteration and returns `continue` / `repair` / `escalate` — a steering
signal, not a halt ([`docs/DORIAN_LOOP_GUARD.md`](docs/DORIAN_LOOP_GUARD.md)). `dorian governance
install` adds a `SubagentStop` gate and a fail-closed `PreToolUse` veto for unattended runs
([`docs/GOVERNANCE_DATA_MODEL.md`](docs/GOVERNANCE_DATA_MODEL.md)).

## Commands at a glance

- `dorian verify <artifact> --claims claims.json` — run every checker and seal the `.warrant`
  (born-verifiable). `--supersede <old-id>` re-seals over an earlier warrant, `--no-quotes` writes a
  content-free sidecar, `--allow-restricted` overrides the `[tool.dorian.scopes]` seal-time lint.
- `dorian revalidate --since <ref> --format md` — re-check only the claims whose watched files
  changed; `md` is the PR-comment body the Action posts.
- `dorian status <artifact>` · `dorian blast <artifact>` — trust state; downstream warrants, which
  are flagged `recalled` when a claim they build on breaks.
- `dorian bindings <artifact>` · `dorian bind-suggest --claims claims.json` · `dorian rebind` —
  binding diagnostics, a preview of the files `verify` would auto-bind, re-derived watches.
- `dorian suggest-claims <file.py>` · `dorian suggest-data-checks <data-file>` — born-verifiable
  claim and C5 checker suggestions to paste into `claims.json`.
- `dorian report --audit` — the event log as byte-identical JSONL.
- `dorian bench mutation` · `bench large-mutation` · `bench binding-lifecycle` · `bench public-repos`
  — the benchmark suites; they need a source checkout with development dependencies (the wheel does
  not ship `bench/`).

Exit codes: `0` ok/TRUSTED · `2` usage/infra · `3` DEGRADED · `4` REVOKED/integrity · `5`
ERRORED-only (checkers could not run; never conflated with broken) · `6` scope violation.
Full reference: [`docs/COMMANDS.md`](docs/COMMANDS.md).

## Evidence

- **Synthetic benchmark.** Over 240 (artifact, mutation) pairs across six invented fixture domains
  with known-truth labels, claim-level revalidation flagged broken claims at precision **0.93** /
  recall **0.93**, versus file-change watchers at recall 1.00 but precision **0.34** (naive),
  **0.56** (path-scope), and **0.59** (line-aware) — **11.6x** fewer false alarms than the path-scope
  watcher (58 → 5) and **10.4x** fewer than the line-aware one (52 → 5). Synthetic, not your
  repository; measured at v0.7.0 ([`docs/BENCHMARK_v0.7.0.md`](docs/BENCHMARK_v0.7.0.md);
  compatibility notes in [`docs/BENCHMARK_CURRENT.md`](docs/BENCHMARK_CURRENT.md)). Historical
  synthetic result, last rerun at v1.2.0. To reproduce from a source checkout with development
  dependencies installed, run `uv run dorian bench large-mutation`.
- **Retrospective public-repository check.** Revalidating a warrant across two pinned httpx commits
  detected the documented Python-support change. This is a scoped reproduction, not evidence of
  deployment adoption or a prevented production defect. The load-bearing claim was that
  [`encode/httpx`](https://github.com/encode/httpx) declares `requires-python = ">=3.8"`; the upstream
  commit for [#3592](https://github.com/encode/httpx/pull/3592) ("Drop Python 3.8 support") flipped the
  warrant WARRANTED → REVOKED (exit 4). Full output and a from-scratch reproduction:
  [`docs/REAL_CATCH_LOG.md`](docs/REAL_CATCH_LOG.md). One documented case, not universal validation.

## Docs

- [`docs/START_HERE.md`](docs/START_HERE.md) — the docs map, by what you are trying to do.
- [`docs/OVERVIEW.md`](docs/OVERVIEW.md) — the long-form tour, incl. what dorian is not and the roadmap.
- [`docs/COMMANDS.md`](docs/COMMANDS.md) — the full command reference.
- [`docs/BINDING.md`](docs/BINDING.md) — binding semantics: trigger vs. truth.
- [`docs/AGENT_CLAIMS.md`](docs/AGENT_CLAIMS.md) and [`spec/checkers.md`](spec/checkers.md) —
  writing claims; the checker grammar.
- [`docs/BENCHMARK_CURRENT.md`](docs/BENCHMARK_CURRENT.md) — archived benchmark results and
  compatibility notes.
- [`SECURITY.md`](SECURITY.md) and [`docs/SECURITY_BOUNDARY.md`](docs/SECURITY_BOUNDARY.md) — security.
- [`docs/ROADMAP_BACKLOG.md`](docs/ROADMAP_BACKLOG.md) — the structured roadmap backlog.

## Contributing

```bash
git clone https://github.com/ajaysurya1221/dorian.git && cd dorian
make install && make lint && make test
```

Small, focused PRs with tests are welcome. Benchmark contributions carry aggregate numbers only.
Development setup, checks, and conventions: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

Apache-2.0. Protocol: VWP (Validity Warrant Protocol), spec in [`spec/`](spec/).
Author: Ajay Surya Senthilrajan ([@ajaysurya1221](https://github.com/ajaysurya1221)).
