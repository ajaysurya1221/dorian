"""Safe, atomic, deterministic writers for local governance sidecar files. Stdlib only.

No model, no network, no clock, no randomness, no global/process state. These helpers only
*write* local sidecar files inside a repository; their output is never read back as an input
to ``loop._decide`` (so they cannot influence a verdict), and they are deliberately NOT a
ledger and NOT a sandbox:

- Containment is enforced by resolving both the root and the target and checking
  ``Path.is_relative_to`` (never a string-prefix or ``commonpath`` compare). ``resolve``
  follows symlinks, so a symlinked path component that escapes the root is rejected.
- There is a benign time-of-check/time-of-use window between the containment check and the
  atomic replace; for local, single-writer sidecars in a trusted repo this is acceptable
  (the trust boundary is the repo + git identity, not OS-level isolation).
- Durability is git's job at commit time, so we do not ``fsync`` — we only guarantee that a
  reader never observes a torn/partial file, via a same-directory temp write + ``os.replace``.
"""

from __future__ import annotations

import json
from pathlib import Path


def ensure_within(base: Path, target: Path) -> Path:
    """Resolve ``target`` and confirm it lies inside ``base``; return the normalized path.

    ``target`` may be relative (resolved under ``base``) or absolute. Both ``base`` and the
    resolved target are passed through ``Path.resolve`` so that ``..`` segments and symlinks
    are normalized consistently before the containment check. Path traversal (``../``) and
    absolute paths that land outside ``base`` raise ``ValueError``. This is containment, not
    sandboxing.
    """
    base_resolved = base.resolve()
    target_resolved = (target if target.is_absolute() else base_resolved / target).resolve()
    if not target_resolved.is_relative_to(base_resolved):
        raise ValueError(f"path escapes root: {target} is not within {base}")
    return target_resolved


def write_sidecar(repo: Path, rel_path: str, payload: dict) -> Path:
    """Atomically write ``payload`` as deterministic JSON to ``rel_path`` under ``repo``.

    ``rel_path`` must be a relative path naming a file under ``repo``. Parent directories are
    created as needed; writes outside ``repo`` (``../`` or absolute) are refused via
    ``ensure_within``. The JSON is serialized with sorted keys, 2-space indent, and a single
    trailing newline (stable on disk and in git), then moved into place via a same-directory
    temp file and ``os.replace`` so a reader never sees a partial file. Returns the final
    path. Does not read or influence Dorian verdicts; not a ledger; no hash chain; no
    timestamps, nonces, clocks, or randomness.
    """
    rel = Path(rel_path)
    if rel.is_absolute():
        raise ValueError(f"rel_path must be relative, got absolute: {rel_path!r}")
    if not rel.parts:
        raise ValueError(f"rel_path must name a file, got empty or '.': {rel_path!r}")

    target = ensure_within(repo, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(data, encoding="utf-8", newline="\n")
    tmp.replace(target)
    return target
