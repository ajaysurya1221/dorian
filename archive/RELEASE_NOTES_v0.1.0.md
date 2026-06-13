# dorian v0.1.0 — R&D Preview

`dorian` is a local-first R&D preview for **validity warrants on AI-generated
work**. It records what a generated artifact read, what it claimed, and how
those claims can be rechecked later. The stable path is manual or reviewed
claims; LLM extraction is experimental.

This is a research preview, not a production release. It exists so the idea
can be tried, broken, and measured in the open.

## What it is

When an AI assistant writes a document — a design doc, a plan, a report — the
document may be correct today and silently wrong next month, because the
code, schemas, configs, prompts, or data it described keep changing while
the document does not. `dorian` attaches a `.warrant` sidecar to the
artifact recording:

- a content-hashed **read-set** (what the producing run read),
- the artifact's **claims**, restated atomically,
- an executable, read-only **checker** per claim.

When sources change, `dorian revalidate` re-checks only the affected claims
— deterministically, with zero model tokens — and reports which claim broke,
how the artifact's trust state changed (TRUSTED → DEGRADED/REVOKED), and
which downstream artifacts inherited the damage.

## What works now

- The full local loop: `capture` → `seal` (every checker must pass at seal
  time) → `revalidate` → `status` / `report --audit` / `blast`.
- Checker families: C1 relocatable span anchors, C3 path/symbol/string/regex
  references, C4 pytest bindings, C5 typed data checks (row count, schema,
  null rate, domain, freshness, snapshot, reconciliation) plus a raw shell
  fallback.
- Trust-state folding with an append-only, exportable audit log
  (`dorian-audit-v1` JSONL) and downstream recall through derives edges.
- Content-free sidecar mode (`--no-quotes`) and seal-time restricted-path
  scope lint.
- A composite GitHub Action that revalidates the claims a PR touches and
  posts one sticky comment — read its security notes first (below).

## How to try it

```bash
pip install 'dorian-vwp @ git+https://github.com/ajaysurya1221/dorian.git'
```

Then follow the 60-second example in the README: seal one artifact with a
handful of manual claims, make a breaking change, run `dorian revalidate`.
A committed fictional demo document lives at
`examples/demo-repo/docs/design.md`. The repo's own deterministic selftest
benchmark runs with `make bench`; the full test suite with `make test`.

## Caveats — read before relying on it

- **R&D stage.** APIs, schemas, and CLI flags may change. The sidecar spec
  is versioned (`spec_version: 0.1`) but not frozen.
- **Benchmark evidence is promising, not public proof.** The headline result
  (32.40× fewer false-positive staleness alarms than file-hash watching at
  0.89 recall) is a research-preview figure on private repositories, not
  independent public proof. A fully public, reproducible micro-benchmark is
  the next evidence step —
  see `docs/SOLO_VALIDATION_LADDER.md`.
- **GitHub Action security.** Checker specs in `.warrant` files are
  executable. Do not run checker specs from untrusted pull requests; the
  Action is currently recommended for trusted/internal repositories. A
  trusted-base mode for public fork PRs is future work. Details in
  `action/README.md`.
- **`--extract` is experimental and draft-only.** Measured extraction churn
  fails its stability gate (the model selects a different claim subset per
  run), so extracted claims are drafts for review, never stable
  warrant inputs. Manual or reviewed claims are the supported workflow.

## Next steps

- Climb the solo validation ladder: public micro-benchmark, then mutation
  benchmark (`docs/SOLO_VALIDATION_LADDER.md`).
- Multi-index binding, weak-binding trust gating, and typed checkers
  (`docs/NEXT_ALGORITHMIC_BETS.md`).
- First PyPI release of `dorian-vwp`.

Issues, replication attempts, and small focused PRs are welcome.
