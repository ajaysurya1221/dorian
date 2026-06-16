"""`public_claims.py` — deterministic machine-derived claim synthesizer.

Removes ad-hoc human claim authoring from the public benchmark. Given a checkout
at a frozen SHA and a small per-repo *targets* spec (file + symbol/key + a
mechanical source edit), it:

1. EXTRACTS the structural fact from source (stdlib `ast` for Python, `tomllib`/
   `json` for config) — the claim operand is machine-derived, never human prose.
2. VERIFIES the claim PASSes at the clean SHA by running the real C3 checker
   (`dorian.checkers.c3_ref`) — true-by-construction.
3. APPLIES the target's mechanical mutation to a one-file temp copy and RUNS the
   checker again, DERIVING `known_truth` from the OBSERVED verdict
   (FAIL → BROKEN, PASS → TRUSTED). This is Chain-of-Verification: the truth label
   is machine-observed, not a human assertion.
4. AUTO-REJECTS any target whose clean claim ERRORs/doesn't PASS, or whose mutation
   does not produce the declared intent (a `py-const` over a comprehension/`Union`
   subscript is rejected here, exactly as the drafts warned).
5. EMITS a proof object per claim and, only if EVERY target validates, promotes a
   `benchmark-ready` `claims.json` + `mutations.yaml` the harness can run.

Allowed origins (no semantic/natural-language claims are possible from this code):
    generated-py-signature | generated-py-const-literal |
    generated-config-value | generated-code-literal

CHECKOUT-ONLY dev tooling: lives in bench/ (not shipped), uses only the stdlib +
the zero-dep dorian core. No network, no model, no execution of subject code.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dorian.checkers import c3_ref
from dorian.checkers.base import CheckContext, Verdict
from dorian.model import CheckerSpec, Claim

EXTRACTOR = "public_claims@1"

_ORIGIN = {
    "py-signature": "generated-py-signature",
    "py-const": "generated-py-const-literal",
    "config-value": "generated-config-value",
    "code": "generated-code-literal",
}
_KIND = {
    "py-signature": "behavior",
    "py-const": "quantity",
    "config-value": "fact",
    "code": "fact",
}
_KNOWN_TRUTH_RULE = {
    "py-signature": "py-signature FAILs iff the def parameter list (names/order/kind) "
    "changes; a comment/body-only edit leaves it PASS. Label = observed verdict.",
    "py-const": "py-const compares the assignment literal by value AND type; any literal "
    "change FAILs. Non-literal RHS ERRORs and is rejected. Label = observed verdict.",
    "config-value": "config-value compares the value at the dotted key by value AND type; "
    "any change FAILs. Label = observed verdict.",
    "code": "code: matches an exact token in comment/docstring-stripped source; removing/"
    "altering it FAILs, a comment-only edit leaves it PASS. Label = observed verdict.",
}
_INTENT_VERDICT = {"break": Verdict.FAIL, "control": Verdict.PASS}
_INTENT_TRUTH = {"break": "BROKEN", "control": "TRUSTED"}


class RejectedTarget(ValueError):
    """A target cannot become a machine-derived benchmark-ready claim (recorded, not fatal)."""


@dataclass(frozen=True)
class Generated:
    claim: dict
    mutation: dict
    proof: dict


# ----------------------------------------------------------------- extraction


def _find_func(tree: ast.AST, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    parts = qualname.split(".")
    scope: list[ast.stmt] = list(getattr(tree, "body", []))
    node = None
    for i, part in enumerate(parts):
        node = None
        for stmt in scope:
            if isinstance(stmt, ast.ClassDef) and stmt.name == part and i < len(parts) - 1:
                node = stmt
                scope = stmt.body
                break
            if (
                isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef)
                and stmt.name == part
                and i == len(parts) - 1
            ):
                node = stmt
                break
        if node is None:
            raise RejectedTarget(f"function {qualname!r} not found")
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        raise RejectedTarget(f"{qualname!r} is not a function/method")
    return node


def names_sigspec(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render a names-only signature spec (`a, b, *args, c, **kw`) — exactly the kinds
    the C3 py-signature checker compares (names/order/kind), no annotations/defaults."""
    a = fn.args
    parts: list[str] = [p.arg for p in a.posonlyargs]
    if a.posonlyargs:
        parts.append("/")
    parts += [p.arg for p in a.args]
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    parts += [p.arg for p in a.kwonlyargs]
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    return ", ".join(parts)


