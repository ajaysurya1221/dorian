"""Git-history replay benchmark harness (H1/H2).

Usage:
    python -m bench.replay --config bench/repos.json \\
        --workspace bench/workspace --out bench/results

Config is JSON — chosen over YAML so the kernel stays zero-dep:
{"repos": [{"name", "path_or_url", "t0", "artifacts": [{"uri", "claims_json"}],
"replay_commits"}]}. Relative `claims_json` paths resolve against the config
file's directory. `path_or_url` is anything `git clone` accepts; the special
value "SELFTEST" instead builds the scripted fixture history below
(tests/conftest.py is not importable outside pytest, so its file contents are
duplicated here as SELFTEST_FILES).

Per repo: materialize the history at t0, capture a manual read-set from each
artifact's claims' watch files, seal the artifact (claims loaded with
claims_io.load_claims — the DORIAN_EXTRACT_STUB shape), then walk the next N
first-parent commits. Per (artifact, commit) two detectors are scored:

- baseline alarm: `git diff --name-only prev commit` intersects the artifact's
  support/watch files — the naive file-watcher strawman.
- dorian alarm: check out the commit and run `revalidate(since=prev)`; alarm
  iff some claim is NEWLY BROKEN at this commit. Claim states persist across
  commits, so an already-broken claim that fails again is not a new alarm; a
  claim that recovers (PASS, in place or relocated) re-arms. ERRORED is never
  an alarm (verdict discipline: infra failure is not staleness).

results.json is byte-identical across runs: fixed git identities and dates
make the scripted shas stable, and no timestamps or absolute paths are
recorded.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dorian import claims_io
from dorian.capture.manual import parse_manual
from dorian.model import Claim
from dorian.revalidate import revalidate
from dorian.seal import seal_artifact

GIT_ENV = {
    "GIT_AUTHOR_NAME": "dorian-bench",
    "GIT_AUTHOR_EMAIL": "bench@dorian.local",
    "GIT_COMMITTER_NAME": "dorian-bench",
    "GIT_COMMITTER_EMAIL": "bench@dorian.local",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}

# --- SELFTEST fixture (duplicated from tests/conftest.py) ------------------------

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

DESIGN_MD = """# Design

Token verification lives in src/auth.py and uses RS256.

The default request timeout is 30 seconds.

Login is served at /v1/login.

