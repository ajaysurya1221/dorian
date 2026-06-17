"""Optional, experimental in-toto interop: render a sealed `.warrant` as an
in-toto Statement carrying a `ClaimVerification` predicate.

in-toto's vetted predicate registry has no ClaimVerification type (closest:
Test Result, Vulnerability, VSA), so dorian emits its own experimental
predicate type. This is a pure, deterministic projection of the warrant body —
no signing, no DSSE, no extra dependencies. The Statement attests *what dorian
sealed and verified at seal time*; the LIVE trust state (which can drift later)
comes from `dorian status`, not from this static export.
"""

from __future__ import annotations

from typing import Any

from dorian.model import SPEC_VERSION, Warrant

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://dorian.vwp/attestations/ClaimVerification/v0.1"


def _subject_digest(artifact_hash: str) -> dict[str, str]:
    """Map dorian's `<algo>:<hex>` artifact hash to an in-toto digest set."""
    algo, sep, hexd = artifact_hash.partition(":")
    if sep and hexd:
        return {algo: hexd}
    return {"sha256": artifact_hash}  # bare hex fallback


def warrant_to_statement(warrant: Warrant, *, dorian_version: str) -> dict[str, Any]:
    """Project a sealed Warrant into an in-toto v1 Statement (a plain dict).

    Deterministic: the same warrant + version always yields the same dict, so a
    caller can dump it with sorted keys for a byte-stable attestation.
    """
    predicate: dict[str, Any] = {
        "warrantId": warrant.id,
        "specVersion": SPEC_VERSION,
        "dorianVersion": dorian_version,
        "gitRef": warrant.git_ref,
        "sealedAt": warrant.sealed_at,
        # the seal is born-verifiable: it exists only because every backed claim
        # passed its deterministic checker at seal time (a FAIL/ERROR refuses it).
        "bornVerifiable": True,
        "producedBy": warrant.produced_by.to_dict(),
        "claims": [
            {
                "id": c.id,
                "text": c.text,
                "kind": c.kind,
                "loadBearing": c.load_bearing,
                "backed": c.backed,
                "checkers": [{"type": ck.type, "program": ck.program} for ck in c.checkers],
            }
            for c in warrant.claims
        ],
    }
    return {
        "_type": STATEMENT_TYPE,
        "subject": [
            {"name": warrant.artifact_uri, "digest": _subject_digest(warrant.artifact_hash)}
        ],
        "predicateType": PREDICATE_TYPE,
        "predicate": predicate,
    }