def _find_assign_value(tree: ast.AST, qualname: str) -> ast.expr:
    parts = qualname.split(".")
    scope: list[ast.stmt] = list(getattr(tree, "body", []))
    for part in parts[:-1]:
        nxt = None
        for stmt in scope:
            if isinstance(stmt, ast.ClassDef) and stmt.name == part:
                nxt = stmt.body
                break
        if nxt is None:
            raise RejectedTarget(f"class {part!r} not found for {qualname!r}")
        scope = nxt
    name = parts[-1]
    for stmt in scope:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in stmt.targets
        ):
            return stmt.value
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == name
            and stmt.value is not None
        ):
            return stmt.value
    raise RejectedTarget(f"assignment {qualname!r} not found")


def extract_operand(checkout: Path, target: dict) -> tuple[str, str]:
    """Return (checker_operand, expected_value) extracted deterministically from source.
    Raises RejectedTarget if the fact is not a clean machine-derivable structural fact."""
    kind = target["kind"]
    rel = target["file"]
    src_path = checkout / rel
    if not src_path.is_file():
        raise RejectedTarget(f"source file {rel!r} missing")

    if kind == "py-signature":
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        sig = names_sigspec(_find_func(tree, target["name"]))
        return f"py-signature:{rel}::{target['name']}::{sig}", sig

    if kind == "py-const":
        text = src_path.read_text(encoding="utf-8")
        value_node = _find_assign_value(ast.parse(text), target["name"])
        segment = ast.get_source_segment(text, value_node)
        if segment is None:
            raise RejectedTarget("could not recover RHS source segment")
        try:
            ast.literal_eval(segment)  # reject comprehensions / Union[...] / calls
        except (ValueError, SyntaxError) as exc:
            raise RejectedTarget(f"RHS is not a literal ({exc}); not py-const eligible") from None
        return f"py-const:{rel}::{target['name']}::{segment}", segment

    if kind == "config-value":
        key = target["key"]
        value = _config_value(src_path, key)
        try:
            literal = json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise RejectedTarget(f"config value not JSON-renderable ({exc})") from None
        return f"config-value:{rel}:{key}:{literal}", literal

    if kind == "code":
        token = target["token"]
        operand = re.escape(token)
        return f"code:{rel}::{operand}", token

    raise RejectedTarget(f"unknown target kind {kind!r}")


def _config_value(path: Path, dotted: str):
    if path.suffix == ".toml":
        import tomllib

        data = tomllib.loads(path.read_text(encoding="utf-8"))
    elif path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise RejectedTarget(f"config-value supports .toml/.json only, got {path.suffix!r}")
    cur = data
    for seg in dotted.split("."):
        if not isinstance(cur, dict) or seg not in cur:
            raise RejectedTarget(f"config key {dotted!r} not found")
        cur = cur[seg]
    return cur


# ----------------------------------------------------- checker invocation (no exec)


