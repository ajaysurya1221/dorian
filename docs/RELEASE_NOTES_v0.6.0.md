# dorian v0.6.0 — R&D Preview

`dorian` is a local-first R&D preview for **validity warrants on AI-generated
work**. It records what a generated artifact read, what it claimed, and how
those claims can be rechecked later. The stable path is manual or reviewed
claims; LLM extraction is experimental.

v0.6.0 is a **falsification release**. It ships a pre-registered,
label-free validation gate for `--extract` — and the honest outcome that the
gate's own calibration mechanism rejected the approach before it could
judge the extractor.

## What's new since v0.5.0

- **Anchor-extraction hardening (code):** deterministic boundary snapping
  (span edges trimmed of blanks/headings/rules/fences before ids derive)
  and **consensus-of-k span voting** — `dorian seal --extract --extract-mode
  anchor --extract-consensus K` and `dorian bench churn --mode anchor
  --consensus K`. Majority line votes, majority adjacency, deterministic
  tie-breaks; the model still never authors claim text.
- **A pre-registered extraction gate** (`docs/EXTRACT_GATE.md`, pushed
  before any run): planted-truth documents, metamorphic transforms, and
  exact promotion/rejection/insufficient thresholds — designed to decide
  `--extract`'s fate with zero human labels.
- **The result** (`docs/EXTRACT_GATE_RESULTS.md`): the battery failed its
  instrument-calibration precondition twice — synthetic documents, even
  with compound multi-clause claims, do not reproduce the difficulty
  profile of real documents (anchor extraction is near-perfect on planted
  240-line docs while churning 0.29–0.37 on comparable real ones; restate
  churn *falls* with planted length but *rises* with real length). Per the
  pre-registered rule, the validation approach is rejected. **`--extract`
  status is unchanged: experimental and draft-only** — its gates were never
  validly evaluated, so there is no promotion and no demotion.
- A real failure surfaced along the way: restate-mode extraction truncates
  on claim-dense long documents (40+ claims overflow a single call); and a
  harness limitation is documented (empty draws compare as identical,
  flattering a failing mode — noted, with corrected numbers that do not
  change the verdict).
- `bench/plant.py`, `bench/metamorph.py`, `bench/extract_gate.py` remain as
  test infrastructure with 16 offline tests (433 total); planted-battery
  numbers may not be cited for promotion claims.

## Why publish a failed gate

The project's premise is that acceptance must be perishable and claims must
be checkable. That standard applies to our own validation designs first. A
promotion decided on the planted battery would have been optimistically
wrong; the calibration precondition caught it twice and the pre-registered
rule fired. The next instrument — metamorphic relations applied to real
documents (extraction invariance under meaning-preserving edits;
anchor-targeted deletion as a fabrication check) — needs no planted truth
and no human labels, and will be pre-registered before any run.

## Unchanged

The full local loop, checker families, trust-state folding, audit export,
downstream recall, content-free sidecars, scope lint, the GitHub Action
(trusted/internal repositories recommended), and every standing caveat —
including: the headline benchmark result (32.40× / 0.89 recall) is
owner-checked and model-adjudicated, not independent public proof.

## How to try it

```bash
pip install 'dorian-vwp[extract] @ git+https://github.com/ajaysurya1221/dorian.git'

# stabilized anchor drafting (still experimental):
dorian seal docs/design.md --readset rs.json --extract --extract-mode anchor --extract-consensus 3
```
