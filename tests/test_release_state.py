"""Deterministic release-state evaluator (bench/release_state.py).

The evaluator is a PURE function over machine-verifiable facts + recorded gate
evidence. It never runs pytest, never touches the network, never asks the user a
question. It emits exactly one decision from the fixed alphabet:

    PROMOTE_1_0_READY | CUT_RC2_READY | STAY_RC
    HALT_UNSAFE | HALT_INSUFFICIENT_EVIDENCE | HALT_PUBLISH_NOT_CONFIGURED
    HALT_VERSION_MISMATCH | HALT_NONDETERMINISTIC

These tests mock the state table directly (Tree-of-Thoughts: every gate is an
independent lever) and assert the resulting decision + invariants.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import release_state as rs  # noqa: E402

_SRC = REPO_ROOT / "bench" / "release_state.py"


# --------------------------------------------------------------- green baseline


def _green_facts(
    *,
    features_after_rc: bool = False,
    version: str = "1.0.0rc1",
    rc_tag: str = "v1.0.0rc1",
) -> dict:
    """A facts dict where every machine-verifiable gate is satisfied. Individual
    tests flip exactly one lever to exercise a transition."""
    head_commit = "a" * 40 if not features_after_rc else "b" * 40
    rc_tag_commit = "a" * 40
    return {
        "pyproject_version": version,
        "init_version": version,
        "lock_version": version,
        "rc_tag": rc_tag,
        "rc_tag_exists": True,
        "rc_tag_target_ok": True,
        "head_commit": head_commit,
        "rc_tag_commit": rc_tag_commit,
        "features_after_rc": features_after_rc,
        "unexpected_dirty": [],
        "week2": {
            "config_value_impl": True,
            "config_value_doc": True,
            "atomicity_impl": True,
        },
        "harness": {"exists": True, "verify_cache": True, "error_distinct_broken": True},
        "machine_claims": ["humanize", "python-dotenv"],
        "bench_doc_text": (
            "candidate benchmark subjects reproducible on these frozen SHAs; "
            "trigger and truth layers reported separately."
        ),
        "workflows": {
            "ci.yml": "on: [push]\npermissions:\n  contents: read\n",
            "public-microbench.yml": "on:\n  workflow_dispatch:\npermissions:\n  contents: read\n",
            "release-gate.yml": "permissions:\n  id-token: write\n  attestations: write\n",
            "publish-testpypi.yml": "permissions:\n  id-token: write\n",
        },
        "security": {"log_injection_test": True},
        "provenance_workflow": True,
        "testpypi_workflow": True,
    }


def _green_evidence() -> dict:
    return {
        "lint_ok": True,
        "format_ok": True,
        "tests_ok": True,
        "tests_total": 730,
        "tests_failed": 0,
        "build_ok": True,
        "install_smoke_ok": True,
        "benchmark": {
            "executed": True,
            "repos": ["humanize", "python-dotenv"],
            "deterministic": True,
            "all_match": True,
            "nondeterministic_fields": [],
        },
    }


def _decide(
    facts: dict, evidence: dict, *, target: str = "1.0.0", strict: bool = True, **kw
) -> str:
    return rs.evaluate(facts, evidence, target=target, strict=strict, **kw)["decision"]


# ------------------------------------------------------------------------ tests


def test_all_gates_green_no_post_rc_features_promotes():
    # mocked green WITH HEAD == current rc tag (no new behavior after that rc) -> PROMOTE
    assert _decide(_green_facts(features_after_rc=False), _green_evidence()) == "PROMOTE_1_0_READY"


def test_post_rc_features_cut_next_rc():
    # real situation before rc2: behavior landed AFTER the current rc tag -> CUT_RC2
    assert _decide(_green_facts(features_after_rc=True), _green_evidence()) == "CUT_RC2_READY"


def test_latest_rc_auto_detect_chooses_rc2_over_rc1():
    tag, target_ok = rs._select_rc_tag(
        ["v1.0.0rc1", "v1.1.0rc1", "not-a-release", "v1.0.0rc2"],
        target="1.0.0",
        requested=None,
    )
    assert tag == "v1.0.0rc2"
    assert target_ok is True


def test_explicit_rc_tag_is_honored():
    tag, target_ok = rs._select_rc_tag(
        ["v1.0.0rc1", "v1.0.0rc2"],
        target="1.0.0",
        requested="v1.0.0rc1",
    )
    assert tag == "v1.0.0rc1"
    assert target_ok is True


def test_auto_detect_rc1_only_scenario_still_works():
    tag, target_ok = rs._select_rc_tag(["v1.0.0rc1"], target="1.0.0", requested=None)
    assert tag == "v1.0.0rc1"
    assert target_ok is True


def test_wrong_target_line_rc_tag_is_ignored_or_rejected():
    tag, target_ok = rs._select_rc_tag(["v1.1.0rc1"], target="1.0.0", requested=None)
    assert tag is None
    assert target_ok is False

    f = _green_facts(rc_tag="v1.1.0rc1")
    f["rc_tag_target_ok"] = False
    assert _decide(f, _green_evidence(), target="1.0.0") == "HALT_VERSION_MISMATCH"


def test_rc2_tag_at_head_promotes_in_green_state():
    f = _green_facts(version="1.0.0rc2", rc_tag="v1.0.0rc2", features_after_rc=False)
    r = rs.evaluate(f, _green_evidence(), target="1.0.0", strict=True)
    assert r["decision"] == "PROMOTE_1_0_READY"
    assert r["rc_tag"] == "v1.0.0rc2"
    assert r["features_after_rc"] is False


def test_rc2_tag_ancestor_but_head_has_new_features_cuts_next_rc():
    f = _green_facts(version="1.0.0rc2", rc_tag="v1.0.0rc2", features_after_rc=True)
    r = rs.evaluate(f, _green_evidence(), target="1.0.0", strict=True)
    assert r["decision"] == "CUT_RC2_READY"
    assert r["rc_tag"] == "v1.0.0rc2"
    assert r["features_after_rc"] is True


def test_legacy_features_after_rc1_fact_remains_compatible():
    f = _green_facts()
    del f["features_after_rc"]
    f["features_after_rc1"] = True
    assert _decide(f, _green_evidence()) == "CUT_RC2_READY"


def test_version_mismatch_halts():
    f = _green_facts()
    f["init_version"] = "1.0.0"  # disagrees with pyproject/lock
    assert _decide(f, _green_evidence()) == "HALT_VERSION_MISMATCH"


def test_missing_rc_tag_halts_version():
    f = _green_facts()
    f["rc_tag_exists"] = False
    assert _decide(f, _green_evidence()) == "HALT_VERSION_MISMATCH"


def test_tests_failing_marker_halts_unsafe():
    e = _green_evidence()
    e["tests_ok"] = False
    e["tests_failed"] = 3
    assert _decide(_green_facts(), e) == "HALT_UNSAFE"


def test_unexpected_dirty_file_halts_unsafe():
    f = _green_facts()
    f["unexpected_dirty"] = ["src/dorian/secret_unreviewed.py"]
    assert _decide(f, _green_evidence()) == "HALT_UNSAFE"


def test_no_public_benchmark_result_stays_rc():
    e = _green_evidence()
    e["benchmark"]["executed"] = False
    assert _decide(_green_facts(), e) == "STAY_RC"


def test_no_machine_claims_stays_rc():
    f = _green_facts()
    f["machine_claims"] = []
    e = _green_evidence()
    e["benchmark"]["executed"] = False  # nothing to execute
    assert _decide(f, e) == "STAY_RC"


def test_benchmark_executed_but_docs_overclaim_halts_unsafe():
    f = _green_facts()
    f["bench_doc_text"] += " This proves dorian works and generalizes."
    assert _decide(f, _green_evidence()) == "HALT_UNSAFE"


def test_nondeterministic_benchmark_halts():
    e = _green_evidence()
    e["benchmark"]["deterministic"] = False
    e["benchmark"]["nondeterministic_fields"] = ["results[0].detail"]
    assert _decide(_green_facts(), e) == "HALT_NONDETERMINISTIC"


def test_benchmark_known_truth_mismatch_is_insufficient_evidence():
    e = _green_evidence()
    e["benchmark"]["all_match"] = False
    assert _decide(_green_facts(), e) == "HALT_INSUFFICIENT_EVIDENCE"


def test_provenance_workflow_absent_cuts_rc2_not_promote():
    f = _green_facts(features_after_rc=False)  # otherwise PROMOTE-eligible
    f["provenance_workflow"] = False
    f["workflows"].pop("release-gate.yml", None)
    assert _decide(f, _green_evidence()) == "CUT_RC2_READY"


def test_provenance_absent_with_require_publish_halts_publish_not_configured():
    f = _green_facts()
    f["provenance_workflow"] = False
    f["testpypi_workflow"] = False
    assert _decide(f, _green_evidence(), require_publish=True) == "HALT_PUBLISH_NOT_CONFIGURED"


def test_pull_request_target_workflow_halts_unsafe():
    f = _green_facts()
    f["workflows"]["evil.yml"] = "on:\n  pull_request_target:\n"
    assert _decide(f, _green_evidence()) == "HALT_UNSAFE"


def test_ci_missing_permissions_halts_unsafe():
    f = _green_facts()
    f["workflows"]["ci.yml"] = "on: [push]\n"  # no permissions block
    assert _decide(f, _green_evidence()) == "HALT_UNSAFE"


def test_missing_log_injection_test_halts_unsafe():
    f = _green_facts()
    f["security"]["log_injection_test"] = False
    assert _decide(f, _green_evidence()) == "HALT_UNSAFE"


def test_strict_missing_evidence_is_insufficient():
    f = _green_facts()
    e = _green_evidence()
    del e["tests_ok"]  # gate result not recorded
    assert _decide(f, e, strict=True) == "HALT_INSUFFICIENT_EVIDENCE"


def test_week2_incomplete_stays_rc():
    f = _green_facts(features_after_rc=False)
    f["week2"]["atomicity_impl"] = False
    assert _decide(f, _green_evidence()) == "STAY_RC"


# ----------------------------------------------------------------- invariants


def test_state_json_is_deterministic_and_sorted():
    f, e = _green_facts(features_after_rc=True), _green_evidence()
    r1 = rs.evaluate(f, e, target="1.0.0", strict=True)
    r2 = rs.evaluate(f, e, target="1.0.0", strict=True)
    a = json.dumps(r1, sort_keys=True, indent=2)
    b = json.dumps(r2, sort_keys=True, indent=2)
    assert a == b  # pure + deterministic
    # canonical serialization the CLI uses is byte-identical on repeat
    assert rs.render_json(r1) == rs.render_json(r2)
    # every state carries id/name/status/blocker
    ids = [s["id"] for s in r1["states"]]
    assert ids == sorted(ids, key=lambda x: int(x[1:]))  # S0..S10 in order
    for s in r1["states"]:
        assert set(s) >= {"id", "name", "status", "evidence", "blocker"}
        assert s["status"] in {"PASS", "FAIL", "SKIP"}


def test_decision_is_from_the_fixed_alphabet():
    r = rs.evaluate(_green_facts(features_after_rc=True), _green_evidence(), target="1.0.0")
    assert r["decision"] in {
        "PROMOTE_1_0_READY",
        "CUT_RC2_READY",
        "STAY_RC",
        "HALT_UNSAFE",
        "HALT_INSUFFICIENT_EVIDENCE",
        "HALT_PUBLISH_NOT_CONFIGURED",
        "HALT_VERSION_MISMATCH",
        "HALT_NONDETERMINISTIC",
    }
    assert "release_claim" in r and "forbidden" in r["release_claim"]


def test_evaluator_never_calls_network_or_llm_or_prompts():
    """Structural guarantee: the module source imports no network/LLM/stdin path
    and never blocks on user input."""
    src = _SRC.read_text(encoding="utf-8")
    for forbidden in (
        "import requests",
        "import socket",
        "import urllib",
        "import http",
        "openai",
        "anthropic",
        "input(",
        "sys.stdin",
    ):
        assert forbidden not in src, f"release_state.py must not reference {forbidden!r}"


def test_parse_porcelain_keeps_leading_dot_and_unquotes():
    # the first ' M path' line must keep its leading '.', and quoted spacey paths unquote
    out = ' M .github/workflows/ci.yml\n?? bench/x.py\n?? "Some Report.md"\n'
    assert rs._parse_porcelain(out) == [
        ".github/workflows/ci.yml",
        "bench/x.py",
        "Some Report.md",
    ]


def test_is_expected_dirty_allows_known_prefixes_and_top_level_md():
    assert rs._is_expected_dirty(".github/workflows/ci.yml")
    assert rs._is_expected_dirty("src/dorian/checkers/c3_ref.py")
    assert rs._is_expected_dirty("Dorian Release v1.0.0rc1 Research Report.md")  # top-level doc
    assert rs._is_expected_dirty("src/dorian/new_module.py")  # any src/dorian/ file is in scope
    assert rs._is_expected_dirty("AGENTS.md")
    assert rs._is_expected_dirty("pyproject.toml")
    assert rs._is_expected_dirty("uv.lock")
    assert not rs._is_expected_dirty("setup.py")  # stray top-level code is NOT expected
    assert not rs._is_expected_dirty("vendor/evil.py")


def test_strip_comments_drops_comment_mentions():
    text = "on:\n  workflow_dispatch:\n# safe by design: NO pull_request_target here\n"
    assert "pull_request_target" not in rs._strip_comments(text)
    assert "workflow_dispatch" in rs._strip_comments(text)


def test_s7_doc_glossary_listing_forbidden_words_still_passes():
    """A doc that ENUMERATES forbidden terms in its 'Allowed vs forbidden wording'
    glossary is honest — only the prose above the glossary is scanned for overclaims."""
    f = _green_facts(features_after_rc=True)
    f["bench_doc_text"] = (
        "Machine-derived benchmark. candidate benchmark subjects reproducible on these "
        "frozen SHAs; trigger and truth layers reported separately.\n\n"
        "## Allowed vs forbidden wording\n"
        "- Forbidden: 'validated on real repos', 'proves dorian works', 'generalizes', "
        "'production-grade', 'proven', 'universal', 'guaranteed', '100% accurate'.\n"
    )
    r = rs.evaluate(f, _green_evidence())
    s7 = next(s for s in r["states"] if s["id"] == "S7")
    assert s7["status"] == "PASS"
    assert r["decision"] == "CUT_RC2_READY"


def test_decision_doc_is_deterministic_and_honest():
    r = rs.evaluate(_green_facts(features_after_rc=True), _green_evidence(), target="1.0.0")
    md1 = rs.render_decision_md(r)
    md2 = rs.render_decision_md(r)
    assert md1 == md2
    assert "CUT_RC2_READY" in md1
    assert "features_after_rc=True" in md1
    assert "features_after_rc1" not in md1
    # the allowed release claim must not itself contain forbidden overclaim language
    allowed = r["release_claim"]["allowed"].lower()
    for bad in ("validated on real repos", "proves dorian works", "100% accurate", "generalizes"):
        assert bad not in allowed


def test_exit_codes_halt_nonzero_decisions_zero():
    assert rs.exit_code("PROMOTE_1_0_READY") == 0
    assert rs.exit_code("CUT_RC2_READY") == 0
    assert rs.exit_code("STAY_RC") == 0
    assert rs.exit_code("HALT_UNSAFE") != 0
    assert rs.exit_code("HALT_VERSION_MISMATCH") != 0
    assert rs.exit_code("HALT_NONDETERMINISTIC") != 0
    assert rs.exit_code("HALT_PUBLISH_NOT_CONFIGURED") != 0
    assert rs.exit_code("HALT_INSUFFICIENT_EVIDENCE") != 0
