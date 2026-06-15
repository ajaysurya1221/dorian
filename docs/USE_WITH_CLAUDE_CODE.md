# Using dorian with Claude Code

If you use Claude Code (or another coding agent) to write code and then a PR description, commit
message, or change note describing it, dorian verifies those notes against the source **now** and
re-checks them on every future commit — deterministically, with **zero model tokens at check time**.

The handshake is *agent-in, checker-out*: the agent (the cheapest, most context-aware author of what
it just did) emits the claims; dorian decides — deterministically, with no model in the loop —
whether they are true against the real code. Nothing here is Claude-specific; any agent or a human can
emit the claims. A complete, runnable version of everything below is in
[`examples/claude-code/`](../examples/claude-code/).

> **First, the boundary.** Checker programs in a `claims.json` are *executable*: `dorian verify` runs
> every one at seal time. C3 and typed C5 only inspect files, but **C4 (`pytest:`) and C5 `shell:`
> execute code** (pytest collection imports the target module and any `conftest.py`). Treat an
> agent-emitted `claims.json` exactly as you treat agent-emitted code — **review it before you run
> `verify`, and never run `verify` on claims from an untrusted source.** dorian is built for trusted,
> internal repositories, not public CI taking forked pull requests. In an untrusted context, add
> `--deny-exec` (env `DORIAN_DENY_EXEC=1`) so C4/C5 `shell:` ERROR instead of running — fail-closed,
> but **not a sandbox** (see [`SECURITY.md`](../SECURITY.md)).

## 1. The loop

```bash
# 1. the agent finishes a change and emits claims.json next to its change note
# 2. verify the note against the real, current code (born-verifiable: refused if already false)
dorian verify change-note.md --claims claims.json
#    -> verified 2/2 claim(s) against current sources -> change-note.md.warrant   (exit 0)

# 3. on every later PR, re-check only the claims whose watched files changed
dorian revalidate --since origin/main
#    -> a load-bearing claim that stopped being true folds the warrant to REVOKED  (exit 4)
```