The lots dataset has 4 rows and a status column limited to open/closed.
"""

LOTS_CSV = """lot_id,site,status,loaded_at
L001,athens,open,2026-01-01
L002,berlin,closed,2026-01-02
L003,athens,open,2026-01-03
L004,cairo,open,2026-01-04
"""

SELFTEST_FILES = {
    "src/auth.py": AUTH_PY,
    "src/config.py": CONFIG_PY,
    "src/routes.py": ROUTES_PY,
    "docs/design.md": DESIGN_MD,
    "data/lots.csv": LOTS_CSV,
}


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _commit_all(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def build_selftest(repo: Path) -> tuple[str, list[str], list[str]]:
    """Scripted fixture history. Returns (t0, replay_shas, breaking_shas).

    After the initial commit (t0): the canonical three-change commit (rename
    auth -> BREAKING for timeout+login claims, relocation for the span claim),
    one unrelated commit, three benign commits — two of which touch support
    files WITHOUT changing the claimed facts (the baseline-FP demo) — one
    more breaking commit that drops a data row (rowcount claim breaks), then
    two MORE benign support-touching commits (second comments on config and
    routes) so the baseline lands 4 FPs and the fp_reduction gate has margin.
    """
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    for rel, content in SELFTEST_FILES.items():
        _write(repo, rel, content)
    t0 = _commit_all(repo, "initial fixture state")

    config_v2 = CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10")
    routes_v2 = ROUTES_PY.replace('    "/v1/login": "auth.login",\n', "")
    shas: list[str] = []

    # 1. the canonical drift commit: breaks c2 (timeout) + c3 (login), relocates c1
    _git(repo, "mv", "src/auth.py", "src/tokens.py")
    _write(repo, "src/config.py", config_v2)
    _write(repo, "src/routes.py", routes_v2)
    shas.append(_commit_all(repo, "refactor: rename auth, tune timeout, drop legacy login"))

    # 2. unrelated commit: must alarm in neither system
    _write(repo, "src/util.py", "def helper():\n    return 42\n")
    shas.append(_commit_all(repo, "chore: add unrelated helper"))

    # 3. benign commit touching no support file
    _write(repo, "README.md", "# selftest\n\nReplay fixture repo.\n")
    shas.append(_commit_all(repo, "docs: add a README"))

    # 4. benign SUPPORT-touching commit: comment in src/config.py, TIMEOUT unchanged
    #    -> baseline false positive, dorian stays quiet
    _write(repo, "src/config.py", config_v2 + "# tuned for the gateway rollout\n")
    shas.append(_commit_all(repo, "docs: comment the timeout default"))

    # 5. second benign support-touching commit (routes), same asymmetry
    _write(repo, "src/routes.py", routes_v2 + "# route table is partly generated\n")
    shas.append(_commit_all(repo, "docs: comment the route table"))

    # 6. breaking data commit: drop the cairo lot -> rowcount 3 != 4, c4 breaks
    lots_v2 = "".join(LOTS_CSV.splitlines(keepends=True)[:4])
    _write(repo, "data/lots.csv", lots_v2)
    shas.append(_commit_all(repo, "data: drop the cairo lot"))

    # 7. third benign support-touching commit: a second comment in src/config.py,
    #    TIMEOUT still unchanged -> baseline FP #3, dorian quiet (c2 already broken)
    _write(
        repo,
        "src/config.py",
        config_v2 + "# tuned for the gateway rollout\n# revisit after the rollout settles\n",
    )
    shas.append(_commit_all(repo, "docs: second comment on the timeout default"))

    # 8. fourth benign support-touching commit (routes again) -> baseline FP #4
    _write(
        repo,
        "src/routes.py",
        routes_v2 + "# route table is partly generated\n# keep the ordering stable\n",
    )
    shas.append(_commit_all(repo, "docs: second comment on the route table"))

    _git(repo, "checkout", "-q", t0)
    return t0, shas, [shas[0], shas[5]]


def prepare_repo(entry: dict, workspace: Path) -> tuple[Path, str, list[str], list[str] | None]:
    """Materialize the repo in the workspace, checked out at t0.

    Returns (repo_dir, t0, replay_shas, breaking_shas-or-None). breaking_shas
    is only known for the scripted SELFTEST history and becomes the hardcoded
    ground truth downstream.
    """
    repo = workspace / entry["name"]
    if repo.exists():
        shutil.rmtree(repo)
    n = int(entry["replay_commits"])
    if entry["path_or_url"] == "SELFTEST":
        t0, shas, breaking = build_selftest(repo)
        return repo, t0, shas[:n], breaking
    workspace.mkdir(parents=True, exist_ok=True)
    # clone target must be absolute: a relative str(repo) would resolve against
    # cwd=workspace and nest the clone at workspace/<workspace>/<name>
    _git(workspace, "clone", "-q", entry["path_or_url"], str(repo.resolve()))
    t0 = _git(repo, "rev-parse", entry["t0"])
    shas = _git(repo, "rev-list", "--first-parent", "--reverse", f"{t0}..HEAD").split()
    _git(repo, "checkout", "-q", t0)
    return repo, t0, shas[:n], None


def _watch_paths(claims: list[Claim]) -> list[str]:
    """Ordered, deduped watch paths across all claims — the manual capture specs
    (rs-0, rs-1, ... ids therefore follow first-appearance order)."""
    seen: list[str] = []
    for claim in claims:
        for spec in claim.checkers:
            for w in spec.watch:
                if w not in seen:
                    seen.append(w)
    return seen


def replay_repo(entry: dict, workspace: Path, config_dir: Path) -> dict:
    repo, t0, shas, breaking = prepare_repo(entry, workspace)

    # seal each artifact at t0
    sealed: list[dict] = []
    for art in entry["artifacts"]:
        claims_path = Path(art["claims_json"])
        if not claims_path.is_absolute():
            claims_path = config_dir / claims_path
        claims = claims_io.load_claims(claims_path)
        readset = parse_manual(_watch_paths(claims), repo)
        warrant = seal_artifact(repo, art["uri"], readset, claims)
        entries = {e.id: e for e in warrant.read_set}
        support: set[str] = set()
        for claim in warrant.claims:
            for spec in claim.checkers:
                support.update(spec.watch)
            support.update(entries[s].uri for s in claim.supports if s in entries)
        sealed.append(
            {
                "uri": art["uri"],
                "warrant_id": warrant.id,
                "support_files": support,
                "claims": [
                    {"id": c.id, "text": c.text, "backed": c.backed} for c in warrant.claims
                ],
                "backed_claim_ratio": (
                    sum(1 for c in warrant.claims if c.backed) / len(warrant.claims)
                    if warrant.claims
                    else 0.0
                ),
            }
        )

    # walk the next N first-parent commits
    commits: list[dict] = []
    records: list[dict] = []
    broken_so_far: dict[str, set[str]] = {a["uri"]: set() for a in sealed}
    prev = t0
    for sha in shas:
        changed = [p for p in _git(repo, "diff", "--name-only", prev, sha).splitlines() if p]
        subject = _git(repo, "log", "-1", "--format=%s", sha)
        _git(repo, "checkout", "-q", sha)
        res = revalidate(repo, since=prev)
        commits.append({"sha": sha, "subject": subject, "changed_files": changed})
        for art in sealed:
            wid = art["warrant_id"]
            broken_now = {cid for w, cid, _ in res.broken if w == wid}
            recovered = {cid for w, cid, _ in res.passed if w == wid}
            relocated = sorted(cid for w, cid, _ in res.relocated if w == wid)
            errored = sorted(cid for w, cid, _ in res.errored if w == wid)
            newly = sorted(broken_now - broken_so_far[art["uri"]])
            broken_so_far[art["uri"]] -= recovered | set(relocated)
            broken_so_far[art["uri"]] |= broken_now
            records.append(
                {
                    "artifact": art["uri"],
                    "commit": sha,
                    "baseline_alarm": bool(set(changed) & art["support_files"]),
                    "dorian_alarm": bool(newly),
                    "broken_claims": newly,
                    "relocated": relocated,
                    "errored": errored,
                }
            )
        prev = sha

    result = {
        "name": entry["name"],
        "t0": t0,
        "commits": commits,
        "artifacts": [
            {
                "uri": a["uri"],
                "backed_claim_ratio": a["backed_claim_ratio"],
                "claims": a["claims"],
            }
            for a in sealed
        ],
        "records": records,
    }
    if breaking is not None:
        result["breaking_commits"] = breaking
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.replay", description=__doc__)
    ap.add_argument("--config", default="bench/repos.json")
    ap.add_argument("--workspace", default="bench/workspace")
    ap.add_argument("--out", default="bench/results")
    args = ap.parse_args(argv)

    config_path = Path(args.config).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    repos = [replay_repo(entry, workspace, config_path.parent) for entry in cfg["repos"]]
    results = {"spec": "dorian-bench-results-v0", "repos": repos}
    results_path = out / "results.json"
    results_path.write_text(
        json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    total = sum(len(r["records"]) for r in repos)
    print(f"replayed {len(repos)} repo(s), {total} (artifact, commit) record(s) -> {results_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
