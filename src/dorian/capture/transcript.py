"""Read-set capture from a Claude Code session transcript (JSONL).

Assistant records carry message.content[] blocks; tool_use blocks tell us what the
producing run actually read. Write/Edit blocks are outputs, never reads.

The parser is tolerant by design: malformed JSON lines, undecodable bytes, and
schema-odd tool inputs (non-string paths, offset=0) are skipped or repaired —
one bad record must never abort the capture.

Coverage is a heuristic honesty metric, not an exact one: Bash commands whose
first word is not a known read command (including compound forms like
'cd x && cat f.py') are skipped entirely and their path tokens do not count
toward the observed denominator.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dorian import gitio
from dorian.model import ProducedBy, ReadSet, ReadSetEntry, lf_normalize, sha256_hex, span_hash

_BASH_READ_CMDS = frozenset({"cat", "head", "tail", "grep", "sed", "awk", "ls"})
_TEXT_EXTS = frozenset(
    {".py", ".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".rst"}
)
_STRIP_CHARS = "\"'`;|&<>()"


def _looks_like_path(token: str) -> bool:
    return "/" in token or Path(token).suffix.lower() in _TEXT_EXTS


def _tool_use_blocks(path: Path) -> Iterator[dict[str, Any]]:
    # Stream line by line: real session logs reach hundreds of MB. errors="replace"
    # keeps one undecodable byte from aborting the whole capture.
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Guard every level: a syntactically valid line may still be a JSON
            # scalar/array, carry message=null, or otherwise defy the schema.
            if not isinstance(rec, dict) or rec.get("type") != "assistant":
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    yield block


def parse_transcript(path: Path, repo: Path) -> ReadSet:
    """Parse a Claude Code session JSONL into the ReadSet its run actually read.

    coverage = recorded / max(1, observed) per spec; a read-free transcript
    therefore yields coverage 0.0 (nothing observed, nothing recorded).
    """
    repo = repo.resolve()
    head = gitio.head_ref(repo)
    entries: list[ReadSetEntry] = []
    seen: set[tuple[str, str | None]] = set()
    observed = 0  # path tokens seen (coverage denominator)
    recorded = 0  # tokens that yielded a capturable file

    def to_abs(raw: str) -> Path:
        p = Path(raw)
        if not p.is_absolute():
            p = repo / p
        return p.resolve()

    def record(uri: str, selector: str | None, content_hash: str, scope: str) -> None:
        nonlocal recorded
        recorded += 1
        if (uri, selector) in seen:  # dedupe by (uri, selector), keep first
            return
        seen.add((uri, selector))
        entries.append(
            ReadSetEntry(
                id=f"rs-{len(entries)}",
                uri=uri,
                selector=selector,
                hash=content_hash,
                version=head,
                scope=scope,
            )
        )

    def read_token(raw: str, selector: str | None = None) -> None:
        nonlocal observed
        observed += 1
        p = to_abs(raw)
        try:
            uri = p.relative_to(repo).as_posix()
        except ValueError:
            if p.is_file():  # outside repo but real: external, absolute uri
                text = lf_normalize(p.read_bytes())
                h = (
                    span_hash(text.decode("utf-8", errors="replace"), selector)
                    if selector
                    else sha256_hex(text)
                )
                record(str(p), selector, h, "external")
            return
        h = gitio.working_hash(repo, uri, selector)
        if h is not None:  # vanished files count only toward the denominator
            record(uri, selector, h, "project")

    for block in _tool_use_blocks(path):
        name, inp = block.get("name"), block.get("input")
        if not isinstance(inp, dict):  # 'input' may be present as JSON null/list
            continue
        if name == "Read":
            raw = inp.get("file_path")
            if not isinstance(raw, str) or not raw:
                continue
            selector = None
            offset, limit = inp.get("offset"), inp.get("limit")
            if isinstance(offset, int) and isinstance(limit, int) and limit >= 1:
                start = max(1, offset)  # the Read schema allows offset=0 (start of file)
                selector = f"L{start}-{start + limit - 1}"
            read_token(raw, selector)
        elif name in ("Grep", "Glob"):
            raw = inp.get("path")
            if not isinstance(raw, str) or not raw:
                continue
            observed += 1
            p = to_abs(raw)
            if p.is_file():  # directories count in the denominator, unrecorded
                try:
                    uri = p.relative_to(repo).as_posix()
                except ValueError:
                    # Deliberate asymmetry with Read: a Grep/Glob target outside the
                    # repo is a search root, not an explicitly read file — count it
                    # in the denominator but do not record an external entry.
                    continue
                h = gitio.working_hash(repo, uri, None)
                if h is not None:
                    record(uri, None, h, "project")
        elif name == "Bash":
            cmd = inp.get("command")
            if not isinstance(cmd, str):
                continue
            try:
                words = shlex.split(cmd)  # keeps quoted paths with spaces whole
            except ValueError:  # unbalanced quotes: degrade to whitespace split
                words = cmd.split()
            if not words or words[0] not in _BASH_READ_CMDS:
                continue
            for tok in words[1:]:
                tok = tok.strip(_STRIP_CHARS)
                if not tok or tok.startswith("-") or not _looks_like_path(tok):
                    continue
                read_token(tok)
        # Write/Edit/NotebookEdit and all other tools: outputs or non-reads, ignored

    produced_by = ProducedBy(
        runner="claude-code",
        captured_at=datetime.now(UTC).isoformat(),
        run_ref=str(path),
    )
    return ReadSet(
        entries=tuple(entries),
        produced_by=produced_by,
        coverage=recorded / max(1, observed),
    )
