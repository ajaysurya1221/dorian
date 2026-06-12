"""Manual read-set capture from explicit 'path' or 'path:Lx-y' specs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dorian import gitio
from dorian.model import ProducedBy, ReadSet, ReadSetEntry, parse_selector


def parse_manual(specs: list[str], repo: Path) -> ReadSet:
    """Build a ReadSet from user-supplied specs. Raises ValueError on a missing
    file or a malformed selector; manual capture is exhaustive (coverage 1.0).

    Known limits, both deliberate for explicit user input:
    - The last ':' always starts a selector, so a filename containing a literal
      ':' cannot be expressed — it fails loudly with a bad-selector error.
    - Specs are taken literally: unlike transcript capture (which dedupes on
      (uri, selector)), duplicate specs yield duplicate entries.
    """
    repo = repo.resolve()
    head = gitio.head_ref(repo)
    entries: list[ReadSetEntry] = []
    for spec in specs:
        raw, selector = spec, None
        if ":" in spec:
            raw, sel = spec.rsplit(":", 1)
            parse_selector(sel)  # raises ValueError on a bad selector
            selector = sel
        p = Path(raw)
        # Resolve both absolute and relative specs and require repo containment,
        # so '../x' or 'src/../../x' cannot escape and be hashed as 'project'.
        resolved = (p if p.is_absolute() else repo / p).resolve()
        try:
            uri = resolved.relative_to(repo).as_posix()
        except ValueError:
            raise ValueError(f"path outside repo: {raw}") from None
        h = gitio.working_hash(repo, uri, selector)
        if h is None:
            raise ValueError(f"missing file: {raw}")
        entries.append(
            ReadSetEntry(
                id=f"rs-{len(entries)}",
                uri=uri,
                selector=selector,
                hash=h,
                version=head,
                scope="project",
            )
        )
    produced_by = ProducedBy(runner="manual", captured_at=datetime.now(UTC).isoformat())
    return ReadSet(entries=tuple(entries), produced_by=produced_by, coverage=1.0)
