"""Large controlled-mutation benchmark (numbers-only, known-truth labels).

This is the v0.7.0 successor to bench/controlled_mutation.py: a wider battery
across several invented, public-safe fixture domains, scoring dorian's
claim-level revalidation against three file-change-watcher baselines.

It tests one scoped property: **dorian suppresses noisy benign-change alarms
when claims are well-warranted**, while measuring (not assuming) where dorian
itself errs. Every label is KNOWN-TRUTH: each mutation's stale / not-stale
outcome for a claim is a mechanical consequence of the edit (e.g. "we changed
TIMEOUT from 30 to 10, so the claim 'the default timeout is 30 seconds' is now
false"), fixed before measurement. No human, model, or panel judgment enters a
label, and no private data is read.

See docs/BENCHMARK_PROTOCOL_v0.7.0.md for the pre-measurement protocol and
docs/BENCHMARK_v0.7.0.md for the rendered results.

Design
------
- Each DOMAIN is a separate, sealed git repo built from invented sources, with
  two or more warranted artifacts. Per-domain repos keep the baselines honest:
  the naive watcher's "project surface" is that domain's source files, not the
  whole filesystem.
- Each mutation is applied INDEPENDENTLY to a fresh copy of its domain's sealed
  t0 repo, committed, and revalidated against t0. Independence is by
  construction: every copy starts from the same sealed VERIFIED baseline.
- Within a domain, every mutation is scored against every artifact (a watcher of
  that project sees every commit). An artifact's label is "stale" iff the
  mutation's frozen `breaks` set intersects that artifact's claim ids.
- Four detectors are scored per (artifact, mutation) pair:
    naive_file_watcher  - alarm iff any of the DOMAIN's source files changed
                          (the crudest project-wide watcher).
    path_scope_watcher  - alarm iff any file THIS artifact's claims reference
                          changed.
    line_aware_watcher  - alarm iff a changed line range overlaps a claim's
                          anchor lines (whole-file/data claims alarm on any
                          change to their file; add/remove/rename alarms). The
                          strongest strawman a careful engineer would build;
                          rename-naive on purpose.
    dorian              - alarm iff revalidate marks any of the artifact's
                          claims BROKEN (ERRORED is never an alarm).
  naive >= path_scope >= line_aware by construction (each refines the last).

Scope / limits, stated up front
-------------------------------
- Invented synthetic fixtures, authored and scored by the same tool. These
  numbers are a reproducible demonstration of the MECHANISM, not evidence about
  any real repository. Results are specific to this benchmark.
- C4 (pytest-subprocess) checkers are excluded for hermeticity; C1, C3
  (path/symbol/string/regex) and C5 (rowcount/schema/nullrate/domain/freshness/
  snapshot/reconcile) are covered.
- Determinism: the committed summary is byte-identical across runs NOT because the
  fixture commit shas are stable (they are not - seal writes a wall-clock `sealed_at`
  into each sidecar, so t0 and per-mutation shas and warrant ids vary run to run), but
  because no sha or warrant id is ever emitted: t0 is used only as an internal diff
  ref, and every broken/errored warrant id is mapped to its stable artifact uri before
  any record is built. The summary records only aggregate numbers, booleans, fixed
  template strings, the fixtures' own public file names, mutation/claim ids, the dorian
  version, a deterministic run id, and a content digest of the fixtures - never
  wall-clock timestamps, warrant ids, or host paths.

Usage
-----
    python -m bench.large_mutation [--out summary.json] [--records recs.jsonl]
        [--md-out doc.md]
    (or: dorian bench large-mutation ... from a dorian checkout)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
from dorian.capture.manual import parse_manual  # noqa: E402
from dorian.model import CheckerSpec, Claim  # noqa: E402
from dorian.revalidate import revalidate  # noqa: E402
from dorian.seal import seal_artifact  # noqa: E402

SCHEMA = "dorian-large-controlled-mutation-v1"
BENCHMARK_ID = "v0.7.0_large_controlled_mutation"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "dorian-bench",
    "GIT_AUTHOR_EMAIL": "bench@dorian.local",
    "GIT_COMMITTER_NAME": "dorian-bench",
    "GIT_COMMITTER_EMAIL": "bench@dorian.local",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}


# --- declarative model ----------------------------------------------------------


@dataclass(frozen=True)
class ClaimEntry:
    """A warranted claim plus the metadata the baselines need.

    `claim` is the real dorian model object that gets sealed. `level` /
    `anchor_file` / `lines` drive the line-aware watcher; `style` labels the
    checker family for stratified metrics.
    """

    claim: Claim
    style: str
    level: str  # "line" | "file"
    anchor_file: str = ""  # for level == "line"
    lines: frozenset[int] | None = None  # for level == "line"

    @property
    def watch_files(self) -> set[str]:
        files: set[str] = set()
        for spec in self.claim.checkers:
            files.update(spec.watch)
        return files


@dataclass(frozen=True)
class ArtifactSpec:
    uri: str
    readset_specs: tuple[str, ...]
    claims: tuple[ClaimEntry, ...]
    note: str = ""  # short, public description for the by-artifact table

    @property
    def claim_ids(self) -> set[str]:
        return {e.claim.id for e in self.claims}

    @property
    def files(self) -> set[str]:
        files: set[str] = set()
        for e in self.claims:
            files |= e.watch_files
        return files


@dataclass(frozen=True)
class MutationSpec:
    id: str
    family: str
    desc: str
    breaks: frozenset[str]  # claim ids whose FACT the edit falsifies (known-truth)
    apply: object  # callable(repo: Path) -> None
    expect_rename: bool = False


@dataclass(frozen=True)
class Domain:
    name: str
    files: dict[str, str]
    artifacts: tuple[ArtifactSpec, ...]
    mutations: tuple[MutationSpec, ...]
    build_extra: object = None  # optional callable(repo: Path) -> None

    @property
    def source_files(self) -> set[str]:
        """Union of every artifact's referenced files - the naive watcher's
        project surface for this domain."""
        files: set[str] = set()
        for a in self.artifacts:
            files |= a.files
        return files


# --- claim builders (cut literal noise) -----------------------------------------


def _c3(
    cid: str,
    text: str,
    program: str,
    watch: str,
    *,
    style: str,
    level: str,
    lines: frozenset[int] | None = None,
    kind: str = "fact",
    lb: bool = True,
) -> ClaimEntry:
    return ClaimEntry(
        claim=Claim(
            id=cid,
            text=text,
            kind=kind,
            load_bearing=lb,
            checkers=(CheckerSpec(type="C3", program=program, watch=(watch,)),),
        ),
        style=style,
        level=level,
        anchor_file=watch if level == "line" else "",
        lines=lines,
    )


def _c5(
    cid: str,
    text: str,
    program: str,
    watch: tuple[str, ...],
    *,
    style: str,
    kind: str = "fact",
    lb: bool = True,
    supports: tuple[str, ...] = (),
) -> ClaimEntry:
    return ClaimEntry(
        claim=Claim(
            id=cid,
            text=text,
            kind=kind,
            load_bearing=lb,
            supports=supports,
            checkers=(CheckerSpec(type="C5", program=program, watch=watch),),
        ),
        style=style,
        level="file",
    )


# --- git + fs helpers -----------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout.strip()


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="\n")


def _rmtree(path: Path) -> None:
    """Robust teardown of a transient git fixture repo. After a commit, git can
    briefly hold files under .git (auto-gc / fsmonitor), so shutil.rmtree races
    with "Directory not empty" / vanished-file errors on loaded CI runners. Retry
    a few times, then give up cleanly — the parent workspace is an ephemeral tmp
    dir removed wholesale, so leftover cruft never affects the (in-memory) result."""
    import time

    for _ in range(6):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.15)
    shutil.rmtree(path, ignore_errors=True)


def _set_file(repo: Path, rel: str, content: str) -> None:
    _write(repo, rel, content)


def _delete_file(repo: Path, rel: str) -> None:
    (repo / rel).unlink()


def _git_mv(repo: Path, old: str, new: str) -> None:
    (repo / new).parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", old, new)


def _changed_line_ranges(repo: Path, since: str, path: str) -> set[int]:
    """Old-side (t0) line numbers touched in `path` between `since` and HEAD,
    from `git diff -U0` hunk headers. A pure insertion (old count 0) touches no
    existing line, so a comment added elsewhere does not alarm."""
    try:
        out = _git(repo, "diff", "-U0", "--no-color", since, "HEAD", "--", path)
    except subprocess.CalledProcessError:
        return set()
    touched: set[int] = set()
    for line in out.splitlines():
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+", line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        touched.update(range(start, start + count))
    return touched


def _changed_paths(repo: Path, since: str) -> tuple[list[str], dict[str, str]]:
    from dorian import gitio

    return gitio.changed_paths(repo, since)


# --- detectors ------------------------------------------------------------------


def _naive_alarm(domain: Domain, changed: set[str]) -> bool:
    return bool(domain.source_files & changed)


def _path_scope_alarm(artifact: ArtifactSpec, changed: set[str]) -> bool:
    return bool(artifact.files & changed)


def _line_aware_alarm(
    repo: Path, t0: str, artifact: ArtifactSpec, changed: set[str], renames: dict[str, str]
) -> bool:
    """Alarm iff a changed line overlaps a claim's anchor lines, a whole-file/
    data claim's watched file changed, or a watched file was added/removed/
    renamed. Rename-naive on purpose."""
    for e in artifact.claims:
        watch = e.watch_files
        touched = watch & (changed | set(renames))
        if not touched:
            continue
        # a watched file deleted or renamed away -> alarm (rename-naive)
        if any(not (repo / w).is_file() or w in renames for w in touched):
            return True
        if e.level == "file":
            return True
        # line level: overlap on the anchor file
        if (
            e.anchor_file in touched
            and e.lines
            and e.lines & _changed_line_ranges(repo, t0, e.anchor_file)
        ):
            return True
    return False


# --- per-domain build + run -----------------------------------------------------


def _artifact_doc(domain_name: str, art: ArtifactSpec) -> str:
    """A generated markdown doc for an artifact: its claim texts as bullets. The
    content only fixes the artifact hash; mutations never touch the doc, so it
    plays no part in any label."""
    body = [
        f"# {art.uri} ({domain_name})",
        "",
        "Fictional demo document; every fact is invented.",
        "",
    ]
    body += [f"- {e.claim.text}" for e in art.claims]
    return "\n".join(body) + "\n"


def _seal_domain(repo: Path, domain: Domain) -> str:
    """Materialize + seal a domain's fixture; return the sealed t0 commit sha."""
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
        readset = parse_manual(list(art.readset_specs), repo)
        claims = [e.claim for e in art.claims]
        seal_artifact(repo, art.uri, readset, claims)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seal warrants")
    return _git(repo, "rev-parse", "HEAD")


