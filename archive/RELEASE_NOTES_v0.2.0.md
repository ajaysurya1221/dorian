# dorian v0.2.0 — R&D Preview

`dorian` is a local-first R&D preview for **validity warrants on AI-generated
work**. It records what a generated artifact read, what it claimed, and how
those claims can be rechecked later. The stable path is manual or reviewed
claims; LLM extraction is experimental.

v0.2.0 is a **verification-and-documentation release**: no functional code
changes since v0.1.0. It exists to publish the release-proof evidence and
keep every public claim auditable.

## What's new since v0.1.0

- **`docs/RELEASE_VALIDATION_REPORT_v0.2.0.md`** — the full release-gate
  evidence: every benchmark number in the README independently recomputed
  from local artifacts via the repo's own aggregate-only commands (32.40×
  fp-reduction = 162 baseline FPs ÷ 5 dorian FPs, recall 0.89 = 8/9, 556
  pairs rederived from window composition, 72-pair spot-check with 2
  overrides, churn 0.49/0.21 vs the 0.20 gate), a 17-step end-to-end
  workflow proof with zero model tokens, clean-archive test results
  (410/410), privacy scans, Action security posture, and the prior-art
  boundary check.
- Version and doc currency: status badge and release-pin examples updated
  to the 0.2 series.

## What it is

When an AI assistant writes a document, the document may be correct today and
silently wrong next month, because the code, schemas, configs, prompts, or
data it described keep changing while the document does not. `dorian`
attaches a `.warrant` sidecar to the artifact recording:

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
  references, C4 pytest bindings, C5 typed data checks plus a raw shell
  fallback.
- Trust-state folding with an append-only, exportable audit log and
  downstream recall through derives edges.
- Content-free sidecar mode (`--no-quotes`) and seal-time restricted-path
  scope lint.
- A composite GitHub Action with a sticky PR comment — read its security
  notes first (below).

## How to try it

```bash
pip install 'dorian-vwp @ git+https://github.com/ajaysurya1221/dorian.git'
```

Then follow the 60-second example in the README: seal one artifact with a
handful of manual claims, make a breaking change, run `dorian revalidate`.
A committed fictional demo document lives at
`examples/demo-repo/docs/design.md`. The deterministic selftest benchmark
runs with `make bench`; the full test suite with `make test`.

## Validation summary

See `archive/RELEASE_VALIDATION_REPORT_v0.2.0.md` for the complete evidence.
Reviews were performed by automated review passes executing real commands; no
independent third-party review is claimed. Headline: all gates passed — lint and
410/410 tests in both the working tree and a clean archive, a full
end-to-end proof (seal, zero-alarm unrelated change, exact-claim breakage,
REVOKED fold, downstream recall, byte-deterministic audit export), clean
privacy scans, and a no-collision prior-art sweep.

## Caveats — read before relying on it

- **R&D stage.** APIs, schemas, and CLI flags may change. The sidecar spec
  is versioned (`spec_version: 0.1`) but not frozen.
- **Benchmark evidence is promising, not public proof.** The headline
  result (32.40× fewer false-positive staleness alarms at 0.89 recall) is
  a research-preview figure on private repositories, not independent public
  proof. A reproducible public micro-benchmark is
  the next evidence step (`docs/SOLO_VALIDATION_LADDER.md`).
- **GitHub Action security.** Checker specs in `.warrant` files are
  executable. Do not run checker specs from untrusted pull requests; the
  Action is currently recommended for trusted/internal repositories.
  Details in `action/README.md`.
- **`--extract` is experimental and draft-only.** Measured churn fails its
  stability gate (re-verified live for this release: exact 0.222 vs the
  0.20 gate on the public demo doc). Extracted claims are drafts for review,
  never stable warrant inputs.

## Next steps

- Level 1 of the validation ladder: the reproducible public
  micro-benchmark.
- Multi-index binding, weak-binding trust gating, and typed checkers
  (`docs/NEXT_ALGORITHMIC_BETS.md`).
- First PyPI release of `dorian-vwp`.

Issues, replication attempts, and small focused PRs are welcome.
