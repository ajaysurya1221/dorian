"""Manifest + mutation validation for the public-repo micro-benchmark harness.

These pin the input contract: a manifest entry that is eligible must be a public repo
with a frozen SHA and a supported permissive license; mutations must carry an explicit
known-truth label. The committed two-repo `repos.public.json` stays protocol-only and is
never treated as executed evidence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # bench/ is a repo-root package, not installed
    sys.path.insert(0, str(REPO_ROOT))

from bench import public_repos as pr  # noqa: E402


def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


VALID_MANIFEST = """
schema_version: 1
benchmark: public-repos
status: candidate-frozen-shas-no-results
repos:
  - name: humanize
    url: https://github.com/python-humanize/humanize
    frozen_sha: 2ddb5903cdc1c7e6eb6b083f4f99f73db50aecd9
    license: MIT
    public: true
    eligible: true
    needs_exec: false
    claims: repos/humanize/claims.json
    mutations: repos/humanize/mutations.yaml
"""


def test_manifest_parses_valid(tmp_path: Path) -> None:
    m = _write(tmp_path / "manifest.yaml", VALID_MANIFEST)
    repos = pr.load_manifest(m)
    assert [r.name for r in repos] == ["humanize"]
    r = repos[0]
    assert r.license == "MIT"
    assert r.frozen_sha == "2ddb5903cdc1c7e6eb6b083f4f99f73db50aecd9"
    assert r.eligible is True
    assert r.needs_exec is False


def test_manifest_rejects_missing_sha(tmp_path: Path) -> None:
    bad = VALID_MANIFEST.replace("    frozen_sha: 2ddb5903cdc1c7e6eb6b083f4f99f73db50aecd9\n", "")
    m = _write(tmp_path / "manifest.yaml", bad)
    with pytest.raises(pr.ManifestError, match="frozen_sha"):
        pr.load_manifest(m)


def test_manifest_rejects_missing_license(tmp_path: Path) -> None:
    bad = VALID_MANIFEST.replace("    license: MIT\n", "")
    m = _write(tmp_path / "manifest.yaml", bad)
    with pytest.raises(pr.ManifestError, match="license"):
        pr.load_manifest(m)


def test_manifest_rejects_non_public(tmp_path: Path) -> None:
    bad = VALID_MANIFEST.replace("    public: true\n", "    public: false\n")
    m = _write(tmp_path / "manifest.yaml", bad)
    with pytest.raises(pr.ManifestError, match="public"):
        pr.load_manifest(m)


def test_manifest_rejects_unsupported_license(tmp_path: Path) -> None:
    bad = VALID_MANIFEST.replace("    license: MIT\n", "    license: GPL-3.0\n")
    m = _write(tmp_path / "manifest.yaml", bad)
    with pytest.raises(pr.ManifestError, match="license"):
        pr.load_manifest(m)


def test_ineligible_entry_is_kept_with_reason_not_rejected(tmp_path: Path) -> None:
    """An eligible:false entry documents an exclusion; it carries a reason and is NOT
    validated for SHA/license strictness (it will be skipped at run time, never run)."""
    text = (
        VALID_MANIFEST
        + """\
  - name: sigstore-python
    url: https://github.com/sigstore/sigstore-python
    license: NOASSERTION
    eligible: false
    reason: SPDX unconfirmed (GitHub returns NOASSERTION)
"""
    )
    m = _write(tmp_path / "manifest.yaml", text)
    repos = pr.load_manifest(m)
    sigstore = next(r for r in repos if r.name == "sigstore-python")
    assert sigstore.eligible is False
    assert "NOASSERTION" in sigstore.reason
    # eligible:false without a reason is itself an error
    no_reason = text.replace("    reason: SPDX unconfirmed (GitHub returns NOASSERTION)\n", "")
    m2 = _write(tmp_path / "m2.yaml", no_reason)
    with pytest.raises(pr.ManifestError, match="reason"):
        pr.load_manifest(m2)


def test_committed_manifest_v1_parses_and_flags_sigstore() -> None:
    repos = pr.load_manifest(REPO_ROOT / "bench" / "public" / "manifest.v1.yaml")
    names = {r.name for r in repos}
    assert {"humanize", "python-dotenv", "tomli", "bandit", "jaffle_shop_duckdb"} <= names
    sigstore = next(r for r in repos if r.name == "sigstore-python")
    assert sigstore.eligible is False  # NOASSERTION license, excluded not swapped
    jaffle = next(r for r in repos if r.name == "jaffle_shop_duckdb")
    assert jaffle.needs_exec is True  # C5 data claims need a build step


def test_repos_public_json_is_not_executed_evidence() -> None:
    data = json.loads((REPO_ROOT / "bench" / "public" / "repos.public.json").read_text())
    assert data["status"] == "protocol-only-no-results"
    assert not pr.is_executed_evidence(data)


MUTATIONS_YAML = """
schema_version: 1
mutations:
  - id: break-add-sig
    claim_id: add-sig
    file: src/mod.py
    op: replace
    from: "def add(a, b)"
    to: "def add(a, b, c)"
    known_truth: BROKEN
"""


def test_mutations_parse_and_carry_known_truth(tmp_path: Path) -> None:
    m = _write(tmp_path / "mutations.yaml", MUTATIONS_YAML)
    muts = pr.parse_mutations(m)
    assert len(muts) == 1
    assert muts[0].known_truth == "BROKEN"
    assert muts[0].claim_id == "add-sig"


def test_mutations_reject_missing_known_truth(tmp_path: Path) -> None:
    bad = MUTATIONS_YAML.replace("    known_truth: BROKEN\n", "")
    m = _write(tmp_path / "mutations.yaml", bad)
    with pytest.raises(pr.MutationError, match="known_truth"):
        pr.parse_mutations(m)


def test_mutations_reject_unknown_label(tmp_path: Path) -> None:
    bad = MUTATIONS_YAML.replace("known_truth: BROKEN", "known_truth: MAYBE")
    m = _write(tmp_path / "mutations.yaml", bad)
    with pytest.raises(pr.MutationError, match="known_truth"):
        pr.parse_mutations(m)


@pytest.mark.parametrize("label", ["BROKEN", "TRUSTED", "ERRORED_EXPECTED"])
def test_mutations_accept_the_three_labels(tmp_path: Path, label: str) -> None:
    text = MUTATIONS_YAML.replace("known_truth: BROKEN", f"known_truth: {label}")
    m = _write(tmp_path / "mutations.yaml", text)
    assert pr.parse_mutations(m)[0].known_truth == label
