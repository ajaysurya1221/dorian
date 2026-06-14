"""Controlled-mutation benchmark (numbers-only, known-truth labels).

This benchmark measures dorian's claim-level revalidation against two
file-change-watcher baselines on a single invented, public-safe fixture. Every
label is KNOWN-TRUTH: each mutation's stale/not-stale outcome is a mechanical
consequence of the edit (e.g. "we changed TIMEOUT from 30 to 10, so the claim
'the default timeout is 30 seconds' is now false"), not a human, model, or
panel judgment. Nothing here depends on opinion, and no private data is read.

Design (see docs/BENCHMARK_v0.6.0.md):

- A fixture git repo is built in a temp dir from invented sources (auth/config/
  routes/CSV) and two warranted artifacts: `docs/design.md` (claims authored
  with the shape-tolerant checkers the docs recommend) and `docs/design-naive.md`
  (one deliberately brittle exact-string claim — an anti-pattern kept on purpose
  so a known dorian false positive is in the battery).
- Each mutation is applied INDEPENDENTLY to a fresh copy of the sealed t0 repo,
  committed, and revalidated against t0. Independence is by construction: every
  copy starts from the same sealed VERIFIED baseline, so there is no carryover.
- Three detectors are scored per (artifact, mutation) pair:
    naive_file_watcher  — alarm iff any of the artifact's watched files changed.
    line_aware_watcher   — alarm iff a changed line range overlaps the claim's
                           anchor lines (or a watched file is added/removed/
                           renamed, or the claim is whole-file/data-level). This
                           is the stronger strawman a careful engineer would
                           build; it is rename-naive on purpose.
    dorian               — alarm iff revalidate marks any of the artifact's
                           claims BROKEN (ERRORED is never an alarm).
- Ground truth per mutation is the frozen set of claims whose FACT the edit
  falsifies (`breaks`). An artifact's label is "stale" iff the mutation breaks
  at least one of its claims. dorian's behavior is MEASURED, never assumed; the
  expected matrix in tests/test_controlled_mutation.py is a regression pin.

Scope/limits, stated up front (not hidden):
- One synthetic fixture, authored and scored by the same tool. These numbers
  are a reproducible demonstration of the MECHANISM, not evidence about any
  real repository. Results are specific to this benchmark.
- C4 (pytest-subprocess) checkers are excluded for hermeticity; C1, C3
  (path/symbol/string/regex) and C5 (rowcount/schema/domain) are covered.
- Determinism: fixed git identities/dates make commit shas stable; the summary
  records only aggregate numbers, booleans, fixed template strings, the
  fixture's own public file names, and mutation ids — never timestamps, warrant
  ids, host paths, or git shas.

Usage:
    python -m bench.controlled_mutation [--out <summary.json>] [--md-out <doc.md>]
    (or: dorian bench mutation ... from a dorian checkout)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

# bench/ is a repo-root package, not installed with dorian; ensure it imports.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bench.metrics import BOOTSTRAP_N, BOOTSTRAP_SEED, _ci, prf  # noqa: E402
from dorian.capture.manual import parse_manual  # noqa: E402
from dorian.model import Anchor, CheckerSpec, Claim  # noqa: E402
from dorian.revalidate import revalidate  # noqa: E402
from dorian.seal import seal_artifact  # noqa: E402

SCHEMA = "dorian-controlled-mutation-v1"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "dorian-bench",
    "GIT_AUTHOR_EMAIL": "bench@dorian.local",
    "GIT_COMMITTER_NAME": "dorian-bench",
    "GIT_COMMITTER_EMAIL": "bench@dorian.local",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}

# --- invented, public-safe fixture (mirrors examples/demo-repo content) ---------

AUTH_PY = '''"""Auth helpers."""


def verify_token(token: str) -> bool:
    """Verify an RS256-signed JWT."""
    algo = "RS256"
    return _check(token, algo)


def _check(token: str, algo: str) -> bool:
    return bool(token) and algo == "RS256"
'''

CONFIG_PY = """TIMEOUT = 30
RETRIES = 3
BASE_URL = "https://api.example.test"
"""

ROUTES_PY = """ROUTES = {
    "/v1/login": "auth.login",
    "/v2/items": "items.list",
}
"""

LOTS_CSV = """lot_id,site,status,loaded_at
L001,athens,open,2026-01-01
L002,berlin,closed,2026-01-02
L003,athens,open,2026-01-03
L004,cairo,open,2026-01-04
"""

DESIGN_MD = """# Gateway service design

Fictional demo document; every system, path, and number is invented.

