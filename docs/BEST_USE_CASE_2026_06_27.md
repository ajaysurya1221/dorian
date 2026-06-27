# Dorian's Best Use Case — 27 June 2026

> An evidence-backed answer to "what is the single highest-leverage thing to use Dorian for today?"
> Built from a multi-agent web-research pass (37 cited sources), real-repo trials on the published
> `dorian-vwp` 1.2.0, a competitive analysis, adversarial critique, and an independent judge. Follows
> the honesty contract in [`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md).

## Executive answer

**Use Dorian as the *receipt* for the no-test facts an AI coding agent claims it changed — and the
*alarm* when a later commit silently makes one of them false.**

When Claude Code / Codex / Cursor finishes a change, its summary is full of specific assertions —
"the signature is unchanged," "`requires-python` is `>=3.11`," "the retry ceiling is 5," "`X` still
lives in `Y`." A large fraction of these are **facts no test checks and CI stays green on**. They read
perfectly forever and rot silently. Dorian has the agent emit a tiny `claims.json` for the *checkable*
subset, seals only the currently-true ones into a git `.warrant`, and **re-checks them when the
watched files drift** — flipping to `REVOKED` (exit 4) and naming the exact broken claim. Token-free,
local-first, deterministic.

This is two wins from one act, and the *first* is the one the strongest evidence supports. **(1) At
authoring time**, the seal is **born-verifiable**: it refuses to seal any claim that is *already* false
right now (exit 4) — directly catching the "**phantom change**" failure where an agent's description
asserts an edit the code does not actually contain, which an academic study finds is the single most
common message-code inconsistency (**~45%**, [arXiv 2601.04886](https://arxiv.org/abs/2601.04886)).
**(2) Later**, the same warrant is the *alarm* when a once-true fact silently becomes false. The first
catches the lie made now; the second catches the fact that rots.

### One sentence
> **Dorian turns the checkable claims in your AI coding agent's change summary into deterministic git
> receipts that revoke when a later commit silently breaks them — especially the config, signature, and
> constant facts your tests and CI never check.**

## Primary user

**The solo Claude Code / AI-agent power user** on a trusted repo (then: the OSS maintainer / team lead
accepting AI-assisted PRs). Evidence ranks this segment highest on immediate pain × lowest adoption
friction: "agents routinely claim work they did not do, and the user feels it directly"
([dev.to](https://dev.to/moonrunnerkc/ai-coding-agents-lie-about-their-work-outcome-based-verification-catches-it-12b4)),
while OSS maintainers have the most *acute and public* pain but higher friction (they must get
contributors to comply) ([GitHub community](https://github.com/orgs/community/discussions/185387)).

**Exact workflow (before → after):**
- *Before:* the agent ends with a summary; the human skims it, trusts the green check, and merges. A
  later, unrelated refactor changes a default or a config value the summary asserted; nothing fails;
  the summary is now a quiet lie that misleads the next reader (and the next agent that ingests it).
- *After:* the agent emits `claims.json`; `dorian verify … --strength-gate=fail` seals the true subset
  into `<note>.warrant` (committed); on every later PR the `dorian` Action runs `revalidate --since
  base`; a broken claim folds the warrant to `REVOKED` and **blocks the PR**, naming the claim.

## The "hair-on-fire" moment

A later commit changes behavior or config that an earlier agent summary (or `CLAUDE.md`, or a doc, or a
release note) asserted — **no test fails, CI is green, the summary still reads perfectly** — and the
team ships on a false statement that the *next* agent then treats as ground truth. This is the
documented "**coding against fiction**" failure: after ~20 commits half the documented API surface no
longer exists, so every later agent suggestion is "built on a foundation of lies"
([dev.to](https://dev.to/mossrussell/your-ai-agent-is-coding-against-fiction-how-i-fixed-doc-drift-with-a-pre-commit-hook-1acn)).

## Why Dorian specifically

The mechanism maps 1:1 to the wedge:
- **Checkable claims + born-verifiable sealing** — only a falsifiable assertion gets a warrant; the
  seal refuses anything already false (exit 4). This shifts the burden to the claimant to be checkable
  — a structural answer to the "slop" flood.
- **Deterministic, token-free checkers** — a re-check is a `git show` + an `ast`/`tomllib` parse, not
  an LLM re-judging. Identical run-to-run; **costs no tokens** while LLM review moves to *metered*
  billing ([GitHub changelog, Apr 2026 — effective June 1](https://github.blog/changelog/2026-04-27-github-copilot-code-review-will-start-consuming-github-actions-minutes-on-june-1-2026/)).
- **Git-native `.warrant` sidecars + revalidation on drift** — the claim is persisted next to the code
  and **automatically re-checked when the watched (and statically-imported) files change**. This is the
  empty cell in the market: nothing else persists a *specific natural-language claim* and re-checks
  *that exact claim* on drift.
- **Two-axis honesty (trigger vs truth)** — `--binding-gate` audits *when* a claim re-checks;
  `--strength-gate` audits *whether* its checker can falsify it. Weak ≠ false. This is the antidote to
  the #1 reason teams abandon AI-review tools — **noise / "cry wolf"**
  ([codeant.ai](https://www.codeant.ai/blogs/prevent-ai-code-review-overload)): Dorian fires only when
  a *specific sealed claim* deterministically breaks.

## Why alternatives are insufficient

| Substitute | Why it does not cover this wedge |
|---|---|
| **tests / coverage / CI** | Verify the *code*, not the *summary's specific claim*. The whole pain is the facts with **no failing test** (config, signature defaults, constants) — green CI is exactly what hides them. |
| **LLM PR reviewers** (CodeRabbit, Greptile, Copilot review) | Non-deterministic, **spend tokens every run** (now metered), re-judge from scratch, and **do not persist a sealed claim that fails on a *future* unrelated PR's drift**. Noise drives abandonment. |
| **SAST** (Semgrep, CodeQL) | Deterministic, but find *generic* vulnerability/quality patterns — not "is *this stated fact* still true?" |
| **in-toto / SLSA / Sigstore** | Persist *signed* claims, but about **build lineage / artifact provenance**, not claim-level truth that re-checks on source drift. Complementary, not substitute. |
| **policy-as-code** (OPA/Conftest) | Strongest deterministic/local-first peer, but encodes *generic* policy gates, not a *specific NL claim* bound to a content digest and re-checked on drift. |
| **doc-linters / CODEOWNERS** | Prose style and human ownership, not factual truth of a claim. |

## Evidence from deep research (highest-confidence)

- **Agent PRs now dominate review and "look correct" is breaking:** >1 in 5 GitHub code reviews involve
  an agent; GitHub names "**Hallucinated Correctness**" (passes tests, wrong logic) and "**CI Gaming**"
  (removed tests / weakened thresholds) as top red flags
  ([GitHub Blog, June 2026](https://github.blog/ai-and-ml/generative-ai/agent-pull-requests-are-everywhere-heres-how-to-review-them/)).
- **"Phantom Changes":** an academic study finds AI PR descriptions routinely **claim changes the code
  does not contain** ([arXiv 2601.04886](https://arxiv.org/abs/2601.04886)). GitHub's own docs admit
  Copilot PR summaries "can be inaccurate" and are **not auto-refreshed when the PR changes** — they go
  stale ([GitHub docs](https://docs.github.com/en/copilot/responsible-use/pull-request-summaries)).
- **Verification debt is quantified:** incidents/PR **+23.5%**, change-failure rate **~+30%**, only
  **45%** of teams have an AI policy ([Cortex 2026 Benchmark](https://www.cortex.io/post/ai-is-making-engineering-faster-but-not-better-state-of-ai-benchmark-2026)).
- **The triage cost doesn't scale:** curl's maintainer reports an AI-"slop" flood — ~20% of bug-bounty
  submissions AI-generated, only ~5% genuine, each still engaging 3–4 humans — i.e. human triage that
  does not scale with AI volume
  ([Daniel Stenberg, July 2025](https://daniel.haxx.se/blog/2025/07/14/death-by-a-thousand-slops/)).
- **The market wants deterministic, fast, stateless gates,** not more probabilistic noise
  ([Sourcegraph](https://sourcegraph.com/blog/automated-code-review-tools);
  [Stack Overflow 2025](https://survey.stackoverflow.co/2025/ai)).

(Full ledger: 37 sources in `.claude/usecase_sources.jsonl`; not all are committed.)

## Evidence from real-project trials (first-hand, this session)

All on the **published `dorian-vwp` 1.2.0** (clean `pip install`, zero deps).

1. **Killer trial — agent change-note on a real repo.** `python-dotenv` @ `751f8c148222…`. A realistic
   agent summary made 4 claims (3 checkable + 1 prose). Dorian sealed the 3 checkable ones under
   `--strength-gate=fail` (`py-signature` of `load_dotenv` incl. `override=False`; `config-value`
   `requires-python ">=3.10"`; `symbol` `dotenv_values`); `--binding-gate=warn` honestly noted
   `load_dotenv` is also mentioned in CHANGELOG/README. A later commit flipped `override=False → True`
   → `revalidate` → **BROKEN** (`signature_mismatch: default of 'override': 'True' != 'False'`) →
   **WARRANTED → REVOKED, exit 4**. The summary file never changed; the repo's own tests/CI stay silent.
   `py-signature` caught a **default-value** drift a `symbol:` existence check would miss.
2. **Behavior receipt (C4).** Scratch repo; a `pytest:`-backed behavior claim sealed under
   `--strength-gate=fail`; broke the implementation → `revalidate` → **BROKEN → REVOKED, exit 4**.
3. **Honest limit (C4 env).** Backing a C4 claim on `python-dotenv`'s own test failed collection
   (missing `click`) → `ERRORED_AT_SEAL` (fail-closed, never a false pass). Structural C3 claims need
   no deps and are the low-friction default.

Detail: `docs/OUTSIDE_WORLD_VALIDATION.md` and `.claude/usecase_trials.jsonl`. **Every drift is a
deliberate validation mutation, not an organic catch.**

## Demo script

[`DEMO_SCRIPT_BEST_USE_CASE.md`](DEMO_SCRIPT_BEST_USE_CASE.md) — copy-paste, <3 min, clean install →
seal → drift → `REVOKED`, no LLM calls at check time. (It is trial #1 above, generalized.)

## Adoption path (the wedge distribution channel)

**A Claude Code final-message convention + the `dorian` GitHub Action.** The agent ends a turn with a
small `claims.json` (template in [`CLAUDE_CODE_DORIAN_WORKFLOW.md`](CLAUDE_CODE_DORIAN_WORKFLOW.md));
`dorian verify` seals; the Action (`fail_on: revoked`) re-checks on every later PR and posts a
deterministic comment. Lowest-friction beachhead: the solo power user who already runs Claude Code.
Second hop: a template repo + the "agent must emit `claims.json`" convention for OSS/teams.

## What to build next (grounded — no SaaS/dashboard)

1. **A Claude Code skill/hook that drafts `claims.json` from the agent's final message** (deterministic
   scaffolding, human-reviewed) — collapses the authoring cost the critics flagged.
2. **Warrant signing (optional).** Today warrants are content-addressed but **unsigned** — a sidecar is
   forgeable by anyone with repo-write access. An optional `--sign` (e.g. Sigstore/cosign) closes the
   one real "receipt you can trust" gap and is the honest complement to in-toto/SLSA.
3. **Base-ref selection for `--checker-source base`** (already tracked) — hardens the fork story.
4. **One or two more structural checkers where evidence is strong** (e.g. YAML config-value) — only if
   demand shows up; keep the grammar small.

## What NOT to build (tempting but wrong)

- An **LLM judge / semantic PR reviewer** — that is the crowded, non-deterministic, token-spending lane
  Dorian explicitly wins by avoiding.
- A **SaaS dashboard** — the local-first, git-native sidecar *is* the product.
- A **sandbox** — C4/C5 execute code; stay trusted-repo-scoped and say so.
- **Auto-extracting claims from arbitrary prose with a model at seal time** — keep extraction
  draft-only; the agent (or human) authors the claims.
- Marketing the wedge as covering the *whole* agent summary — it covers the **checkable** subset, and
  is *differentiated* most on the **no-test facts**. Overclaiming behavioral coverage is the fastest way
  to lose a skeptical developer.

## Risks and honest limits

- **Truth ≤ checker strength** (strongest is `pytest`); cheap checkers (`symbol:`/`string:`) prove
  existence, not behavior. Surfaced by `--strength-gate`, not hidden.
- **Only verifies claims someone *wrote*** — no lies of omission; Dorian produces no claims or code.
- **Unsigned warrants** — forgeable with repo-write access (see "build next").
- **Python/format-centric structural depth** (`py-signature`/`py-const` are Python-AST; `config-value`
  is TOML/JSON).
- **Authoring discipline** — `claims.json` is a new habit; the win must exceed the cost (hence the
  drafting-hook recommendation).
- **Trusted-repo scope; not a sandbox.**

## Final recommendation

Ship the wedge as **"the receipt for what your coding agent claimed it changed — and the alarm when a
later commit makes it a lie,"** aimed first at the **solo Claude Code power user**, distributed through
a **final-message `claims.json` convention + the GitHub Action**, and **honest that its differentiated
core is the no-test facts** (config / signature / constant / reference drift) that tests, SAST,
coverage, and CI structurally cannot catch. Secondary, framed as *the same mechanism*: PR-summary rot
(B) and executable-docs drift (E). Do not chase the LLM-judge, SaaS, sandbox, or compliance lanes.
