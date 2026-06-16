"""Machine-derived claim synthesizer (bench/public_claims.py).

Deterministic, offline (a tiny in-tree fixture, never a real clone). Proves: claim
operands are EXTRACTED from source, known_truth is OBSERVED by running the C3 checker
on the mutated copy, non-literal / non-TOML-JSON / non-unique-mutation targets are
auto-REJECTED (not ERRORED into the benchmark), and only an all-valid target set is
promoted to benchmark-ready.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import public_claims as pc  # noqa: E402

MOD = '''\
def greet(name, greeting="hi"):
    return greeting + name


def farewell(name):
    """say bye"""
    return name  # bye-comment


TIMEOUT = 30
POWERS = [10**x for x in (1, 2)]
ROUTES = {"login": "/v1/login"}
'''

CONF_TOML = "[tool]\nlimit = 5\n"
CONF_YAML = "x: 1\n"


def _fixture(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(MOD, encoding="utf-8")
    (tmp_path / "conf.toml").write_text(CONF_TOML, encoding="utf-8")
    (tmp_path / "conf.yaml").write_text(CONF_YAML, encoding="utf-8")
    return tmp_path


# valid targets (one per allowed origin) + a TRUSTED control
_VALID = [
    {
        "id": "greet-sig",
        "kind": "py-signature",
        "file": "pkg/mod.py",
        "name": "greet",
        "intent": "break",
        "mutation": {
            "id": "m-greet",
            "from": 'def greet(name, greeting="hi"):',
            "to": 'def greet(who, greeting="hi"):',
        },
    },
    {
        "id": "farewell-control",
        "kind": "py-signature",
        "file": "pkg/mod.py",
        "name": "farewell",
        "intent": "control",
        "mutation": {
            "id": "m-farewell",
            "from": "return name  # bye-comment",
            "to": "return name  # adieu-comment",
        },
    },
    {
        "id": "timeout-const",
        "kind": "py-const",
        "file": "pkg/mod.py",
        "name": "TIMEOUT",
        "intent": "break",
        "mutation": {"id": "m-timeout", "from": "TIMEOUT = 30", "to": "TIMEOUT = 31"},
    },
    {
        "id": "limit-config",
        "kind": "config-value",
        "file": "conf.toml",
        "key": "tool.limit",
        "intent": "break",
        "mutation": {"id": "m-limit", "from": "limit = 5", "to": "limit = 6"},
    },
    {
        "id": "route-code",
        "kind": "code",
        "file": "pkg/mod.py",
        "token": "/v1/login",
        "intent": "break",
        "mutation": {"id": "m-route", "from": '"/v1/login"', "to": '"/v2/login"'},
    },
]


def test_all_valid_targets_promote_with_proof_objects(tmp_path):
    repo = _fixture(tmp_path)
    claims_doc, mutations_doc, rejected = pc.synthesize(repo, _VALID, artifact="change-note.md")
    assert rejected == []
    assert claims_doc["status"] == "benchmark-ready"
    assert mutations_doc["status"] == "benchmark-ready"
    assert len(claims_doc["claims"]) == len(_VALID)
    allowed_origins = set(pc._ORIGIN.values())
    for c in claims_doc["claims"]:
        assert isinstance(c["proof"], dict)  # (test 1) every claim has a proof object
        assert c["proof"]["origin"] in allowed_origins
        assert c["proof"]["deterministic"] is True
        for fld in (
            "source_file",
            "checker_operand",
            "expected_value",
            "mutation_id",
            "known_truth_rule",
            "known_truth_observed",
        ):
            assert c["proof"][fld]


def test_known_truth_is_observed_not_asserted(tmp_path):
    repo = _fixture(tmp_path)
    _claims_doc, mutations_doc, _ = pc.synthesize(repo, _VALID, artifact="a.md")
    truth = {m["claim_id"]: m["known_truth"] for m in mutations_doc["mutations"]}
    assert truth["greet-sig"] == "BROKEN"
    assert truth["timeout-const"] == "BROKEN"
    assert truth["limit-config"] == "BROKEN"
    assert truth["route-code"] == "BROKEN"
    assert truth["farewell-control"] == "TRUSTED"  # comment-only edit observed PASS -> TRUSTED


def test_non_literal_py_const_is_rejected_not_errored(tmp_path):
    repo = _fixture(tmp_path)
    target = {
        "id": "powers-const",
        "kind": "py-const",
        "file": "pkg/mod.py",
        "name": "POWERS",  # RHS is a list comprehension -> not literal_eval-able
        "intent": "break",
        "mutation": {"id": "m-pow", "from": "(1, 2)", "to": "(1, 3)"},
    }
    claims_doc, _, rejected = pc.synthesize(repo, [target], artifact="a.md")
    assert claims_doc["status"] != "benchmark-ready"
    assert claims_doc["claims"] == []
    assert rejected and rejected[0]["id"] == "powers-const"
    assert "literal" in rejected[0]["reason"]


def test_config_value_only_for_toml_json(tmp_path):
    repo = _fixture(tmp_path)
    target = {
        "id": "yaml-config",
        "kind": "config-value",
        "file": "conf.yaml",  # unsupported extension
        "key": "x",
        "intent": "break",
        "mutation": {"id": "m-x", "from": "x: 1", "to": "x: 2"},
    }
    _, _, rejected = pc.synthesize(repo, [target], artifact="a.md")
    assert rejected and "toml/.json" in rejected[0]["reason"]


def test_mutation_must_match_exactly_once(tmp_path):
    repo = _fixture(tmp_path)
    target = {
        "id": "dup",
        "kind": "py-const",
        "file": "pkg/mod.py",
        "name": "TIMEOUT",
        "intent": "break",
        "mutation": {"id": "m-dup", "from": "name", "to": "nom"},  # 'name' occurs many times
    }
    _, _, rejected = pc.synthesize(repo, [target], artifact="a.md")
    assert rejected and "exactly 1" in rejected[0]["reason"]


def test_one_rejected_target_prevents_benchmark_ready(tmp_path):
    repo = _fixture(tmp_path)
    bad = {
        "id": "powers-const",
        "kind": "py-const",
        "file": "pkg/mod.py",
        "name": "POWERS",
        "intent": "break",
        "mutation": {"id": "m-pow", "from": "(1, 2)", "to": "(1, 3)"},
    }
    claims_doc, _, rejected = pc.synthesize(repo, [_VALID[0], bad], artifact="a.md")
    assert rejected  # one bad target
    assert claims_doc["status"] == "draft-incomplete"  # not benchmark-ready


def test_output_is_byte_stable(tmp_path):
    repo = _fixture(tmp_path)
    a = pc.synthesize(repo, _VALID, artifact="a.md")
    b = pc.synthesize(repo, _VALID, artifact="a.md")
    assert json.dumps(a[0], sort_keys=True) == json.dumps(b[0], sort_keys=True)
    assert json.dumps(a[1], sort_keys=True) == json.dumps(b[1], sort_keys=True)


def test_claim_text_is_templated_not_freeform_semantics(tmp_path):
    """Broad natural-language semantic claims are impossible: every claim text is a
    fixed template over the extracted fact, and every origin is a generated-* tag."""
    repo = _fixture(tmp_path)
    claims_doc, _, _ = pc.synthesize(repo, _VALID, artifact="a.md")
    for c in claims_doc["claims"]:
        assert c["text"].startswith("In pkg/") or c["text"].startswith("In conf.")
        assert c["proof"]["origin"].startswith("generated-")


def test_write_generated_only_writes_claims_json_when_ready(tmp_path):
    repo = _fixture(tmp_path)
    out = tmp_path / "out"
    # all valid -> promoted
    docs = pc.synthesize(repo, _VALID, artifact="a.md")
    assert pc.write_generated(out, *docs) is True
    assert (out / "claims.json").is_file()
    assert (out / "mutations.yaml").is_file()
    assert (out / "claims.generated.json").is_file()
    # a rejected target -> NOT promoted, no claims.json overwrite
    out2 = tmp_path / "out2"
    bad = dict(_VALID[2])
    bad["mutation"] = {"id": "x", "from": "DOES_NOT_EXIST", "to": "y"}
    docs2 = pc.synthesize(repo, [bad], artifact="a.md")
    assert pc.write_generated(out2, *docs2) is False
    assert not (out2 / "claims.json").exists()
    assert (out2 / "claims.generated.json").is_file()  # audit trail still written


def test_generated_doc_marks_machine_derived_provenance(tmp_path):
    repo = _fixture(tmp_path)
    claims_doc, _, _ = pc.synthesize(repo, _VALID, artifact="a.md")
    assert claims_doc["extractor"] == pc.EXTRACTOR
    assert "machine-derived" in claims_doc["_provenance"]