def _run_mutation(
    template: Path, work_root: Path, t0: str, domain: Domain, mut: MutationSpec
) -> list[dict]:
    """Apply one mutation to a fresh copy and score all detectors for every
    artifact in the domain."""
    work = work_root / f"{domain.name}__{mut.id}"
    if work.exists():
        _rmtree(work)
    shutil.copytree(template, work)

    mut.apply(work)  # type: ignore[operator]
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", mut.id)

    changed_list, renames = _changed_paths(work, t0)
    changed = set(changed_list)
    if mut.expect_rename and not renames:
        raise RuntimeError(f"rename mutation {mut.id!r} produced no git rename")
    result = revalidate(work, since=t0)

    broken_by_uri: dict[str, set[str]] = {}
    errored_by_uri: dict[str, set[str]] = {}
    for wid, cid, _ in result.broken:
        broken_by_uri.setdefault(result.artifacts.get(wid, wid), set()).add(cid)
    for wid, cid, _ in result.errored:
        errored_by_uri.setdefault(result.artifacts.get(wid, wid), set()).add(cid)

    records = []
    for art in domain.artifacts:
        broken = broken_by_uri.get(art.uri, set())
        errored = errored_by_uri.get(art.uri, set())
        label = bool(mut.breaks & art.claim_ids)
        records.append(
            {
                "domain": domain.name,
                "artifact": art.uri,
                "mutation": mut.id,
                "family": mut.family,
                "true": label,
                "expected_broken": sorted(mut.breaks & art.claim_ids),
                "naive": _naive_alarm(domain, changed),
                "pathscope": _path_scope_alarm(art, changed),
                "lineaware": _line_aware_alarm(work, t0, art, changed, renames),
                "dorian": bool(broken),
                "dorian_broken": sorted(broken),
                "errored": sorted(errored),
                "changed_files": sorted(changed),
                "checker_styles": sorted({e.style for e in art.claims}),
            }
        )
    _rmtree(work)
    return records


