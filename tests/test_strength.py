"""Checker-strength and claim-risk diagnostics (advisory; no execution).

Pins the WP2 acceptance matrix: a deterministic classification of each checker's
TRUTH strength (distinct from trigger coverage), kind-vs-strength adequacy
mismatches, an advisory C4 test-adequacy lint (WP6: zero/constant assertions), and
a per-claim risk level. Everything here is advisory — it never runs a checker,
changes a verdict/trust state, or moves an exit code.
"""

from __future__ import annotations

from pathlib import Path

from dorian import strength
from dorian.model import CheckerSpec, Claim


def _claim(kind: str, load_bearing: bool, *programs: tuple[str, str]) -> Claim:
    return Claim(
        id="c",
        text="x",
        kind=kind,
        load_bearing=load_bearing,
        checkers=tuple(CheckerSpec(type=t, program=p) for t, p in programs),
    )


# --- checker strength classification ------------------------------------------


def test_checker_strength_classification() -> None:
    f = strength.checker_strength
    assert f(CheckerSpec(type="C3", program="path:src/x.py")) == "existence"
    assert f(CheckerSpec(type="C3", program="symbol:src/x.py::F")) == "existence"
    assert f(CheckerSpec(type="C3", program="string:src/x.py::lit")) == "raw_text"
    assert f(CheckerSpec(type="C3", program="regex:src/x.py::p")) == "raw_text"
    assert f(CheckerSpec(type="C3", program="code:src/x.py::p")) == "semantic_text"
    assert f(CheckerSpec(type="C3", program="py-signature:src/x.py::F::a")) == "structural"
    assert f(CheckerSpec(type="C3", program="py-const:src/x.py::K::1")) == "structural"
    assert f(CheckerSpec(type="C4", program="pytest:t.py::test_a")) == "behavioral"
    assert f(CheckerSpec(type="C5", program="rowcount:d.csv::>0")) == "data"
    assert f(CheckerSpec(type="C5", program="snapshot:d.csv")) == "snapshot"
    assert f(CheckerSpec(type="C5", program="shell:grep x f")) == "shell_executable"
    assert f(CheckerSpec(type="C1", program="rs-0")) == "snapshot"


def test_claim_strength_is_the_strongest_backing(tmp_path: Path) -> None:
    c = _claim("behavior", True, ("C3", "symbol:a.py::F"), ("C4", "pytest:t.py::test_a"))
    assert strength.claim_strength(c) == "behavioral"  # the C4 dominates the symbol
    assert strength.claim_strength(_claim("fact", True)) == "unbacked"


# --- adequacy mismatch (kind vs strength) -------------------------------------


def test_behavior_claim_backed_only_by_symbol_warns(tmp_path: Path) -> None:
    (rec,) = strength.analyze(tmp_path, [_claim("behavior", True, ("C3", "symbol:a.py::F"))])
    assert rec["strength"] == "existence"
    assert any("adequacy_mismatch" in n for n in rec["adequacy"])
    assert rec["risk"] == "high"


def test_behavior_claim_backed_only_by_regex_warns(tmp_path: Path) -> None:
    (rec,) = strength.analyze(tmp_path, [_claim("behavior", True, ("C3", "regex:a.py::F\\("))])
    assert any("adequacy_mismatch" in n for n in rec["adequacy"])  # raw_text is weak for behavior


def test_behavior_claim_backed_by_pytest_has_no_mismatch(tmp_path: Path) -> None:
    (rec,) = strength.analyze(tmp_path, [_claim("behavior", True, ("C4", "pytest:t.py::test_a"))])
    # the test file does not exist here, so the C4 adequacy lint stays silent (the
    # checker itself reports test_gone) — and there is no kind/strength mismatch
    assert not any("adequacy_mismatch" in n for n in rec["adequacy"])
    assert rec["strength"] == "behavioral"


def test_quantity_claim_with_value_checker_has_no_mismatch(tmp_path: Path) -> None:
    (rec,) = strength.analyze(tmp_path, [_claim("quantity", True, ("C3", "py-const:c.py::T::30"))])
    assert rec["adequacy"] == []
    assert rec["risk"] == "low"


def test_quantity_claim_backed_only_by_existence_warns(tmp_path: Path) -> None:
    (rec,) = strength.analyze(tmp_path, [_claim("quantity", True, ("C3", "symbol:c.py::T"))])
    assert any("adequacy_mismatch" in n for n in rec["adequacy"])


def test_data_claim_with_typed_c5_has_no_mismatch(tmp_path: Path) -> None:
    (rec,) = strength.analyze(tmp_path, [_claim("quantity", True, ("C5", "rowcount:d.csv::>0"))])
    assert rec["adequacy"] == []


# --- unbacked risk ------------------------------------------------------------


def test_unbacked_load_bearing_is_high_risk(tmp_path: Path) -> None:
    (rec,) = strength.analyze(tmp_path, [_claim("fact", True)])
    assert rec["risk"] == "high"
    assert "unbacked" in rec["reasons"]