- Token verification lives in src/auth.py and uses RS256.
- The default request timeout is 30 seconds.
- Login is served at /v1/login.
- The lots dataset has 4 rows with a status of open or closed.
"""

DESIGN_NAIVE_MD = """# Gateway service design (naive authoring variant)

Fictional demo document. This variant binds the timeout fact with a brittle
exact-string checker on purpose, to surface a known false-positive mode.

- The default request timeout is 30 seconds.
"""

FIXTURE_FILES = {
    "src/auth.py": AUTH_PY,
    "src/config.py": CONFIG_PY,
    "src/routes.py": ROUTES_PY,
    "data/lots.csv": LOTS_CSV,
    "docs/design.md": DESIGN_MD,
    "docs/design-naive.md": DESIGN_NAIVE_MD,
}

ARTIFACT_A = "docs/design.md"
ARTIFACT_B = "docs/design-naive.md"

# Read-set spec order fixes the entry ids: rs-0 is the auth span (cA1's anchor).
READSET_SPECS = ["src/auth.py:L4-7", "src/config.py", "src/routes.py", "data/lots.csv"]


def _claims_a() -> list[Claim]:
    """Artifact A: claims authored with the shape-tolerant checkers the docs
    recommend (regex for reformat-prone facts, typed C5 for data)."""
    return [
        Claim(
            id="cA1",
            text="Token verification lives in src/auth.py and uses RS256.",
            kind="fact",
            load_bearing=True,
            anchor=Anchor(line_start=4, line_end=7, quote="RS256"),
            supports=("rs-0",),
            checkers=(CheckerSpec(type="C1", program="rs-0", watch=("src/auth.py",)),),
        ),
        Claim(
            id="cA2",
            text="Token verification is implemented by verify_token().",
            kind="reference",
            load_bearing=True,
            checkers=(
                CheckerSpec(
                    type="C3", program="symbol:src/auth.py::verify_token", watch=("src/auth.py",)
                ),
            ),
        ),
        Claim(
            id="cA3",
            text="The default request timeout is 30 seconds.",
            kind="quantity",
            load_bearing=True,
            checkers=(
                CheckerSpec(
                    type="C3",
                    program=r"regex:src/config.py::TIMEOUT\s*=\s*30",
                    watch=("src/config.py",),
                ),
            ),
        ),
        Claim(
            id="cA4",
            text="Login is served at /v1/login.",
            kind="reference",
            load_bearing=True,
            checkers=(
                CheckerSpec(
                    type="C3", program="string:src/routes.py::/v1/login", watch=("src/routes.py",)
                ),
            ),
        ),
        Claim(
            id="cA5",
            text="The lots dataset has 4 rows.",
            kind="quantity",
            load_bearing=True,
            checkers=(
                CheckerSpec(
                    type="C5", program="rowcount:data/lots.csv::== 4", watch=("data/lots.csv",)
                ),
            ),
        ),
        Claim(
            id="cA6",
            text="The lots dataset has columns lot_id, site, status, loaded_at.",
            kind="fact",
            load_bearing=True,
            checkers=(
                CheckerSpec(
                    type="C5",
                    program="schema:data/lots.csv::lot_id,site,status,loaded_at",
                    watch=("data/lots.csv",),
                ),
            ),
        ),
        Claim(
            id="cA7",
            text="Lot status is limited to open or closed.",
            kind="fact",
            load_bearing=False,
            checkers=(
                CheckerSpec(
                    type="C5",
                    program="domain:data/lots.csv::status::{open,closed}",
                    watch=("data/lots.csv",),
                ),
            ),
        ),
        Claim(
            id="cA8",
            text="Configuration lives in src/config.py.",
            kind="reference",
            load_bearing=True,
            checkers=(
                CheckerSpec(type="C3", program="path:src/config.py", watch=("src/config.py",)),
            ),
        ),
    ]


def _claims_b() -> list[Claim]:
    """Artifact B: one deliberately brittle exact-string claim (anti-pattern)."""
    return [
        Claim(
            id="cB1",
            text="The default request timeout is 30 seconds.",
            kind="quantity",
            load_bearing=True,
            checkers=(
                CheckerSpec(
                    type="C3",
                    program="string:src/config.py::TIMEOUT = 30",
                    watch=("src/config.py",),
                ),
            ),
        )
    ]


# Per-claim anchor metadata for the line-aware baseline. "line" claims alarm only
# when a changed line range overlaps these t0 line numbers; "file" claims (path,
# data) alarm on any change to the watched file. Mirrors what a careful engineer
# would diff-watch; it is intentionally rename-naive.
ANCHORS: dict[str, tuple[str, str, frozenset[int] | None]] = {
    "cA1": ("src/auth.py", "line", frozenset({4, 5, 6, 7})),
    "cA2": ("src/auth.py", "line", frozenset({4})),
    "cA3": ("src/config.py", "line", frozenset({1})),
    "cA4": ("src/routes.py", "line", frozenset({2})),
    "cA5": ("data/lots.csv", "file", None),
    "cA6": ("data/lots.csv", "file", None),
    "cA7": ("data/lots.csv", "file", None),
    "cA8": ("src/config.py", "file", None),
    "cB1": ("src/config.py", "line", frozenset({1})),
}

ARTIFACT_CLAIMS = {
    ARTIFACT_A: ["cA1", "cA2", "cA3", "cA4", "cA5", "cA6", "cA7", "cA8"],
    ARTIFACT_B: ["cB1"],
}


# --- git helpers ----------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout.strip()


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="\n")


def _rmtree(path: Path) -> None:
    """Robust teardown of a transient git fixture repo. After a commit, git can
    briefly hold files under .git (auto-gc / fsmonitor), so shutil.rmtree races
    with "Directory not empty" / vanished-file errors on loaded CI runners. Retry
    a few times, then give up cleanly — the parent workspace is an ephemeral tmp
    dir removed wholesale, so leftover cruft never affects the (in-memory) result."""
    import time

    for _ in range(6):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.15)
    shutil.rmtree(path, ignore_errors=True)


def _changed_line_ranges(repo: Path, since: str, path: str) -> set[int]:
    """Old-side (t0) line numbers touched in `path` between `since` and HEAD,
    parsed from `git diff -U0` hunk headers. A pure insertion (old count 0)
    touches no existing line, so a comment added elsewhere does not alarm."""
    try:
        out = _git(repo, "diff", "-U0", "--no-color", since, "HEAD", "--", path)
    except subprocess.CalledProcessError:
        return set()
    touched: set[int] = set()
    for line in out.splitlines():
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+", line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        touched.update(range(start, start + count))
    return touched


# --- fixture build --------------------------------------------------------------


def build_fixture(repo: Path) -> str:
    """Materialize and seal the fixture; return the sealed t0 commit sha."""
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for rel, content in FIXTURE_FILES.items():
        _write(repo, rel, content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial fixture state")

    readset = parse_manual(READSET_SPECS, repo)
    seal_artifact(repo, ARTIFACT_A, readset, _claims_a())
    seal_artifact(repo, ARTIFACT_B, readset, _claims_b())

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seal warrants")
    return _git(repo, "rev-parse", "HEAD")


# --- mutations ------------------------------------------------------------------
#
# Each mutation declares `breaks`: the frozen set of claim ids whose FACT the
# edit falsifies (the known-truth label). `apply` edits the working tree of a
# fresh copy. `score` lists the artifacts whose pair is recorded (B is only in
# play for edits to its single watched file, src/config.py).


def _set_file(repo: Path, rel: str, content: str) -> None:
    _write(repo, rel, content)


def _delete_file(repo: Path, rel: str) -> None:
    (repo / rel).unlink()


def _git_mv(repo: Path, old: str, new: str) -> None:
    (repo / new).parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", old, new)


MUTATIONS: list[dict] = [
    # --- true-stale: a fact is genuinely falsified -----------------------------
    {
        "id": "auth_algo_changed",
        "desc": "auth.py: RS256 -> HS256",
        "breaks": {"cA1"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(r, "src/auth.py", AUTH_PY.replace("RS256", "HS256")),
    },
    {
        "id": "auth_symbol_renamed",
        "desc": "auth.py: verify_token -> issue_token",
        "breaks": {"cA1", "cA2"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(
            r, "src/auth.py", AUTH_PY.replace("verify_token", "issue_token")
        ),
    },
    {
        "id": "auth_file_deleted",
        "desc": "delete src/auth.py",
        "breaks": {"cA1", "cA2"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _delete_file(r, "src/auth.py"),
    },
    {
        "id": "cfg_value_changed",
        "desc": "config.py: TIMEOUT 30 -> 10",
        "breaks": {"cA3", "cB1"},
        "score": [ARTIFACT_A, ARTIFACT_B],
        "apply": lambda r: _set_file(
            r, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10")
        ),
    },
    {
        "id": "cfg_line_deleted",
        "desc": "config.py: remove the TIMEOUT line",
        "breaks": {"cA3", "cB1"},
        "score": [ARTIFACT_A, ARTIFACT_B],
        "apply": lambda r: _set_file(r, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30\n", "")),
    },
    {
        "id": "cfg_file_deleted",
        "desc": "delete src/config.py",
        "breaks": {"cA3", "cA8", "cB1"},
        "score": [ARTIFACT_A, ARTIFACT_B],
        "apply": lambda r: _delete_file(r, "src/config.py"),
    },
    {
        "id": "routes_login_removed",
        "desc": "routes.py: remove the /v1/login entry",
        "breaks": {"cA4"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(
            r, "src/routes.py", ROUTES_PY.replace('    "/v1/login": "auth.login",\n', "")
        ),
    },
    {
        "id": "routes_file_deleted",
        "desc": "delete src/routes.py",
        "breaks": {"cA4"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _delete_file(r, "src/routes.py"),
    },
    {
        "id": "data_row_dropped",
        "desc": "lots.csv: drop a row (4 -> 3)",
        "breaks": {"cA5"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(
            r, "data/lots.csv", "".join(LOTS_CSV.splitlines(keepends=True)[:4])
        ),
    },
    {
        "id": "data_column_renamed",
        "desc": "lots.csv: status -> state header",
        "breaks": {"cA6", "cA7"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(r, "data/lots.csv", LOTS_CSV.replace("status", "state", 1)),
    },
    {
        "id": "data_column_dropped",
        "desc": "lots.csv: drop the loaded_at column",
        "breaks": {"cA6"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(r, "data/lots.csv", _drop_loaded_at(LOTS_CSV)),
    },
    {
        "id": "data_out_of_domain",
        "desc": "lots.csv: one open -> pending",
        "breaks": {"cA7"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(
            r, "data/lots.csv", LOTS_CSV.replace("athens,open", "athens,pending", 1)
        ),
    },
    {
        "id": "data_emptied",
        "desc": "lots.csv: truncate to header (0 rows)",
        "breaks": {"cA5"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(r, "data/lots.csv", LOTS_CSV.splitlines(keepends=True)[0]),
    },
    # --- true-stale that dorian's substring checker MISSES (false negatives) ----
    {
        "id": "routes_login_to_comment",
        "desc": "routes.py: /v1/login -> /v1/signin, old path left in a comment",
        "breaks": {"cA4"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(
            r,
            "src/routes.py",
            ROUTES_PY.replace(
                '"/v1/login": "auth.login",', '"/v1/signin": "auth.login",  # was /v1/login'
            ),
        ),
    },
    {
        "id": "routes_login_to_docstring",
        "desc": "routes.py: remove /v1/login entry, old path survives in a docstring",
        "breaks": {"cA4"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(
            r,
            "src/routes.py",
            '"""Route table; /v1/login was retired."""\n'
            + ROUTES_PY.replace('    "/v1/login": "auth.login",\n', ""),
        ),
    },
    {
        "id": "routes_login_to_constant",
        "desc": "routes.py: remove /v1/login entry, old path survives in an unused constant",
        "breaks": {"cA4"},
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(
            r,
            "src/routes.py",
            ROUTES_PY.replace('    "/v1/login": "auth.login",\n', "")
            + '_LEGACY = "/v1/login"  # retired, unused\n',
        ),
    },
    # --- benign: every fact still holds ----------------------------------------
    {
        "id": "auth_comment_prepended",
        "desc": "auth.py: insert a comment at the top",
        "breaks": set(),
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(
            r, "src/auth.py", "# module: authentication helpers\n" + AUTH_PY
        ),
    },
    {
        "id": "auth_comment_appended",
        "desc": "auth.py: append a comment at EOF",
        "breaks": set(),
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(r, "src/auth.py", AUTH_PY + "\n# end of module\n"),
    },
    {
        "id": "cfg_whitespace_reformat",
        "desc": "config.py: TIMEOUT = 30 -> TIMEOUT  =  30 (extra spaces)",
        "breaks": set(),
        "score": [ARTIFACT_A, ARTIFACT_B],
        "apply": lambda r: _set_file(
            r, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT  =  30")
        ),
    },
    {
        "id": "cfg_type_annotation_added",
        "desc": "config.py: TIMEOUT = 30 -> TIMEOUT: int = 30",
        "breaks": set(),
        "score": [ARTIFACT_A, ARTIFACT_B],
        "apply": lambda r: _set_file(
            r, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT: int = 30")
        ),
    },
    {
        "id": "cfg_constant_added",
        "desc": "config.py: add an unrelated DEBUG constant",
        "breaks": set(),
        "score": [ARTIFACT_A, ARTIFACT_B],
        "apply": lambda r: _set_file(r, "src/config.py", CONFIG_PY + "DEBUG = False\n"),
    },
    {
        "id": "cfg_comment_appended",
        "desc": "config.py: append a trailing comment",
        "breaks": set(),
        "score": [ARTIFACT_A, ARTIFACT_B],
        "apply": lambda r: _set_file(
            r, "src/config.py", CONFIG_PY + "# tuned for the gateway rollout\n"
        ),
    },
    {
        "id": "cfg_file_renamed",
        "desc": "git mv src/config.py -> src/settings.py",
        "breaks": set(),
        "score": [ARTIFACT_A, ARTIFACT_B],
        "expect_rename": True,
        "apply": lambda r: _git_mv(r, "src/config.py", "src/settings.py"),
    },
    {
        "id": "cfg_fact_relocated",
        "desc": "config.py: TIMEOUT line moved to a new src/timeouts.py (fact preserved)",
        "breaks": set(),
        "score": [ARTIFACT_A, ARTIFACT_B],
        "apply": lambda r: _split_timeout(r),
    },
    {
        "id": "routes_comment_added",
        "desc": "routes.py: add a comment line",
        "breaks": set(),
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(
            r, "src/routes.py", ROUTES_PY + "# route table is partly generated\n"
        ),
    },
    {
        "id": "routes_entries_reordered",
        "desc": "routes.py: swap the two route entries",
        "breaks": set(),
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(
            r,
            "src/routes.py",
            'ROUTES = {\n    "/v2/items": "items.list",\n    "/v1/login": "auth.login",\n}\n',
        ),
    },
    {
        "id": "routes_file_renamed",
        "desc": "git mv src/routes.py -> src/endpoints.py",
        "breaks": set(),
        "score": [ARTIFACT_A],
        "expect_rename": True,
        "apply": lambda r: _git_mv(r, "src/routes.py", "src/endpoints.py"),
    },
    {
        "id": "data_rows_reordered",
        "desc": "lots.csv: reorder the rows (same values)",
        "breaks": set(),
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(r, "data/lots.csv", _reorder_rows(LOTS_CSV)),
    },
    {
        "id": "data_column_added",
        "desc": "lots.csv: add an unrelated region column",
        "breaks": set(),
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(r, "data/lots.csv", _add_region(LOTS_CSV)),
    },
    {
        "id": "data_unclaimed_cell_edited",
        "desc": "lots.csv: change a site value (not referenced by any claim)",
        "breaks": set(),
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(r, "data/lots.csv", LOTS_CSV.replace("athens", "sparta", 1)),
    },
    # --- neutral: touches no watched file --------------------------------------
    {
        "id": "unrelated_file_added",
        "desc": "add an unrelated src/util.py",
        "breaks": set(),
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(r, "src/util.py", "def helper():\n    return 42\n"),
    },
    {
        "id": "readme_edited",
        "desc": "add/modify README.md",
        "breaks": set(),
        "score": [ARTIFACT_A],
        "apply": lambda r: _set_file(r, "README.md", "# fixture\n\nUnrelated docs change.\n"),
    },
]


def _drop_loaded_at(csv: str) -> str:
    rows = [line.split(",")[:3] for line in csv.splitlines()]
    return "".join(",".join(cells) + "\n" for cells in rows)


def _reorder_rows(csv: str) -> str:
    lines = csv.splitlines(keepends=True)
    return lines[0] + "".join([lines[2], lines[4], lines[1], lines[3]])


def _add_region(csv: str) -> str:
    lines = csv.splitlines()
    regions = ["region", "emea", "emea", "emea", "mea"]
    return "".join(f"{line},{regions[i]}\n" for i, line in enumerate(lines))


def _split_timeout(repo: Path) -> None:
    """Move the TIMEOUT line out of config.py into a new file (fact preserved)."""
    _set_file(repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30\n", ""))
    _set_file(repo, "src/timeouts.py", "TIMEOUT = 30\n")


# --- detectors ------------------------------------------------------------------


def _support_files(artifact: str) -> set[str]:
    return {ANCHORS[cid][0] for cid in ARTIFACT_CLAIMS[artifact]}


def _naive_alarm(artifact: str, changed: set[str]) -> bool:
    return bool(_support_files(artifact) & changed)


def _line_aware_alarm(
    repo: Path, t0: str, artifact: str, changed: set[str], renames: dict[str, str]
) -> bool:
    """A diff-hunk watcher: alarm iff a changed line overlaps a claim's anchor
    lines, the claim is whole-file/data-level and its file changed, or the file
    was added/removed/renamed. Rename-naive on purpose."""
    for cid in ARTIFACT_CLAIMS[artifact]:
        watch, level, lines = ANCHORS[cid]
        if watch not in changed and watch not in renames:
            continue
        if not (repo / watch).is_file():  # deleted or renamed away
            return True
        if level == "file":
            return True
        if lines and (lines & _changed_line_ranges(repo, t0, watch)):
            return True
    return False


def _run_mutation(template: Path, work_root: Path, t0: str, mut: dict) -> dict:
    """Apply one mutation to a fresh copy and score all three detectors."""
    work = work_root / mut["id"]
    if work.exists():
        _rmtree(work)
    shutil.copytree(template, work)

    mut["apply"](work)
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", mut["id"])

    changed_list, renames = _changed_paths(work, t0)
    changed = set(changed_list)
    result = revalidate(work, since=t0)  # enable_c2lite stays False (default)

    broken_by_uri: dict[str, set[str]] = {}
    errored_by_uri: dict[str, set[str]] = {}
    for wid, cid, _ in result.broken:
        broken_by_uri.setdefault(result.artifacts.get(wid, wid), set()).add(cid)
    for wid, cid, _ in result.errored:
        errored_by_uri.setdefault(result.artifacts.get(wid, wid), set()).add(cid)

    records = []
    for artifact in mut["score"]:
        broken = broken_by_uri.get(artifact, set())
        errored = errored_by_uri.get(artifact, set())
        label = bool(mut["breaks"] & set(ARTIFACT_CLAIMS[artifact]))
        records.append(
            {
                "artifact": artifact,
                "mutation": mut["id"],
                "true": label,
                "naive": _naive_alarm(artifact, changed),
                "lineaware": _line_aware_alarm(work, t0, artifact, changed, renames),
                "dorian": bool(broken),
                "dorian_broken": sorted(broken),
                "errored": sorted(errored),
            }
        )
    _rmtree(work)
    return {"records": records, "rename_detected": bool(renames)}


def _changed_paths(repo: Path, since: str) -> tuple[list[str], dict[str, str]]:
    from dorian import gitio

    return gitio.changed_paths(repo, since)


# --- metrics --------------------------------------------------------------------

_SYSTEMS = ("naive", "lineaware", "dorian")
_SYSTEM_LABELS = {
    "naive": "naive_file_watcher",
    "lineaware": "line_aware_watcher",
    "dorian": "dorian",
}


def _bootstrap_ci(pairs: list[dict], system: str, metric: str) -> list[float]:
    """In-fixture 95% CI for one system+metric, reusing metrics.prf / _ci with
    the same seed and resample count as the rest of the suite."""
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(pairs)
    samples = []
    for _ in range(BOOTSTRAP_N):
        resample = [pairs[rng.randrange(n)] for _ in range(n)]
        samples.append(prf(resample, system)[metric])
    return _ci(samples)


def _system_block(pairs: list[dict], system: str) -> dict:
    s = prf(pairs, system)
    return {
        "alarms": s["tp"] + s["fp"],
        "tp": s["tp"],
        "fp": s["fp"],
        "fn": s["fn"],
        "tn": s["tn"],
        "precision": round(s["precision"], 4),
        "recall": round(s["recall"], 4),
        "precision_ci": [round(x, 4) for x in _bootstrap_ci(pairs, system, "precision")],
        "recall_ci": [round(x, 4) for x in _bootstrap_ci(pairs, system, "recall")],
    }


def _attribution(records: list[dict], pairs: list[dict]) -> dict:
    """Descriptive: which checker types produced dorian's FPs / FNs (no labels
    invented — read from the per-claim verdicts of the FP/FN pairs)."""
    checker_of = {
        "cA1": "C1",
        "cA2": "C3-symbol",
        "cA3": "C3-regex",
        "cA4": "C3-string",
        "cA5": "C5-rowcount",
        "cA6": "C5-schema",
        "cA7": "C5-domain",
        "cA8": "C3-path",
        "cB1": "C3-string",
    }
    by_pair = {(r["artifact"], r["mutation"]): r for r in records}
    fps, fns = [], []
    for p in pairs:
        rec = by_pair[(p["artifact"], p["mutation"])]
        if p["dorian"] and not p["true"]:
            fps.append(
                {
                    "artifact": p["artifact"],
                    "mutation": p["mutation"],
                    "checkers": sorted({checker_of[c] for c in rec["dorian_broken"]}),
                }
            )
        elif not p["dorian"] and p["true"]:
            fns.append({"artifact": p["artifact"], "mutation": p["mutation"]})
    return {"false_positives": fps, "false_negatives": fns}


def compute(records: list[dict]) -> dict:
    pairs = [
        {k: r[k] for k in ("artifact", "mutation", "true", "naive", "lineaware", "dorian")}
        for r in records
    ]
    fixture_files = sorted(FIXTURE_FILES)
    systems = {_SYSTEM_LABELS[s]: _system_block(pairs, s) for s in _SYSTEMS}
    naive_fp = systems["naive_file_watcher"]["fp"]
    line_fp = systems["line_aware_watcher"]["fp"]
    dorian_fp = systems["dorian"]["fp"]

    by_artifact = {}
    for artifact in (ARTIFACT_A, ARTIFACT_B):
        ap = [p for p in pairs if p["artifact"] == artifact]
        d = prf(ap, "dorian")
        by_artifact[artifact] = {
            "pairs": len(ap),
            "tp": d["tp"],
            "fp": d["fp"],
            "fn": d["fn"],
            "tn": d["tn"],
            "precision": round(d["precision"], 4),
            "recall": round(d["recall"], 4),
        }

    return {
        "schema": SCHEMA,
        "fixture": {
            "artifacts": len(ARTIFACT_CLAIMS),
            "claims": sum(len(v) for v in ARTIFACT_CLAIMS.values()),
            "files": fixture_files,
        },
        "pairs": len(pairs),
        "true_stale_pairs": sum(1 for p in pairs if p["true"]),
        "benign_pairs": sum(1 for p in pairs if not p["true"]),
        "errored_pairs": sum(1 for r in records if r["errored"]),
        "systems": systems,
        "fp_reduction": {
            "naive_fp": naive_fp,
            "line_aware_fp": line_fp,
            "dorian_fp": dorian_fp,
            "vs_naive_file_watcher": round(naive_fp / max(1, dorian_fp), 2),
            "vs_line_aware_watcher": round(line_fp / max(1, dorian_fp), 2),
            "note": "ratio = baseline FP / max(1, dorian FP); read raw counts alongside it",
        },
        "by_artifact": by_artifact,
        "dorian_error_attribution": _attribution(records, pairs),
        "bootstrap": {"resamples": BOOTSTRAP_N, "seed": BOOTSTRAP_SEED, "scope": "in-fixture"},
    }


# --- run + render ---------------------------------------------------------------


def run_benchmark(workspace: Path) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    template = workspace / "t0"
    if template.exists():
        _rmtree(template)
    t0 = build_fixture(template)
    work_root = workspace / "work"
    work_root.mkdir(exist_ok=True)

    records: list[dict] = []
    for mut in MUTATIONS:
        out = _run_mutation(template, work_root, t0, mut)
        records.extend(out["records"])
        if mut.get("expect_rename") and not out["rename_detected"]:
            raise RuntimeError(f"rename mutation {mut['id']!r} produced no git rename")
    _rmtree(template)
    return compute(records)


def render_markdown(m: dict) -> str:
    sys_rows = []
    for key in ("naive_file_watcher", "line_aware_watcher", "dorian"):
        s = m["systems"][key]
        sys_rows.append(
            f"| {key} | {s['tp']} | {s['fp']} | {s['fn']} | {s['tn']} "
            f"| {s['precision']:.2f} ({s['precision_ci'][0]:.2f}-{s['precision_ci'][1]:.2f}) "
            f"| {s['recall']:.2f} ({s['recall_ci'][0]:.2f}-{s['recall_ci'][1]:.2f}) |"
        )
    fpr = m["fp_reduction"]
    a, b = m["by_artifact"][ARTIFACT_A], m["by_artifact"][ARTIFACT_B]
    fns = m["dorian_error_attribution"]["false_negatives"]
    fps = m["dorian_error_attribution"]["false_positives"]
    fn_muts = ", ".join(f"`{x}`" for x in sorted({x["mutation"] for x in fns})) or "none"
    fp_muts = ", ".join(f"`{x}`" for x in sorted({x["mutation"] for x in fps})) or "none"
    lines = [
        "# dorian controlled-mutation benchmark (v0.6.0)",
        "",
        "Numbers only. Labels are **known-truth**: each mutation's stale / not-stale",
        "outcome is a mechanical consequence of the edit (e.g. changing `TIMEOUT = 30`",
        'to `10` falsifies the claim "the default timeout is 30 seconds"). The expected',
        "outcome is fixed by the edit itself, before measurement — no review step and no",
        "opinion enters the labels. Reproduce with `python -m bench.controlled_mutation`",
        "(or `dorian bench mutation`).",
        "",
        "## What this is — and is not",
        "",
        "This is a reproducible **demonstration on a single invented, synthetic fixture**",
        "(the fixture, the mutations, and the labels are all authored here). It shows how",
        "claim-level revalidation and file-change watching diverge under known edits — a",
        "property of the mechanism. It is **not** evidence about any real repository and",
        "**not** a universal performance claim. Results are specific to this benchmark.",
        "C4 (pytest-subprocess) checkers are excluded for hermeticity; C1, C3, and C5 are",
        "exercised.",
        "",
        "## Composition",
        "",
        f"- Fixture: {m['fixture']['artifacts']} warranted artifacts, {m['fixture']['claims']} "
        f"claims, {len(m['fixture']['files'])} files.",
        f"- {m['pairs']} (artifact, mutation) pairs: {m['true_stale_pairs']} true-stale, "
        f"{m['benign_pairs']} benign/neutral.",
        f"- Errored pairs (checker could not run): {m['errored_pairs']}.",
        "",
        "## Detectors",
        "",
        "- **naive_file_watcher** — alarms if any watched file changed.",
        "- **line_aware_watcher** — alarms only if a changed line range overlaps a claim's",
        "  anchor lines (whole-file/data claims alarm on any change to their file). The",
        "  stronger strawman a careful engineer would build; rename-naive on purpose.",
        "- **dorian** — alarms if `revalidate` marks any of the artifact's claims BROKEN.",
        "",
        "## Results",
        "",
        "| detector | TP | FP | FN | TN | precision (95% CI) | recall (95% CI) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *sys_rows,
        "",
        f"False-positive reduction (baseline FP / max(1, dorian FP)): "
        f"**{fpr['vs_naive_file_watcher']}x** vs the naive watcher "
        f"({fpr['naive_fp']} vs {fpr['dorian_fp']} false positives), "
        f"**{fpr['vs_line_aware_watcher']}x** vs the line-aware watcher "
        f"({fpr['line_aware_fp']} vs {fpr['dorian_fp']}).",
        "",
        "Confidence intervals are bootstrap (1000 resamples, seed 42) and **in-fixture**:",
        f"with {m['pairs']} pairs over one fixture they describe resampling noise on this",
        "battery, not generalization. Read them as wide.",
        "",
        "## dorian by artifact",
        "",
        "| artifact | pairs | TP | FP | FN | TN | precision | recall |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        f"| `{ARTIFACT_A}` (shape-tolerant claims) | {a['pairs']} | {a['tp']} | {a['fp']} "
        f"| {a['fn']} | {a['tn']} | {a['precision']:.2f} | {a['recall']:.2f} |",
        f"| `{ARTIFACT_B}` (brittle exact-string claim) | {b['pairs']} | {b['tp']} | {b['fp']} "
        f"| {b['fn']} | {b['tn']} | {b['precision']:.2f} | {b['recall']:.2f} |",
        "",
        "## Where dorian errs (honest failure modes)",
        "",
        f"- **False negatives** ({len(fns)}): {fn_muts}. dorian's `string:` checker passes",
        "  when the cited literal survives elsewhere (a comment, docstring, or unused",
        "  constant) while the real binding changed — a substring-match weakness. An",
        "  anchored `regex:` or `symbol:` checker would catch these.",
        f"- **False positives** ({len(fps)}): {fp_muts}. Exact-string and tightly-anchored",
        "  regex checkers alarm on reformatting (extra spaces, a type annotation) or when a",
        "  fact is relocated to another file — the value is still correct. More tolerant",
        "  checker authoring narrows this; the brittle `docs/design-naive.md` claim shows",
        "  the worst case.",
        "",
        "## Reading",
        "",
        "dorian trades some recall for substantially higher precision: it suppresses the",
        "benign-edit false alarms that make file-watching noisy (comments, reformatting,",
        "reordering, renames, unrelated columns), at the cost of misses when a claim is",
        "bound by a substring checker. The precision gap holds against the line-aware",
        "watcher, not only the naive one. All figures are specific to this fixture.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.controlled_mutation", description=__doc__)
    ap.add_argument("--workspace", default="bench/workspace/mutation")
    ap.add_argument("--out", default="bench/results/v0.6.0_controlled_mutation_summary.json")
    ap.add_argument("--md-out", help="also render the public markdown summary to this path")
    args = ap.parse_args(argv)

    summary = run_benchmark(Path(args.workspace))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if args.md_out:
        md = Path(args.md_out)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_markdown(summary), encoding="utf-8")
    d = summary["systems"]["dorian"]
    print(
        f"controlled-mutation: {summary['pairs']} pairs, "
        f"dorian precision {d['precision']:.2f} recall {d['recall']:.2f}, "
        f"FP reduction {summary['fp_reduction']['vs_naive_file_watcher']}x (naive) / "
        f"{summary['fp_reduction']['vs_line_aware_watcher']}x (line-aware) -> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
