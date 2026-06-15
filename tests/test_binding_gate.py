"""The opt-in weak-binding gate: `--binding-gate off|warn|fail`.

A trust-semantics slice, so the matrix guards the invariants, not just the happy path:
- default (and explicit off) preserve today's behavior exactly and stay silent;
- warn seals + prints deterministic diagnostics, exit 0;
- fail refuses a HIGH-RISK weak binding BEFORE any sidecar/store write (atomic
  no-write), exit 4 — but never on 'single-file' alone, the expected shape of an
  honest one-checker C3 claim (the launch-train warrant has five);
- the gate never masks a false claim (a failing checker still wins at step 2);
- the in-memory candidate analyzer matches the file-backed `dorian bindings`;
- `seal` is symmetric with `verify`.
The gate never marks a claim BROKEN/false and never touches trust/claim state.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import commit_all, write
from dorian import bindings, cli, commands, gitio
from dorian.capture.manual import parse_manual
from dorian.model import CheckerSpec, Claim
from dorian.seal import seal_artifact

ART = "docs/design.md"
WARRANT = "docs/design.md.warrant"


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


# a green, one-checker C3 claim -> 'single-file' only (warn-only, never blocks fail)
SINGLE_FILE_CLAIMS = json.dumps(
    {
        "claims": [
            {
                "id": "vt",
                "text": "verify_token is defined.",
                "kind": "behavior",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "symbol:src/auth.py::verify_token"}],
            }
        ]
    }
)

# the green claim plus a load-bearing UNBACKED claim -> high-risk, blocks fail
UNBACKED_CLAIMS = json.dumps(
    {
        "claims": [
            {
                "id": "vt",
                "text": "verify_token is defined.",
                "kind": "behavior",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "symbol:src/auth.py::verify_token"}],
            },
            {
                "id": "aspirational",
                "text": "The system is robust.",
                "kind": "decision",
                "load_bearing": True,
            },
        ]
    }
)

# a claim whose checker is FALSE right now -> must be refused at step 2, not by the gate
FALSE_CLAIMS = json.dumps(
    {
        "claims": [
            {
                "id": "bad",
                "text": "a symbol that does not exist.",
                "kind": "fact",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "symbol:src/auth.py::does_not_exist"}],
            }
        ]
    }
)


def _verify(repo: Path, claims_json: str, *flags: str) -> int:
    # cmd_* resolve --claims relative to CWD, the artifact relative to --repo: pass abs
    claims_path = repo / "claims.json"
    claims_path.write_text(claims_json)
    return commands.cmd_verify(
        _ns("--repo", str(repo), "verify", ART, "--claims", str(claims_path), *flags)
    )


def _seal(repo: Path, claims_json: str, *flags: str) -> int:
    rs = parse_manual(["src/auth.py"], repo)
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


# --- refactor: in-memory candidate analyzer == file-backed analyze ------------------


def test_analyze_candidate_matches_file_backed(fixture_repo: Path) -> None:
    w = seal_artifact(
        fixture_repo,
        ART,
        parse_manual(["src/auth.py"], fixture_repo),
        [
            Claim(
                id="vt",
                text="verify_token is defined.",
                kind="behavior",
                load_bearing=True,
                checkers=(CheckerSpec(type="C3", program="symbol:src/auth.py::verify_token"),),
            )
        ],
    )
    file_backed = bindings.analyze(fixture_repo, ART)
    candidate = bindings.analyze_candidate(
        fixture_repo,
        artifact_uri=ART,
        claims=list(w.claims),
        entry_uris={e.id: e.uri for e in w.read_set},
    )
    assert candidate == file_backed
    assert file_backed[0]["flags"] == ["single-file"]


def _seal_verify_token_claim(fixture_repo: Path) -> dict:
    seal_artifact(
        fixture_repo,
        ART,
        parse_manual(["src/auth.py"], fixture_repo),
        [
            Claim(
                id="vt",
                text="verify_token is defined.",
                kind="behavior",
                load_bearing=True,
                checkers=(CheckerSpec(type="C3", program="symbol:src/auth.py::verify_token"),),
            )
        ],
    )
    (diag,) = bindings.analyze(fixture_repo, ART)
    return diag


def test_claim_input_sibling_claims_json_is_not_unwatched_evidence(
    fixture_repo: Path,
) -> None:
    write(fixture_repo, "docs/claims.json", '{"text": "verify_token"}\n')
    commit_all(fixture_repo, "add sibling claims input")

    diag = _seal_verify_token_claim(fixture_repo)

    assert "unwatched-mention" not in diag["flags"]
    assert diag["mentions"] == []


def test_claim_input_stem_claims_json_is_not_unwatched_evidence(fixture_repo: Path) -> None:
    write(fixture_repo, "docs/design.claims.json", '{"text": "verify_token"}\n')
    commit_all(fixture_repo, "add stem claims input")

    diag = _seal_verify_token_claim(fixture_repo)

    assert "unwatched-mention" not in diag["flags"]
    assert diag["mentions"] == []


def test_claim_input_artifact_claims_json_is_not_unwatched_evidence(
    fixture_repo: Path,
) -> None:
    write(fixture_repo, "docs/design.md.claims.json", '{"text": "verify_token"}\n')
    commit_all(fixture_repo, "add artifact claims input")

    diag = _seal_verify_token_claim(fixture_repo)

    assert "unwatched-mention" not in diag["flags"]
    assert diag["mentions"] == []


def test_unrelated_tracked_file_with_claim_token_still_flags(fixture_repo: Path) -> None:
    write(fixture_repo, "docs/notes.json", '{"text": "verify_token"}\n')
    commit_all(fixture_repo, "add unrelated notes")

    diag = _seal_verify_token_claim(fixture_repo)

    assert "unwatched-mention" in diag["flags"]
    assert diag["mentions"] == [{"token": "verify_token", "unwatched_files": ["docs/notes.json"]}]


# --- gate policy: single-file is warn-only; the rest are high-risk ------------------


def test_high_risk_flags_exclude_single_file() -> None:
    assert "single-file" not in bindings.HIGH_RISK_FLAGS
    assert {
        "unbacked",
        "short-literal",
        "ambiguous-mention",
        "trigger-only-symbol",
        "unwatched-mention",
    } == bindings.HIGH_RISK_FLAGS


def test_blocking_findings_ignores_single_file_only() -> None:
    diags = [
        {"claim_id": "a", "flags": ["single-file"], "watch": ["x"], "mentions": []},
        {"claim_id": "b", "flags": ["single-file", "unbacked"], "watch": [], "mentions": []},
    ]
    assert [d["claim_id"] for d in bindings.blocking_findings(diags)] == ["b"]


# --- default / off: behavior preserved, no gate output ------------------------------


def test_verify_default_off_seals_and_is_silent(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, SINGLE_FILE_CLAIMS)  # no flag == off
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()
    err = capsys.readouterr().err
    assert "weak binding" not in err and "binding-gate" not in err


def test_verify_explicit_off_matches_default(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, SINGLE_FILE_CLAIMS, "--binding-gate", "off")
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()
    assert "weak binding" not in capsys.readouterr().err


def test_verify_off_with_high_risk_still_seals(fixture_repo: Path, capsys) -> None:
    """off must not gate even a high-risk (unbacked) claim — default behavior."""
    rc = _verify(fixture_repo, UNBACKED_CLAIMS)
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()


# --- warn: seals, reports diagnostics, exit 0 ---------------------------------------


def test_verify_warn_seals_and_reports(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, SINGLE_FILE_CLAIMS, "--binding-gate", "warn")
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()
    err = capsys.readouterr().err
    assert "weak binding: claim 'vt' flags=single-file watch=src/auth.py" in err
    assert "--binding-gate=warn: 1 claim(s) flagged, 0 high-risk" in err


def test_verify_warn_does_not_refuse_high_risk(fixture_repo: Path, capsys) -> None:
    """warn surfaces a high-risk flag but still seals (only fail refuses)."""
    rc = _verify(fixture_repo, UNBACKED_CLAIMS, "--binding-gate", "warn")
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()
    err = capsys.readouterr().err
    assert "flags=unbacked" in err
    assert "1 high-risk" in err  # reported, not refused


# --- fail: refuses high-risk before any write (atomic), exit 4 ----------------------


def test_verify_fail_refuses_high_risk_no_sidecar(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, UNBACKED_CLAIMS, "--binding-gate", "fail")
    assert rc == 4
    assert not (fixture_repo / WARRANT).exists()  # atomic no-write
    err = capsys.readouterr().err
    assert "no sidecar written" in err
    assert "'aspirational'" in err  # names the blocking claim


def test_verify_fail_writes_no_store_row(fixture_repo: Path, capsys) -> None:
    """Atomicity beyond the sidecar: no warrant is indexed either."""
    assert _verify(fixture_repo, UNBACKED_CLAIMS, "--binding-gate", "fail") == 4
    capsys.readouterr()
    assert commands.cmd_status(_ns("--repo", str(fixture_repo), "status", ART)) == 0
    assert ART not in capsys.readouterr().out  # nothing sealed or indexed


def test_verify_fail_allows_single_file_only(fixture_repo: Path, capsys) -> None:
    """The launch-train policy in miniature: a single-file-only warrant seals under fail."""
    rc = _verify(fixture_repo, SINGLE_FILE_CLAIMS, "--binding-gate", "fail")
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()
    assert "--binding-gate=fail: 1 claim(s) flagged, 0 high-risk" in capsys.readouterr().err


# --- the gate never masks a false claim ---------------------------------------------


def test_gate_does_not_mask_a_false_claim(fixture_repo: Path, capsys) -> None:
    rc = _verify(fixture_repo, FALSE_CLAIMS, "--binding-gate", "warn")
    assert rc == 4  # the failing checker wins at step 2, before the gate
    assert not (fixture_repo / WARRANT).exists()
    err = capsys.readouterr().err
    assert "FAILED_AT_SEAL" in err
    assert "weak binding" not in err  # gate never ran; weak binding != claim falsity


# --- seal is symmetric with verify --------------------------------------------------


def test_seal_fail_refuses_high_risk_no_sidecar(fixture_repo: Path, capsys) -> None:
    rc = _seal(fixture_repo, UNBACKED_CLAIMS, "--binding-gate", "fail")
    assert rc == 4
    assert not (fixture_repo / WARRANT).exists()
    assert "no sidecar written" in capsys.readouterr().err


def test_seal_warn_seals_and_reports(fixture_repo: Path, capsys) -> None:
    rc = _seal(fixture_repo, SINGLE_FILE_CLAIMS, "--binding-gate", "warn")
    assert rc == 0
    assert (fixture_repo / WARRANT).is_file()
    assert "flags=single-file" in capsys.readouterr().err


def test_binding_gate_warning_readback_failure_is_warn_only(
    fixture_repo: Path, capsys, monkeypatch
) -> None:
    def fail_readback(repo: Path, artifact_uri: str) -> list[dict]:
        raise gitio.GitError("index unavailable")

    monkeypatch.setattr(commands.bindings, "analyze", fail_readback)

    commands._emit_binding_gate_warnings("dorian verify", fixture_repo, ART, "warn")

    assert (
        "dorian verify: warning: --binding-gate=warn diagnostics could not be read back; "
        "seal remains valid"
    ) in capsys.readouterr().err
