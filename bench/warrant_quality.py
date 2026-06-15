"""`dorian bench warrant-quality` — per-claim warrant quality by mutation testing.

Repo-level benchmarks answer "does the mechanism work on this suite?". This answers
the question a USER actually has about THEIR warrant: *for this claim, would the
checker catch the drift it is supposed to?* It is an OFFLINE evidence generator, not
runtime revalidation, and it never mutates the real repo (each mutation runs against a
throwaway copy of only the file the checker reads).

For each claim it derives deterministic mutations from the checker grammar and records,
per mutation, whether the checker's verdict matched the expectation:

- **falsify** — a change that SHOULD make the claim false (rename the symbol, change the
  constant's value, change a parameter). Expect FAIL. A PASS here is a **miss** — the
  checker cannot see the very drift it implies it guards.
- **benign** — a formatting-only change the checker promises to tolerate. Expect PASS. A
  FAIL here is **brittle** — a false alarm.
- **ceiling** — a content change that the checker is KNOWN to be blind to (an existence
  checker cannot see a body/content change). Expect PASS, recorded as the documented
  trigger-vs-truth ceiling, never counted against the claim.

Scope (honest): mutations are generated for the C3 structural/existence forms
(`symbol:`, `py-signature:`, `py-const:`) where a falsifying edit is mechanically
unambiguous. Other forms (`string:`/`regex:`/`code:`, typed C5, C1, C4) are reported
with their checker strength and `mutation: unsupported` — the harness does not fabricate
a mutation it cannot make deterministically. ERROR (e.g. an executable checker blocked by
`--deny-exec`) is its own bucket, never conflated with a miss or a FAIL. Output is
deterministic (no timestamps, no randomness) and stable for golden tests.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

from dorian.checkers.base import CheckContext, Verdict, run_checker
from dorian.model import CheckerSpec, Claim, Warrant
from dorian.policy import ExecutionPolicy, executable_kind
from dorian.strength import claim_strength

SCHEMA = "dorian-warrant-quality-v1"

# (mutation name, expectation) — expectation is the verdict that means "as designed".
_FALSIFY = "falsify"  # expect FAIL (catch the drift)
_BENIGN = "benign"  # expect PASS (tolerate formatting)
_CEILING = "ceiling"  # expect PASS (known-blind; never a penalty)


def _c3_parts(spec: CheckerSpec) -> tuple[str, str, str]:
    """(prefix, file, operand) for a `<prefix>:<file>::<operand>` C3 program."""
    prefix, _, rest = spec.program.partition(":")
    file, _, operand = rest.partition("::")
    return prefix, file, operand


def _mutations(spec: CheckerSpec) -> Iterator[tuple[str, str, str, object]]:
    """Yield (name, file, expectation, mutate) where mutate(text)->text. Empty for
    forms the harness does not deterministically mutate."""
    if spec.type != "C3":
        return
    prefix, file, operand = _c3_parts(spec)
    if not file:
        return
    if prefix == "symbol":
        name = operand
        yield (
            "rename_definition",
            file,
            _FALSIFY,
            lambda t: re.sub(rf"\b(def|class)\s+{re.escape(name)}\b", r"\1 dorian_mut", t),
        )
        # an existence checker is blind to any content change that keeps the name:
        yield ("append_content", file, _CEILING, lambda t: t + "\n# dorian: content drift\n")
    elif prefix == "py-const":
        qual = operand.partition("::")[0]
        if "." in qual:
            return  # dotted (class attr): a top-level reassignment would not shadow it
        yield ("reassign_value", file, _FALSIFY, lambda t: t + f'\n{qual} = "__dorian_mut__"\n')
        yield ("append_comment", file, _BENIGN, lambda t: t + "\n# dorian: benign comment\n")
    elif prefix == "py-signature":
        qual = operand.partition("::")[0]
        if "." in qual:
            return  # dotted (method): a top-level def would not shadow it
        yield (
            "change_param",
            file,
            _FALSIFY,
            lambda t: t + f"\n\ndef {qual}(dorian_mut_param):\n    return None\n",
        )
        yield ("append_comment", file, _BENIGN, lambda t: t + "\n# dorian: benign comment\n")


def _run_mutated(repo: Path, claim: Claim, spec_index: int, file: str, mutate, policy) -> Verdict:
    """Run one checker against a throwaway copy of `file` with `mutate` applied. Only the
    one file the checker reads is materialized — the real repo is never touched, and a
    warrant-controlled `file` operand that escapes the repo (e.g. `../`) is refused so the
    harness cannot read or write outside its sandbox (the checker would ERROR on it anyway)."""
    repo = repo.resolve()
    src = (repo / file).resolve()
    if not src.is_relative_to(repo) or not src.is_file():
        return Verdict.ERROR  # path escape or missing: do not read/write outside the repo
    original = src.read_text(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory() as td:
        work = Path(td).resolve()
        target = (work / file).resolve()
        if not target.is_relative_to(work):
            return Verdict.ERROR  # write would escape the temp sandbox
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(mutate(original), encoding="utf-8")
        ctx = CheckContext(repo=work, claim=claim, policy=policy)
        return run_checker(ctx, spec_index).verdict


def _score_mutation(verdict: Verdict, expectation: str) -> str:
    """Classify a mutation outcome. ERROR is always its own bucket."""
    if verdict is Verdict.ERROR:
        return "errored"
    if expectation == _FALSIFY:
        return "caught" if verdict is Verdict.FAIL else "missed"
    if expectation == _BENIGN:
        return "brittle" if verdict is Verdict.FAIL else "ok"
    return "ceiling" if verdict is Verdict.PASS else "ceiling_caught"  # _CEILING


def score_claim(repo: Path, claim: Claim, policy: ExecutionPolicy) -> dict:
    """Per-claim quality record: strength, trigger watch, and mutation outcomes."""
    strongest = claim_strength(claim)  # rank-aware (existence < ... < behavioral)
    mutations: list[dict] = []
    for i, spec in enumerate(claim.checkers):
        any_mutation = False
        for name, file, expectation, mutate in _mutations(spec):
            any_mutation = True
            verdict = _run_mutated(repo, claim, i, file, mutate, policy)
            mutations.append(
                {
                    "checker": spec.type,
                    "program": spec.program,
                    "mutation": name,
                    "expectation": expectation,
                    "verdict": verdict.value,
                    "outcome": _score_mutation(verdict, expectation),
                }
            )
        if not any_mutation:
            mutations.append(
                {
                    "checker": spec.type,
                    "program": spec.program,
                    "mutation": "unsupported",
                    "expectation": "n/a",
                    "verdict": "n/a",
                    "outcome": "unsupported",
                    "executes": executable_kind(spec),
                }
            )
    outcomes = [m["outcome"] for m in mutations]
    quality = (
        "weak"
        if "missed" in outcomes
        else "brittle"
        if "brittle" in outcomes
        else "strong"
        if "caught" in outcomes
        else "unscored"
    )
    return {
        "claim_id": claim.id,
        "kind": claim.kind,
        "load_bearing": claim.load_bearing,
        "strongest_strength": strongest,
        "watch": sorted({w for s in claim.checkers for w in s.watch}),
        "mutations": mutations,
        "quality": quality,
    }


def summarize(records: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in records:
        counts[r["quality"]] = counts.get(r["quality"], 0) + 1
    mut: dict[str, int] = {}
    for r in records:
        for m in r["mutations"]:
            mut[m["outcome"]] = mut.get(m["outcome"], 0) + 1
    return {
        "claims": len(records),
        "by_quality": dict(sorted(counts.items())),
        "by_outcome": dict(sorted(mut.items())),
    }


def render(report: dict) -> str:
    lines = [f"# warrant quality: {report['artifact_uri']}", ""]
    for r in report["claims"]:
        lines.append(f"- `{r['claim_id']}` [{r['quality']}] strongest={r['strongest_strength']}")
        for m in r["mutations"]:
            lines.append(f"    {m['mutation']}: {m['outcome']} ({m['verdict']})")
    s = report["summary"]
    lines += ["", f"{s['claims']} claim(s): {s['by_quality']}", f"mutations: {s['by_outcome']}"]
    return "\n".join(lines) + "\n"


def build(repo: Path, artifact_uri: str, policy: ExecutionPolicy) -> dict:
    warrant = Warrant.load(repo / (artifact_uri + ".warrant"))
    records = [score_claim(repo, c, policy) for c in warrant.claims]
    return {
        "schema": SCHEMA,
        "artifact_uri": artifact_uri,
        "claims": records,
        "summary": summarize(records),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="dorian bench warrant-quality")
    ap.add_argument("artifact", help="warranted artifact (its .warrant is scored)")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--deny-exec", action="store_true")
    ap.add_argument("--deny-shell", action="store_true")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    artifact_uri = Path(args.artifact).as_posix()
    sidecar = repo / (artifact_uri + ".warrant")
    if not sidecar.is_file():
        print(f"dorian bench warrant-quality: no warrant for {artifact_uri}", file=sys.stderr)
        return 2
    policy = ExecutionPolicy.from_flags_and_env(
        deny_exec=args.deny_exec, deny_shell=args.deny_shell
    )
    report = build(repo, artifact_uri, policy)
    print(json.dumps(report, sort_keys=True, indent=2) if args.json else render(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