# --- metrics --------------------------------------------------------------------

_SYSTEMS = ("naive", "pathscope", "lineaware", "dorian")
_SYSTEM_LABELS = {
    "naive": "naive_file_watcher",
    "pathscope": "path_scope_watcher",
    "lineaware": "line_aware_watcher",
    "dorian": "dorian",
}
# benign families that genuinely change a watched file (vs. neutral = unrelated file)
_NEUTRAL_FAMILIES = {"unrelated_file"}
_ADVERSARIAL_FAMILIES = {
    "adversarial_comment_survival",
    "adversarial_docstring_survival",
    "adversarial_constant_survival",
}


def _pair_view(records: list[dict]) -> list[dict]:
    return [
        {k: r[k] for k in ("true", "naive", "pathscope", "lineaware", "dorian")} for r in records
    ]


def _bootstrap_ci(pairs: list[dict], system: str, metric: str) -> list[float]:
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(pairs)
    if n == 0:
        return [1.0, 1.0]
    samples = []
    for _ in range(BOOTSTRAP_N):
        resample = [pairs[rng.randrange(n)] for _ in range(n)]
        samples.append(prf(resample, system)[metric])
    return _ci(samples)


def _system_block(pairs: list[dict], system: str) -> dict:
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


def _f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if (p + r) else 0.0


