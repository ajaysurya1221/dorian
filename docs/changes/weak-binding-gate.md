# Change note — opt-in weak-binding gate (`--binding-gate`)

Adds an opt-in seal-time review gate (`--binding-gate off|warn|fail`, default `off`) to `verify`
and `seal`. It reuses the existing binding diagnostics via a new pure in-memory analyzer and refuses
a seal *before any sidecar is written* on a high-risk weak binding. It changes no default behavior,
no trust/claim state, no schema, no fold policy, and no checker grammar — weak binding is a
false-confidence smell, never proof a claim is false. `single-file` is warn-only.

The checkable claims behind this note are in
[`weak-binding-gate.claims.json`](weak-binding-gate.claims.json).
