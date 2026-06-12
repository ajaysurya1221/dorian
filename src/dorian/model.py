"""Core VWP data model.

`.warrant` sidecars are the git-committed source of truth; everything here must
round-trip through canonical JSON deterministically. The SQLite store is a derived
index built from these objects.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

SPEC_VERSION = "0.1"

CheckerType = Literal["C1", "C3", "C4", "C5"]
ClaimKind = Literal["fact", "reference", "behavior", "quantity", "decision"]
ClaimState = Literal["PROPOSED", "UNBACKED", "VERIFIED", "BROKEN", "ERRORED", "SUPERSEDED"]
TrustState = Literal["WARRANTED", "TRUSTED", "DEGRADED", "REVOKED", "UNKNOWN", "SUPERSEDED"]

_SELECTOR_RE = re.compile(r"^L(\d+)-(\d+)$")


def lf_normalize(data: bytes) -> bytes:
    """Normalize CRLF/CR to LF so span hashes are platform-stable."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> bytes:
    """Canonical JSON: sorted keys, minimal separators, UTF-8. Hash-stable."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def parse_selector(selector: str | None) -> tuple[int, int] | None:
    """Parse a span selector like 'L40-88' into 1-based inclusive line bounds."""
    if selector is None:
        return None
    m = _SELECTOR_RE.match(selector)
    if not m:
        raise ValueError(f"bad selector: {selector!r}")
    start, end = int(m.group(1)), int(m.group(2))
    if start < 1 or end < start:
        raise ValueError(f"bad selector bounds: {selector!r}")
    return start, end


def extract_span(text: str, selector: str | None) -> str:
    """Extract the selector's lines (inclusive) from LF-normalized text.

    With no selector, returns the whole text. Out-of-range selectors return the
    intersecting lines (callers treat a shrunken file as drift via hashing).
    """
    bounds = parse_selector(selector)
    if bounds is None:
        return text
    start, end = bounds
    lines = text.split("\n")
    return "\n".join(lines[start - 1 : end])


def span_hash(text: str, selector: str | None) -> str:
    return sha256_hex(extract_span(text, selector).encode("utf-8"))


@dataclass(frozen=True)
class ReadSetEntry:
    id: str
    uri: str  # repo-relative path for project files
    selector: str | None  # 'L<start>-<end>' or None for whole file
    hash: str  # sha256:* of the (span of the) LF-normalized content
    version: str | None  # git SHA at capture time
    scope: str = "project"  # project | external | unknown

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "uri": self.uri,
            "selector": self.selector,
            "hash": self.hash,
            "version": self.version,
            "scope": self.scope,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ReadSetEntry:
        return ReadSetEntry(
            id=d["id"],
            uri=d["uri"],
            selector=d.get("selector"),
            hash=d["hash"],
            version=d.get("version"),
            scope=d.get("scope", "project"),
        )


@dataclass(frozen=True)
class Anchor:
    line_start: int
    line_end: int
    quote: str = ""  # exact artifact substring; empty in --no-quotes mode (ring 1)

    def to_dict(self) -> dict[str, Any]:
        return {"line_start": self.line_start, "line_end": self.line_end, "quote": self.quote}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Anchor:
        return Anchor(line_start=d["line_start"], line_end=d["line_end"], quote=d.get("quote", ""))


@dataclass(frozen=True)
class CheckerSpec:
    type: str  # C1 | C3 | C4 | C5
    program: str  # type-specific grammar; see spec/checkers.md
    expect: str = "exit:0"  # exit:0 | regex:<re> | eq:<literal> (shell C5 only)
    watch: tuple[str, ...] = ()  # repo-relative paths/globs that trigger re-check
    timeout_s: int = 30

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "program": self.program,
            "expect": self.expect,
            "watch": list(self.watch),
            "timeout_s": self.timeout_s,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> CheckerSpec:
        return CheckerSpec(
            type=d["type"],
            program=d["program"],
            expect=d.get("expect", "exit:0"),
            watch=tuple(d.get("watch", ())),
            timeout_s=d.get("timeout_s", 30),
        )


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    kind: str
    load_bearing: bool
    anchor: Anchor | None = None
    supports: tuple[str, ...] = ()  # ReadSetEntry ids
    checkers: tuple[CheckerSpec, ...] = ()

    @property
    def backed(self) -> bool:
        return len(self.checkers) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "anchor": self.anchor.to_dict() if self.anchor else None,
            "load_bearing": self.load_bearing,
            "supports": list(self.supports),
            "checkers": [c.to_dict() for c in self.checkers],
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Claim:
        return Claim(
            id=d["id"],
            text=d["text"],
            kind=d["kind"],
            anchor=Anchor.from_dict(d["anchor"]) if d.get("anchor") else None,
            load_bearing=d["load_bearing"],
            supports=tuple(d.get("supports", ())),
            checkers=tuple(CheckerSpec.from_dict(c) for c in d.get("checkers", ())),
        )


@dataclass(frozen=True)
class ProducedBy:
    runner: str  # claude-code | manual | bench-synthetic
    captured_at: str  # RFC3339
    run_ref: str = ""
    model: str = ""
    prompt_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner": self.runner,
            "captured_at": self.captured_at,
            "run_ref": self.run_ref,
            "model": self.model,
            "prompt_hash": self.prompt_hash,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ProducedBy:
        return ProducedBy(
            runner=d["runner"],
            captured_at=d["captured_at"],
            run_ref=d.get("run_ref", ""),
            model=d.get("model", ""),
            prompt_hash=d.get("prompt_hash", ""),
        )


@dataclass(frozen=True)
class FoldPolicy:
    revoke_on: str = "load_bearing_broken"  # | any_broken
    degrade_on: str = "any_stale_or_broken"  # | any_broken

    def to_dict(self) -> dict[str, Any]:
        return {"revoke_on": self.revoke_on, "degrade_on": self.degrade_on}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> FoldPolicy:
        return FoldPolicy(
            revoke_on=d.get("revoke_on", "load_bearing_broken"),
            degrade_on=d.get("degrade_on", "any_stale_or_broken"),
        )


@dataclass(frozen=True)
class Warrant:
    id: str  # sha256:* of canonical body (everything below except id)
    artifact_uri: str
    artifact_hash: str
    git_ref: str
    produced_by: ProducedBy
    read_set: tuple[ReadSetEntry, ...]
    claims: tuple[Claim, ...]
    fold_policy: FoldPolicy
    sealed_at: str
    derives_from: tuple[str, ...] = ()
    supersedes: str | None = None

    def body_dict(self) -> dict[str, Any]:
        """The id-free body whose canonical JSON is hashed into the warrant id."""
        return {
            "artifact": {
                "uri": self.artifact_uri,
                "content_hash": self.artifact_hash,
                "git_ref": self.git_ref,
            },
            "produced_by": self.produced_by.to_dict(),
            "read_set": [e.to_dict() for e in self.read_set],
            "claims": [c.to_dict() for c in self.claims],
            "derives_from": list(self.derives_from),
            "fold_policy": self.fold_policy.to_dict(),
            "sealed_at": self.sealed_at,
            "supersedes": self.supersedes,
        }

    @staticmethod
    def compute_id(body: dict[str, Any]) -> str:
        return sha256_hex(canonical_json(body))

    def to_dict(self) -> dict[str, Any]:
        body = self.body_dict()
        return {"spec_version": SPEC_VERSION, "warrant": {"id": self.id, **body}}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Warrant:
        w = d["warrant"]
        return Warrant(
            id=w["id"],
            artifact_uri=w["artifact"]["uri"],
            artifact_hash=w["artifact"]["content_hash"],
            git_ref=w["artifact"].get("git_ref", ""),
            produced_by=ProducedBy.from_dict(w["produced_by"]),
            read_set=tuple(ReadSetEntry.from_dict(e) for e in w.get("read_set", ())),
            claims=tuple(Claim.from_dict(c) for c in w.get("claims", ())),
            fold_policy=FoldPolicy.from_dict(w.get("fold_policy", {})),
            sealed_at=w["sealed_at"],
            derives_from=tuple(w.get("derives_from", ())),
            supersedes=w.get("supersedes"),
        )

    @staticmethod
    def create(**kwargs: Any) -> Warrant:
        """Build a Warrant computing its content-addressed id from the body."""
        w = Warrant(id="", **kwargs)
        return Warrant(id=Warrant.compute_id(w.body_dict()), **kwargs)

    def sidecar_path(self, repo: Path) -> Path:
        return repo / (self.artifact_uri + ".warrant")

    def dump(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n")

    @staticmethod
    def load(path: Path) -> Warrant:
        w = Warrant.from_dict(json.loads(path.read_text()))
        recomputed = Warrant.compute_id(w.body_dict())
        if recomputed != w.id:
            raise IntegrityError(f"warrant id mismatch in {path}: {w.id} != {recomputed}")
        return w


class IntegrityError(Exception):
    """Sidecar content does not match its content-addressed id."""


@dataclass(frozen=True)
class ReadSet:
    """Capture output: the entries a producing run actually read."""

    entries: tuple[ReadSetEntry, ...]
    produced_by: ProducedBy
    coverage: float = 1.0  # captured paths / path tokens observed (transcript mode)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "produced_by": self.produced_by.to_dict(),
            "coverage": self.coverage,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ReadSet:
        return ReadSet(
            entries=tuple(ReadSetEntry.from_dict(e) for e in d["entries"]),
            produced_by=ProducedBy.from_dict(d["produced_by"]),
            coverage=d.get("coverage", 1.0),
        )

    def dump(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n")

    @staticmethod
    def load(path: Path) -> ReadSet:
        return ReadSet.from_dict(json.loads(path.read_text()))

    def entry(self, entry_id: str) -> ReadSetEntry:
        for e in self.entries:
            if e.id == entry_id:
                return e
        raise KeyError(entry_id)