def _short_block(pairs: list[dict], system: str) -> dict:
    s = prf(pairs, system)
    # A slice where the system never alarms (tp+fp==0) has no measured precision;
    # report null rather than the vacuous 1.0 convention (e.g. dorian on the
    # adversarial-only slice catches 0/5, so its precision there is undefined, not
    # perfect). Likewise recall is null when the slice has no true-stale pairs.
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
    """dorian vs baselines, sliced by a record key (domain/family/...)."""
    out: dict[str, dict] = {}
    for val in sorted({r[key] for r in records}):
        sub = _pair_view([r for r in records if r[key] == val])
        out[val] = {sys_lbl: _short_block(sub, sys) for sys, sys_lbl in _SYSTEM_LABELS.items()}
    return out


def _checker_of(records: list[dict], domains: list[Domain]) -> dict[str, str]:
    style: dict[str, str] = {}
    for d in domains:
        for a in d.artifacts:
            for e in a.claims:
                style[e.claim.id] = e.style
    return style


def _attribution(records: list[dict], style: dict[str, str]) -> dict:
    """Descriptive: where dorian's FPs / FNs land (read from per-claim verdicts /
    the frozen expected-broken sets; no labels invented)."""
    fps, fns = [], []
    for r in records:
        if r["dorian"] and not r["true"]:
            fps.append(
                {
                    "domain": r["domain"],
                    "artifact": r["artifact"],
                    "mutation": r["mutation"],
                    "family": r["family"],
                    "checkers": sorted({style.get(c, "?") for c in r["dorian_broken"]}),
                }
            )
        elif not r["dorian"] and r["true"]:
            fns.append(
                {
                    "domain": r["domain"],
                    "artifact": r["artifact"],
                    "mutation": r["mutation"],
                    "family": r["family"],
                    "missed_claims": r["expected_broken"],
                    "checkers": sorted({style.get(c, "?") for c in r["expected_broken"]}),
                }
            )
    return {"false_positives": fps, "false_negatives": fns}


