# Change note — Claude Code onboarding + launch-train scaffolding

This change moves dorian toward a launch-safe state with docs and examples only — no product
behavior change, no new runtime dependency, no trust-state or schema change.

What it did:

- **README** — added a prominent local-first / token-free / trusted-repo **boundary callout** near
  the top and a **"Using dorian with Claude Code"** workflow section above the command surface
  (additive; the ring-1 command surface and exit-code contract are unchanged).
- **`docs/USE_WITH_CLAUDE_CODE.md`** — the Claude Code workflow pack: a paste-ready prompt, a worked
  example, the executable-input safety boundary, and a "what dorian is / is not" section.
- **`examples/claude-code/`** — a runnable example pack (`app.py`, `change-note.md`, `claims.json`,
  `settings.example.json`, `README.md`), pinned by a black-box test.
- **`docs/PUBLIC_BENCHMARK_PROTOCOL.md`** — a *pre-registered, protocol-only* design for a real
  public-repo micro-benchmark (frozen SHAs, manual claims, trigger-vs-truth layers, manifest); no
  results, and the private `genai-core` clone is excluded from public evidence.
- **`docs/TRUSTED_BASE_ACTION_DESIGN.md`** — a design (not implemented) for a trusted-base Action
  mode, flagged HUMAN REVIEW REQUIRED.
- **`docs/START_HERE.md`** — a navigation index across the docs.

The checkable claims behind this note are in
[`launch-train-claude-code-onboarding.claims.json`](launch-train-claude-code-onboarding.claims.json).
