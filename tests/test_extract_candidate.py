"""Candidate-first extraction (--extract-mode candidate): offline tests.

The challenger pre-registered in docs/REAL_DOC_METAMORPHIC_GATE.md: the
document is segmented into candidate blocks deterministically (code, not
model); the model only classifies candidates, so span boundaries cannot
jitter and selection is a per-candidate vote.

Matrix:
segmentation:
(a) blocks split on blank/heading/rule/fence-marker lines; list items and
    table rows start their own candidate; paragraphs merge; blocks cap at 6
    lines; fence markers are excluded, fenced content is segmentable;
    deterministic across calls
derivation:
(b) selected candidates become claims with spans/ids derived from the
    segmentation; out-of-range/bool indices and unknown kinds are dropped,
    never guessed; duplicate selections collapse; nothing valid -> ValueError
protocol:
(c) candidate mode has its own protocol hash, distinct from restate/anchor
consensus:
(d) consensus(mode="candidate") majority-votes per candidate; adjacent
    candidates never merge; kind/load_bearing vote with the standard
    tie-breaks; anchor consensus behavior is unchanged
cli:
(e) --extract-mode candidate parses; bench.churn accepts --mode candidate
    with --consensus
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dorian import extract  # noqa: E402
from dorian.cli import build_parser  # noqa: E402
from dorian.model import Anchor, Claim  # noqa: E402

CAND_DOC = """\
# Title

Paragraph line one
continues on line two.

- bullet item one
- bullet item two

```text
code line A
code line B
```

| h | v |
| --- | --- |
| row | 1 |

L1
L2
L3
L4
L5
L6
L7
"""

EXPECTED_BLOCKS = [
    (3, 4),  # paragraph merges
    (6, 6),  # each bullet stands alone
    (7, 7),
    (10, 11),  # fenced content is a block; markers excluded
    (14, 14),  # each table row stands alone
    (15, 15),
    (16, 16),
    (18, 23),  # plain run capped at 6 lines...
    (24, 24),  # ...remainder becomes its own block
]


def test_segment_candidates_blocks_and_cap() -> None:
    got = extract.segment_candidates(CAND_DOC)
    assert got == EXPECTED_BLOCKS
    assert extract.segment_candidates(CAND_DOC) == got  # deterministic


def test_claims_from_candidates_derive_and_drop() -> None:
    cands = extract.segment_candidates(CAND_DOC)
    data = {
        "candidates": [
            {"index": 0, "kind": "fact", "load_bearing": False},
            {"index": 0, "kind": "fact", "load_bearing": False},  # dup collapses
            {"index": 99, "kind": "fact", "load_bearing": False},  # out of range
            {"index": True, "kind": "fact", "load_bearing": False},  # bool is not an index
            {"index": 1, "kind": "bogus", "load_bearing": False},  # unknown kind
            {"index": 2, "kind": "fact", "load_bearing": "yes"},  # non-bool
        ]
    }
    got = extract._claims_from_candidates(data, CAND_DOC, cands)["claims"]
    assert [c["id"] for c in got] == ["cL3-4"]
    assert got[0]["text"] == "Paragraph line one continues on line two."
    assert got[0]["anchor"]["line_start"] == 3 and got[0]["anchor"]["line_end"] == 4

    with pytest.raises(ValueError, match="no valid"):
        extract._claims_from_candidates({"candidates": [{"index": 99}]}, CAND_DOC, cands)
    with pytest.raises(ValueError, match="no candidates"):
        extract._claims_from_candidates({}, CAND_DOC, cands)


def test_candidate_protocol_is_distinct() -> None:
    hashes = {extract.prompt_hash(m) for m in ("restate", "anchor", "candidate")}
    assert len(hashes) == 3
    rendered = extract._render_candidates(CAND_DOC, extract.segment_candidates(CAND_DOC))
    assert "b0 [lines 3-4]" in rendered
    assert "Paragraph line one" in rendered


def _claim(a: int, b: int, kind: str = "quantity", lb: bool = False) -> Claim:
    quote = "\n".join(CAND_DOC.split("\n")[a - 1 : b])
    return Claim(
        id=f"cL{a}-{b}",
        text=" ".join(quote.split()),
        kind=kind,
        load_bearing=lb,
        anchor=Anchor(line_start=a, line_end=b, quote=quote),
    )


def _fake_runs(monkeypatch: pytest.MonkeyPatch, runs: list[list[Claim]], mode: str) -> None:
    calls = {"n": 0}

    def fake(text, **kwargs):
        assert kwargs["use_cache"] is False and kwargs["mode"] == mode
        out = runs[calls["n"]]
        calls["n"] += 1
        return out

    monkeypatch.setattr(extract, "extract_claims", fake)


def test_consensus_candidate_votes_per_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = {"model": "m", "cache_dir": Path("c"), "artifact_hash": "sha256:x"}
    # candidate (3,4) in all runs; (6,6) in one run only -> dropped
    _fake_runs(
        monkeypatch,
        [[_claim(3, 4)], [_claim(3, 4)], [_claim(3, 4), _claim(6, 6)]],
        mode="candidate",
    )
    got = extract.extract_claims_consensus(CAND_DOC, k=3, mode="candidate", **kwargs)
    assert [c.id for c in got] == ["cL3-4"]

    # adjacent candidates never merge, even when all runs select both
    _fake_runs(
        monkeypatch,
        [[_claim(6, 6), _claim(7, 7)]] * 3,
        mode="candidate",
    )
    got = extract.extract_claims_consensus(CAND_DOC, k=3, mode="candidate", **kwargs)
    assert [c.id for c in got] == ["cL6-6", "cL7-7"]

    # kind majority with lexicographic tie-break; load_bearing ties -> False
    _fake_runs(
        monkeypatch,
        [[_claim(3, 4, "quantity", True)], [_claim(3, 4, "fact", False)]],
        mode="candidate",
    )
    got = extract.extract_claims_consensus(CAND_DOC, k=2, mode="candidate", **kwargs)
    assert got[0].kind == "fact" and got[0].load_bearing is False

    with pytest.raises(ValueError, match="k must be >= 2"):
        extract.extract_claims_consensus(CAND_DOC, k=1, mode="candidate", **kwargs)


def test_consensus_anchor_mode_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = {"model": "m", "cache_dir": Path("c"), "artifact_hash": "sha256:x"}
    _fake_runs(monkeypatch, [[_claim(3, 4)], [_claim(3, 4)], [_claim(3, 4)]], mode="anchor")
    got = extract.extract_claims_consensus(CAND_DOC, k=3, **kwargs)  # default mode
    assert [c.id for c in got] == ["cL3-4"]


def test_cli_and_churn_accept_candidate_mode() -> None:
    args = build_parser().parse_args(
        ["seal", "a.md", "--readset", "rs.json", "--extract", "--extract-mode", "candidate"]
    )
    assert args.extract_mode == "candidate"

    from bench import churn

    parsed = False
    try:
        churn.main(["--doc", "missing.md", "--mode", "candidate", "--consensus", "3"])
        parsed = True
    except SystemExit:  # argparse rejection would raise SystemExit
        pass
    assert parsed  # mode accepted; missing doc is a normal exit-2 path, not a parse error