def compute(records: list[dict], domains: list[Domain]) -> dict:
    pairs = _pair_view(records)
    style = _checker_of(records, domains)
    systems = {lbl: _system_block(pairs, sys) for sys, lbl in _SYSTEM_LABELS.items()}
    fp = {lbl: systems[lbl]["fp"] for lbl in _SYSTEM_LABELS.values()}
    dorian_fp = fp["dorian"]

    n_artifacts = sum(len(d.artifacts) for d in domains)
    n_claims = sum(len(a.claims) for d in domains for a in d.artifacts)
    neutral = sum(1 for r in records if r["family"] in _NEUTRAL_FAMILIES)
    adversarial = sum(1 for r in records if r["family"] in _ADVERSARIAL_FAMILIES)

    by_artifact = {}
    for d in domains:
        for a in d.artifacts:
            ap = _pair_view([r for r in records if r["artifact"] == a.uri])
            by_artifact[a.uri] = {**_short_block(ap, "dorian"), "domain": d.name, "note": a.note}

    return {
        "schema": SCHEMA,
        "provenance": {
            "benchmark_id": BENCHMARK_ID,
            "dorian_version": _dorian_version(),
            "measured_commit": "unspecified",  # filled by main() with the repo HEAD
            "run_id": _run_id(domains),
            "seed": BOOTSTRAP_SEED,
            "fixture_manifest_digest": _fixture_digest(domains),
        },
        "composition": {
            "domains": len(domains),
            "domain_names": [d.name for d in domains],
            "artifacts": n_artifacts,
            "claims": n_claims,
            "checker_styles": sorted(style[c] for c in style)
            and sorted({v for v in style.values()}),
            "pairs": len(records),
            "true_stale_pairs": sum(1 for r in records if r["true"]),
            "benign_pairs": sum(1 for r in records if not r["true"]),
            "neutral_pairs": neutral,
            "adversarial_pairs": adversarial,
            "errored_pairs": sum(1 for r in records if r["errored"]),
        },
        "systems": systems,
        "fp_reduction": {
            **{f"{lbl}_fp": fp[lbl] for lbl in _SYSTEM_LABELS.values()},
            "vs_naive_file_watcher": round(fp["naive_file_watcher"] / max(1, dorian_fp), 2),
            "vs_path_scope_watcher": round(fp["path_scope_watcher"] / max(1, dorian_fp), 2),
            "vs_line_aware_watcher": round(fp["line_aware_watcher"] / max(1, dorian_fp), 2),
            "note": "ratio = baseline FP / max(1, dorian FP); read raw counts alongside it",
        },
        "by_domain": _strata(records, "domain"),
        "by_family": _strata(records, "family"),
        "by_artifact": by_artifact,
        "adversarial_slice": {
            lbl: _short_block(
                _pair_view([r for r in records if r["family"] in _ADVERSARIAL_FAMILIES]), sys
            )
            for sys, lbl in _SYSTEM_LABELS.items()
        },
        "dorian_error_attribution": _attribution(records, style),
        "bootstrap": {"resamples": BOOTSTRAP_N, "seed": BOOTSTRAP_SEED, "scope": "in-fixture"},
    }


def _dorian_version() -> str:
    try:
        from dorian import __version__

        return __version__
    except Exception:  # pragma: no cover - version import is trivial
        return "unknown"