def _run_checker(file_rel: str, file_text: str, operand: str) -> Verdict:
    """Run the C3 checker against a ONE-FILE temp repo (read-only AST/config parse;
    never executes subject code). Returns the verdict only."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        dest = repo / file_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(file_text, encoding="utf-8")
        spec = CheckerSpec(type="C3", program=operand)
        claim = Claim(id="g", text="x", kind="fact", load_bearing=True, checkers=(spec,))
        return c3_ref.check(CheckContext(repo=repo, claim=claim), spec).verdict


def _apply_once(text: str, frm: str, to: str) -> str:
    n = text.count(frm)
    if n != 1:
        raise RejectedTarget(f"mutation 'from' occurs {n}x (need exactly 1)")
    return text.replace(frm, to, 1)


# ------------------------------------------------------------------ synthesis


def synthesize(
    checkout: Path, targets: list[dict], *, artifact: str
) -> tuple[dict, dict, list[dict]]:
    """Return (claims_doc, mutations_doc, rejected). claims_doc/mutations_doc are
    benchmark-ready ONLY if `rejected` is empty (all targets validated)."""
    claims: list[dict] = []
    muts: list[dict] = []
    rejected: list[dict] = []

    for t in targets:
        try:
            gen = _synthesize_one(checkout, t)
        except RejectedTarget as exc:
            rejected.append({"id": t.get("id"), "kind": t.get("kind"), "reason": str(exc)})
            continue
        claims.append(gen.claim)
        muts.append(gen.mutation)

    status = "benchmark-ready" if claims and not rejected else "draft-incomplete"
    claims_doc = {
        "schema_version": 1,
        "status": status,
        "artifact": artifact,
        "extractor": EXTRACTOR,
        "_provenance": "machine-derived by bench/public_claims.py; claim operands extracted "
        "from source, known_truth observed by running the C3 checker on the mutated copy.",
        "claims": claims,
    }
    mutations_doc = {"schema_version": 1, "status": status, "mutations": muts}
    return claims_doc, mutations_doc, rejected


def _synthesize_one(checkout: Path, t: dict) -> Generated:
    kind = t["kind"]
    if kind not in _ORIGIN:
        raise RejectedTarget(f"unsupported kind {kind!r}")
    rel = t["file"]
    intent = t.get("intent", "break")
    if intent not in _INTENT_VERDICT:
        raise RejectedTarget(f"unknown intent {intent!r}")

    operand, expected = extract_operand(checkout, t)
    file_text = (checkout / rel).read_text(encoding="utf-8")

    # (1) clean must PASS — claim is true-by-construction at the frozen SHA
    if _run_checker(rel, file_text, operand) is not Verdict.PASS:
        raise RejectedTarget("claim does not PASS at the clean SHA")

    # (2) mutated verdict must match the declared intent; known_truth = observed
    mut = t["mutation"]
    mutated_text = _apply_once(file_text, mut["from"], mut["to"])
    observed = _run_checker(rel, mutated_text, operand)
    if observed is not _INTENT_VERDICT[intent]:
        raise RejectedTarget(
            f"intent={intent} expected {_INTENT_VERDICT[intent].name} but observed "
            f"{observed.name} on the mutated copy"
        )
    known_truth = _INTENT_TRUTH[intent]

    claim_id = t["id"]
    claim = {
        "id": claim_id,
        "text": _claim_text(kind, t, expected),
        "kind": _KIND[kind],
        "load_bearing": True,
        "anchor": None,
        "supports": [],
        "checkers": [{"type": "C3", "program": operand}],
        "proof": {
            "claim_id": claim_id,
            "origin": _ORIGIN[kind],
            "extractor": EXTRACTOR,
            "source_file": rel,
            "source_locator": t.get("name") or t.get("key") or t.get("token"),
            "checker_operand": operand,
            "expected_value": expected,
            "mutation_id": mut["id"],
            "known_truth_rule": _KNOWN_TRUTH_RULE[kind],
            "known_truth_observed": known_truth,
            "deterministic": True,
        },
    }
    mutation = {
        "id": mut["id"],
        "claim_id": claim_id,
        "file": rel,
        "op": "replace",
        "from": mut["from"],
        "to": mut["to"],
        "known_truth": known_truth,
        "rationale": f"machine-derived: {_KNOWN_TRUTH_RULE[kind]} Observed "
        f"{observed.name} on the mutated copy at the frozen SHA.",
    }
    return Generated(claim=claim, mutation=mutation, proof=claim["proof"])


def _claim_text(kind: str, t: dict, expected: str) -> str:
    rel = t["file"]
    if kind == "py-signature":
        return f"In {rel}, {t['name']} has parameter list ({expected})."
    if kind == "py-const":
        return f"In {rel}, the module/class constant {t['name']} has the literal value {expected}."
    if kind == "config-value":
        return f"In {rel}, the config value at {t['key']} equals {expected} (by value and type)."
    return f"In {rel}, the executable source contains the token {expected!r}."


# ----------------------------------------------------------------------- output


def write_generated(repo_dir: Path, claims_doc: dict, mutations_doc: dict, rejected: list[dict]):
    """Write the audit trail (claims.generated.json + rejected.json) always, and the
    harness-consumed claims.json + mutations.yaml only when benchmark-ready."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "claims.generated.json").write_text(
        json.dumps(claims_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (repo_dir / "rejected.json").write_text(
        json.dumps(rejected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    promoted = claims_doc["status"] == "benchmark-ready"
    if promoted:
        (repo_dir / "claims.json").write_text(
            json.dumps(claims_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (repo_dir / "mutations.yaml").write_text(_mutations_yaml(mutations_doc), encoding="utf-8")
    return promoted


def _mutations_yaml(doc: dict) -> str:
    """Deterministic YAML emit (stdlib only — no pyyaml dependency at write time).
    Block scalars are quoted via JSON so any character is safe to round-trip."""
    lines = [
        "# MACHINE-GENERATED by bench/public_claims.py — do not hand-edit.",
        "# known_truth is the verdict OBSERVED by running the C3 checker on the mutated copy.",
        f"schema_version: {doc['schema_version']}",
        f"status: {doc['status']}",
        "mutations:",
    ]
    for m in doc["mutations"]:
        lines.append(f"- id: {json.dumps(m['id'])}")
        lines.append(f"  claim_id: {json.dumps(m['claim_id'])}")
        lines.append(f"  file: {json.dumps(m['file'])}")
        lines.append(f"  op: {json.dumps(m['op'])}")
        lines.append(f"  from: {json.dumps(m['from'])}")
        lines.append(f"  to: {json.dumps(m['to'])}")
        lines.append(f"  known_truth: {json.dumps(m['known_truth'])}")
        lines.append(f"  rationale: {json.dumps(m['rationale'])}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- CLI


def load_targets(path: Path) -> tuple[list[dict], str]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("targets"), list):
        raise ValueError(f"{path}: targets file must be an object with a 'targets' list")
    return doc["targets"], doc.get("artifact", "change-note.md")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="public_claims", description=__doc__)
    ap.add_argument("--targets", required=True, help="per-repo targets.json")
    ap.add_argument("--checkout", required=True, help="frozen-SHA checkout to extract from")
    ap.add_argument("--out-dir", required=True, help="bench/public/repos/<repo> output dir")
    ap.add_argument("--json", action="store_true", help="print a machine-readable summary")
    args = ap.parse_args(argv)

    targets, artifact = load_targets(Path(args.targets))
    claims_doc, mutations_doc, rejected = synthesize(
        Path(args.checkout), targets, artifact=artifact
    )
    promoted = write_generated(Path(args.out_dir), claims_doc, mutations_doc, rejected)
    summary = {
        "out_dir": args.out_dir,
        "status": claims_doc["status"],
        "promoted": promoted,
        "claims": len(claims_doc["claims"]),
        "rejected": rejected,
        "known_truth": {m["claim_id"]: m["known_truth"] for m in mutations_doc["mutations"]},
    }
    if args.json:
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            f"{args.out_dir}: status={summary['status']} promoted={promoted} "
            f"claims={summary['claims']} rejected={len(rejected)}\n"
        )
        for cid, kt in summary["known_truth"].items():
            sys.stdout.write(f"  {cid}: {kt}\n")
        for r in rejected:
            sys.stdout.write(f"  REJECTED {r['id']}: {r['reason']}\n")
    return 0 if promoted else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
