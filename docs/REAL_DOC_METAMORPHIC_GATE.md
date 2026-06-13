# The Real-Document Metamorphic Gate (pre-registered)

> **Status:** pre-registered, not yet run. This document and its thresholds
> must be committed and pushed publicly **before** any gate measurement is
> taken. No exploratory run on real documents may inform these thresholds;
> the harness (`bench/extract_real_gate.py`) mechanically refuses to run
> until this file is committed, the tree is clean (no staged, unstaged, **or
> untracked** changes — a stray selector/scorer/test could otherwise alter the
> result), the results document does not yet exist, and HEAD is pushed.
> Results will be published separately in
> `REAL_DOC_METAMORPHIC_GATE_RESULTS.md`, which may not exist before the
> pre-registration commit is public.

This is the v0.7.0 promotion/rejection instrument for `--extract`, replacing
the planted-truth gate that was rejected by its own calibration rule
([`EXTRACT_GATE_RESULTS.md`](../archive/EXTRACT_GATE_RESULTS.md)). It applies
metamorphic relations to **real, committed documents**: no planted truth, no
manual labels, no LLM scorer. An LLM appears only as the system under test;
every verdict input is a deterministic computation over extraction outputs.

## Why this gate, after v0.6.0

The planted-truth route failed because generated documents are systematically
easier than real prose — the synthetic-to-real transfer gap was measured
twice, in both directions. Metamorphic relations need no ground truth: they
compare the extractor **with itself** across meaning-preserving (or
claim-killing) edits of the *same real document*, so the measurement happens
at real-document difficulty by construction. The price is scope: a
metamorphic gate can validate **stability, edit-invariance, and
non-fabrication**. It cannot validate authoring judgment.

**This gate can validate only that `--extract` is a stable, invariant,
non-fabricating draft generator on the tested documents. It cannot validate
which claims are important, whether coverage is complete, or whether an author
would have selected the same claims. Extracted claims remain drafts for
manual review at seal time regardless of the verdict.**

## Systems under test

Both SUTs are measured under the identical protocol. Each is judged
independently against the same thresholds.

- **SUT-A (incumbent): anchor + consensus.** `--extract-mode anchor` with
  deterministic boundary snapping and consensus-of-k span voting, k = 3 —
  the architecture shipped in v0.4.0–v0.6.0.
- **SUT-B (challenger): candidate-first + consensus.** `--extract-mode
  candidate`, k = 3. The document is segmented into candidate blocks
  **deterministically** (code, not model); the model only classifies which
  candidates state checkable claims. Span boundaries are fixed by the
  segmentation, so boundary jitter is zero by construction, and selection
  becomes a per-candidate vote. This is the "deterministic checkability
  prefilter" named in v0.5.0 finding 5 and
  [`NEXT_ALGORITHMIC_BETS.md`](NEXT_ALGORITHMIC_BETS.md) bet 5, now
  implemented as a small, reversible extraction mode. It is included because
  it directly attacks the measured failure mode: long-document selection
  jitter plus boundary jitter.

Restate mode is out of scope: it failed the standing 0.20 advisory gate on
all four real documents in v0.5.0 and truncates on claim-dense long
documents; it has no promotion path to test.

Fixed parameters: model `claude-sonnet-4-6` (continuity with every prior
measurement), temperature 0.0, `max_tokens` 8192, every draw a fresh API call
(`use_cache=False`; consensus components always bypass the cache), k = 3,
R = 3 baseline consensus draws per document, one draw per transform, at most
D = 3 deletion probes per document. Adaptive parameter degradations
(temperature/forced-tools rejected by the model) are recorded in the output
as in `bench/churn.py`.

## Document corpus (selector, not a list)

The corpus is selected by rule, not curated: **every git-tracked `*.md` file
in this repository at the pre-registration commit with at least 30 lines**,
excluding only this gate's own two documents
(`docs/REAL_DOC_METAMORPHIC_GATE.md`,
`docs/REAL_DOC_METAMORPHIC_GATE_RESULTS.md`), which the gate release itself
edits. Documents are LF-normalized before measurement; the run manifest pins
each document's sha256 and the HEAD commit, and `aggregate` verifies results
against the manifest.

Length tiers (1-based content line count after LF normalization, one
trailing newline stripped):

| tier | lines | rationale |
|---|---|---|
| short | 30–79 | the region where anchor mode passed the v0.5.0 gate |
| medium | 80–119 | the approach to the measured failure boundary |
| long | ≥ 120 | the measured failure region (v0.5.0: anchor exact churn 0.29 at 121 lines, 0.37 at 152) |

