# dorian — the long-form tour

The [README](../README.md) is the short version. This page keeps the full narrative it used to
carry: the illustrative walkthrough, the story behind the name, the Claude Code and loop-guard
integrations, the governance preview, the complete getting-started path, and the roadmap. The
command reference is in [`COMMANDS.md`](COMMANDS.md); binding semantics (trigger vs. truth) are in
[`BINDING.md`](BINDING.md).

An AI agent says it *added rate-limiting to `/login`, set the timeout to 30s, and updated every
caller.* Some of that is already false; the rest goes false on the next commit — and CI stays green
the whole time. `dorian` turns each checkable claim into a deterministic, token-free check that holds
now and is re-checked on every future change, so a confident summary doesn't quietly become a lie.

> **Local-first and token-free.** dorian runs offline against your git repo — a CLI and your
> commits, nothing else — with **zero model tokens at check time**, so the checker can't be talked
> past by the code it verifies. Because checker programs are *executable* (C4 runs `pytest`, C5
> `shell:` runs a command), it is built for **trusted, internal repositories** — not public CI
> taking forked pull requests by default (for public/fork PRs, `checker_trust: base` runs only
> base-approved checker specs — a trust root, still not a sandbox). Pairs naturally with a coding
> agent such as **Claude Code** ([how](#using-dorian-with-claude-code)).

## The 60-second aha

*(Illustrative — these files are not in your checkout; run the copy-paste demo in the
[README](../README.md#try-it) to try it yourself.)*
An agent finishes a change and emits the claims it just made — a `claims.json` next to
the work, each claim bound to a read-only deterministic checker:

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

> **Trust states.** A warrant is born **WARRANTED**. Each `revalidate` folds it to **TRUSTED**
> (all re-checked claims hold), **DEGRADED** or **REVOKED** (a claim broke — DEGRADED for a
> non-load-bearing break, REVOKED for a load-bearing one), or **UNKNOWN** (a checker could not
> run — ERROR is never silently green and never counted as broken). So `WARRANTED -> REVOKED`
> above is the born state folding on its first revalidation.

## We ran this on dorian itself

The `verify` and `revalidate` output above is exactly what dorian prints, shown for an illustrative
`/login` change. The mechanism is no mock-up — we ran it on **dorian's own repository**: `dorian
verify` sealed five true claims about dorian's code (e.g. that `cmd_verify`
and `referenced_paths` exist) — `verified 5/5 claim(s)`, exit 0 — and then renaming a symbol one of
those claims named made `dorian revalidate` flag exactly that claim `BROKEN` and fold the warrant to
`REVOKED` (exit 4), leaving the other four `VERIFIED`. That was a throwaway demo on a real repo — not
a committed artifact and not a benchmark figure — but it is evidence that the mechanism can catch
this kind of checked break on real code, for zero model tokens.

We have since recorded a **documented, reproducible cross-PR catch on a public repo**. A
load-bearing claim sealed against [`encode/httpx`](https://github.com/encode/httpx) at one
commit — `requires-python` is `">=3.8"` — was flipped `WARRANTED → REVOKED` (exit 4) by a real
*later* upstream PR ([#3592](https://github.com/encode/httpx/pull/3592), "Drop Python 3.8
support", which moved it to `">=3.9"`), while httpx's own test suite stayed green (no test
references `requires-python`) and no stateless per-PR review bot would have re-opened the
original claim. The full command output and a from-scratch reproduction on the public repo are
in [`docs/REAL_CATCH_LOG.md`](REAL_CATCH_LOG.md) — one documented catch, with honest
scope, not a validation claim.

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
performance claim. The headline figures were **measured at v0.7.0** and are **historical**; the
current version reproduces them unchanged (240 pairs, P=R=0.93) — see the version-stamped
[`docs/BENCHMARK_CURRENT.md`](BENCHMARK_CURRENT.md). See
[`docs/BENCHMARK_v0.7.0.md`](BENCHMARK_v0.7.0.md) (protocol:
[`docs/BENCHMARK_PROTOCOL_v0.7.0.md`](BENCHMARK_PROTOCOL_v0.7.0.md)); reproduce with
`dorian bench large-mutation`, and measure your own repos with the harness in `bench/`.

## How it works

1. **Write `claims.json`** — your agent emits it as it works, or you write it by hand
   (see [`docs/AGENT_CLAIMS.md`](AGENT_CLAIMS.md)).
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

## Using dorian with Claude Code

> **One command: `dorian claude-code install-claim-warrants`.** In a trusted repo this scaffolds a
> project-local Claude Code skill — invoke **`/dorian-claim-warrants`** after a change — that drafts the
> change note + `claims.json` for the checkable facts your agent claimed, then prints the verify command:
> `dorian verify docs/changes/<slug>.md --claims docs/changes/<slug>.claims.json --strength-gate=fail
> --binding-gate=warn`. The **model only drafts; `dorian verify` proves** it deterministically and
> token-free. Later, `dorian revalidate --since <base>` REVOKEs a claim the code drifted away from. Add
> `--with-hook` for an opt-in, reminder-only Stop hook. Not a sandbox — trusted repos only. Guide:
> [`docs/DORIAN_CLAIM_WARRANTS_CLAUDE_CODE_SKILL.md`](DORIAN_CLAIM_WARRANTS_CLAUDE_CODE_SKILL.md)
> (and how it differs from Agent Receipts:
> [`docs/CLAIM_WARRANTS_VS_AGENT_RECEIPTS.md`](CLAIM_WARRANTS_VS_AGENT_RECEIPTS.md)).

The intended loop is an agent-in, checker-out handshake: a coding agent writes the change *and* the
`claims.json` for what it just did, dorian verifies those claims against the real code, and then
keeps re-checking them on every later commit. Nothing about dorian is Claude-specific — any agent (or
you) can emit the claims — but the canonical setup is **Claude Code**:

1. After a change, have the agent emit a `claims.json` of the checkable things it just claimed. The
   paste-ready prompt, a runnable example pack, and a `settings.json` permissions sample live in
   [`docs/USE_WITH_CLAUDE_CODE.md`](USE_WITH_CLAUDE_CODE.md) and
   [`examples/claude-code/`](../examples/claude-code/).
2. `dorian verify <artifact> --claims claims.json` — born-verifiable: the seal is refused (exit 4,
   nothing written) if any claim is already false.
3. `dorian revalidate --since <base>` on every later PR re-checks only the claims whose watched files
   changed — zero model tokens — and folds the warrant to REVOKED the instant one stops being true.

> **An agent-emitted `claims.json` is executable input.** `dorian verify` *runs* every checker, and
> C4 (`pytest:`) / C5 `shell:` execute code — review it exactly as you review agent-emitted code, and
> never run `verify` on claims from an untrusted source. When you cannot fully trust the claims, pass
> `--deny-exec` (on `seal`/`verify`/`revalidate`; env `DORIAN_DENY_EXEC=1`): it refuses to run the
> executable families, so a blocked claim ERRORs — it never seals and never silently passes. deny-exec
> is fail-closed, **not a sandbox**; see [SECURITY.md](../SECURITY.md) and
> [docs/SECURITY_BOUNDARY.md](SECURITY_BOUNDARY.md).

## Using dorian inside AI coding loops

When you hand an agent a long-running or unattended task, **Dorian Loop Guard** is the
deterministic verify step the loop runs *before each iteration*. `dorian loop preflight`
re-checks the claim warrants the change touched (token-free, the same `revalidate` engine)
and returns a steering signal — **Dorian does not stop the loop by default**:

- **`continue`** — the warranted claims still hold; do the next planned step.
- **`repair`** — a load-bearing claim is `REVOKED`; fix the smallest cause (or update the
  claim if the change was intentional), re-check, and log the attempt.
- **`escalate`** — a checker `ERRORED`, a sensitive/denylisted path is involved, the repair
  cap was hit, or the break is out of scope; stop autonomous edits and hand off to a human.

```bash
dorian loop preflight --since <base> --policy assist --format json   # the decision packet
dorian loop install                                                  # scaffold /dorian-loop-guard
```

Sealed warrants become the loop's **deterministic memory**: the next iteration revalidates
them instead of re-deriving the facts. Loop Guard steers; it does **not** judge whole-loop
success, replace tests/review, or sandbox execution — and `REVOKED` is a steering signal,
not a halt. Full guide: [`docs/DORIAN_LOOP_GUARD.md`](DORIAN_LOOP_GUARD.md); how it fits
loop engineering: [`docs/LOOP_ENGINEERING_ALIGNMENT.md`](LOOP_ENGINEERING_ALIGNMENT.md).

## Governance foundation (preview)

The deterministic spine of the *"give your goal and go to sleep"* direction — a goal record, a
preflight gate, and a Claude Code adapter that can enforce the loop decision. **The pane/TUI is not
shipped** (see the archived vision note [`archive/docs/DORIAN_PANE.md`](../archive/docs/DORIAN_PANE.md)); this is the CLI + hook layer it will
sit on.

- **`dorian goal add --id <id> --title <t> [--statement … --scope <glob> …]`** — record a
  **human-authored** goal (written to `.dorian/goals/<id>.goal.json`) with a path-scoped coverage
  contract. The `statement` is context for humans; it never feeds a verdict. Read it back with
  **`dorian goal show --id <id>`**.
- **`dorian goal check --id <id> [--since <ref>] [--fail-on-uncovered]`** — a deterministic,
  path-derived **coverage diff**: which changed, in-scope paths are not yet covered by a warrant
  (exit **4** with `--fail-on-uncovered`). It does **not** judge whether the goal is "done".
- **`dorian gate`** — reads a tool-call JSON on stdin and emits the same
  **`continue`/`repair`/`escalate`** decision as Loop Guard; exits `0`/`4` on the decision (or `2`
  only for malformed input) and never uses exit 2 as a veto.
- **`dorian governance install`** — scaffold the **Claude Code** governance adapter: a
  `SubagentStop` hook that runs `dorian gate`, plus a **fail-closed** `PreToolUse` veto (blocks a
  mutating tool on a standing `escalate` under a strict policy — `unattended`, or
  `DORIAN_EFFORT=godmode`; fails open when a human is attended). It is **steering plus a host-side
  veto, not a sandbox**.

Data model and trust boundary: [`docs/GOVERNANCE_DATA_MODEL.md`](GOVERNANCE_DATA_MODEL.md),
[`docs/SECURITY_BOUNDARY.md`](SECURITY_BOUNDARY.md). Provenance is deferred to v1.5; effort
presets are not in core.

## What gets committed

- the artifact (e.g. `docs/changes/login.md`),
- its `.warrant` sidecar (`docs/changes/login.md.warrant`),
- optional config in `pyproject.toml` (e.g. restricted-path scopes).

**Sidecars are the source of truth.** The SQLite index under `.warrant/` is a local, derived cache —
rebuildable at any time with `dorian sync` — and is never committed.

## Getting started

The distribution is `dorian-vwp`; the import and CLI are `dorian`. Install from PyPI:

```bash
pip install dorian-vwp             # core, zero runtime dependencies
pip install 'dorian-vwp[data]'     # + duckdb for parquet data claims
pip install 'dorian-vwp[extract]'  # + anthropic for LLM claim drafting (frozen/experimental)
```

To install the latest unreleased changes, install from source instead:

```bash
pip install 'dorian-vwp @ git+https://github.com/ajaysurya1221/dorian.git'

# extras
pip install 'dorian-vwp[data] @ git+https://github.com/ajaysurya1221/dorian.git'     # + duckdb for parquet data claims
pip install 'dorian-vwp[extract] @ git+https://github.com/ajaysurya1221/dorian.git'  # + anthropic for LLM claim drafting (frozen/experimental)
```

The fastest start is `dorian init`, which scaffolds a born-verifiable starter `claims.json`, the
change note it backs, and a GitHub Action workflow — so the very first `dorian verify` seals green:

```bash
cd your-repo
dorian init                                                # writes claims.json + change note + .github/workflows/dorian.yml
dorian verify dorian-change-note.md --claims claims.json   # seals the warrant — exit 0
```

The starter claim is **load-bearing**: if a later change breaks it, `dorian revalidate` folds the
warrant to **REVOKED** (exit 4) and a default `fail_on: revoked` Action blocks the PR — so the broken
promise can't silently ship. Edit `claims.json` for the real facts your change depends on (add code
claims with `dorian suggest-claims <module.py>`), then commit `dorian-change-note.md.warrant`. For CI, add the composite
[GitHub Action](../action/README.md) — it revalidates the claims a pull request touches and posts a
sticky PR comment. **Read its
[security notes](../action/README.md#security-checker-execution-and-untrusted-pull-requests) first:**
checker specs in `.warrant` files are *executable* (C4 runs `pytest`, C5 `shell:` runs a command), so
the Action is currently recommended for trusted/internal repositories, not for public repos taking
forked PRs.

The workflow snippet, pinned to the released Action tag, lives in the
[README](../README.md#github-action) and in [`action/README.md`](../action/README.md#usage) —
those two copies are the ones the release tests keep in sync with the package version.

Now that `dorian` is installed, the copy-paste runnable demo at the top —
[Try it](../README.md#try-it) — runs end to end against a throwaway repo.

## Writing claims an agent can be held to

A warrant is worth only what its checkers actually catch. The full authoring contract — the
`claims.json` shape, the four checker families, and the three false-confidence rules (**back** every
load-bearing claim, **bind** the file that would change if the claim went false, **prefer**
shape-tolerant checks like `regex:`/`symbol:`/typed-C5 over brittle `string:`) — lives in
[`docs/AGENT_CLAIMS.md`](AGENT_CLAIMS.md). Checker program grammars (C1 span, C3
path/symbol/string/regex plus the V1 structural forms `py-signature:`/`py-const:` and the
comment/docstring-stripped `code:`, C4 `pytest:<nodeid>`, C5 typed data) are documented in
[`spec/checkers.md`](../spec/checkers.md). What V1 strengthening does and does not promise is in
[`docs/V1_SCOPE.md`](V1_SCOPE.md). Worked good/bad claim pairs — and the gutted-body
ceiling, where an existence check is too weak and you need a C4/C5 behavior check — are in
[`docs/WRITING_GOOD_CLAIMS.md`](WRITING_GOOD_CLAIMS.md).

> **Checker programs are executable.** `dorian verify` *runs* every checker at seal time. C3 and typed
> C5 only inspect files, but C4 (`pytest:`) and C5 `shell:` execute code — review an agent-emitted
> `claims.json` exactly as you would review agent-emitted code, and never run `verify` on claims from
> an untrusted source. In untrusted contexts add `--deny-exec` to refuse the executable families
> (fail-closed, not a sandbox — see [SECURITY.md](../SECURITY.md)). For one copy-paste safe recipe for
> public/untrusted fork PRs (`checker_trust: base` + `deny_exec`), see
> [`docs/SECURITY_AND_SAFE_RUNNERS.md`](SECURITY_AND_SAFE_RUNNERS.md).

## What dorian is not

Not an LLM judge. Not an eval framework. Not a doc generator. Not a framework for running AI tools.
Not a SaaS, a dashboard, or an AI-governance platform. Not a token-burning re-scanner that re-reads
your repo on every PR. It is a small, deterministic CLI that tells you whether stated claims are
**true against the source** — never whether the code is *good* — and makes acceptance of AI-generated
work perishable, so you find out when it expired.

## Roadmap

- **Real catches on real repos** — the loop is usable and the first documented cross-PR catch is
  recorded ([`docs/REAL_CATCH_LOG.md`](REAL_CATCH_LOG.md), on `encode/httpx`); next is using it
  daily and recording more of the breaks it catches that would otherwise have shipped.
- **The binding gap, narrowed and measured** — a symbol→defining-file index now re-checks a claim
  when its symbol's definer changes, closing the silent-skip *trigger* gap
  ([`docs/BENCHMARK_BINDING_LIFECYCLE.md`](BENCHMARK_BINDING_LIFECYCLE.md)). C4 behavior claims
  get the same treatment: `dorian` statically resolves the repo-local files a `pytest:` test imports
  and watches them too, so an implementation edit re-runs the test even when the claim text names no
  symbol (`dorian bench c4-import-binding`). What remains is the honest ceiling: a trigger fires the
  re-check, but only the behavior checker proves a behavior change (the gutted-body case), and
  ambiguous or non-Python imports are still left for explicit binding
  (archived planning note: [`archive/docs/NEXT_ALGORITHMIC_BETS.md`](../archive/docs/NEXT_ALGORITHMIC_BETS.md)).
- **A public benchmark on real repositories** — the `dorian bench public-repos` harness now runs
  **machine-derived** structural claims (operands extracted from source; known-truth observed by
  running the checker on the mutated copy) against frozen public-repo SHAs. Two subjects
  (`humanize`, `python-dotenv`) are executed and byte-deterministic across two runs
  ([`docs/BENCHMARK_PUBLIC_REAL_REPOS.md`](BENCHMARK_PUBLIC_REAL_REPOS.md)). These are
  **reproducible on those frozen SHAs only** — not a real-world performance claim; the trigger and
  truth layers are reported separately.
- **PyPI trusted publishing** — `dorian-vwp` is published to PyPI via a Trusted Publisher
  (latest: **`v1.4.0`**); `pip install dorian-vwp` installs the released package.

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

## Contact

- Issues and discussions: [github.com/ajaysurya1221/dorian](https://github.com/ajaysurya1221/dorian)
- Author: Ajay Surya Senthilrajan ([@ajaysurya1221](https://github.com/ajaysurya1221))