def test_unbacked_non_load_bearing_is_low(tmp_path: Path) -> None:
    (rec,) = strength.analyze(tmp_path, [_claim("fact", False)])
    assert rec["risk"] in ("low", "medium")  # advisory, not high for a non-load-bearing claim
    assert rec["risk"] != "high"


# --- C4 test adequacy lint (WP6) ----------------------------------------------


def _w(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_c4_zero_assertion_test_warns(tmp_path: Path) -> None:
    _w(tmp_path, "t.py", "def test_a():\n    do_something()\n")
    notes = strength.c4_adequacy(tmp_path, CheckerSpec(type="C4", program="pytest:t.py::test_a"))
    assert any("no assertion" in n.lower() for n in notes)


def test_c4_assert_constant_warns(tmp_path: Path) -> None:
    _w(tmp_path, "t.py", "def test_a():\n    assert True\n")
    notes = strength.c4_adequacy(tmp_path, CheckerSpec(type="C4", program="pytest:t.py::test_a"))
    assert any("constant" in n.lower() for n in notes)


def test_c4_normal_asserting_test_is_silent(tmp_path: Path) -> None:
    _w(tmp_path, "t.py", "def test_a():\n    x = f()\n    assert x == 42\n")
    notes = strength.c4_adequacy(tmp_path, CheckerSpec(type="C4", program="pytest:t.py::test_a"))
    assert notes == []


def test_c4_assertion_helper_is_not_flagged(tmp_path: Path) -> None:
    """unittest-style assertion methods and pytest.raises count as assertions."""
    _w(tmp_path, "t.py", "class T:\n    def test_a(self):\n        self.assertEqual(f(), 42)\n")
    notes = strength.c4_adequacy(tmp_path, CheckerSpec(type="C4", program="pytest:t.py::T::test_a"))
    assert notes == []
    _w(
        tmp_path,
        "t2.py",
        "import pytest\ndef test_b():\n    with pytest.raises(ValueError):\n        f()\n",
    )
    notes = strength.c4_adequacy(tmp_path, CheckerSpec(type="C4", program="pytest:t2.py::test_b"))
    assert notes == []


def test_c4_missing_or_unfound_node_is_silent(tmp_path: Path) -> None:
    """The checker itself reports test_gone; the linter does not guess."""
    assert strength.c4_adequacy(tmp_path, CheckerSpec(type="C4", program="pytest:gone.py::t")) == []
    _w(tmp_path, "t.py", "def test_a():\n    assert 1\n")
    assert (
        strength.c4_adequacy(tmp_path, CheckerSpec(type="C4", program="pytest:t.py::test_z")) == []
    )


def test_c4_adequacy_surfaces_in_behavior_claim(tmp_path: Path) -> None:
    _w(tmp_path, "t.py", "def test_a():\n    f()\n")
    (rec,) = strength.analyze(tmp_path, [_claim("behavior", True, ("C4", "pytest:t.py::test_a"))])
    assert any("assertion" in n.lower() for n in rec["adequacy"])


# --- executes field + determinism ---------------------------------------------


def test_executes_field(tmp_path: Path) -> None:
    (rec,) = strength.analyze(
        tmp_path, [_claim("behavior", True, ("C4", "pytest:t.py::t"), ("C5", "shell:echo hi"))]
    )
    assert set(rec["executes"]) == {"pytest", "shell"}


def test_analyze_is_deterministic(tmp_path: Path) -> None:
    claims = [
        _claim("behavior", True, ("C3", "symbol:a.py::F")),
        _claim("quantity", True, ("C3", "py-const:c.py::T::30")),
    ]
    assert strength.analyze(tmp_path, claims) == strength.analyze(tmp_path, claims)


# --- CLI surface: `dorian bindings` carries strength (JSON + human) ------------


def test_cmd_bindings_surfaces_strength(fixture_repo: Path, capsys) -> None:
    """A behavior claim backed only by symbol: seals (exit 0) but `dorian bindings`
    must surface its weak strength, high risk, and adequacy mismatch — JSON + human."""
    import json

    from dorian import cli

    claims = {
        "claims": [
            {
                "id": "vt-behavior",
                "text": "verify_token authenticates the request.",
                "kind": "behavior",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "symbol:src/auth.py::verify_token"}],
            }
        ]
    }
    cp = fixture_repo / "claims.json"
    cp.write_text(json.dumps(claims), encoding="utf-8")
    assert (
        cli.main(["--repo", str(fixture_repo), "verify", "docs/design.md", "--claims", str(cp)])
        == 0
    )
    capsys.readouterr()

    assert cli.main(["--repo", str(fixture_repo), "--json", "bindings", "docs/design.md"]) == 0
    payload = json.loads(capsys.readouterr().out)
    (diag,) = payload["claims"]
    assert diag["strength"]["strength"] == "existence"
    assert diag["strength"]["risk"] == "high"
    assert any("adequacy_mismatch" in n for n in diag["strength"]["adequacy"])

    assert cli.main(["--repo", str(fixture_repo), "bindings", "docs/design.md"]) == 0
    out = capsys.readouterr().out
    assert "strength: existence" in out and "risk: high" in out
