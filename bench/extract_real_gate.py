"""Real-document metamorphic gate runner (pre-registered in
docs/REAL_DOC_METAMORPHIC_GATE.md — that document is normative; the constants
here implement it).

Three subcommands:

  select     emit the document manifest by RULE (tracked *.md >= 30 lines at
             HEAD, minus the gate's own two documents): path, tier, line
             count, sha256, HEAD commit. Content-free; runs before any
             measurement.

  run        measure every manifest document for ONE system under test
             (--sut anchor | candidate; consensus k=3): R baseline consensus
             draws, filler-insert and section-reorder invariance in mapped
             original-line space, and anchor-targeted deletion probes on
             uniquely testable anchors. One JSON per document; existing
             outputs are skipped, so an aborted run resumes. REFUSES to run
             until the pre-registration is committed, the tree is clean, and
             HEAD is pushed (preregistration_error) — no measurement may
             precede the public thresholds.

  aggregate  pool per-document JSONs for both SUTs, verify them against the
             manifest, apply the pre-registered gates (classify is a pure
             function), and emit a report (JSON + markdown skeleton).
             Exit codes: 0 any SUT promoted, 3 both rejected (track closed),
             4 insufficient evidence, 2 usage/infra.

Scoring rules carried over from the v0.6.0 lessons: a ValueError draw is an
EMPTY DRAW (behavioral, hurts agreement) unless it is a truncation (artifact,
excluded and counted); an empty-vs-empty comparison is flagged and excluded,
never scored as agreement; an empty re-extraction after a deletion is an
ARTIFACT, never "the claim vanished".
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench import real_metamorph as rm  # noqa: E402
from bench.churn import exact_distance, fuzzy_distance, normalize  # noqa: E402
from dorian import extract  # noqa: E402
from dorian.model import lf_normalize, sha256_hex  # noqa: E402

GATE_DOC = "docs/REAL_DOC_METAMORPHIC_GATE.md"
RESULTS_DOC = "docs/REAL_DOC_METAMORPHIC_GATE_RESULTS.md"

GATES = {  # pre-registered thresholds — docs/REAL_DOC_METAMORPHIC_GATE.md is normative
    "boundary_churn_tier": 0.20,
    "exact_churn_tier": 0.30,
    "invariance_effect": 0.10,
    "reject_long_boundary_churn": 0.35,
    "reject_artifact_share": 0.20,
    "empty_draw_share": 0.05,
    "iou_match": 0.5,
    "survivor_fuzzy": 0.75,
    "support_jaccard": 0.90,
    # anti-triviality sanity floor (pre-registered): a SUT cannot win by
    # emitting one giant span, echoing the whole document, or returning
    # near-nothing. Applied identically to both SUTs (candidate-first fairness).
    "max_span_share": 0.50,  # promotion: no single span covers >= 50% of its doc
    "reject_whole_doc_share": 0.80,  # reject: any span covering >= 80% of a doc
    "max_line_coverage": 0.50,  # promotion: pooled mean selected-line coverage < 0.50
    "reject_line_coverage": 0.70,  # reject: pooled mean selected-line coverage >= 0.70
    "min_claims_per_doc": 2.0,  # promotion: pooled mean claims per complete doc >= 2
    "max_filler_overselect": 0.50,  # promotion: <= 50% of filler claims touch inserts
    "min_doc_lines": 30,
    "min_docs_complete": 15,
    "min_docs_per_tier": 3,
    "min_long_docs": 4,
    "min_reorder_testable": 8,
    "min_deletion_probes": 10,
    "k": 3,
    "baseline_draws": 3,
    "deletion_cap": 3,
}

TIERS = (("short", 30, 79), ("medium", 80, 119), ("long", 120, None))


def tier_of(lines: int) -> str:
    for name, lo, hi in TIERS:
        if lines >= lo and (hi is None or lines <= hi):
            return name
    return "short"  # < 30 never enters the corpus; defensive only


# --- span mapping and matching -------------------------------------------------------


def mapped_line_set(
    span: tuple[int, int], orig_of: tuple[int | None, ...]
) -> tuple[frozenset[int], int]:
    """Map a 1-based inclusive span on a TRANSFORMED document to the set of
    original line numbers it covers, plus how many of its lines were
    transform-inserted (no original counterpart)."""
    mapped: set[int] = set()
    inserted = 0
    for j in range(span[0], span[1] + 1):
        src = orig_of[j - 1] if 1 <= j <= len(orig_of) else None
        if src is None:
            inserted += 1
        else:
            mapped.add(src)
    return frozenset(mapped), inserted


def _iou(a: frozenset[int], b: frozenset[int]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def match_decomposition(a: list[frozenset[int]], b: list[frozenset[int]]) -> dict:
    """Greedy span matching by line-set IoU >= 0.5 (deterministic order:
    spans sorted by (min, max, size)). Decomposes a pair of extraction runs
    into exact matches, boundary-only jitter (matched but not identical), and
    genuine selection disagreement (unmatched). Empty-vs-empty is flagged and
    carries no distance — it can never score as agreement."""
    if not a and not b:
        return {
            "exact_matches": 0,
            "boundary_jitter": 0,
            "selection_only": 0,
            "boundary_distance": None,
            "empty_empty": True,
        }
    key = lambda s: (min(s), max(s), len(s))  # noqa: E731 — local sort key
    a_sorted, b_sorted = sorted(a, key=key), sorted(b, key=key)
    free = list(range(len(b_sorted)))
    exact = jitter = 0
    for sa in a_sorted:
        best_idx, best_iou = -1, 0.0
        for pos, bi in enumerate(free):
            iou = _iou(sa, b_sorted[bi])
            if iou > best_iou:
                best_idx, best_iou = pos, iou
        if best_idx >= 0 and best_iou >= GATES["iou_match"]:
            matched = b_sorted[free[best_idx]]
            del free[best_idx]
            if matched == sa:
                exact += 1
            else:
                jitter += 1
    matches = exact + jitter
    denom = len(a) + len(b) - matches
    return {
        "exact_matches": exact,
        "boundary_jitter": jitter,
        "selection_only": (len(a) - matches) + len(free),
        "boundary_distance": 1.0 - matches / denom if denom else 0.0,
        "empty_empty": False,
    }


def invariance_effect(
    baseline_sets: list[list[frozenset[int]]], transformed: list[frozenset[int]]
) -> float | None:
    """Baseline mean pairwise boundary-normalized agreement minus the mean
    agreement between the transformed run and each baseline draw. Positive =
    the transform degraded stability beyond intrinsic churn. None when no
    valid (non-empty-empty) comparison exists."""
    base: list[float] = []
    for i in range(len(baseline_sets)):
        for j in range(i + 1, len(baseline_sets)):
            d = match_decomposition(baseline_sets[i], baseline_sets[j])["boundary_distance"]
            if d is not None:
                base.append(1.0 - d)
    trans: list[float] = []
    for draws in baseline_sets:
        d = match_decomposition(transformed, draws)["boundary_distance"]
        if d is not None:
            trans.append(1.0 - d)
    if not base or not trans:
        return None
    return sum(base) / len(base) - sum(trans) / len(trans)


# --- deletion scoring ----------------------------------------------------------------


def score_deletion(target, deleted_text: str, claims: list, error: str | None) -> dict:
    """Outcome of one anchor-targeted deletion probe. An errored or empty
    re-extraction is an ARTIFACT — never scored as the claim vanishing. A
    survivor (fuzzy text similarity >= 0.75 to the deleted claim) is
    FABRICATED when its own anchor lines, re-read from the transformed
    document, do not lexically support its text; a supported survivor means
    the content exists elsewhere (DUPLICATE_POSTHOC, untestable)."""
    if error or not claims:
        return {"outcome": "artifact", "detail": error or "empty extraction"}
    target_norm = normalize(target.text)
    lines = deleted_text.split("\n")
    survivors = [
        c
        for c in claims
        if SequenceMatcher(None, normalize(c.text), target_norm).ratio() >= GATES["survivor_fuzzy"]
    ]
    if not survivors:
        return {"outcome": "vanished", "detail": ""}
    worst: tuple[float, str] | None = None
    for c in survivors:
        if c.anchor is None or not 1 <= c.anchor.line_start <= c.anchor.line_end <= len(lines):
            support = 0.0  # anchor points outside the document: stale state
        else:
            window = rm._token_set(" ".join(lines[c.anchor.line_start - 1 : c.anchor.line_end]))
            tokens = rm._token_set(c.text)
            union = tokens | window
            support = len(tokens & window) / len(union) if union else 0.0
        if worst is None or support < worst[0]:
            worst = (support, c.id)
    support, cid = worst
    if support < GATES["support_jaccard"]:
        return {
            "outcome": "fabricated",
            "detail": f"survivor {cid} support {support:.2f}",
        }
    return {
        "outcome": "duplicate_posthoc",
        "detail": f"survivor {cid} support {support:.2f}",
    }


# --- verdict (pure) ------------------------------------------------------------------


def classify(m: dict) -> dict:
    """Pre-registered verdict logic, a pure function of pooled metrics.
    Precedence: hard-evidence rejection first (fabrication, filler false
    positives, uninterpretable artifact share, long-tier churn at/over the
    rejection band — churn rejection requires the long-tier evidence floor);
    then promotion only when every check holds; otherwise insufficient."""
    total_draws = m["total_draws"]
    artifact_share = (m["truncation"] + m["behavioral_empty"]) / total_draws if total_draws else 1.0
    long_floor = m["docs_per_tier"].get("long", 0) >= GATES["min_long_docs"]
    long_churn = m["tier_boundary_churn"].get("long")
    rejection = {
        "deletion fabrication > 0": m["deletion_fabricated"] > 0,
        "filler hard false positives > 0": m["filler_hard_fp"] > 0,
        "artifact draws > 20%": artifact_share > GATES["reject_artifact_share"],
        "long-tier boundary churn >= 0.35": bool(
            long_floor
            and long_churn is not None
            and long_churn >= GATES["reject_long_boundary_churn"]
        ),
        "whole-document spans (>= 80% of a doc) > 0": m["whole_doc_spans"] > 0,
        "selected-line coverage >= 0.70 (echoing, not extracting)": bool(
            m["sanity_line_coverage"] is not None
            and m["sanity_line_coverage"] >= GATES["reject_line_coverage"]
        ),
    }

    def _tiers_ok(values: dict, bound: float) -> bool:
        return all(values.get(t) is not None and values[t] < bound for t, _, _ in TIERS)

    def _effects_ok(values: dict) -> bool:
        return all(v is not None and v <= GATES["invariance_effect"] for v in values.values())

    promotion = {
        "boundary churn < 0.20 every tier": _tiers_ok(
            m["tier_boundary_churn"], GATES["boundary_churn_tier"]
        ),
        "exact churn < 0.30 every tier": _tiers_ok(
            m["tier_exact_churn"], GATES["exact_churn_tier"]
        ),
        "filler hard false positives == 0": m["filler_hard_fp"] == 0,
        "filler invariance effect <= 0.10": _effects_ok(m["filler_effect_by_tier"]),
        "filler testable on > half the corpus": m["filler_testable"] * 2 >= m["docs_total"],
        "reorder invariance effect <= 0.10": _effects_ok(m["reorder_effect_by_tier"]),
        "reorder testable >= 8 docs": m["reorder_testable"] >= GATES["min_reorder_testable"],
        "deletion fabrication == 0": m["deletion_fabricated"] == 0,
        "deletion probes >= 10": m["deletion_probes"] >= GATES["min_deletion_probes"],
        "max single-span share < 0.50": bool(
            m["sanity_max_span_share"] is not None
            and m["sanity_max_span_share"] < GATES["max_span_share"]
        ),
        "selected-line coverage < 0.50": bool(
            m["sanity_line_coverage"] is not None
            and m["sanity_line_coverage"] < GATES["max_line_coverage"]
        ),
        "mean claims per complete doc >= 2": bool(
            m["sanity_mean_claims"] is not None
            and m["sanity_mean_claims"] >= GATES["min_claims_per_doc"]
        ),
        "filler over-selection rate <= 0.50": bool(
            m["filler_overselect_rate"] is not None
            and m["filler_overselect_rate"] <= GATES["max_filler_overselect"]
        ),
        "truncation == 0": m["truncation"] == 0,
        "behavioral-empty draws <= 5%": bool(
            total_draws and m["behavioral_empty"] / total_draws <= GATES["empty_draw_share"]
        ),
        "empty-vs-empty pairs == 0": m["empty_empty_pairs"] == 0,
        "unanchored claims == 0": m["unanchored"] == 0,
        "complete docs >= 15": m["docs_complete"] >= GATES["min_docs_complete"],
        "every tier >= 3 docs, long >= 4": (
            all(m["docs_per_tier"].get(t, 0) >= GATES["min_docs_per_tier"] for t, _, _ in TIERS)
            and long_floor
        ),
    }
    if any(rejection.values()):
        verdict = "REJECTION"
    elif all(promotion.values()):
        verdict = "PROMOTION"
    else:
        verdict = "INSUFFICIENT"
    return {
        "verdict": verdict,
        "rejection_triggers": rejection,
        "promotion_checks": promotion,
        "insufficient_reasons": (
            sorted(k for k, ok in promotion.items() if not ok) if verdict == "INSUFFICIENT" else []
        ),
        "metrics": m,
    }


# --- pre-registration guard ----------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def preregistration_error(root: Path) -> str | None:
    """The hard rule, mechanically enforced: no live measurement until the
    pre-registration document is committed, the tree is fully clean (no
    staged, unstaged, OR untracked changes — an untracked selector/scorer/test
    could silently alter the result), the results document does not yet exist,
    and HEAD is reachable from a remote ref (pushed publicly). `git status
    --porcelain` honors .gitignore, so the gitignored local result directory
    never trips this — only genuinely stray files do."""
    try:
        if not _git(root, "ls-files", "--", GATE_DOC):
            return f"{GATE_DOC} is not tracked at HEAD — commit the pre-registration first"
        # the most specific guard first: an existing results document (tracked
        # OR untracked) means measurement is being attempted after results exist
        if (root / RESULTS_DOC).exists():
            return (
                f"{RESULTS_DOC} already exists — the results document must not predate the"
                " measurement; remove it (and any pre-registration-era draft) before running"
            )
        dirty = _git(root, "status", "--porcelain", "--untracked-files=normal")
        if dirty:
            return (
                "working tree is not clean (staged, unstaged, or untracked changes present)"
                f" — commit or remove first:\n{dirty}"
            )
        if not _git(root, "branch", "-r", "--contains", "HEAD"):
            return "HEAD is not reachable from any remote ref — push the pre-registration first"
    except subprocess.CalledProcessError as exc:
        return f"git check failed: {exc.stderr or exc}"
    return None


# --- per-document measurement --------------------------------------------------------


def _one_draw(text: str, sut: str, model: str) -> tuple[list, str | None]:
    """One consensus draw; ValueError -> empty draw, split into truncation
    (artifact) vs behavioral empty. Transport/SDK errors propagate as infra."""
    try:
        claims = extract.extract_claims_consensus(
            text,
            k=GATES["k"],
            model=model,
            cache_dir=Path(".claims_cache"),
            artifact_hash=sha256_hex(text.encode("utf-8")),
            temperature=0.0,
            mode=sut,
        )
        return claims, None
    except ValueError as exc:
        kind = "truncation" if "truncated at max_tokens" in str(exc) else "empty"
        return [], f"{kind}: {exc}"


def _spans(claims: list) -> tuple[list[tuple[int, int]], int]:
    spans, unanchored = [], 0
    for c in claims:
        if c.anchor is None:
            unanchored += 1
        else:
            spans.append((c.anchor.line_start, c.anchor.line_end))
    return sorted(spans), unanchored


def _identity_sets(spans: list[tuple[int, int]]) -> list[frozenset[int]]:
    return [frozenset(range(a, b + 1)) for a, b in spans]


def _sanity(text: str, per_draw: list[dict]) -> dict:
    """Anti-triviality sanity metrics for one document, computed purely from
    the recorded baseline spans — no extra model calls. Catches the degenerate
    extractions a stability gate would otherwise reward: one giant span,
    whole-document echoing, near-empty output. Errored draws are skipped (they
    are already counted as artifacts/empties elsewhere)."""
    n_lines = rm.total_lines(text)
    ok = [d for d in per_draw if d["error"] is None]
    coverages: list[float] = []
    max_shares: list[float] = []
    whole = 0
    for d in ok:
        spans = [tuple(s) for s in d["spans"]]
        covered: set[int] = set()
        biggest = 0
        for a, b in spans:
            covered.update(range(a, b + 1))
            width = b - a + 1
            biggest = max(biggest, width)
            if n_lines and width / n_lines >= GATES["reject_whole_doc_share"]:
                whole += 1
        coverages.append(len(covered) / n_lines if n_lines else 0.0)
        max_shares.append(biggest / n_lines if n_lines else 0.0)
    return {
        "n_lines": n_lines,
        "mean_line_coverage": sum(coverages) / len(coverages) if coverages else None,
        "max_span_share": max(max_shares) if max_shares else None,
        "mean_claims": sum(d["n_claims"] for d in ok) / len(ok) if ok else None,
        "whole_doc_spans": whole,
    }


def _score_transform(
    result: rm.TransformResult | rm.Untestable,
    baseline_sets: list[list[frozenset[int]]],
    sut: str,
    model: str,
    counters: dict,
) -> dict:
    if isinstance(result, rm.Untestable):
        return {
            "testable": False,
            "reason": result.reason,
            "hard_fp": 0,
            "boundary_overlap": 0,
            "n_claims": 0,
            "touch_inserted": 0,
            "effect": None,
            "error": None,
        }
    claims, err = _one_draw(result.text, sut, model)
    counters["total_draws"] += 1
    if err:
        counters["truncation" if err.startswith("truncation") else "behavioral_empty"] += 1
        return {
            "testable": True,
            "reason": None,
            "hard_fp": 0,
            "boundary_overlap": 0,
            "n_claims": 0,
            "touch_inserted": 0,
            "effect": None,
            "error": err,
        }
    spans, unanchored = _spans(claims)
    counters["unanchored"] += unanchored
    mapped: list[frozenset[int]] = []
    hard_fp = overlap = 0
    for span in spans:
        line_set, inserted = mapped_line_set(span, result.orig_of)
        if not line_set:
            hard_fp += 1  # the claim lives entirely on transform-inserted lines
        else:
            if inserted:
                overlap += 1
            mapped.append(line_set)
    return {
        "testable": True,
        "reason": None,
        "hard_fp": hard_fp,
        "boundary_overlap": overlap,
        # over-selection on a transformed doc: claims touching any inserted line
        # (entirely = hard FP, partially = boundary overlap) over total claims
        "n_claims": len(spans),
        "touch_inserted": hard_fp + overlap,
        "effect": invariance_effect(baseline_sets, mapped),
        "error": None,
    }


def run_doc(text: str, sut: str, model: str) -> dict:
    counters = {
        "truncation": 0,
        "behavioral_empty": 0,
        "unanchored": 0,
        "total_draws": 0,
    }

    per_draw: list[dict] = []
    draws_claims: list[list] = []
    for _ in range(GATES["baseline_draws"]):
        claims, err = _one_draw(text, sut, model)
        counters["total_draws"] += 1
        if err:
            counters["truncation" if err.startswith("truncation") else "behavioral_empty"] += 1
        spans, unanchored = _spans(claims)
        counters["unanchored"] += unanchored
        draws_claims.append(claims)
        per_draw.append(
            {
                "n_claims": len(claims),
                "spans": [list(s) for s in spans],
                "texts": sorted(normalize(c.text) for c in claims),
                "error": err,
            }
        )

    # truncated draws are artifacts: excluded from pair scoring entirely;
    # behavioral-empty draws participate as empty sets (they hurt agreement)
    valid = [
        i for i, d in enumerate(per_draw) if d["error"] is None or d["error"].startswith("empty")
    ]
    pairs: list[dict] = []
    exact_d, fuzzy_d, boundary_d = [], [], []
    empty_empty = 0
    for x in range(len(valid)):
        for y in range(x + 1, len(valid)):
            i, j = valid[x], valid[y]
            sets_i = _identity_sets([tuple(s) for s in per_draw[i]["spans"]])
            sets_j = _identity_sets([tuple(s) for s in per_draw[j]["spans"]])
            d = match_decomposition(sets_i, sets_j)
            if d["empty_empty"]:
                empty_empty += 1
                pairs.append(d)
                continue
            ti, tj = set(per_draw[i]["texts"]), set(per_draw[j]["texts"])
            d["exact_distance"] = exact_distance(ti, tj)
            d["fuzzy_distance"] = fuzzy_distance(ti, tj, GATES["survivor_fuzzy"])
            exact_d.append(d["exact_distance"])
            fuzzy_d.append(d["fuzzy_distance"])
            boundary_d.append(d["boundary_distance"])
            pairs.append(d)

    baseline_sets = [
        _identity_sets([tuple(s) for s in per_draw[i]["spans"]])
        for i in valid
        if per_draw[i]["error"] is None
    ]
    baseline = {
        "per_draw": per_draw,
        "pairs": pairs,
        "exact_churn": sum(exact_d) / len(exact_d) if exact_d else None,
        "fuzzy_churn": sum(fuzzy_d) / len(fuzzy_d) if fuzzy_d else None,
        "boundary_churn": sum(boundary_d) / len(boundary_d) if boundary_d else None,
        "empty_empty_pairs": empty_empty,
    }
    baseline["sanity"] = _sanity(text, per_draw)

    filler = _score_transform(rm.filler_insert_real(text), baseline_sets, sut, model, counters)
    reorder = _score_transform(rm.section_reorder_real(text), baseline_sets, sut, model, counters)

    deletion: dict = {
        "candidates": 0,
        "untestable": [],
        "probes": [],
        "vanished": 0,
        "fabricated": 0,
        "duplicate_posthoc": 0,
        "artifact": 0,
    }
    if per_draw[0]["error"] is None:
        targets, untestable = rm.unique_anchor_targets(
            text, draws_claims[0], cap=GATES["deletion_cap"]
        )
        deletion["candidates"] = len(draws_claims[0])
        deletion["untestable"] = [[c.id, reason] for c, reason in untestable]
        for target in targets:
            deleted = rm.delete_lines(text, target.anchor.line_start, target.anchor.line_end)
            claims, err = _one_draw(deleted.text, sut, model)
            counters["total_draws"] += 1
            if err:
                counters["truncation" if err.startswith("truncation") else "behavioral_empty"] += 1
            outcome = score_deletion(target, deleted.text, claims, err)
            deletion["probes"].append({"claim_id": target.id, **outcome})
            deletion[outcome["outcome"]] += 1
    else:
        deletion["untestable"] = [["*", f"baseline draw 0 errored: {per_draw[0]['error']}"]]

    return {
        "schema": "dorian-real-gate-v1",
        "sut": sut,
        "baseline": baseline,
        "filler": filler,
        "reorder": reorder,
        "deletion": deletion,
        "artifact_counters": counters,
    }


# --- subcommands ---------------------------------------------------------------------


def cmd_select(args: argparse.Namespace) -> int:
    tracked = _git(REPO_ROOT, "ls-files", "*.md").split("\n")
    head = _git(REPO_ROOT, "rev-parse", "HEAD")
    docs = []
    for rel in sorted(filter(None, tracked)):
        if rel in (GATE_DOC, RESULTS_DOC):
            continue
        raw = lf_normalize((REPO_ROOT / rel).read_bytes())
        lines = rm.total_lines(raw.decode("utf-8", errors="replace"))
        if lines < GATES["min_doc_lines"]:
            continue
        docs.append(
            {
                "path": rel,
                "lines": lines,
                "tier": tier_of(lines),
                "sha256": sha256_hex(raw),
            }
        )
    manifest = {
        "schema": "dorian-real-gate-manifest-v1",
        "head": head,
        "selector": f"git-tracked *.md >= {GATES['min_doc_lines']} lines, minus the gate docs",
        "docs": docs,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    by_tier: dict[str, int] = {}
    for d in docs:
        by_tier[d["tier"]] = by_tier.get(d["tier"], 0) + 1
    print(f"select: {len(docs)} documents {by_tier} at HEAD {head[:12]} -> {out}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    err = preregistration_error(REPO_ROOT)
    if err:
        print(f"extract-real-gate: refusing to measure: {err}", file=sys.stderr)
        return 2
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    head = manifest["head"]
    for entry in manifest["docs"]:
        out = out_dir / (entry["path"].replace("/", "__") + ".json")
        if out.is_file():
            # resume is safe only when the existing result was produced against
            # THIS manifest commit and SUT — never silently reuse a stale draw
            prior = json.loads(out.read_text(encoding="utf-8"))
            if prior.get("manifest_head") != head or prior.get("sut") != args.sut:
                print(
                    f"extract-real-gate: {out.name} is stale"
                    f" (manifest {prior.get('manifest_head')!r} sut {prior.get('sut')!r},"
                    f" expected {head!r}/{args.sut!r})"
                    " — remove pre-registration-era outputs before measuring",
                    file=sys.stderr,
                )
                return 2
            print(f"run [{args.sut}] {entry['path']}: exists, skipped")
            continue
        raw = lf_normalize((REPO_ROOT / entry["path"]).read_bytes())
        if sha256_hex(raw) != entry["sha256"]:
            print(
                f"extract-real-gate: {entry['path']} does not match the manifest hash"
                " — re-run select on the pre-registration commit",
                file=sys.stderr,
            )
            return 2
        result = run_doc(raw.decode("utf-8", errors="replace"), args.sut, args.model)
        result.update(
            doc=entry["path"],
            tier=entry["tier"],
            lines=entry["lines"],
            sha256=entry["sha256"],
            manifest_head=head,
            model=args.model,
            temperature=None if extract.temperature_unsupported(args.model) else 0.0,
            tool_choice=("auto" if extract.forced_tools_unsupported(args.model) else "forced"),
        )
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        b = result["baseline"]
        churn = f"{b['boundary_churn']:.3f}" if b["boundary_churn"] is not None else "n/a"
        print(
            f"run [{args.sut}] {entry['path']}: boundary-churn {churn},"
            f" deletions {result['deletion']['vanished']}v/{result['deletion']['fabricated']}f"
        )
    return 0


def _pool(results: list[dict], docs_total: int) -> dict:
    complete = [r for r in results if all(d["error"] is None for d in r["baseline"]["per_draw"])]
    per_tier: dict[str, list[dict]] = {}
    for r in complete:
        per_tier.setdefault(r["tier"], []).append(r)

    def _tier_mean(key: str) -> dict:
        out: dict[str, float | None] = {}
        for tier, docs in sorted(per_tier.items()):
            vals = [r["baseline"][key] for r in docs if r["baseline"][key] is not None]
            out[tier] = sum(vals) / len(vals) if vals else None
        return out

    def _effect_by_tier(relation: str) -> tuple[dict, int]:
        testable = [
            r for r in results if r[relation]["testable"] and r[relation]["effect"] is not None
        ]
        out: dict[str, float | None] = {}
        groups: dict[str, list[float]] = {}
        for r in testable:
            groups.setdefault(r["tier"], []).append(r[relation]["effect"])
        for tier, vals in sorted(groups.items()):
            out[tier] = sum(vals) / len(vals)
        return out, len(testable)

    filler_effects, filler_testable = _effect_by_tier("filler")
    reorder_effects, reorder_testable = _effect_by_tier("reorder")

    # anti-triviality sanity (pre-registered): coverage / span-share / claim
    # counts pooled over docs with complete baselines; whole-doc spans pooled
    # over all results; filler over-selection over filler-testable docs.
    sane = [r["baseline"]["sanity"] for r in complete]

    def _sanity_mean(key: str) -> float | None:
        vals = [s[key] for s in sane if s.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    def _claims_by_tier() -> dict:
        out: dict[str, float | None] = {}
        for tier, docs in sorted(per_tier.items()):
            vals = [
                r["baseline"]["sanity"]["mean_claims"]
                for r in docs
                if r["baseline"]["sanity"]["mean_claims"] is not None
            ]
            out[tier] = sum(vals) / len(vals) if vals else None
        return out

    filler_claims = sum(r["filler"]["n_claims"] for r in results if r["filler"]["testable"])
    filler_touch = sum(r["filler"]["touch_inserted"] for r in results if r["filler"]["testable"])
    return {
        "docs_total": docs_total,
        "docs_complete": len(complete),
        "docs_per_tier": {t: len(d) for t, d in sorted(per_tier.items())},
        "tier_boundary_churn": _tier_mean("boundary_churn"),
        "tier_exact_churn": _tier_mean("exact_churn"),
        "tier_fuzzy_churn": _tier_mean("fuzzy_churn"),
        "sanity_line_coverage": _sanity_mean("mean_line_coverage"),
        "sanity_max_span_share": max(
            (s["max_span_share"] for s in sane if s["max_span_share"] is not None),
            default=None,
        ),
        "sanity_mean_claims": _sanity_mean("mean_claims"),
        "sanity_claims_by_tier": _claims_by_tier(),
        "whole_doc_spans": sum(r["baseline"]["sanity"]["whole_doc_spans"] for r in results),
        "filler_overselect_rate": (filler_touch / filler_claims if filler_claims else None),
        "filler_hard_fp": sum(r["filler"]["hard_fp"] for r in results),
        "filler_testable": filler_testable,
        "filler_effect_by_tier": filler_effects,
        "reorder_testable": reorder_testable,
        "reorder_effect_by_tier": reorder_effects,
        "deletion_probes": sum(
            r["deletion"]["vanished"] + r["deletion"]["fabricated"] for r in results
        ),
        "deletion_fabricated": sum(r["deletion"]["fabricated"] for r in results),
        "deletion_duplicate_posthoc": sum(r["deletion"]["duplicate_posthoc"] for r in results),
        "deletion_artifact": sum(r["deletion"]["artifact"] for r in results),
        "truncation": sum(r["artifact_counters"]["truncation"] for r in results),
        "behavioral_empty": sum(r["artifact_counters"]["behavioral_empty"] for r in results),
        "total_draws": sum(r["artifact_counters"]["total_draws"] for r in results),
        "empty_empty_pairs": sum(r["baseline"]["empty_empty_pairs"] for r in results),
        "unanchored": sum(r["artifact_counters"]["unanchored"] for r in results),
        "untestable": {
            "filler": [
                [r["doc"], r["filler"]["reason"]] for r in results if not r["filler"]["testable"]
            ],
            "reorder": [
                [r["doc"], r["reorder"]["reason"]] for r in results if not r["reorder"]["testable"]
            ],
            "deletion_duplicates": sum(len(r["deletion"]["untestable"]) for r in results),
        },
        "missing_docs": docs_total - len(results),
    }


def _load_results(path: str, manifest: dict) -> list[dict] | str:
    sha_of = {d["path"]: d["sha256"] for d in manifest["docs"]}
    results = []
    for p in sorted(Path(path).glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        expected = sha_of.get(r.get("doc"))
        if expected is None or r.get("sha256") != expected:
            return f"{p.name} does not match the manifest (doc {r.get('doc')!r})"
        results.append(r)
    return results


def _fmt(x: float | None) -> str:
    return f"{x:.3f}" if x is not None else "n/a"


def _render_md(report: dict) -> str:
    lines = ["# Real-document metamorphic gate — run report", ""]
    for name in ("sut_a", "sut_b"):
        v = report[name]
        m = v["metrics"]
        lines += [
            f"## {name}: {v['sut']} — **{v['verdict']}**",
            "",
            "| tier | boundary churn | exact churn | fuzzy churn |",
            "|---|---:|---:|---:|",
        ]
        for tier, _, _ in TIERS:
            b = m["tier_boundary_churn"].get(tier)
            e = m["tier_exact_churn"].get(tier)
            f = m["tier_fuzzy_churn"].get(tier)
            fmt = lambda x: f"{x:.3f}" if x is not None else "n/a"  # noqa: E731
            lines.append(f"| {tier} | {fmt(b)} | {fmt(e)} | {fmt(f)} |")
        lines += [
            "",
            f"- filler: hard FPs {m['filler_hard_fp']}, testable {m['filler_testable']}",
            f"- reorder: testable {m['reorder_testable']}",
            f"- deletion: probes {m['deletion_probes']}, fabricated"
            f" {m['deletion_fabricated']}, duplicate {m['deletion_duplicate_posthoc']},"
            f" artifact {m['deletion_artifact']}",
            f"- artifacts: truncation {m['truncation']}, behavioral-empty"
            f" {m['behavioral_empty']}, empty-vs-empty pairs {m['empty_empty_pairs']},"
            f" unanchored {m['unanchored']}, draws {m['total_draws']}",
            "- sanity: line-coverage {}, max-span-share {}, mean-claims/doc {},"
            " whole-doc spans {}, filler over-selection {}".format(
                _fmt(m["sanity_line_coverage"]),
                _fmt(m["sanity_max_span_share"]),
                _fmt(m["sanity_mean_claims"]),
                m["whole_doc_spans"],
                _fmt(m["filler_overselect_rate"]),
            ),
        ]
        if v["verdict"] == "REJECTION":
            lines.append(
                "- triggers: " + "; ".join(k for k, hit in v["rejection_triggers"].items() if hit)
            )
        if v["insufficient_reasons"]:
            lines.append("- shortfalls: " + "; ".join(v["insufficient_reasons"]))
        lines.append("")
    lines.append(f"track verdict: **{report['track']}**")
    lines.append("")
    return "\n".join(lines)


def cmd_aggregate(args: argparse.Namespace) -> int:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    docs_total = len(manifest["docs"])
    verdicts = {}
    for name, path in (("sut_a", args.dir_a), ("sut_b", args.dir_b)):
        results = _load_results(path, manifest)
        if isinstance(results, str):
            print(f"extract-real-gate aggregate: {results}", file=sys.stderr)
            return 2
        if not results:
            print(f"extract-real-gate aggregate: no results in {path}", file=sys.stderr)
            return 2
        verdict = classify(_pool(results, docs_total))
        verdict["sut"] = results[0]["sut"]
        verdicts[name] = verdict

    states = {name: v["verdict"] for name, v in verdicts.items()}
    if "PROMOTION" in states.values():
        promoted = [verdicts[n]["sut"] for n, s in states.items() if s == "PROMOTION"]
        track, code = f"promoted: {', '.join(promoted)}", 0
    elif set(states.values()) == {"REJECTION"}:
        track, code = "closed: both systems rejected", 3
    else:
        track, code = "insufficient evidence", 4

    report = {
        "schema": "dorian-real-gate-report-v1",
        "manifest_head": manifest["head"],
        "gates": GATES,
        "sut_a": verdicts["sut_a"],
        "sut_b": verdicts["sut_b"],
        "track": track,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.md:
        Path(args.md).write_text(_render_md(report), encoding="utf-8")
    for name, v in verdicts.items():
        print(f"{name} ({v['sut']}): {v['verdict']}")
    print(f"track: {track}")
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.extract_real_gate", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sel = sub.add_parser("select", help="emit the rule-based document manifest")
    sel.add_argument("--out", default="bench/results/real_gate/manifest.json")
    run = sub.add_parser("run", help="measure every manifest document for one SUT")
    run.add_argument("--manifest", required=True)
    run.add_argument("--sut", choices=["anchor", "candidate"], required=True)
    run.add_argument("--out-dir", required=True)
    run.add_argument("--model", default="claude-sonnet-4-6")
    agg = sub.add_parser("aggregate", help="apply the pre-registered gates to both SUTs")
    agg.add_argument("--manifest", required=True)
    agg.add_argument("--dir-a", required=True, help="per-doc results for SUT-A (anchor)")
    agg.add_argument("--dir-b", required=True, help="per-doc results for SUT-B (candidate)")
    agg.add_argument("--out", required=True)
    agg.add_argument("--md", help="also render a markdown skeleton for the results doc")
    args = ap.parse_args(argv)
    if args.cmd == "select":
        return cmd_select(args)
    if args.cmd == "run":
        try:
            return cmd_run(args)
        except Exception as exc:  # transport/SDK/file errors are infra, never a verdict
            print(f"extract-real-gate: infra error: {exc}", file=sys.stderr)
            return 2
    return cmd_aggregate(args)


if __name__ == "__main__":
    sys.exit(main())