def _run_id(domains: list[Domain]) -> str:
    """Deterministic run id: a digest over schema + fixture manifest (no clock)."""
    return hashlib.sha256((SCHEMA + "|" + _fixture_digest(domains)).encode()).hexdigest()[:16]


def _fixture_digest(domains: list[Domain]) -> str:
    h = hashlib.sha256()
    for d in domains:
        h.update(d.name.encode())
        for rel in sorted(d.files):
            h.update(rel.encode())
            h.update(d.files[rel].encode())
        for a in d.artifacts:
            h.update(a.uri.encode())
            for e in a.claims:
                h.update(e.claim.id.encode())
                for spec in e.claim.checkers:
                    h.update(spec.program.encode())
        for m in d.mutations:
            h.update(m.id.encode())
            h.update("".join(sorted(m.breaks)).encode())
    return h.hexdigest()[:32]


# --- run ------------------------------------------------------------------------


def run_benchmark(workspace: Path) -> dict:
    from bench.large_mutation_domains import DOMAINS

    workspace.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    for domain in DOMAINS:
        template = workspace / f"t0__{domain.name}"
        if template.exists():
            _rmtree(template)
        t0 = _seal_domain(template, domain)
        work_root = workspace / "work"
        work_root.mkdir(exist_ok=True)
        for mut in domain.mutations:
            records.extend(_run_mutation(template, work_root, t0, domain, mut))
        _rmtree(template)
    records.sort(key=lambda r: (r["domain"], r["mutation"], r["artifact"]))
    return compute(records, list(DOMAINS)), records


def _records_for_jsonl(records: list[dict]) -> list[dict]:
    cols = (
        "domain",
        "artifact",
        "mutation",
        "family",
        "true",
        "expected_broken",
        "naive",
        "pathscope",
        "lineaware",
        "dorian",
        "dorian_broken",
        "errored",
        "changed_files",
        "checker_styles",
    )
    return [{k: r[k] for k in cols} for r in records]


# --- render ---------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return f"{x:.2f}" if x is not None else "n/a"


