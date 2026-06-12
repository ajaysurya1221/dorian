"""Thin git plumbing used by capture, checkers, and revalidation.

All functions take a repo root and shell out to git; no state is kept. Renames are
first-class because C1's relocation tolerance depends on them.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from dorian.model import lf_normalize, sha256_hex, span_hash


class GitError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def head_ref(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def actor(repo: Path) -> str:
    """Audit actor: git author name, else $USER, else ''. Never raises."""
    try:
        name = _git(repo, "config", "user.name").strip()
        if name:
            return name
    except GitError:
        pass
    return os.environ.get("USER", "")


def ls_files(repo: Path) -> list[str]:
    """Tracked paths (git ls-files), repo-relative posix, sorted. -z avoids
    core.quotepath mangling of non-ASCII names."""
    return sorted(p for p in _git(repo, "ls-files", "-z").split("\0") if p)


def changed_paths(repo: Path, since_ref: str) -> tuple[list[str], dict[str, str]]:
    """Paths changed between since_ref and the working tree, with a rename map.

    Returns (changed, rename_map) where changed contains repo-relative paths —
    for renames both the old and new path — and rename_map maps old -> new.
    Includes uncommitted working-tree changes (diff against since_ref directly).
    """
    out = _git(repo, "diff", "--name-status", "--find-renames", since_ref)
    changed: list[str] = []
    renames: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) == 3:
            old, new = parts[1], parts[2]
            renames[old] = new
            changed.extend([old, new])
        elif len(parts) >= 2:
            changed.append(parts[1])
    return changed, renames


def file_at_ref(repo: Path, ref: str, path: str) -> bytes | None:
    """File content at a git ref, LF-normalized; None if absent at that ref."""
    proc = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True, check=False
    )
    if proc.returncode != 0:
        return None
    return lf_normalize(proc.stdout)


def working_file(repo: Path, path: str) -> bytes | None:
    """Working-tree file content, LF-normalized; None if missing."""
    p = repo / path
    if not p.is_file():
        return None
    return lf_normalize(p.read_bytes())


def working_hash(repo: Path, path: str, selector: str | None = None) -> str | None:
    """Hash of a working-tree file (or span); None if the file is missing."""
    data = working_file(repo, path)
    if data is None:
        return None
    if selector is None:
        return sha256_hex(data)
    return span_hash(data.decode("utf-8", errors="replace"), selector)


def span_at_ref(repo: Path, ref: str, path: str, selector: str | None) -> str | None:
    """The original span text at a ref (for C1 relocation); None if unreachable."""
    data = file_at_ref(repo, ref, path)
    if data is None:
        return None
    from dorian.model import extract_span

    return extract_span(data.decode("utf-8", errors="replace"), selector)