At pre-registration time the selector yields 22 documents (11 short,
5 medium, 6 long, 34–336 lines). One corpus caveat is pinned now: the
documents are this repository's own docs — largely AI-drafted project prose,
claim-dense, table-heavy. That is the tool's target distribution, but it is
one repository's distribution; the results document must say "on this
repository's documents", not more. `examples/demo-repo/docs/design.md` is a
committed fictional demo document; it is included because every prior churn
measurement used it (comparability), and flagged here as fixture-flavored.

## Metamorphic relations and oracles

All comparisons happen in **mapped original-line space**: every transform
returns a line map from transformed line numbers back to original line
numbers (or "inserted"), and extracted spans on transformed documents are
mapped through it before comparison. Raw absolute line numbers are never
compared across documents.

### Relation 1 — filler invariance (meaning-preserving)

Deterministic non-claim filler paragraphs are inserted at blank lines outside
code fences: `max(3, total_lines // 25)` insertion points (capped at 8),
evenly spaced over eligible blanks, each inserting two sentences from the
mechanically claim-free distractor pool (`bench/plant.py` `DISTRACTORS`: no
digits, no path tokens — the separation rule the offline tests enforce).
The pool is reused as *perturbation infrastructure*; no planted-battery
number is cited by this gate. Fewer than 3 eligible blank lines marks the
document **untestable for this relation** (counted, with reason).

Oracles:
- **Hard false positive:** an extracted claim whose snapped span consists
  entirely of inserted lines. Non-claim filler became a claim. Count must
  be 0.
- **Invariance effect:** baseline mean pairwise boundary-normalized
  agreement minus the mean agreement between the filler-run extraction
  (mapped to original lines, inserted lines dropped) and each baseline draw.
  The transform must not degrade agreement by more than the intrinsic-churn
  margin below.
- Claims partially overlapping inserted lines are counted as
  `filler_boundary_overlap` (reported; they participate in matching by their
  original-line subset).

### Relation 2 — section-reorder invariance (meaning-preserving)

