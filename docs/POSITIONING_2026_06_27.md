# Positioning — 27 June 2026

> Sharp, honest positioning for Dorian's best use case (see
> [`BEST_USE_CASE_2026_06_27.md`](BEST_USE_CASE_2026_06_27.md)). Every line is constrained by
> [`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md): no sandbox, no LLM judging, no semantic proof, no
> broad compliance, not a replacement for tests/review.

## Naming update (v1.3.0)

> **Product name: "claim warrants."** After discovering the nearby **Agent Receipts** / Obsigna project
> (a signed, hash-chained audit trail of agent *actions* — W3C Verifiable Credentials, Ed25519), the
> shipped product name is **Dorian claim warrants**, not "agent receipts." "Receipt" stays only as an
> explanatory metaphor: a Dorian claim warrant is a *receipt for a checkable engineering claim, not a
> receipt for an agent action.* The two are complementary, not substitutes — see
> [`CLAIM_WARRANTS_VS_AGENT_RECEIPTS.md`](CLAIM_WARRANTS_VS_AGENT_RECEIPTS.md). Updated tagline:
>
> **Claim warrants for what your coding agent said changed.**
>
> Shipped in v1.3.0 as a one-command Claude Code skill: `dorian claude-code install-claim-warrants` →
> `/dorian-claim-warrants` (the model drafts; Dorian proves). See
> [`DORIAN_CLAIM_WARRANTS_CLAUDE_CODE_SKILL.md`](DORIAN_CLAIM_WARRANTS_CLAUDE_CODE_SKILL.md).

## Primary tagline

> **Claim warrants for what your coding agent said changed.**

(Earlier metaphor framing: "receipts for what your AI coding agent claimed it changed" — kept only as
descriptive prose, never as the brand.)

Sub-line (when there's room):

> The checkable claims in your agent's change summary become deterministic git receipts that **revoke
> when a later commit makes one false** — token-free, in your own repo.

## Landing-page hero

> **Your coding agent's summary reads perfectly. Six commits later, half of it is quietly false.**
>
> Dorian turns the *checkable* claims an AI coding agent makes — a signature default, a config value, a
> constant, "X still lives in Y" — into deterministic receipts sealed into git. When a later change
> silently breaks one, Dorian flips it to **REVOKED** and names it. No tokens at check time. No LLM
> judging. Your repo, your machine.
>
> `pip install dorian-vwp` · CLI + GitHub Action · zero runtime dependencies

## README pitch (option)

> **Dorian — hold your AI coding agent to what it said it changed.**
> An agent finishes a change and summarizes it. Most of that summary is facts **no test checks** —
> signatures, config defaults, constants, references — so they rot silently as the code drifts. Dorian
> seals the checkable subset into a git `.warrant` (born-verifiable: it won't seal anything already
> false), then **re-checks exactly those claims when the watched files change** — deterministically,
> token-free. A broken claim folds the warrant to `REVOKED` (exit 4) and blocks the PR, naming the
> claim. Not an LLM judge, not a sandbox, not a replacement for tests — the receipt layer that keeps
> stated facts honest as the code moves underneath them.

## GitHub release blurb

> Dorian is the receipt for what your AI coding agent claimed it changed. Seal the checkable claims from
> a change summary into git `.warrant` sidecars; Dorian re-checks them on drift and `REVOKE`s the ones a
> later commit broke — deterministic, local-first, **token-free**. Best for the no-test facts (config,
> signatures, constants, references) your CI stays green on. `pip install dorian-vwp`.

## 5 post drafts

1. Your AI agent's PR summary isn't auto-refreshed when the PR changes — GitHub says so in its own
   docs. So it goes stale, and the next agent treats the stale summary as ground truth. Dorian seals the
   *checkable* claims into git and revokes them when the code drifts. Token-free. `pip install dorian-vwp`

2. Tests verify your code. Nothing verifies your agent's *claim* that "the default is still False" — no
   test fails when it flips. That's the gap Dorian fills: a deterministic receipt that REVOKES on drift.
   Real demo (python-dotenv, 3 min) → [demo link].

3. LLM PR reviewers re-judge from scratch every run and now bill you per review in tokens + CI minutes.
   Dorian re-checks a *specific sealed claim* with a `git show` + an `ast` parse — same answer every
   time, zero tokens. Deterministic > probabilistic for a hard gate.

4. "Phantom changes" — AI PR descriptions that claim edits the code doesn't contain — are now a measured
   phenomenon (arXiv 2601.04886). Make your agent emit `claims.json`; Dorian refuses to seal anything
   that isn't actually true *right now*, and revokes it later if it stops being true.

5. Dorian isn't a sandbox, an LLM judge, or a dashboard. It's a 1-file-per-claim git sidecar that says
   "this stated fact was true at commit X" and yells when a later commit makes it false. Boring,
   deterministic, token-free. That's the point.

## Maintainer-facing explanation

You're merging AI-assisted PRs whose summaries you can't fully re-derive by hand. Ask the change to ship
a `claims.json` of its load-bearing, *checkable* facts (signatures, config, constants, references, and
behavior backed by a `pytest:` node). `dorian verify --strength-gate=fail` seals only the true ones; the
committed `.warrant` then re-checks on every later PR via the Action. You get a deterministic,
low-noise signal — `REVOKED` names the exact claim — instead of re-reading a 30-line summary or trusting
a green check. It complements your tests and review; it does not replace them, and it is scoped to your
own trusted repo (not untrusted forks).

## Enterprise / platform-engineer explanation

Standardize "every risky agent-authored change emits checkable claims" across your trusted internal
repos. Dorian is a local-first, **token-free**, deterministic gate that persists claim-level truth in
git and re-checks on drift — a primitive that *scales with PR volume* without per-review model cost
(unlike LLM reviewers, which are moving to metered billing). It **complements** SLSA/in-toto build
provenance (lineage) with claim-level truth, and policy-as-code (generic gates) with *specific stated
facts*. Roll it out bottom-up from power users; it is not a SaaS and stores nothing off your machine.

## Anti-hype disclaimers (always attach)

- Dorian verifies **specific, checkable** claims — **not** arbitrary correctness, design, or taste, and
  it has **no semantic understanding** of prose.
- It is **not a sandbox** (`C4 pytest:`/`C5 shell:` execute code; trusted repos only), **not an LLM
  judge**, **not a replacement** for tests/SAST/code review/human judgment.
- Truth is only as strong as the checker behind a claim (strongest is `pytest`); weak binding or weak
  checker strength means **low confidence, not a false claim**.
- It verifies only claims someone **wrote** — it cannot catch a lie of omission.
- Warrants are content-addressed but **unsigned** today — trust the repo's write access accordingly.
- Evidence so far is one documented real cross-PR catch plus synthetic/scoped benchmarks and the trials
  in `OUTSIDE_WORLD_VALIDATION.md` — **not** broad market validation.
