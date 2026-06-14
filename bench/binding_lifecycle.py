"""Binding-lifecycle benchmark — known-truth, two-layer, trigger-vs-truth honest.

This measures the symbol->defining-file binding fix (and the Phase-0 precision
nits) on dorian's lifecycle promise: a claim is verified at seal time and
re-checked when watched evidence changes. Every label is KNOWN-TRUTH — each
mutation carries TWO frozen, mechanically-authored break sets (see below), fixed
BEFORE measurement. No human, model, or panel judgment enters a label, and no
private data is read.

Two truth labels (the whole point — keep them separate)
-------------------------------------------------------
Binding widens the re-check TRIGGER set; it does not prove behavior. A
checker-fact break always lives in a file the checker reads, so a checker-path
watcher never misses it — the binding fix's value is catching DEFINER changes the
checker does NOT read. To express that honestly we score two layers against two
labels:

  breaks_trigger : claim ids whose TRUE DEPENDENCY the edit touches (a checker
                   file, or a file defining a symbol the claim is about). "This
                   claim should be RE-CHECKED." Superset of breaks_fact.
  breaks_fact    : claim ids whose CHECKER-VERIFIABLE fact the edit falsifies.
                   "This claim should ALARM (BROKEN)."

1. SELECTION (trigger) layer, scored vs breaks_trigger — did a watcher flag the
   pair for re-check?
     naive_file_watcher       any domain source file changed.
     checker_path_watcher     a file a claim's CHECKER names changed (dorian
                              BEFORE the binding fix — the pre-binding ablation).
     bound_dorian_candidate   revalidate SELECTED a claim for re-check (the sealed
                              watch, incl. the symbol-definer, was hit).
     overbroad_symbol_watcher ANY file containing a mentioned identifier changed
                              (the rejected "any file with the token" shortcut — a
                              CAUTIONARY baseline, never a serious competitor).

2. VERDICT (truth) layer, scored vs breaks_fact — did revalidate mark a claim
   BROKEN? ERRORED is reported separately and is NEVER an alarm.
     bound_dorian_broken      revalidate marked a claim BROKEN.

The honest result this is built to show: bound_dorian_candidate has HIGHER
selection recall than checker_path (it re-checks definer changes the pre-binding
watcher silently skipped — the false-TRUSTED TRIGGER reduction), at the cost of
LOWER selection precision (it re-checks benign definer churn too) — but those
extra re-checks do NOT become alarms: bound_dorian_broken precision stays high.
Candidate noise is not alarm noise. The gutted-body stratum makes the ceiling
explicit: binding fires the trigger (candidate) but a deterministic existence
checker cannot prove a behavior change, so no BROKEN. That gap is measured, never
counted as a binding win.

Scope / limits (stated up front)
--------------------------------
- Invented synthetic fixtures authored and scored by the same tool. These numbers
  are a reproducible demonstration of the MECHANISM on this suite, not evidence
  about any real repository.
- Determinism: the committed summary is byte-identical across runs because no sha,
  warrant id, wall-clock timestamp, or host path is ever emitted — every broken /
  errored / candidate warrant id is mapped to its stable artifact uri before any
  record is built; provenance is a content digest of the fixtures plus a
  deterministic run id.

Usage
-----
    python -m bench.binding_lifecycle [--quick] [--out summary.json]
        [--records recs.jsonl] [--md-out doc.md]
    (or: dorian bench binding-lifecycle ... from a dorian checkout)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# bench/ is a repo-root package, not installed with dorian; ensure it imports.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bench.metrics import BOOTSTRAP_N, BOOTSTRAP_SEED, _ci, prf  # noqa: E402
from dorian import bindings, gitio, symbol_index  # noqa: E402
from dorian.capture.manual import parse_manual  # noqa: E402
from dorian.model import Claim  # noqa: E402
from dorian.revalidate import revalidate  # noqa: E402
from dorian.seal import referenced_paths, seal_artifact  # noqa: E402

SCHEMA = "dorian-binding-lifecycle-v1"
BENCHMARK_ID = "binding_lifecycle"

# Overclaim guard: committed benchmark output must never contain these phrases.
FORBIDDEN_WORDS = (
    "proven",
    "validated",
    "production-grade",
    "production-ready",
    "universal",
    "real-world validated",
    "guaranteed",
    "semantic proof",
    "fully solves stale docs",
    "fully solves agent claim drift",
)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "dorian-bench",
    "GIT_AUTHOR_EMAIL": "bench@dorian.local",
    "GIT_COMMITTER_NAME": "dorian-bench",
    "GIT_COMMITTER_EMAIL": "bench@dorian.local",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}

_IDENT_SCAN = "(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])"


# --- declarative model ----------------------------------------------------------


@dataclass(frozen=True)
class BClaim:
    """A warranted claim plus the metadata baselines + strata need.

    `claim` is the real dorian model object that gets sealed. `binding_type`
    labels the symbol-binding stratum; `style` labels the checker family;
    `symbols` are the identifiers the claim text mentions (the overbroad baseline
    scans the repo for these)."""

    claim: Claim
    binding_type: str
    style: str
    symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class Artifact:
    uri: str
    claims: tuple[BClaim, ...]
    note: str = ""

    @property
    def claim_ids(self) -> set[str]:
        return {c.claim.id for c in self.claims}

    @property
    def checker_named_files(self) -> set[str]:
        """Files this artifact's CHECKERS name — the pre-binding watch (no
        symbol-definer expansion); the checker_path_watcher surface."""
        out: set[str] = set()
        for c in self.claims:
            out |= bindings._checker_named_files(c.claim, {})
        return out

    @property
    def mentioned_symbols(self) -> set[str]:
        return {s for c in self.claims for s in c.symbols}


@dataclass(frozen=True)
class Mutation:
    id: str
    mtype: str  # mutation_type stratum
    desc: str
    breaks_fact: frozenset[str]  # claims whose CHECKER-verifiable fact is falsified (verdict truth)
    breaks_trigger: frozenset[
        str
    ]  # claims whose true dependency the edit touches (selection truth)
    apply: object  # callable(repo: Path) -> None
    expect_rename: bool = False


@dataclass(frozen=True)
class Domain:
    name: str
    files: dict[str, str]
    artifacts: tuple[Artifact, ...]
    mutations: tuple[Mutation, ...]
    build_extra: object = None  # optional callable(repo: Path) -> None
    quick: bool = False  # included in the --quick subset

    @property
    def source_files(self) -> set[str]:
        """The naive watcher's project surface — every authored source file
        (never the generated artifact docs or .warrant sidecars)."""
        return set(self.files)


# --- git + fs helpers -----------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    import os

    env = {**os.environ, **GIT_ENV}
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# --- detectors ------------------------------------------------------------------


def _overbroad_files(domain: Domain, art: Artifact) -> set[str]:
    """The rejected shortcut: every domain source file whose t0 content has a
    whole-word match for any identifier the artifact's claims mention. A
    cautionary baseline, never serious."""
    syms = art.mentioned_symbols
    if not syms:
        return set()
    pat = re.compile("|".join(_IDENT_SCAN.format(re.escape(s)) for s in sorted(syms)))
    return {rel for rel, body in domain.files.items() if pat.search(body)}


# --- per-domain build + run -----------------------------------------------------


def _artifact_doc(domain_name: str, art: Artifact) -> str:
    body = [
        f"# {art.uri} ({domain_name})",
        "",
        "Fictional demo document; every fact is invented.",
        "",
    ]
    body += [f"- {c.claim.text}" for c in art.claims]
    return "\n".join(body) + "\n"


def _seal_bound(repo: Path, art: Artifact) -> None:
    """Seal one artifact exactly as `dorian verify` does: auto-capture the
    checker-referenced read-set, WIDEN it + the per-claim watch with the files
    that DEFINE the symbols the claims mention (symbol_index), then seal. This is
    the bound path under test — `seal_artifact` alone does not bind."""
    claims = [c.claim for c in art.claims]
    paths = referenced_paths(claims)
    symbol_watch = symbol_index.claim_symbol_watch_paths(repo, claims)
    for path in sorted({p for ps in symbol_watch.values() for p in ps}):
        if path not in paths:
            paths.append(path)
    readset = parse_manual(paths, repo)
    seal_artifact(repo, art.uri, readset, claims, extra_watch=symbol_watch)


def _seal_domain(repo: Path, domain: Domain) -> str:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for rel, content in domain.files.items():
        _write(repo, rel, content)
    for art in domain.artifacts:
        _write(repo, art.uri, _artifact_doc(domain.name, art))
    if domain.build_extra is not None:
        domain.build_extra(repo)  # type: ignore[operator]
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial fixture state")

    for art in domain.artifacts:
        _seal_bound(repo, art)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seal warrants")
    return _git(repo, "rev-parse", "HEAD")


def _by_uri(buckets, artifacts: dict[str, str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for bucket in buckets:
        for wid, cid, _ in bucket:
            out.setdefault(artifacts.get(wid, wid), set()).add(cid)
    return out


def _run_mutation(
    template: Path, work_root: Path, t0: str, domain: Domain, mut: Mutation
) -> list[dict]:
    """Apply one mutation to a fresh copy of the sealed t0 repo, revalidate
    against t0, and score every detector for every artifact in the domain."""
    work = work_root / f"{domain.name}__{mut.id}"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(template, work)

    mut.apply(work)  # type: ignore[operator]
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", mut.id)

    changed_list, renames = gitio.changed_paths(work, t0)
    changed = set(changed_list)
    if mut.expect_rename and not renames:
        raise RuntimeError(f"rename mutation {mut.id!r} produced no git rename")
    result = revalidate(work, since=t0)

    # candidate = re-checked at all (any bucket); broken / errored kept distinct.
    cand_by_uri = _by_uri(
        (result.passed, result.broken, result.relocated, result.errored), result.artifacts
    )
    broken_by_uri = _by_uri((result.broken,), result.artifacts)
    errored_by_uri = _by_uri((result.errored,), result.artifacts)

    records = []
    for art in domain.artifacts:
        cand = cand_by_uri.get(art.uri, set())
        broken = broken_by_uri.get(art.uri, set())
        errored = errored_by_uri.get(art.uri, set())
        records.append(
            {
                "domain": domain.name,
                "artifact": art.uri,
                "mutation": mut.id,
                "mutation_type": mut.mtype,
                "binding_types": sorted({c.binding_type for c in art.claims}),
                "checker_styles": sorted({c.style for c in art.claims}),
                "true_fact": bool(mut.breaks_fact & art.claim_ids),
                "true_trigger": bool(mut.breaks_trigger & art.claim_ids),
                "expected_broken": sorted(mut.breaks_fact & art.claim_ids),
                # selection (trigger) layer
                "naive": bool(domain.source_files & changed),
                "checker_path": bool(art.checker_named_files & changed),
                "bound_cand": bool(cand),
                "overbroad": bool(_overbroad_files(domain, art) & changed),
                # verdict (truth) layer
                "bound_broken": bool(broken),
                # raw, for stratification + attribution
                "candidate_claims": sorted(cand),
                "broken_claims": sorted(broken),
                "errored_claims": sorted(errored),
                "changed_files": sorted(changed),
            }
        )
    shutil.rmtree(work)
    return records


# --- metrics --------------------------------------------------------------------

_SELECTION = {
    "naive": "naive_file_watcher",
    "checker_path": "checker_path_watcher",
    "bound_cand": "bound_dorian_candidate",
    "overbroad": "overbroad_symbol_watcher",
}
_VERDICT = {"bound_broken": "bound_dorian_broken_alarm"}
_ALL_SYSTEMS = {**_SELECTION, **_VERDICT}


def _f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if (p + r) else 0.0


def _sys_pairs(records: list[dict], system: str) -> list[dict]:
    """Pairs for one detector against ITS truth label: the verdict alarm is
    scored vs breaks_fact; every trigger watcher vs breaks_trigger."""
    truth = "true_fact" if system in _VERDICT else "true_trigger"
    return [{"true": r[truth], system: r[system]} for r in records]


def _bootstrap_ci(pairs: list[dict], system: str, metric: str) -> list[float]:
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(pairs)
    if n == 0:
        return [1.0, 1.0]
    samples = [
        prf([pairs[rng.randrange(n)] for _ in range(n)], system)[metric] for _ in range(BOOTSTRAP_N)
    ]
    return _ci(samples)


def _block(records: list[dict], system: str) -> dict:
    pairs = _sys_pairs(records, system)
    s = prf(pairs, system)
    return {
        "alarms": s["tp"] + s["fp"],
        "tp": s["tp"],
        "fp": s["fp"],
        "fn": s["fn"],
        "tn": s["tn"],
        "precision": round(s["precision"], 4),
        "recall": round(s["recall"], 4),
        "f1": round(_f1(s["precision"], s["recall"]), 4),
        "specificity": round(s["tn"] / (s["tn"] + s["fp"]) if s["tn"] + s["fp"] else 1.0, 4),
        "false_positive_rate": round(
            s["fp"] / (s["fp"] + s["tn"]) if s["fp"] + s["tn"] else 0.0, 4
        ),
        "alarm_rate": round((s["tp"] + s["fp"]) / len(pairs) if pairs else 0.0, 4),
        "precision_ci": [round(x, 4) for x in _bootstrap_ci(pairs, system, "precision")],
        "recall_ci": [round(x, 4) for x in _bootstrap_ci(pairs, system, "recall")],
    }


def _short(records: list[dict], system: str) -> dict:
    pairs = _sys_pairs(records, system)
    s = prf(pairs, system)
    return {
        "pairs": len(pairs),
        "tp": s["tp"],
        "fp": s["fp"],
        "fn": s["fn"],
        "tn": s["tn"],
        "precision": round(s["precision"], 4) if s["tp"] + s["fp"] else None,
        "recall": round(s["recall"], 4) if s["tp"] + s["fn"] else None,
    }


def _strata(records: list[dict], key: str) -> dict:
    out: dict[str, dict] = {}
    vals: set[str] = set()
    for r in records:
        v = r[key]
        vals.update(v) if isinstance(v, list) else vals.add(v)
    for val in sorted(vals):
        sub = [r for r in records if (val in r[key] if isinstance(r[key], list) else r[key] == val)]
        out[val] = {lbl: _short(sub, sys) for sys, lbl in _ALL_SYSTEMS.items()}
    return out


def _dorian_version() -> str:
    try:
        from dorian import __version__

        return __version__
    except Exception:  # pragma: no cover
        return "unknown"


def _fixture_digest(domains: list[Domain]) -> str:
    h = hashlib.sha256()
    for d in domains:
        h.update(d.name.encode())
        for rel in sorted(d.files):
            h.update(rel.encode())
            h.update(d.files[rel].encode())
        for a in d.artifacts:
            h.update(a.uri.encode())
            for c in a.claims:
                h.update(c.claim.id.encode())
                for spec in c.claim.checkers:
                    h.update(spec.program.encode())
        for m in d.mutations:
            h.update(m.id.encode())
            h.update("".join(sorted(m.breaks_fact)).encode())
            h.update("".join(sorted(m.breaks_trigger)).encode())
    return h.hexdigest()[:32]


def _run_id(domains: list[Domain]) -> str:
    return hashlib.sha256((SCHEMA + "|" + _fixture_digest(domains)).encode()).hexdigest()[:16]


def _attribution(records: list[dict]) -> dict:
    """Descriptive: where the bound_broken alarm errs vs breaks_fact (read
    straight from frozen labels + per-claim verdicts; no label is invented)."""
    fps, fns = [], []
    for r in records:
        if r["bound_broken"] and not r["true_fact"]:
            fps.append({k: r[k] for k in ("domain", "artifact", "mutation", "mutation_type")})
        elif not r["bound_broken"] and r["true_fact"]:
            fns.append(
                {k: r[k] for k in ("domain", "artifact", "mutation", "mutation_type")}
                | {"missed": r["expected_broken"]}
            )
    return {"false_positives": fps, "false_negatives": fns}


def compute(records: list[dict], domains: list[Domain]) -> dict:
    n_artifacts = sum(len(d.artifacts) for d in domains)
    n_claims = sum(len(a.claims) for d in domains for a in d.artifacts)
    n_mut = sum(len(d.mutations) for d in domains)

    selection = {lbl: _block(records, sys) for sys, lbl in _SELECTION.items()}
    verdict = {lbl: _block(records, sys) for sys, lbl in _VERDICT.items()}

    # headline: binding lifts SELECTION recall on trigger-stale pairs the
    # pre-binding checker_path watcher silently skipped (false-TRUSTED trigger gap).
    trig_stale = [r for r in records if r["true_trigger"]]
    false_trusted = {
        "trigger_stale_pairs": len(trig_stale),
        "checker_path_selection_recall": round(
            prf(_sys_pairs(trig_stale, "checker_path"), "checker_path")["recall"], 4
        )
        if trig_stale
        else None,
        "bound_candidate_selection_recall": round(
            prf(_sys_pairs(trig_stale, "bound_cand"), "bound_cand")["recall"], 4
        )
        if trig_stale
        else None,
        "trigger_stale_pairs_checker_path_misses_but_binding_catches": sum(
            1 for r in trig_stale if not r["checker_path"] and r["bound_cand"]
        ),
        "note": "selection recall on known trigger-stale pairs; binding's value is the "
        "pairs checker_path silently skips but bound_candidate re-checks",
    }

    # the ceiling, surfaced not hidden: gutted-body changes behavior, symbol still
    # exists -> bound_candidate SELECTS (trigger) but the existence checker's fact is
    # intact so bound_broken correctly does NOT alarm. A behavior (C4) checker on the
    # same edit DOES break (the behavior_catch contrast).
    ceiling = [
        r
        for r in records
        if r["mutation_type"] == "gutted_body" and "semantic_ceiling" in r["binding_types"]
    ]
    contrast = [
        r
        for r in records
        if r["mutation_type"] == "gutted_body" and "behavior_checked" in r["binding_types"]
    ]
    semantic_ceiling = {
        "gutted_body_existence_checker": {
            "pairs": len(ceiling),
            "bound_candidate_selection_recall": round(
                prf(_sys_pairs(ceiling, "bound_cand"), "bound_cand")["recall"], 4
            )
            if ceiling
            else None,
            "bound_broken_alarm_count": sum(1 for r in ceiling if r["bound_broken"]),
        },
        "gutted_body_behavior_checker_contrast": {
            "pairs": len(contrast),
            "bound_broken_alarm_recall": round(
                prf(_sys_pairs(contrast, "bound_broken"), "bound_broken")["recall"], 4
            )
            if contrast
            else None,
        },
        "note": "an existence/shape checker fires the TRIGGER on a gutted body but cannot "
        "prove the behavior change (no BROKEN) — the documented ceiling, NOT a binding "
        "failure and NOT a semantic catch; only a checker that EXERCISES behavior catches it",
    }

    return {
        "schema": SCHEMA,
        "provenance": {
            "benchmark_id": BENCHMARK_ID,
            "dorian_version": _dorian_version(),
            "measured_commit": "unspecified",  # filled by main() with repo HEAD
            "run_id": _run_id(domains),
            "seed": BOOTSTRAP_SEED,
            "fixture_manifest_digest": _fixture_digest(domains),
        },
        "composition": {
            "domains": len(domains),
            "domain_names": [d.name for d in domains],
            "artifacts": n_artifacts,
            "claims": n_claims,
            "mutations": n_mut,
            "pairs": len(records),
            "fact_stale_pairs": sum(1 for r in records if r["true_fact"]),
            "trigger_stale_pairs": sum(1 for r in records if r["true_trigger"]),
            "benign_pairs": sum(1 for r in records if not r["true_trigger"]),
            "errored_pairs": sum(1 for r in records if r["errored_claims"]),
            "binding_types": sorted({bt for r in records for bt in r["binding_types"]}),
            "mutation_types": sorted({r["mutation_type"] for r in records}),
        },
        "selection_layer": selection,
        "verdict_layer": verdict,
        "false_trusted_analysis": false_trusted,
        "semantic_ceiling": semantic_ceiling,
        "fp_counts": {
            "naive_file_watcher_fp": selection["naive_file_watcher"]["fp"],
            "checker_path_watcher_fp": selection["checker_path_watcher"]["fp"],
            "bound_candidate_fp": selection["bound_dorian_candidate"]["fp"],
            "overbroad_symbol_watcher_fp": selection["overbroad_symbol_watcher"]["fp"],
            "bound_broken_alarm_fp": verdict["bound_dorian_broken_alarm"]["fp"],
            "note": "candidate FP (vs breaks_trigger) is HARMLESS — a zero-token re-check "
            "that passes; the alarm FP (bound_broken vs breaks_fact) is the one that "
            "matters. Read raw counts.",
        },
        "by_binding_type": _strata(records, "binding_types"),
        "by_mutation_type": _strata(records, "mutation_type"),
        "by_domain": _strata(records, "domain"),
        "error_attribution": _attribution(records),
        "errored_detail": [
            {
                "domain": r["domain"],
                "artifact": r["artifact"],
                "mutation": r["mutation"],
                "errored": r["errored_claims"],
            }
            for r in records
            if r["errored_claims"]
        ],
        "bootstrap": {"resamples": BOOTSTRAP_N, "seed": BOOTSTRAP_SEED, "scope": "in-fixture"},
    }


def _records_for_jsonl(records: list[dict]) -> list[dict]:
    cols = (
        "domain",
        "artifact",
        "mutation",
        "mutation_type",
        "binding_types",
        "checker_styles",
        "true_fact",
        "true_trigger",
        "expected_broken",
        "naive",
        "checker_path",
        "bound_cand",
        "overbroad",
        "bound_broken",
        "candidate_claims",
        "broken_claims",
        "errored_claims",
        "changed_files",
    )
    return [{k: r[k] for k in cols} for r in records]


# --- run ------------------------------------------------------------------------


def run_benchmark(workspace: Path, quick: bool = False) -> tuple[dict, list[dict]]:
    from bench.binding_lifecycle_domains import domains as all_domains

    domains = [d for d in all_domains() if (d.quick or not quick)]
    workspace.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    for domain in domains:
        template = workspace / f"t0__{domain.name}"
        if template.exists():
            shutil.rmtree(template)
        t0 = _seal_domain(template, domain)
        work_root = workspace / "work"
        work_root.mkdir(exist_ok=True)
        for mut in domain.mutations:
            records.extend(_run_mutation(template, work_root, t0, domain, mut))
        shutil.rmtree(template)
    records.sort(key=lambda r: (r["domain"], r["mutation"], r["artifact"]))
    return compute(records, domains), records


# --- render ---------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return f"{x:.2f}" if x is not None else "n/a"


def _row(label: str, b: dict) -> str:
    pci = f"{b['precision']:.2f} ({b['precision_ci'][0]:.2f}-{b['precision_ci'][1]:.2f})"
    rci = f"{b['recall']:.2f} ({b['recall_ci'][0]:.2f}-{b['recall_ci'][1]:.2f})"
    return f"| {label} | {b['tp']} | {b['fp']} | {b['fn']} | {pci} | {rci} | {b['f1']:.2f} |"


def render_markdown(m: dict) -> str:
    c = m["composition"]
    ft = m["false_trusted_analysis"]
    sc = m["semantic_ceiling"]
    v = m["verdict_layer"]["bound_dorian_broken_alarm"]
    lines = [
        "# dorian binding-lifecycle benchmark",
        "",
        "> Generated from machine output by `bench.binding_lifecycle`. Known-truth labels,",
        "> in-fixture results — a reproducible demonstration of the MECHANISM on this suite,",
        "> not evidence about any real repository.",
        "",
        "## Scope",
        "",
        f"- schema `{m['schema']}` · dorian `{m['provenance']['dorian_version']}` · "
        f"run_id `{m['provenance']['run_id']}`",
        f"- {c['domains']} domains · {c['artifacts']} artifacts · {c['claims']} claims · "
        f"{c['mutations']} mutations · {c['pairs']} (artifact, mutation) pairs",
        f"- {c['fact_stale_pairs']} fact-stale · {c['trigger_stale_pairs']} trigger-stale · "
        f"{c['benign_pairs']} benign · {c['errored_pairs']} errored pairs",
        "",
        "Two truth labels: **breaks_trigger** (should be re-checked) scores the selection",
        "layer; **breaks_fact** (should ALARM) scores the verdict layer. A definer change is",
        "trigger-stale without being fact-stale — that is the whole point.",
        "",
        "## Selection (trigger) layer — flagged for re-check? (scored vs breaks_trigger)",
        "",
        "| watcher | TP | FP | FN | precision (95% CI) | recall (95% CI) | F1 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for lbl in _SELECTION.values():
        lines.append(_row(lbl, m["selection_layer"][lbl]))
    lines += [
        "",
        "## Verdict (truth) layer — marked BROKEN? (scored vs breaks_fact)",
        "",
        "| alarm | TP | FP | FN | precision (95% CI) | recall (95% CI) | F1 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        _row("bound_dorian_broken_alarm", v),
        "",
        f"ERRORED is reported separately, never an alarm: {c['errored_pairs']} pair(s).",
        "",
        "## False-TRUSTED reduction (the binding fix's point — TRIGGER level)",
        "",
        f"- selection recall on the {ft['trigger_stale_pairs']} trigger-stale pairs: "
        f"checker_path (pre-binding) **{_pct(ft['checker_path_selection_recall'])}** "
        f"-> bound_candidate **{_pct(ft['bound_candidate_selection_recall'])}**",
        f"- trigger-stale pairs checker_path SILENTLY SKIPS but binding RE-CHECKS: "
        f"**{ft['trigger_stale_pairs_checker_path_misses_but_binding_catches']}**",
        "",
        "## Semantic ceiling (trigger != truth) — surfaced, not solved",
        "",
        f"- gutted-body + existence checker: {sc['gutted_body_existence_checker']['pairs']} pairs, "
        f"candidate sel-recall "
        f"**{_pct(sc['gutted_body_existence_checker']['bound_candidate_selection_recall'])}**, "
        f"BROKEN alarms **{sc['gutted_body_existence_checker']['bound_broken_alarm_count']}**",
        f"- SAME edit + behavior (C4) checker: "
        f"{sc['gutted_body_behavior_checker_contrast']['pairs']} pairs, BROKEN recall "
        f"**{_pct(sc['gutted_body_behavior_checker_contrast']['bound_broken_alarm_recall'])}**",
        f"- {sc['note']}",
        "",
        "## By binding type",
        "",
        "| binding_type | pairs | checker_path sel-recall | bound_cand sel-recall | "
        "bound_broken precision | bound_broken recall |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for bt, blocks in sorted(m["by_binding_type"].items()):
        cp, bc, bb = (
            blocks["checker_path_watcher"],
            blocks["bound_dorian_candidate"],
            blocks["bound_dorian_broken_alarm"],
        )
        lines.append(
            f"| {bt} | {bc['pairs']} | {_pct(cp['recall'])} | {_pct(bc['recall'])} "
            f"| {_pct(bb['precision'])} | {_pct(bb['recall'])} |"
        )
    lines += [
        "",
        "## By mutation type (verdict precision / recall)",
        "",
        "| mutation_type | pairs | bound_broken precision | bound_broken recall |",
        "| --- | --- | --- | --- |",
    ]
    for mt, blocks in sorted(m["by_mutation_type"].items()):
        bb = blocks["bound_dorian_broken_alarm"]
        lines.append(f"| {mt} | {bb['pairs']} | {_pct(bb['precision'])} | {_pct(bb['recall'])} |")
    lines += [
        "",
        "## Reproduce",
        "",
        "```bash",
        "dorian bench binding-lifecycle            # full",
        "dorian bench binding-lifecycle --quick    # CI subset",
        "```",
        "",
    ]
    return "\n".join(lines) + "\n"


def _measured_commit() -> str:
    try:
        return _git(_REPO_ROOT, "rev-parse", "HEAD")
    except Exception:  # pragma: no cover
        return "unspecified"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.binding_lifecycle", description=__doc__)
    ap.add_argument("--quick", action="store_true", help="run the small deterministic CI subset")
    ap.add_argument("--out", default=f"bench/results/{BENCHMARK_ID}_summary.json")
    ap.add_argument("--records", default=f"bench/results/{BENCHMARK_ID}_records.jsonl")
    ap.add_argument("--md-out", default="docs/BENCHMARK_BINDING_LIFECYCLE.md")
    ap.add_argument("--workspace", default="")
    args = ap.parse_args(argv)

    import tempfile

    ws = (
        Path(args.workspace) if args.workspace else Path(tempfile.mkdtemp(prefix="dorian-blbench-"))
    )
    try:
        summary, records = run_benchmark(ws, quick=args.quick)
    finally:
        if not args.workspace and ws.exists():
            shutil.rmtree(ws, ignore_errors=True)
    summary["provenance"]["measured_commit"] = _measured_commit()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    recs = Path(args.records)
    recs.parent.mkdir(parents=True, exist_ok=True)
    with recs.open("w", encoding="utf-8") as f:
        for row in _records_for_jsonl(records):
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    if args.md_out:
        md_out = Path(args.md_out)
        md_out.parent.mkdir(parents=True, exist_ok=True)
        md_out.write_text(render_markdown(summary), encoding="utf-8")

    cmp = summary["composition"]
    ft = summary["false_trusted_analysis"]
    print(
        f"binding-lifecycle: {cmp['pairs']} pairs · selection recall "
        f"checker_path {_pct(ft['checker_path_selection_recall'])} -> "
        f"bound_candidate {_pct(ft['bound_candidate_selection_recall'])} · "
        f"bound_broken precision "
        f"{summary['verdict_layer']['bound_dorian_broken_alarm']['precision']:.2f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