Top-level `## ` sections (outside code fences) are rotated by one; the
preamble stays fixed. A document is **untestable for this relation** when it
has fewer than 3 sections or when any section contains an ordering-dependent
reference (case-insensitive: standalone "above"/"below", "previous section",
"next section", "earlier section", "following section", "later in this
document", or a numbered `## N.` heading). Code-fence content is verbatim
data, not document narration: it is excluded from both section detection and
the lock scan (a `## ` or an "above" inside a fenced block neither defines a
section nor locks ordering). Untestable is recorded with a reason — never
silently scored as a pass. Markdown intra-document links (`](#...)`) are
position-independent and do not lock ordering.

Oracle: same invariance-effect computation as Relation 1, with spans mapped
through the block permutation. A model that re-selects different claims
because independent sections moved is measured as unstable — the document's
claims did not change.

### Relation 3 — anchor-targeted deletion (claim-killing)

For each claim in the first baseline draw whose anchor is **uniquely
testable**, the exact anchor lines are deleted and extraction re-runs once.
Uniquely testable: no other same-length line window in the document reaches
normalized token-set Jaccard ≥ 0.5 with the claim's tokens. Up to D = 3
targets per document, most-unique first (ascending maximum window
similarity, then ascending line start). Claims failing the uniqueness test
are **untestable (duplicate anchor)** — counted, never passed.

Outcomes per probe (exactly one):
- **vanished** — no extracted claim on the deleted document has fuzzy text
  similarity ≥ 0.75 to the deleted claim. Pass.
- **fabricated** — a survivor exists whose own anchor lines (re-read from
  the transformed document, never trusted from the claim object) do **not**
  lexically support its text (token-set Jaccard < 0.9). The extractor
  asserted a claim its source no longer states. Any count > 0 rejects.
- **duplicate (post-hoc)** — a survivor exists but its anchor lines do
  support it: the content genuinely exists elsewhere and the uniqueness
  prefilter missed a paraphrase. Untestable, not a pass, not a fabrication.
- **artifact** — the re-extraction truncated or returned empty. Untestable;
  an empty re-extraction is **never** scored as "the claim vanished" (the
  v0.6.0 empty-vs-empty lesson, now a hard rule with an offline test).

Honesty note, pinned before any run: in both SUTs the claim text is derived
from document lines by construction, so genuine fabrication should be
impossible *unless the pipeline leaks state* (cache contamination, stale
spans, harness defects). This oracle therefore verifies end-to-end that the
non-fabrication construction actually holds — and becomes a true fabrication
test for any future mode where the model authors text. A pass here may not
be quoted as "the model cannot hallucinate"; it means "the pipeline was
caught inventing nothing on the tested probes."

## Metrics (all are required outputs)

Per document, per SUT, from R = 3 baseline consensus draws (3 pairs):

- **exact churn** — mean pairwise Jaccard distance over normalized claim
  text sets (identical definition to v0.3.0–v0.5.0).
- **fuzzy churn** — the v0.5.0 fuzzy metric (threshold 0.75); reported for
  comparability, never gated on.
- **boundary-normalized churn** (primary) — greedy span matching in line
  space: spans match when line-set IoU ≥ 0.5; distance is
  `1 − matches/(|A|+|B|−matches)`.
- **pair decomposition** — counts per pair: exact span matches,
  boundary-jitter matches (IoU ≥ 0.5 but not identical — boundary-only
  jitter), unmatched spans (genuine selection disagreement).
- **invariance effects** for filler and reorder, as defined above.
- **deletion outcomes** — vanished / fabricated / duplicate / artifact
  counts, plus untestable-duplicate prefilter counts.
- **artifact counters** — truncation count, behavioral-empty draw count
  (model returned no valid spans), empty-vs-empty comparison count (always
  excluded from churn means and flagged), unanchored-claim count (must be 0
  in both SUTs; > 0 is a harness flag), untestable/skip counts with reasons.
- **sanity-floor metrics** (anti-triviality, computed from the baseline spans,
  no extra calls): selected-line coverage ratio (union of selected lines over
  document lines, per draw → per-doc mean → pooled mean), max single-span
  share (longest span as a fraction of its document, pooled maximum),
  whole-document span count (spans covering ≥ 80% of a document), mean claims
  per complete document (pooled and per tier), and filler over-selection rate
  (fraction of filler-run claims touching any inserted line). For SUT-B the
  candidate blocks **are** the spans, so selected-line coverage is also its
  selected-block coverage by construction — measured and gated identically to
  SUT-A so neither SUT can win by emitting coarser spans.
- Tier aggregates: mean of document means per tier; pooled counts for
  oracles. Long-tier results are always broken out.

## Pre-registered decision gates

Verdicts are computed per SUT by `bench/extract_real_gate.py aggregate` as a
pure function of the metrics above; the classification logic ships with
offline tests before any measurement.

**Promotion gate** (all must hold for a SUT):

1. boundary-normalized churn tier mean < 0.20 on **every** tier, and exact
   churn tier mean < 0.30 on every tier. (0.20 is the repository's standing
   advisory gate, applied to the boundary-forgiving metric; v0.5.0 measured
   single-draw anchor at 0.20–0.22 fuzzy on long documents, so consensus
   must beat single-draw behavior for promotion to mean anything.)
2. filler hard false positives = 0, and filler invariance effect ≤ 0.10 on
   every tier with testable documents.
3. reorder invariance effect ≤ 0.10 on every tier with testable documents.
4. deletion fabrication = 0, with ≥ 10 testable deletion probes pooled.
5. truncation = 0 across all draws; behavioral-empty draws ≤ 5% of all
   draws; empty-vs-empty comparisons = 0.
6. evidence floor: ≥ 15 documents with complete baselines; ≥ 3 per tier;
   ≥ 4 long-tier documents; ≥ 8 reorder-testable documents.
7. anti-triviality sanity floor — a stability gate must not reward degenerate
   extractions, so all of these must hold: max single-span share < 0.50 (no
   claim spans half its document); pooled selected-line coverage < 0.50 (the
   extractor selects claims, not the whole document); mean claims per complete
   document ≥ 2 (not near-empty); filler over-selection rate ≤ 0.50 (filler
   paragraphs are not being grabbed as claims). These are computed from the
   baseline spans and applied identically to both SUTs, so neither can win by
   emitting coarser spans (a candidate-first segmentation that selects nearly
   every block fails the coverage floor exactly as an anchor run would).

Outcome: the passing SUT is promoted from "experimental" to **"supported
draft generator under the tested real-document metamorphic relations"** —
with the published wording stating exactly that, and explicitly **not**
"correct automatic claim extractor", not "complete coverage", not "safe to
auto-seal", not "manual review no longer needed". If both SUTs pass, the
documented default becomes the one with lower long-tier boundary-normalized
churn (tie → incumbent); the other remains available with its measured
numbers.

**Rejection gate** (any one triggers, per SUT):

- deletion fabrication > 0 on testable unique anchors;
- filler hard false positives > 0;
- long-tier boundary-normalized churn mean ≥ 0.35 (v0.5.0 measured 0.37
  exact at 152 lines single-draw; at or above this band, consensus/candidate
  voting has not moved the failure mode);
- any whole-document span — a single span covering ≥ 0.80 of a document
  (trivial stability bought by selecting everything at once);
- pooled selected-line coverage ≥ 0.70 (the extractor is echoing the
  document, not extracting claims);
- truncation plus behavioral-empty draws > 20% of all draws (main result
  uninterpretable).

Outcome if **both** SUTs reject: the extraction track is recorded as closed
for solo-dev validation in `NEXT_ALGORITHMIC_BETS.md`; `--extract` is
demoted from "experimental" to "not recommended; manual claims only."

**Insufficient-evidence gate** (otherwise), including explicitly:

- any churn metric landing between the promotion and rejection bands;
- evidence floors unmet, or more than 50% of documents untestable for any
  single relation;
- any empty-vs-empty comparison, unanchored claim, or other discovered
  scoring artifact (the v0.6.0 class of measurement bug);
- fewer than 10 testable deletion probes.

Outcome: no promotion, no demotion. One remediation round is permitted for
**harness defects only** — thresholds do not move — followed by exactly one
re-run. A second insufficient verdict from the same cause closes this
validation approach, as the two-strikes rule closed the planted route. If a
threshold is judged wrong after results exist, that judgment is published
and a v2 gate is pre-registered before any re-run; results may never be
re-scored against altered thresholds.

## Run protocol (exact, in order)

1. This document, the harness, the candidate mode, and the offline tests are
   committed and **pushed publicly**. No gate measurement exists before this
   push; the harness refuses to run otherwise (tracked gate doc; tree clean of
   staged, unstaged, and untracked changes; no results document yet; HEAD
   reachable from a remote ref). On resume, an existing per-document output is
   reused only when it was produced against this manifest commit and SUT —
   a stale draw is refused, never silently aggregated.
2. `uv run python -m bench.extract_real_gate select --out bench/results/real_gate/manifest.json`
3. `uv run python -m bench.extract_real_gate run --manifest bench/results/real_gate/manifest.json --sut anchor --out-dir bench/results/real_gate/anchor`
4. `uv run python -m bench.extract_real_gate run --manifest bench/results/real_gate/manifest.json --sut candidate --out-dir bench/results/real_gate/candidate`
   (steps 3–4 are resumable; existing per-document files are skipped)
5. `uv run python -m bench.extract_real_gate aggregate --manifest bench/results/real_gate/manifest.json --dir-a bench/results/real_gate/anchor --dir-b bench/results/real_gate/candidate --out bench/results/real_gate/report.json --md bench/results/real_gate/report.md`
6. `docs/REAL_DOC_METAMORPHIC_GATE_RESULTS.md` is written from the report —
   exact commands, model, temperature/cache settings and recorded
   degradations, manifest HEAD sha and document hashes, every metric above,
   the verdict, and a "what this proves / what this does not prove" section
   — and committed with the verdict applied to README/version. Raw
   per-document JSONs stay local (`bench/results/` is gitignored); published
   numbers are aggregates plus per-document metric tables (paths and
   metrics only — no document content beyond what is already public in this
   repository).

Estimated cost, pinned for honesty: ≤ 24 fresh extraction calls per document
per SUT ⇒ ≤ ~1,060 calls total; order of $15–40 and 2–4 hours at
sonnet-4-6 pricing. Abort-and-resume is supported; partial runs are never
aggregated silently (the aggregate step reports missing documents as
incomplete evidence).

## What this gate cannot prove (non-claims)

- **Not claim importance, not coverage.** A stable extractor can stably
  select unhelpful spans; importance judgment stays with the author at
  claims.json review, by design.
- **Not real-history warrant value.** That remains a research-preview figure
  on private repositories, not independent public proof.
- **Not distributional generality.** 22 documents from one repository, one
  model, R = 3 (3 pairs per document; tier means pool 9–33 pairs). The
  reorder safety check is a conservative lexical heuristic; documents it
  cannot clear are untestable, not evidence.
- **Not "the model cannot hallucinate"** — see the deletion-oracle honesty
  note.
- No number from this gate may be quoted as externally verified, as recall
  against true claims, or as planted-battery performance; planted documents
  remain test infrastructure only.
