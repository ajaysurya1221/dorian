"""The opt-in truth-axis strength gate: `--strength-gate off|warn|fail`.

The companion to `--binding-gate`. Binding is the TRIGGER axis (WHEN a claim
re-checks); strength is the TRUTH axis (WHETHER the checker can FALSIFY the claim).
`strength.py` already computes `adequacy_mismatch`/`claim_risk` but only PRINTS it
(advisory); this gate lets a LOAD-BEARING claim whose checker is too weak for its
kind refuse the seal (fail) or be surfaced (warn).

Invariants the matrix guards (mirrors test_binding_gate.py):
- default (and explicit off) preserve today's behavior exactly and stay silent;
- warn seals + prints deterministic adequacy diagnostics, exit 0;
- fail refuses a load-bearing high-risk claim BEFORE any sidecar/store write
  (atomic no-write), exit 4 — only load-bearing high-risk: a `behavior` claim
  backed by structural/behavioral evidence, a `fact` claim backed by existence,
  and any non-load-bearing claim all seal under fail;
- the gate never masks a false claim (a failing checker still wins at step 2);
- the gate never marks a claim BROKEN/false and never touches trust/claim state;
- the truth lattice is monotonic: an opaque shell-only behavior claim (rank below
  existence) is at least as blocking as an existence-only one (no inversion);
- strength stays OUT of the trust-state fold path (fold.py / revalidate.py);
- `seal` is symmetric with `verify`.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from dorian import cli, commands, gitio, strength
from dorian.capture.manual import parse_manual
from dorian.model import CheckerSpec, Claim

ART = "docs/design.md"
WARRANT = "docs/design.md.warrant"


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def _claim(cid: str, kind: str, load_bearing: bool, program: str, ptype: str = "C3") -> Claim:
    return Claim(
        id=cid,
        text=f"{cid} claim text",
        kind=kind,
        load_bearing=load_bearing,
        checkers=(CheckerSpec(type=ptype, program=program),),
    )


def _unbacked(cid: str, kind: str, load_bearing: bool) -> Claim:
    return Claim(id=cid, text=f"{cid} claim text", kind=kind, load_bearing=load_bearing)


# --- claims.json bodies for end-to-end (every checker is GREEN on the fixture) -------

# load-bearing behavior claim backed only by an existence checker -> high-risk mismatch
BEHAVIOR_EXISTENCE = json.dumps(
    {
        "claims": [
            {
                "id": "beh",
                "text": "login rejects expired tokens.",
                "kind": "behavior",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "symbol:src/auth.py::verify_token"}],
            }
        ]
    }
)

# load-bearing behavior claim backed by a STRUCTURAL checker -> adequate, never blocks
BEHAVIOR_STRUCTURAL = json.dumps(
    {
        "claims": [
            {
                "id": "sig",
                "text": "verify_token takes a token.",
                "kind": "behavior",
                "load_bearing": True,
                "checkers": [
                    {"type": "C3", "program": "py-signature:src/auth.py::verify_token::token"}
                ],
            }
        ]
    }
)

# load-bearing FACT claim backed by existence -> existence IS adequate for a fact
FACT_EXISTENCE = json.dumps(
    {
        "claims": [
            {
                "id": "fct",
                "text": "verify_token is defined.",
                "kind": "fact",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "symbol:src/auth.py::verify_token"}],
            }
        ]
    }
)

# a load-bearing UNBACKED claim -> high-risk (the weakest possible truth backing)
UNBACKED = json.dumps(
    {
        "claims": [
            {
                "id": "aspirational",
                "text": "The system is robust.",
                "kind": "decision",
                "load_bearing": True,
            }
        ]
    }
)

# a claim whose checker is FALSE right now -> must be refused at step 2, not by the gate
FALSE_BEHAVIOR = json.dumps(
    {
        "claims": [
            {
                "id": "bad",
                "text": "a symbol that does not exist.",
                "kind": "behavior",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "symbol:src/auth.py::does_not_exist"}],
            }
        ]
    }
)


def _verify(repo: Path, claims_json: str, *flags: str) -> int:
    claims_path = repo / "claims.json"
    claims_path.write_text(claims_json)
    return commands.cmd_verify(
        _ns("--repo", str(repo), "verify", ART, "--claims", str(claims_path), *flags)
    )


def _seal(repo: Path, claims_json: str, *flags: str) -> int:
    rs = parse_manual(["src/auth.py", "src/config.py"], repo)
    rs_path = repo / "rs.json"
    rs.dump(rs_path)
    claims_path = repo / "claims.json"
    claims_path.write_text(claims_json)
    return commands.cmd_seal(
        _ns(
            "--repo",
            str(repo),
            "seal",
            ART,
            "--readset",
            str(rs_path),
            "--claims",
            str(claims_path),
            *flags,
        )
    )


# --- correctness precondition: fix the shell-only-behavior adequacy inversion --------


def test_behavior_backed_only_by_shell_is_a_mismatch(fixture_repo: Path) -> None:
    """An opaque C5 shell: checker (rank below existence) cannot prove behavior, so a
    behavior claim backed only by it MUST trip the adequacy lint — else the weakest
    backing silently passes while a stronger existence backing fails (an inversion)."""
    sh = _claim("sh", "behavior", True, "shell:run-it", ptype="C5")
    assert strength.adequacy_notes(fixture_repo, sh)  # not silently adequate


def test_shell_only_behavior_is_at_least_as_blocking_as_existence(fixture_repo: Path) -> None:
    diags = strength.analyze(
        fixture_repo, [_claim("sh", "behavior", True, "shell:run-it", ptype="C5")]
    )
    assert [d["claim_id"] for d in strength.gate_blocking(diags)] == ["sh"]


def test_quantity_backed_only_by_shell_is_a_mismatch(fixture_repo: Path) -> None:
    diags = strength.analyze(
        fixture_repo, [_claim("q", "quantity", True, "shell:run-it", ptype="C5")]
    )
    assert [d["claim_id"] for d in strength.gate_blocking(diags)] == ["q"]


# --- unit: gate_blocking is the truth-axis filter (load-bearing high-risk) -----------


def test_gate_blocking_behavior_backed_only_by_existence(fixture_repo: Path) -> None:
    diags = strength.analyze(
        fixture_repo, [_claim("beh", "behavior", True, "symbol:src/auth.py::verify_token")]
    )
    assert [d["claim_id"] for d in strength.gate_blocking(diags)] == ["beh"]


def test_gate_blocking_behavior_backed_by_structural_is_allowed(fixture_repo: Path) -> None:
    diags = strength.analyze(
        fixture_repo,
        [_claim("sig", "behavior", True, "py-signature:src/auth.py::verify_token::token")],
    )
    assert strength.gate_blocking(diags) == []


def test_gate_blocking_behavior_backed_by_behavioral_is_allowed(fixture_repo: Path) -> None:
    diags = strength.analyze(
        fixture_repo, [_claim("c4", "behavior", True, "pytest:tests/test_x.py::test_x", ptype="C4")]
    )
    assert strength.gate_blocking(diags) == []


def test_gate_blocking_non_load_bearing_is_allowed(fixture_repo: Path) -> None:
    diags = strength.analyze(
        fixture_repo, [_claim("soft", "behavior", False, "symbol:src/auth.py::verify_token")]
    )
    assert strength.gate_blocking(diags) == []


def test_gate_blocking_fact_backed_by_existence_is_allowed(fixture_repo: Path) -> None:
    diags = strength.analyze(
        fixture_repo, [_claim("fct", "fact", True, "symbol:src/auth.py::verify_token")]
    )
    assert strength.gate_blocking(diags) == []


def test_gate_blocking_quantity_backed_only_by_existence(fixture_repo: Path) -> None:
    diags = strength.analyze(fixture_repo, [_claim("qty", "quantity", True, "path:src/config.py")])
    assert [d["claim_id"] for d in strength.gate_blocking(diags)] == ["qty"]


def test_gate_blocking_unbacked_load_bearing(fixture_repo: Path) -> None:
    diags = strength.analyze(fixture_repo, [_unbacked("u", "decision", True)])
    assert [d["claim_id"] for d in strength.gate_blocking(diags)] == ["u"]


def test_gate_blocking_behavior_semantic_text_is_only_medium(fixture_repo: Path) -> None:
    """code: (semantic_text) on a behavior claim notes a mismatch but scores MEDIUM,
    not high -> warn surfaces it, fail does not refuse (conservative)."""
    diags = strength.analyze(
        fixture_repo, [_claim("sem", "behavior", True, "code:src/auth.py::RS256")]
    )
    assert strength.gate_blocking(diags) == []


def test_gate_blocking_behavior_raw_text_blocks(fixture_repo: Path) -> None:
    diags = strength.analyze(
        fixture_repo, [_claim("rgx", "behavior", True, "regex:src/auth.py::RS256")]
    )
    assert [d["claim_id"] for d in strength.gate_blocking(diags)] == ["rgx"]


# --- default / off: behavior preserved, no gate output ------------------------------


def test_verify_default_off_seals_and_is_silent(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, BEHAVIOR_EXISTENCE)  # no flag == off
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()
    assert "strength-gate" not in capsys.readouterr().err


def test_verify_explicit_off_with_high_risk_still_seals(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, BEHAVIOR_EXISTENCE, "--strength-gate", "off")
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()
    assert "strength-gate" not in capsys.readouterr().err


# --- warn: seals, reports the truth-axis mismatch, exit 0 ---------------------------


def test_verify_warn_seals_and_reports_mismatch(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, BEHAVIOR_EXISTENCE, "--strength-gate", "warn")
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()
    err = capsys.readouterr().err
    assert "adequacy_mismatch" in err
    assert "beh" in err
    assert "--strength-gate=warn" in err


# --- fail: refuses a load-bearing high-risk claim, atomic no-write, exit 4 -----------


def test_verify_fail_refuses_behavior_existence_no_sidecar(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, BEHAVIOR_EXISTENCE, "--strength-gate", "fail")
    assert rc == 4
    assert not (fixture_repo / WARRANT).exists()  # atomic no-write
    err = capsys.readouterr().err
    assert "strength-gate" in err
    assert "'beh'" in err


def test_verify_fail_writes_no_store_row(fixture_repo: Path, capsys) -> None:
    assert _verify(fixture_repo, BEHAVIOR_EXISTENCE, "--strength-gate", "fail") == 4
    capsys.readouterr()
    assert commands.cmd_status(_ns("--repo", str(fixture_repo), "status", ART)) == 0
    assert ART not in capsys.readouterr().out  # nothing sealed or indexed


def test_verify_fail_refuses_unbacked(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, UNBACKED, "--strength-gate", "fail")
    assert rc == 4
    assert not (fixture_repo / WARRANT).exists()


def test_verify_fail_allows_structural_behavior(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, BEHAVIOR_STRUCTURAL, "--strength-gate", "fail")
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()


def test_verify_fail_allows_fact_existence(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, FACT_EXISTENCE, "--strength-gate", "fail")
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()


# --- the gate never masks a false claim ---------------------------------------------


def test_gate_does_not_mask_a_false_claim(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, FALSE_BEHAVIOR, "--strength-gate", "warn")
    assert rc == 4  # the failing checker wins at step 2, before the gate
    assert not (fixture_repo / WARRANT).exists()
    err = capsys.readouterr().err
    assert "FAILED_AT_SEAL" in err


# --- seal is symmetric with verify --------------------------------------------------


def test_seal_fail_refuses_behavior_existence_no_sidecar(fixture_repo: Path, capsys) -> None:
    rc = _seal(fixture_repo, BEHAVIOR_EXISTENCE, "--strength-gate", "fail")
    assert rc == 4
    assert not (fixture_repo / WARRANT).exists()
    assert "strength-gate" in capsys.readouterr().err


def test_seal_warn_seals_and_reports(fixture_repo: Path, capsys) -> None:
    rc = _seal(fixture_repo, BEHAVIOR_EXISTENCE, "--strength-gate", "warn")
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()
    assert "adequacy_mismatch" in capsys.readouterr().err


def test_strength_gate_warning_readback_failure_is_warn_only(
    fixture_repo: Path, capsys, monkeypatch
) -> None:
    def fail_readback(*a, **k):
        raise gitio.GitError("index unavailable")

    monkeypatch.setattr(commands.Warrant, "load", staticmethod(fail_readback))
    commands._emit_strength_gate_warnings("dorian verify", fixture_repo, ART, "warn")
    assert (
        "dorian verify: warning: --strength-gate=warn diagnostics could not be read back; "
        "seal remains valid"
    ) in capsys.readouterr().err


# --- honesty contract: strength stays out of the trust-state fold path ---------------


def test_strength_not_imported_by_fold_or_revalidate() -> None:
    """The advisory-only boundary: the NEW opt-in gate (seal.py) is the only place
    strength touches a verdict. The trust-state fold path must never import it."""
    src = Path(__file__).resolve().parents[1] / "src" / "dorian"
    for mod in ("fold.py", "revalidate.py"):
        tree = ast.parse((src / mod).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                for a in node.names:
                    imported.add(f"{node.module}.{a.name}")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    imported.add(a.name)
        assert not any("strength" in m for m in imported), f"{mod} imports strength"