def render_markdown(m: dict) -> str:
    c = m["composition"]
    sys_rows = []
    for lbl in ("naive_file_watcher", "path_scope_watcher", "line_aware_watcher", "dorian"):
        s = m["systems"][lbl]
        sys_rows.append(
            f"| {lbl} | {s['tp']} | {s['fp']} | {s['fn']} | {s['tn']} "
            f"| {s['precision']:.2f} ({s['precision_ci'][0]:.2f}-{s['precision_ci'][1]:.2f}) "
            f"| {s['recall']:.2f} ({s['recall_ci'][0]:.2f}-{s['recall_ci'][1]:.2f}) "
            f"| {s['f1']:.2f} | {s['specificity']:.2f} |"
        )
    fpr = m["fp_reduction"]
    dom_rows = []
    for name, blocks in m["by_domain"].items():
        d = blocks["dorian"]
        dom_rows.append(
            f"| {name} | {d['pairs']} | {d['tp']} | {d['fp']} | {d['fn']} | {d['tn']} "
            f"| {_pct(d['precision'])} | {_pct(d['recall'])} |"
        )
    fam_rows = []
    for name, blocks in m["by_family"].items():
        d, ps, la = blocks["dorian"], blocks["path_scope_watcher"], blocks["line_aware_watcher"]
        fam_rows.append(
            f"| {name} | {d['pairs']} | {ps['fp']} | {la['fp']} | {d['fp']} "
            f"| {d['tp']} | {d['fn']} |"
        )
    fns = m["dorian_error_attribution"]["false_negatives"]
    fps = m["dorian_error_attribution"]["false_positives"]
    fn_set = sorted({x["mutation"] for x in fns})
    fp_set = sorted({x["mutation"] for x in fps})
    fn_muts = ", ".join(f"`{x}`" for x in fn_set) or "none"
    fp_muts = ", ".join(f"`{x}`" for x in fp_set) or "none"

    lines = [
        "# dorian large controlled-mutation benchmark (v0.7.0)",
        "",
        "Numbers only. Labels are **known-truth**: each mutation's stale / not-stale",
        "outcome for a claim is a mechanical consequence of the edit (e.g. changing",
        '`TIMEOUT = 30` to `10` falsifies the claim "the default timeout is 30 seconds").',
        "The expected outcome is fixed by the edit itself, before measurement - no review",
        "step and no opinion enters the labels. Reproduce with",
        "`python -m bench.large_mutation` (or `dorian bench large-mutation`).",
        "",
        "## What this is - and is not",
        "",
        "A reproducible **demonstration on invented, synthetic fixtures** (the fixtures,",
        "mutations, and labels are all authored here). It shows how claim-level",
        "revalidation and file-change watching diverge under known edits - a property of",
        "the mechanism. It is **not** evidence about any real repository and **not** a",
        "universal performance claim. Results are specific to this benchmark. C4",
        "(pytest-subprocess) checkers are excluded for hermeticity; C1, C3, and C5 are",
        "exercised.",
        "",
        "## Composition",
        "",
        f"- {c['domains']} fixture domains ({', '.join(c['domain_names'])}), "
        f"{c['artifacts']} warranted artifacts, {c['claims']} claims.",
        f"- Checker styles exercised: {', '.join(c['checker_styles'])}.",
        f"- {c['pairs']} (artifact, mutation) pairs: {c['true_stale_pairs']} true-stale, "
        f"{c['benign_pairs']} benign ({c['neutral_pairs']} of them neutral / unrelated-file, "
        f"{c['adversarial_pairs']} adversarial).",
        f"- Errored pairs (a checker could not run): {c['errored_pairs']}.",
        "",
        "## Detectors",
        "",
        "- **naive_file_watcher** - alarms if any *warranted source file* in the domain",
        "  changed (the union of every artifact's referenced files; it ignores files no",
        "  artifact references, so it is the crudest watcher over the warranted surface,",
        "  not a literal whole-repo watcher).",
        "- **path_scope_watcher** - alarms if any file this artifact's claims reference",
        "  changed.",
        "- **line_aware_watcher** - alarms only if a changed line range overlaps a claim's",
        "  anchor lines (whole-file/data claims alarm on any change to their file; "
        "add/remove/rename alarm). The strongest strawman; rename-naive on purpose.",
        "- **dorian** - alarms if `revalidate` marks any of the artifact's claims BROKEN.",
        "",
        "## Aggregate results",
        "",
        "| detector | TP | FP | FN | TN | precision (95% CI) | recall (95% CI) | F1 | spec. |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        *sys_rows,
        "",
        f"False-positive reduction (baseline FP / max(1, dorian FP)): "
        f"**{fpr['vs_naive_file_watcher']}x** vs naive "
        f"({fpr['naive_file_watcher_fp']} vs {fpr['dorian_fp']} FP), "
        f"**{fpr['vs_path_scope_watcher']}x** vs path-scope "
        f"({fpr['path_scope_watcher_fp']} vs {fpr['dorian_fp']}), "
        f"**{fpr['vs_line_aware_watcher']}x** vs line-aware "
        f"({fpr['line_aware_watcher_fp']} vs {fpr['dorian_fp']}).",
        "",
        "Confidence intervals are bootstrap (1000 resamples, seed 42) and **in-fixture**:",
        "they describe resampling noise on this battery, not generalization. Read them as",
        "wide.",
        "",
        "All three baselines show recall 1.00 **by construction**: a known-truth label only",
        "fires when a watched file changed, and every file-change watcher alarms on that, so",
        "no baseline can miss a true-stale pair here. The meaningful baseline axis is",
        "therefore precision / specificity, not recall.",
        "",
        "## By domain (dorian)",
        "",
        "| domain | pairs | TP | FP | FN | TN | precision | recall |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        *dom_rows,
        "",
        "## By mutation family (FP by detector; dorian TP/FN for context)",
        "",
        "| family | pairs | path-scope FP | line-aware FP | dorian FP | dorian TP | dorian FN |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *fam_rows,
        "",
        "## Where dorian errs (honest failure modes)",
        "",
        f"- **False negatives** ({len(fns)} pairs across {len(fn_set)} mutations): {fn_muts}.",
        "  The cited path/literal is genuinely removed from its binding but survives verbatim",
        "  elsewhere (a comment, docstring, or unused constant), so a substring scan still",
        "  hits. This weakness is shared by `string:` **and un-anchored `regex:`** checkers -",
        "  here it bites both a `string:/v1/login` and a bare `regex:/v1/login` claim, because",
        "  `re.search` finds the path in the surviving comment. Switching string -> regex does",
        "  **not** fix it; the real fix is a structurally anchored matcher (e.g. one anchored",
        "  to the route-table key position), which this fixture does not author.",
        f"- **False positives** ({len(fps)} pairs across {len(fp_set)} mutations): {fp_muts}.",
        "  Two mechanisms, both observed here: (1) brittle exact-`string:` claims break on any",
        "  reformat (extra spaces, an inserted `: int` type annotation); (2) even the",
        "  shape-tolerant `regex:TIMEOUT\\s*=\\s*30` breaks when a type annotation is inserted",
        "  between the name and `=` (`TIMEOUT: int = 30`), since the colon defeats the",
        "  name-to-operator adjacency. More tolerant or structurally anchored checker authoring",
        "  narrows this; the brittle artifacts show the worst case. (A byte-exact `snapshot:`",
        "  claim would also alarm on any edit to its file; that is a true-stale signal here,",
        "  not one of these false positives.)",
        "",
        "## Reading",
        "",
        "dorian trades some recall for substantially higher precision: it suppresses the",
        "benign-edit false alarms that make file-watching noisy (comments, reformatting,",
        "reordering, renames, unrelated files), at the cost of misses when a claim is bound",
        "by a substring scan (`string:` or un-anchored `regex:`) and the old literal survives",
        "elsewhere. The precision gap holds against the line-aware watcher, not only the naive",
        "one, though on this battery line-aware refines path-scope by only a few pairs (its",
        "line-overlap gate rarely bites), so read the path-scope comparison as the stronger",
        "claim. All figures are specific to this fixture suite.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.large_mutation", description=__doc__)
    ap.add_argument("--workspace", default="bench/workspace/large_mutation")
    ap.add_argument("--out", default=f"bench/results/{BENCHMARK_ID}_summary.json")
    ap.add_argument("--records", default=f"bench/results/{BENCHMARK_ID}_records.jsonl")
    ap.add_argument("--md-out", help="also render the public markdown summary to this path")
    args = ap.parse_args(argv)

    summary, records = run_benchmark(Path(args.workspace))
    # provenance: the measured dorian repo HEAD (bare hex, not a leak; omitted from
    # the deterministic core so run_benchmark() stays byte-identical across runs)
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
        md = Path(args.md_out)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_markdown(summary), encoding="utf-8")

    c = summary["composition"]
    d = summary["systems"]["dorian"]
    fpr = summary["fp_reduction"]
    print(
        f"large-mutation: {c['pairs']} pairs over {c['domains']} domains, "
        f"dorian precision {d['precision']:.2f} recall {d['recall']:.2f}, "
        f"FP reduction {fpr['vs_path_scope_watcher']}x (path-scope) / "
        f"{fpr['vs_line_aware_watcher']}x (line-aware) -> {out}"
    )
    return 0


def _measured_commit() -> str:
    try:
        return _git(_REPO_ROOT, "rev-parse", "HEAD")
    except Exception:
        return "unspecified"


if __name__ == "__main__":
    sys.exit(main())
