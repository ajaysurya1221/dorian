"""Determinism and flake-resistance — the actual contracts, not assumptions.

A subtlety worth pinning: the warrant id is content-addressed over the *whole*
body, including `sealed_at` (a wall-clock stamp) — so `Warrant.create` is a pure
function of its body (same body -> same id; a different `sealed_at` -> a different
id). At the seal layer, though, re-running verify/seal on MATERIALLY identical
content is idempotent: the existing sidecar is kept byte-for-byte (the two wall-clock
stamps are masked when comparing), so a re-run never churns a committed sidecar; a
real change still re-seals. `report --audit` is byte-identical across runs and
`sync` rebuilds the same index from the sidecars.
"""

from __future__ import annotations

import io
import json
import shutil
from contextlib import redirect_stdout
from pathlib import Path

from dorian import cli, store
from dorian.model import FoldPolicy, ProducedBy, Warrant, canonical_json


def _mk(sealed_at: str) -> Warrant:
    return Warrant.create(
        artifact_uri="a.md",
        artifact_hash="sha256:x",
        git_ref="r",
        produced_by=ProducedBy(runner="m", captured_at="2026-01-01T00:00:00Z"),
        read_set=(),
        claims=(),
        fold_policy=FoldPolicy(),
        sealed_at=sealed_at,
    )


def test_warrant_id_is_pure_function_of_body() -> None:
    assert _mk("2026-01-01T00:00:00Z").id == _mk("2026-01-01T00:00:00Z").id
    # sealed_at is in the hashed body, so a re-seal at a later second changes the id
    assert _mk("2026-01-01T00:00:00Z").id != _mk("2099-01-01T00:00:00Z").id


def test_canonical_json_is_key_order_independent_and_stable() -> None:
    a = {"b": 1, "a": [3, 2, 1], "c": {"y": 1, "x": 2}}
    b = {"c": {"x": 2, "y": 1}, "a": [3, 2, 1], "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert canonical_json(a) == canonical_json(a)


def _capture(repo: Path, *args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["--repo", str(repo), *args])
    return rc, buf.getvalue()


def _seal_and_break(repo: Path) -> None:
    claims = {
        "claims": [
            {
                "id": "login-route",
                "text": "Login is served at /v1/login.",
                "kind": "reference",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "string:src/routes.py::/v1/login"}],
            }
        ]
    }
    cp = repo / "claims.json"
    cp.write_text(json.dumps(claims), encoding="utf-8")
    rc, _ = _capture(repo, "verify", "docs/design.md", "--claims", str(cp))
    assert rc == 0
    routes = repo / "src/routes.py"
    routes.write_text(routes.read_text().replace('"/v1/login": "auth.login",\n', ""))


def test_audit_export_is_byte_identical_across_runs(fixture_repo: Path) -> None:
    _seal_and_break(fixture_repo)
    rc, _ = _capture(fixture_repo, "revalidate", "--since", "HEAD")
    assert rc == 4
    _rc1, a = _capture(fixture_repo, "report", "--audit")
    _rc2, b = _capture(fixture_repo, "report", "--audit")
    assert a == b and a.strip(), "audit export must be byte-identical and non-empty"


def test_sync_rebuild_from_sidecars_is_idempotent(fixture_repo: Path) -> None:
    _seal_and_break(fixture_repo)

    def indexed_ids() -> list[str]:
        conn = store.connect(fixture_repo)
        try:
            rows = conn.execute("SELECT id, artifact_uri FROM warrant ORDER BY id").fetchall()
        finally:
            conn.close()
        return [(r["id"], r["artifact_uri"]) for r in rows]

    rc, out1 = _capture(fixture_repo, "sync")
    assert rc == 0
    before = indexed_ids()
    assert before, "expected at least one indexed warrant"

    # blow away the derived index entirely and rebuild from the committed sidecars
    shutil.rmtree(fixture_repo / store.DORIAN_DIR)
    rc, out2 = _capture(fixture_repo, "sync")
    assert rc == 0
    after = indexed_ids()

    assert before == after, "sync rebuild must reproduce the same warrant index"
    assert out1.strip() == out2.strip(), "sync must report the same indexed count"


def test_revalidate_is_deterministic_across_repeats(fixture_repo: Path) -> None:
    """No flake: re-running revalidate on the same working tree yields the same verdict."""
    _seal_and_break(fixture_repo)
    outcomes = []
    for _ in range(3):
        rc, out = _capture(fixture_repo, "revalidate", "--since", "HEAD")
        outcomes.append((rc, "BROKEN" in out and "login-route" in out))
    assert outcomes == [(4, True), (4, True), (4, True)], outcomes


def test_reseal_of_identical_content_is_idempotent(fixture_repo: Path, monkeypatch) -> None:
    """Re-running verify on byte-identical content keeps the committed sidecar (no churn),
    even across a time gap; only a material change re-seals. A forced clock makes the two
    runs' wall-clock stamps differ, so this fails if those stamps aren't masked."""
    import datetime as _dt

    from dorian import seal as _seal
    from dorian.capture import manual as _manual

    class _Clock:
        n = 0

        @classmethod
        def now(cls, tz=None):
            cls.n += 1
            return _dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=_dt.UTC) + _dt.timedelta(seconds=cls.n)

    monkeypatch.setattr(_seal, "datetime", _Clock)
    monkeypatch.setattr(_manual, "datetime", _Clock)

    cp = fixture_repo / "claims.json"

    def _claims(cid: str, program: str) -> None:
        cp.write_text(
            json.dumps(
                {
                    "claims": [
                        {
                            "id": cid,
                            "text": "x",
                            "kind": "reference",
                            "load_bearing": False,
                            "checkers": [{"type": "C3", "program": program}],
                        }
                    ]
                }
            )
        )

    args = ["--repo", str(fixture_repo), "verify", "docs/design.md", "--claims", str(cp)]
    sidecar = fixture_repo / "docs/design.md.warrant"

    _claims("login-route", "string:src/routes.py::/v1/login")
    assert cli.main(args) == 0
    bytes1 = sidecar.read_bytes()

    # re-verify identical content; the clock advanced, so the stamps would differ if unmasked
    assert cli.main(args) == 0
    assert sidecar.read_bytes() == bytes1, "re-seal of identical content churned the sidecar"

    # a material change (different claim + watched file) DOES re-seal
    _claims("timeout", "string:src/config.py::TIMEOUT")
    assert cli.main(args) == 0
    assert sidecar.read_bytes() != bytes1, "a material change must produce a new warrant"
