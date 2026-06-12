"""Planted-truth extraction gate: offline tests (no API anywhere).

Matrix:
plant:
(a) determinism: same (seed, tier) -> byte-identical doc + manifest; sha matches
(b) separation rule: every claim line carries a digit; every non-empty
    distractor line carries none; manifest line numbers point at exact texts
(c) tier sizing bounded; claim density sane; claim texts unique
metamorph:
(d) filler_insert keeps every claim text, adds no digits, deterministic
(e) section_reorder preserves the line multiset and all claim texts
(f) claim_delete removes exactly the victims (deterministic), keeps survivors
snapping:
(g) _snap_span trims blank/heading/rule/fence edges, drops fully-trimmed
    spans; ids reflect snapped ranges through _claims_from_spans
consensus (fake extract_claims):
(h) majority line voting (2/3 keeps, 1/3 drops); adjacency split vs merge by
    majority same-span votes; kind majority with lexicographic tie-break;
    load_bearing strict majority with ties -> False; k < 2 raises
gate math:
(i) _draw_metrics recall/precision/covered-lines hand-computed
(j) aggregate verdicts: PROMOTION (exit 0), REJECTION (exit 3),
    INSUFFICIENT (exit 4); calibration validity logic
churn passthrough:
(k) --consensus K reaches extract_claims_consensus and is recorded; restate
    + consensus is usage error (exit 2)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench import churn, extract_gate, metamorph, plant  # noqa: E402

from dorian import extract  # noqa: E402
from dorian.model import Anchor, Claim  # noqa: E402

# --- plant -------------------------------------------------------------------------


def test_plant_deterministic() -> None:
    t1, m1 = plant.generate(3, 40)
    t2, m2 = plant.generate(3, 40)
    assert t1 == t2 and m1 == m2
    import hashlib

    assert m1["doc_sha256"] == hashlib.sha256(t1.encode("utf-8")).hexdigest()
    assert plant.generate(4, 40)[0] != t1  # seed actually matters


def test_plant_separation_rule_and_manifest() -> None:
    for tier in (40, 120, 240):
        text, manifest = plant.generate(1, tier)
        lines = text.split("\n")
        claim_lines = {c["line"] for c in manifest["claims"]}
        for c in manifest["claims"]:
            assert lines[c["line"] - 1] == c["text"]  # manifest points at exact lines
            # claims carry a digit or a path token; distractors carry neither
            assert re.search(r"[\d/]", c["text"]), c["text"]
        for i, line in enumerate(lines, start=1):
            if i not in claim_lines and line.strip():
                assert not re.search(r"[\d/]", line), f"distractor with claim token: {line!r}"


def test_plant_sizing_density_uniqueness() -> None:
    for tier in (40, 120, 240):
        for seed in (1, 2, 3):
            _text, manifest = plant.generate(seed, tier)
            total = manifest["total_lines"]
            assert tier - 2 <= total <= tier + 10, (tier, total)
            texts = [c["text"] for c in manifest["claims"]]
            assert len(texts) == len(set(texts))  # unique claim texts
            assert len(texts) >= tier // 12  # battery is not claim-free


# --- metamorph ---------------------------------------------------------------------


def test_filler_insert_preserves_claims() -> None:
    text, manifest = plant.generate(1, 120)
    t1, present, absent = metamorph.filler_insert(text, manifest, seed=1)
    t2, _, _ = metamorph.filler_insert(text, manifest, seed=1)
    assert t1 == t2 and absent == []
    new_lines = t1.split("\n")
    for claim_text in present:
        assert claim_text in new_lines
    assert len(new_lines) > manifest["total_lines"]


def test_section_reorder_preserves_lines() -> None:
    text, manifest = plant.generate(2, 120)
    t1, present, absent = metamorph.section_reorder(text, manifest)
    assert absent == []
    assert sorted(t1.split("\n")) == sorted(text.split("\n"))  # pure permutation
    assert t1 != text  # actually moved
    for claim_text in present:
        assert claim_text in t1.split("\n")


def test_claim_delete_removes_exactly_victims() -> None:
    text, manifest = plant.generate(1, 120)
    t1, present, absent = metamorph.claim_delete(text, manifest, seed=1)
    t2, _, absent2 = metamorph.claim_delete(text, manifest, seed=1)
    assert t1 == t2 and absent == absent2 and len(absent) == 3
    new_lines = t1.split("\n")
    for victim in absent:
        assert victim not in new_lines
    for survivor in present:
        assert survivor in new_lines
    assert set(present) | set(absent) == {c["text"] for c in manifest["claims"]}


# --- snapping ----------------------------------------------------------------------

SNAP_DOC = "# Title\n\nThe budget is 4 attempts.\n```text\nx\n```\n---\n## H\n"


def test_snap_span_trims_non_content_edges() -> None:
    lines = SNAP_DOC.split("\n")
    assert extract._snap_span(lines, 1, 3) == (3, 3)  # heading + blank trimmed
    assert extract._snap_span(lines, 3, 7) == (3, 5)  # fence/rule trimmed, code kept
    assert extract._snap_span(lines, 1, 2) is None  # nothing left
    assert extract._snap_span(lines, 8, 8) is None  # pure heading
    got = extract._claims_from_spans(
        {"spans": [{"line_start": 1, "line_end": 3, "kind": "quantity", "load_bearing": True}]},
        SNAP_DOC,
    )["claims"]
    assert [c["id"] for c in got] == ["cL3-3"]  # id reflects the SNAPPED range


# --- consensus ---------------------------------------------------------------------

CONS_DOC = "intro line\nThe budget is 4 attempts.\nLogin is at /v1/login.\nepilogue line\n"


def _claim(a: int, b: int, kind: str = "quantity", lb: bool = False) -> Claim:
    quote = "\n".join(CONS_DOC.split("\n")[a - 1 : b])
    return Claim(
        id=f"cL{a}-{b}",
        text=" ".join(quote.split()),
        kind=kind,
        load_bearing=lb,
        anchor=Anchor(line_start=a, line_end=b, quote=quote),
    )


def _fake_runs(monkeypatch: pytest.MonkeyPatch, runs: list[list[Claim]]) -> None:
    calls = {"n": 0}

    def fake(text, **kwargs):
        assert kwargs["use_cache"] is False and kwargs["mode"] == "anchor"
        out = runs[calls["n"]]
        calls["n"] += 1
        return out

    monkeypatch.setattr(extract, "extract_claims", fake)


def test_consensus_majority_and_split(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = {"model": "m", "cache_dir": Path("c"), "artifact_hash": "sha256:x"}
    # line 2 in all runs; line 3 in only one -> dropped
    _fake_runs(monkeypatch, [[_claim(2, 2)], [_claim(2, 2)], [_claim(2, 2), _claim(3, 3)]])
    got = extract.extract_claims_consensus(CONS_DOC, k=3, **kwargs)
    assert [c.id for c in got] == ["cL2-2"]

    # both lines pass, but only one run spanned them together -> split
    _fake_runs(
        monkeypatch, [[_claim(2, 3)], [_claim(2, 2), _claim(3, 3)], [_claim(2, 2), _claim(3, 3)]]
    )
    got = extract.extract_claims_consensus(CONS_DOC, k=3, **kwargs)
    assert [c.id for c in got] == ["cL2-2", "cL3-3"]

    # majority spanned them together -> merged
    _fake_runs(monkeypatch, [[_claim(2, 3)], [_claim(2, 3)], [_claim(2, 2), _claim(3, 3)]])
    got = extract.extract_claims_consensus(CONS_DOC, k=3, **kwargs)
    assert [c.id for c in got] == ["cL2-3"]


def test_consensus_meta_votes_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = {"model": "m", "cache_dir": Path("c"), "artifact_hash": "sha256:x"}
    # kind majority: quantity x2 vs fact x1; load_bearing 2/3 True -> True
    _fake_runs(
        monkeypatch,
        [
            [_claim(2, 2, "quantity", True)],
            [_claim(2, 2, "quantity", True)],
            [_claim(2, 2, "fact", False)],
        ],
    )
    got = extract.extract_claims_consensus(CONS_DOC, k=3, **kwargs)
    assert got[0].kind == "quantity" and got[0].load_bearing is True

    # kind tie -> lexicographically smallest; load_bearing tie (1/2) -> False
    _fake_runs(monkeypatch, [[_claim(2, 2, "quantity", True)], [_claim(2, 2, "fact", False)]])
    got = extract.extract_claims_consensus(CONS_DOC, k=2, **kwargs)
    assert got[0].kind == "fact" and got[0].load_bearing is False

    with pytest.raises(ValueError, match="k must be >= 2"):
        extract.extract_claims_consensus(CONS_DOC, k=1, **kwargs)


# --- gate math ---------------------------------------------------------------------


def test_draw_metrics_hand_computed() -> None:
    claims = [_claim(2, 2), _claim(3, 4)]  # span 2 covers claim line 3 + distractor 4
    m = extract_gate._draw_metrics(claims, claim_lines={2, 3})
    assert m["found"] == 2 and m["covered_claim_lines"] == [2, 3]
    assert m["n_spans"] == 2 and m["tp_spans"] == 2
    m2 = extract_gate._draw_metrics([_claim(4, 4)], claim_lines={2, 3})
    assert m2["found"] == 0 and m2["tp_spans"] == 0 and m2["n_spans"] == 1


def _gate_doc(tier: int, found: int, planted: int, sel: float, txt: float, **over) -> dict:
    doc = {
        "doc_id": f"t{tier}-s1",
        "tier": tier,
        "seed": 1,
        "doc_sha256": "x",
        "mode": "anchor",
        "consensus": 3,
        "draws": 3,
        "n_planted": planted,
        "per_draw": [
            {
                "found": found,
                "tp_spans": found,
                "n_spans": found + 1,
                "covered_claim_lines": list(range(found)),
                "texts": [],
                "n_claims": found,
            }
        ]
        * 3,
        "selection_churn_mean": sel,
        "text_churn_mean": txt,
        "failures": [],
        "transforms": {
            "filler_insert": {"survived": 9, "denom": 9, "survival": 1.0},
            "section_reorder": {"survived": 9, "denom": 9, "survival": 1.0},
            "claim_delete": {"deleted": 3, "fabricated": []},
        },
    }
    doc.update(over)
    return doc


def _calib_doc(tier: int, txt: float) -> dict:
    return {"tier": tier, "text_churn_mean": txt}


def _run_aggregate(tmp_path: Path, gate_docs: list[dict]) -> int:
    gate_dir, ra, rr = tmp_path / "gate", tmp_path / "ca", tmp_path / "cr"
    for d in (gate_dir, ra, rr):
        d.mkdir()
    for i, doc in enumerate(gate_docs):
        (gate_dir / f"{i}.json").write_text(json.dumps(doc))
    for i, (tier, txt) in enumerate([(40, 0.1), (240, 0.15)]):
        (ra / f"{i}.json").write_text(json.dumps(_calib_doc(tier, txt)))
    for i, (tier, txt) in enumerate([(40, 0.3), (240, 0.7)]):
        (rr / f"{i}.json").write_text(json.dumps(_calib_doc(tier, txt)))
    return extract_gate.main(
        [
            "aggregate",
            "--gate-dir",
            str(gate_dir),
            "--calib-anchor-dir",
            str(ra),
            "--calib-restate-dir",
            str(rr),
            "--out",
            str(tmp_path / "report.json"),
        ]
    )


def test_aggregate_promotion(tmp_path: Path) -> None:
    docs = [_gate_doc(t, found=9, planted=10, sel=0.05, txt=0.1) for t in (40, 120, 240)]
    assert _run_aggregate(tmp_path, docs) == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["verdict"] == "PROMOTION" and report["calibration"]["valid"] is True


def test_aggregate_rejection_on_selection_churn(tmp_path: Path) -> None:
    docs = [_gate_doc(t, found=9, planted=10, sel=0.05, txt=0.1) for t in (40, 120)]
    docs.append(_gate_doc(240, found=9, planted=10, sel=0.25, txt=0.1))
    assert _run_aggregate(tmp_path, docs) == 3


def test_aggregate_insufficient_between_bands(tmp_path: Path) -> None:
    docs = [_gate_doc(t, found=7, planted=10, sel=0.05, txt=0.1) for t in (40, 120, 240)]
    assert _run_aggregate(tmp_path, docs) == 4  # recall 0.70: below promote, above reject


def test_aggregate_rejection_on_fabrication(tmp_path: Path) -> None:
    docs = [_gate_doc(t, found=9, planted=10, sel=0.05, txt=0.1) for t in (40, 120)]
    bad = _gate_doc(240, found=9, planted=10, sel=0.05, txt=0.1)
    bad["transforms"]["claim_delete"]["fabricated"] = ["a ghost claim"]
    docs.append(bad)
    assert _run_aggregate(tmp_path, docs) == 3


# --- churn passthrough -------------------------------------------------------------


def test_churn_consensus_passthrough(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DORIAN_EXTRACT_STUB", raising=False)
    seen: list[int] = []

    def fake_consensus(text, *, k, model, cache_dir, artifact_hash, temperature=0.0):
        seen.append(k)
        return [_claim(2, 2)]

    monkeypatch.setattr(extract, "extract_claims_consensus", fake_consensus)
    doc = tmp_path / "doc.md"
    doc.write_text(CONS_DOC, encoding="utf-8")
    out = tmp_path / "churn.json"
    rc = churn.main(["--doc", str(doc), "--mode", "anchor", "--consensus", "3", "--out", str(out)])
    assert rc == 0 and seen == [3, 3, 3]
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["consensus"] == 3 and record["mode"] == "anchor"

    assert churn.main(["--doc", str(doc), "--consensus", "3", "--out", str(out)]) == 2
