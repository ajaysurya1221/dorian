# Start here

A map of dorian's docs, by what you're trying to do. Each entry is a pointer — the linked
file is authoritative; this page never restates it (a second copy is exactly the drift dorian
exists to catch).

## I'm new — what is this?

- [`README.md`](../README.md) — what dorian is, the 60-second aha, install, and the command surface.
- [What dorian is **not**](../README.md#what-dorian-is-not) — read this before assuming a category.

## I use Claude Code (or another coding agent)

- [`USE_WITH_CLAUDE_CODE.md`](USE_WITH_CLAUDE_CODE.md) — the agent-in, checker-out loop: a paste-ready
  prompt, the safety boundaries, and a worked example.
- [`examples/claude-code/`](../examples/claude-code/) — a runnable example pack (artifact +
  `claims.json` + `settings.json` sample) you can verify in one command.

## I'm writing claims by hand

- [`AGENT_CLAIMS.md`](AGENT_CLAIMS.md) — the authoring contract: the `claims.json` shape,
  `load_bearing`, and the three false-confidence rules.
- [`spec/checkers.md`](../spec/checkers.md) — the authoritative checker grammar (C1/C3/C4/C5).
- [`spec/warrant.schema.json`](../spec/warrant.schema.json) — the sealed-sidecar JSON schema.

## I want the evidence

- [`BENCHMARK_v0.7.0.md`](BENCHMARK_v0.7.0.md) — the controlled-mutation benchmark (precision/recall
  vs. file watchers), with its [protocol](BENCHMARK_PROTOCOL_v0.7.0.md).
- [`BENCHMARK_BINDING_LIFECYCLE.md`](BENCHMARK_BINDING_LIFECYCLE.md) — the two-layer trigger-vs-truth
  benchmark for symbol binding, with its [protocol](BENCHMARK_BINDING_LIFECYCLE_PROTOCOL.md).
- [`REALWORLD_USECASES.md`](REALWORLD_USECASES.md) — offline reproductions of public problem classes,
  with its [protocol](REALWORLD_USECASES_PROTOCOL.md).
- [`PUBLIC_BENCHMARK_PROTOCOL.md`](PUBLIC_BENCHMARK_PROTOCOL.md) — the pre-registered protocol for the
  next rung: real public repos at frozen SHAs (no results yet — protocol only).

## I'm running it in CI

- [`action/README.md`](../action/README.md) — the composite GitHub Action and its **security notes**
  (checker programs are executable; trusted repos only).
- [`TRUSTED_BASE_ACTION_DESIGN.md`](TRUSTED_BASE_ACTION_DESIGN.md) — design (not yet implemented) for a
  trusted-base Action mode that executes only base-branch checker specs.

## I want the why and the roadmap

- [`NEXT_ALGORITHMIC_BETS.md`](NEXT_ALGORITHMIC_BETS.md) — open correctness bets (binding is the main one).
- [`SOLO_VALIDATION_LADDER.md`](SOLO_VALIDATION_LADDER.md) — the rungs from synthetic to real-repo evidence.
- [`NAMING_AND_PRIOR_ART.md`](NAMING_AND_PRIOR_ART.md) — the name, and how dorian relates to prior art.
- [`TESTING.md`](TESTING.md) — how the test suite and coverage gates are organized.
