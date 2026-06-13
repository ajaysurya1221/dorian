"""Edge-case and error-handling tests through the CLI entrypoint.

Feed malformed / empty / oversized / unicode / out-of-repo inputs the way a user
would (raw claims.json), and assert the externally visible contract: the right
exit code, a prefixed (never a raw traceback) error, and that a failed command
writes no sidecar. cli.main is the public entrypoint; no deeper internals are used.
"""

from __future__ import annotations

import json
from pathlib import Path

from dorian import cli


def _claims_file(repo: Path, obj: dict) -> Path:
    p = repo / "claims.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _verify(repo: Path, artifact: str, claims_path: Path, capsys):
    rc = cli.main(["--repo", str(repo), "verify", artifact, "--claims", str(claims_path)])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def _backed_claim(cid: str, program: str) -> dict:
    return {
        "id": cid,
        "text": "x",
        "kind": "fact",
        "load_bearing": False,
        "checkers": [{"type": "C3", "program": program}],
    }


def test_invalid_json_is_usage_error_no_traceback(fixture_repo: Path, capsys) -> None:
    p = fixture_repo / "claims.json"
    p.write_text("{not json", encoding="utf-8")
    rc, _out, err = _verify(fixture_repo, "docs/design.md", p, capsys)
    assert rc == 2
    assert "not valid JSON" in err
    assert "Traceback" not in err
    assert not (fixture_repo / "docs/design.md.warrant").exists()


def test_bad_kind_is_usage_error(fixture_repo: Path, capsys) -> None:
    p = _claims_file(
        fixture_repo,
        {"claims": [{"id": "c1", "text": "x", "kind": "nope", "load_bearing": False}]},
    )
    rc, _out, err = _verify(fixture_repo, "docs/design.md", p, capsys)
    assert rc == 2
    assert "kind" in err.lower() and "Traceback" not in err


def test_bad_checker_type_is_usage_error(fixture_repo: Path, capsys) -> None:
    p = _claims_file(
        fixture_repo,
        {
            "claims": [
                {
                    "id": "c1",
                    "text": "x",
                    "kind": "fact",
                    "load_bearing": False,
                    "checkers": [{"type": "C9", "program": "x"}],
                }
            ]
        },
    )
    rc, _out, err = _verify(fixture_repo, "docs/design.md", p, capsys)
    assert rc == 2
    assert "C9" in err or "checker type" in err.lower()


def test_duplicate_claim_id_is_usage_error(fixture_repo: Path, capsys) -> None:
    p = _claims_file(
        fixture_repo,
        {
            "claims": [
                {"id": "dup", "text": "a", "kind": "fact", "load_bearing": False},
                {"id": "dup", "text": "b", "kind": "fact", "load_bearing": False},
            ]
        },
    )
    rc, _out, err = _verify(fixture_repo, "docs/design.md", p, capsys)
    assert rc == 2
    assert "duplicate" in err.lower()


def test_missing_claims_file_is_usage_error(fixture_repo: Path, capsys) -> None:
    rc = cli.main(
        ["--repo", str(fixture_repo), "verify", "docs/design.md", "--claims", "nope.json"]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "Traceback" not in err


def test_empty_claims_list_seals_vacuously(fixture_repo: Path, capsys) -> None:
    p = _claims_file(fixture_repo, {"claims": []})
    rc, out, err = _verify(fixture_repo, "docs/design.md", p, capsys)
    assert rc == 0, err
    assert "verified 0/0 claim(s)" in out
    assert (fixture_repo / "docs/design.md.warrant").is_file()


def test_artifact_outside_repo_is_usage_error(fixture_repo: Path, capsys) -> None:
    p = _claims_file(fixture_repo, {"claims": [_backed_claim("c1", "string:src/auth.py::RS256")]})
    rc = cli.main(["--repo", str(fixture_repo), "verify", "../outside.md", "--claims", str(p)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "outside" in err.lower() and "Traceback" not in err


def test_unicode_in_claim_text_artifact_path_and_content(fixture_repo: Path, capsys) -> None:
    art = fixture_repo / "docs" / "规范_🎯.md"
    art.write_text("# 规范\n\nRS256 と RS256。\n", encoding="utf-8")
    p = _claims_file(
        fixture_repo,
        {
            "claims": [
                {
                    "id": "u1",
                    "text": "令牌验证使用 RS256 🔐。",
                    "kind": "fact",
                    "load_bearing": False,
                    "checkers": [{"type": "C3", "program": "string:src/auth.py::RS256"}],
                }
            ]
        },
    )
    rc, out, err = _verify(fixture_repo, "docs/规范_🎯.md", p, capsys)
    assert rc == 0, err
    assert "verified 1/1 claim(s)" in out
    assert (fixture_repo / "docs/规范_🎯.md.warrant").is_file()


def test_large_claims_file_seals(fixture_repo: Path, capsys) -> None:
    claims = [
        {"id": f"c{i}", "text": f"claim {i} " + "x" * 200, "kind": "fact", "load_bearing": False}
        for i in range(500)
    ]
    p = _claims_file(fixture_repo, {"claims": claims})
    rc, out, err = _verify(fixture_repo, "docs/design.md", p, capsys)
    assert rc == 0, err
    assert "verified 0/500 claim(s)" in out


def test_capture_bad_selector_is_usage_error(fixture_repo: Path, capsys) -> None:
    rc = cli.main(
        ["--repo", str(fixture_repo), "capture", "--manual", "src/auth.py:LXYZ", "--out", "rs.json"]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "Traceback" not in err


def test_seal_malformed_readset_is_prefixed_error_not_traceback(fixture_repo: Path, capsys) -> None:
    bad = fixture_repo / "rs.json"
    bad.write_text('{"wrong": "shape"}')
    p = _claims_file(
        fixture_repo,
        {"claims": [{"id": "c1", "text": "x", "kind": "fact", "load_bearing": False}]},
    )
    argv = ["--repo", str(fixture_repo), "seal", "docs/design.md"]
    argv += ["--readset", str(bad), "--claims", str(p)]
    rc = cli.main(argv)
    err = capsys.readouterr().err
    assert rc == 2
    assert "dorian seal:" in err and "malformed" in err.lower() and "Traceback" not in err
