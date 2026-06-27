# Dorian claim warrants vs Agent Receipts

Two projects with adjacent names answer **different questions**. They are
complementary, not substitutes. This page keeps them distinct so you pick the right
tool — and so Dorian's "receipt" metaphor is never mistaken for the Agent Receipts
protocol.

## Two different questions

| | **Agent Receipts** / Obsigna | **Dorian claim warrants** |
|---|---|---|
| Core question | *What did the agent do, on whose authority, with what inputs — and was the log tampered with?* | *Is this specific engineering claim true now, and will it revoke when later code makes it false?* |
| Unit of record | An **action** (a tool call the agent made) | A **claim** (a checkable fact a change asserts) |
| Mechanism | A daemon records a tamper-evident **receipt for every tool call**, structured as a W3C Verifiable Credential (`type AgentReceipt`), **signed with Ed25519** and **hash-chained** to the previous receipt | A deterministic checker (AST/regex/file-symbol/`pytest`/data) seals a passing claim into a git `.warrant`; later drift folds it to `REVOKED` |
| Trust property | Integrity of the **action log** (it can't be silently altered) | Truth of the **stated claim** (it can't silently rot as code drifts) |
| When it runs | Continuously, as the agent acts | At seal time, then on later diffs — **token-free**, no model |
| Cryptography | Ed25519 signatures, hash-chain | Content-addressed warrant id (SHA-256); **unsigned** today |
| Surface | Obsigna ecosystem: hook, MCP proxy, SDKs (Go/TS/Python), dashboard | Local-first CLI + GitHub Action; no SaaS, no dashboard |

> Facts about Agent Receipts above are from agentreceipts.ai (verified 2026-06-27):
> "a tamper-evident receipt for every tool call your agent makes", "structured as a
> W3C Verifiable Credential with type AgentReceipt", "signed with Ed25519", "hash
> link to the previous receipt, forming a tamper-evident sequence".

## Why "receipt" here is a metaphor, not a brand

Dorian claim warrants are **receipts for checkable engineering claims, not receipts
for agent actions.** The word describes the artifact ("proof this stated fact held
when sealed, and an alarm if it later breaks"). Dorian does **not**:

- record every tool call the agent made,
- prove *what the agent did* or *who authorized it*,
- produce a signed, hash-chained action audit trail,
- replace Agent Receipts, Sigstore, SLSA, in-toto, or audit logs.

So the product name is **claim warrants**, never "agent receipts".

## They are complementary

- **Agent Receipts** can prove the agent actually called `Edit`/`Write`/`Run` — the
  provenance of the *actions*.
- **Dorian** can prove the agent's stated engineering *claim* ("the default is still
  `False`", "`requires-python` is `>=3.11`") was true when sealed, and detect when a
  later commit silently makes it false.

An action log tells you *that the agent did something*. A claim warrant tells you
*whether what it said it accomplished is still true*. Used together: Agent Receipts
for action provenance, Dorian for claim truth over time.

## What Dorian deliberately is not

Dorian is local-first, git-native, deterministic, and token-free at check time. It
is **not** a sandbox (`C4`/`C5` checkers execute code — trusted repos only), not an
LLM judge, not a SaaS, not a dashboard, and not a generic agent-action recorder. See
[`SECURITY_BOUNDARY.md`](SECURITY_BOUNDARY.md) and
[`VALIDATION_HONESTY.md`](VALIDATION_HONESTY.md).
