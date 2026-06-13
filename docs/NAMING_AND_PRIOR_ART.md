# Naming + prior-art memo (W1.2)

## Naming (2026-06-11)

- Project/import/CLI: **dorian** (The Picture of Dorian Gray, inverted — the sidecar is
  the portrait). PyPI `dorian` is squatted (one 0.0.1 release, unrelated
  "Data-Oriented experiment Reproducibility…" tool) → **distribution name `dorian-vwp`**
  (verified 404/available 2026-06-11). `stet` (fallback) also taken on PyPI.
- Rejected in sweeps: tripwire (file-integrity security brand = our baseline mechanism),
  claimwire (insurance platform, Origami Risk), drift-* (crowded: Drift, driftpy,
  driftdev.sh), errata (Red Hat advisory tooling), claimbell (approved then judged
  insufficiently distinctive).

## Prior-art boundary (to re-verify in the 2h day-1 sweep)

- **CASCADE (arXiv:2604.19400)** — closest prior art: code↔doc inconsistency detection via
  LLM-generated tests, explicitly fighting false positives. dorian differs: generation-time
  read-set capture + deterministic per-claim checkers + revalidation lifecycle, vs LLM-test
  regeneration at scan time. CONFIRM this boundary holds against the paper's artifact.
- SLSA/in-toto: build provenance, immutable point-in-time attestations — no NL claims, no lifecycle.
- OpenLineage: job/run/dataset lineage — not claim/artifact level.
- Great Expectations/dbt: validate data batches/tables — not claims *about* code/data/docs.
- Doc-drift scanners (Swimm, driftdev.sh, doc-drift, DeepDocs, Doctective, Dosu): post-hoc
  LLM rescans at PR time — no generation-time capture, no executable checkers, no recall.
- PaperTrail (2602.21045), WarrantScore (2601.17377): claim-evidence at display time, no lifecycle.


---

# W1.2 Prior-Art Memo — Validity Warrant Protocol ("dorian")

## Verdict

**NO KILL — composition unclaimed.** Three independent sweeps (arXiv/Semantic Scholar, GitHub/npm/PyPI, commercial tooling) found every fragment of the triad shipped or published somewhere, but **no system composes** (a) generation-time content-hashed read-set capture, (b) per-claim executable read-only checkers incl. typed data checks, and (c) change-driven zero-token revalidation with VERIFIED→BROKEN / TRUSTED→REVOKED states and transitive `derives_from` invalidation. The vocabulary is converging fast (AAR, Jun-2026 provenance survey), so the window is real but open.

## Closest matches

| Name | Overlap | Gap | Kill risk |
|---|---|---|---|
| coredipper/scriptorium (PyPI) | Same thesis: compile-time input hashing, content-hashed per-claim quote anchors verified deterministically with relocation tolerance, hash-driven transitive staleness, selective recompile, zero LLM tokens | Curated KB vault, not git-repo artifacts; one checker type only; no typed data checks; no trust fold/state machine; no CI/commit integration; single raw→derived level | **HIGH** |
| fiberplane/drift | Symbol/span anchors with AST-fingerprint relocation tolerance, commit provenance, deterministic `--changed` CI checks, tool-aware | Anchors hand-linked, not captured from an LLM run; no claims, no data checks, binary stale/fresh, no transitive invalidation | Medium |
| Swimm (commercial) | Per-commit deterministic anchor re-verification, Auto-sync relocation, CI gate with status transitions | Hand-authored couplings, no read-set warrant, code-span checks only, no trust lifecycle | Medium |
| PRISM (arXiv 2510.25890) | Evidence bundles of machine-checkable certificates re-verifiable independently of the generator | Schema-constrained MDE artifacts; no read-set, no NL claims, one-shot — no later-commit revalidation | Medium |
| @whenlabs/stale | Nine typed deterministic claim checkers extracted from prose docs, zero LLM | Scan-time pattern extraction, no generation capture/sidecar, full rescan, no data checks or lifecycle | Low |
| ftl-beliefs | Claims with source hashes, depends-on edges, retraction propagation through dependents | Manually curated AI-session memory; existence/recency checks only; no warrant, no CI loop | Low |
| Evergreen (arXiv 2604.26180) | NL data claims compiled to executable verification queries with provenance explanations | Post-hoc, static data, semantic ops not zero-token, no lifecycle | Low |
| VeriTrail (MSR) | Claim extraction + provenance tracing through multi-step derivation graphs | LLM-judged, once at generation, no checkers, no revalidation | Low |
| Fragments (in-toto/witness; dbt/GX/elementary; DVC) | Each leg proven individually: hashed read-set attestation; the exact typed data-check grammar; hash-DAG incremental recompute | None touches claims in AI prose or a trust lifecycle — explicitly non-kills; delimits commodity legs | None |

## CASCADE boundary

CASCADE (FSE 2026) owns "LLM-extracted per-behavior executable checks for doc consistency" — cite and differentiate, do not compete. The precise boundary: **CASCADE is a post-hoc, stateless scanner of hand-written method docs; dorian is a generation-time warrant with a persistent lifecycle.** CASCADE records no provenance (no read-set, hashes, git versions), regenerates token-burning unit tests on every scan (~6 LLM calls/method), executes code rather than read-only typed data checks, and emits one transient per-method boolean — no claim states, no revalidation on later commits, no trust folding. Its dual-validation precision trick (doc-derived reference code as oracle) is orthogonal and potentially complementary to the warrant model.

## Watch list (re-check at v0.1)

1. **scriptorium SPEC.md** — any move toward git-versioned repo artifacts, additional checker types, or CI hooks would close most of the gap; diff against it before release.
   *Checked 2026-06-12 (v0.1 public push): scriptorium is at v0.2 (SPEC v2, `scrip ingest`, optional embeddings) and remains a curated `vault/` KB — still no git-repo artifacts, single checker type, no typed data checks, no trust lifecycle, no CI/commit integration. Boundary holds.*
2. **fiberplane/drift roadmap** — auto-anchoring from AI-tool edits + claim extraction would compose two legs.
3. **AAR (2602.13855) / provenance survey (2606.04990) implementations** — first system papers operationalizing Derive/Invalidate edges.
4. **Swimm + Dosu product moves** — AI-generation-time capture or data-claim checks.
5. **PRISM follow-ups** — extension to NL artifacts or post-release revalidation.
6. **Kang et al. line** — persistence of generated tests as durable sidecars would be the nearest academic threat.