`dorian verify` requires the artifact and `--claims`; `dorian revalidate --since <ref>` diffs against
a git ref and re-checks only the intersecting claims. (For a C1 *span* claim — a quoted slice of the
artifact itself — use `dorian capture` + `dorian seal` instead; `verify` can't derive that read-set.)

> **Optional review gate.** Once you've reviewed the agent-emitted `claims.json`, you can make the
> seal itself flag or block weak bindings. During early adoption run `dorian verify … --binding-gate
> warn` (it prints binding diagnostics after sealing, exit 0); switch to `--binding-gate fail` only
> when you want a stricter gate (it refuses the seal, writing nothing, on a high-risk weak binding).
> It is **off** by default and never treats weak binding as a claim being false — see
> [`AGENT_CLAIMS.md`](AGENT_CLAIMS.md).

## 2. The paste-ready prompt

Give your agent this once you've finished a change and want it held to its summary:

```text
You just finished a change. Produce two files next to it:

1. change-note.md — a short, honest account of what you changed.
2. claims.json — the checkable claims that note makes, in dorian's format:
   { "claims": [ { "id": "...", "text": "...", "kind": "fact|reference|behavior|quantity|decision",
                   "load_bearing": true|false, "checkers": [ { "type": "C3", "program": "..." } ] } ] }

Rules for claims.json:
- One claim per verifiable assertion. id is a stable kebab-case handle; never renumber.
- load_bearing: true if this breaking should BLOCK a merge (folds REVOKED), false for a soft warning.
- Back every load-bearing claim with at least one checker. If you cannot name a deterministic check
  for an assertion, do NOT emit a claim for it — leave it as prose.
- Prefer shape-tolerant checkers that survive reformatting:
    "X exists"            -> C3 symbol:<file>::X
    "value is N"          -> C3 regex:<file>::KEY\s*=\s*N\b      (anchor BOTH key and value)
    "file/path exists"    -> C3 path:<repo/path>
    "tests for X pass"    -> C4 pytest:<file>::<test>            (this RUNS the test)
    data shape/rowcount   -> typed C5 (schema:/rowcount:/domain:/nullrate:/freshness:/snapshot:)
  Avoid C3 string: for anything that must survive reformatting, and avoid short (<6 char) literals.
- Use repo-relative paths only. No absolute paths, no "..".
- Bind the file that would CHANGE if the claim went false — not merely a file the name appears in.

Then run:  dorian verify change-note.md --claims claims.json
If it exits 4, a claim is already false or its checker can't run — fix the claim or the code, never
fake a checker. Then run `dorian bindings change-note.md` and resolve every flag before you're done.
```

The full authoring contract (the `claims.json` shape, `load_bearing`, the three false-confidence
rules, and a checker-choice table) is [`docs/AGENT_CLAIMS.md`](AGENT_CLAIMS.md); the authoritative
checker grammar is [`spec/checkers.md`](../spec/checkers.md). This page points at them rather than
restating them — a second copy is exactly the drift dorian exists to catch.

## 3. A worked example

The artifact ([`examples/claude-code/change-note.md`](../examples/claude-code/change-note.md)):

```markdown
# Change note — login handler
Added a `login_handler` to `app.py` and set the login request timeout to 30 seconds.
```

The claims ([`examples/claude-code/claims.json`](../examples/claude-code/claims.json)):

```json
{
  "claims": [
    { "id": "login-handler-added", "text": "app.py defines a login_handler.",
      "kind": "behavior", "load_bearing": true,
      "checkers": [{ "type": "C3", "program": "symbol:app.py::login_handler" }] },
    { "id": "login-timeout-30s", "text": "The login request timeout is 30 seconds.",
      "kind": "quantity", "load_bearing": true,
      "checkers": [{ "type": "C3", "program": "regex:app.py::LOGIN_TIMEOUT\\s*=\\s*30\\b" }] }
  ]
}
```

```text
$ dorian verify change-note.md --claims claims.json
verified 2/2 claim(s) against current sources -> change-note.md.warrant   # exit 0

# later, app.py renames login_handler and drops the timeout to 10:
$ dorian revalidate --since HEAD
BROKEN  login-handler-added   C3: symbol_missing
BROKEN  login-timeout-30s     C3: regex_missing
fold    WARRANTED -> REVOKED                                              # exit 4
```

Run it end-to-end with the copy-paste block in
[`examples/claude-code/README.md`](../examples/claude-code/README.md).

## 4. Permissions

[`examples/claude-code/settings.example.json`](../examples/claude-code/settings.example.json) is a
review-first snippet to merge into your project's `.claude/settings.json`. By default it pre-allows
only inspection-oriented commands (`status`, `bindings`, `bind-suggest`) so an agent can inspect the
repo without executing claim checkers.

`dorian verify` runs checkers from `claims.json`; in plain terms, verify runs checker programs, so an
agent-emitted `claims.json` is executable input and should require review before execution. The
`dorian revalidate` command can also execute checker specs from existing sidecars. C4 (`pytest:`) and
C5 `shell:` execute code; `seal`, `--extract`, and arbitrary shell are likewise left under normal
review by the default sample.

For a faster trusted-local workflow, opt into
[`examples/claude-code/settings.trusted-local.example.json`](../examples/claude-code/settings.trusted-local.example.json)
only when you trust the local repo and review agent-emitted `claims.json` before execution. That
trusted-local sample pre-allows `verify`/`revalidate` for speed, but it is not the default and still
does not pre-allow `seal`, `--extract`, or arbitrary shell.

## 5. Claim extraction is frozen — emit claims, don't extract them

`dorian seal --extract` (drafting claims with an LLM from a blank file) still works but is **frozen
and experimental** — it failed its stability gate twice. The supported path is the agent emitting
`claims.json` directly, as above; treat any `--extract` output as a draft for review, never a stable
warrant input. dorian itself runs **no model at check time, ever** — that is the point.

## 6. What dorian is / is not

**Is:** a local-first, git-native CLI that turns the checkable claims in an AI-authored change into
deterministic, token-free checks, seals them into a content-addressed `.warrant` sidecar, and
re-checks only the affected claims when sources change.

**Is not:** an LLM judge, an eval framework, a doc generator, a framework for running AI tools, a
SaaS/dashboard/AI-governance platform, or a token-burning re-scanner. It tells you whether stated
claims are **true against the source** — never whether the code is *good*. And binding a claim to a
symbol widens *when it's re-checked*; the checker still decides whether it's *true* (a watched file
changing never makes a claim BROKEN by itself).
