"""Multi-index binding (WP5): config-key index for TOML/JSON.

Binding widens the set of source changes that RE-CHECK a claim. v0.11 indexed only
Python definers and pyproject console scripts; this adds config keys in tracked
`.toml`/`.json` files, so a claim mentioning a config key is re-checked when the
defining config file changes. It stays conservative and trigger-only:

- only UNAMBIGUOUS keys (defined in exactly one tracked config file) are bound; a key
  in more than one file is surfaced and left unwatched (a wrong watch is a false alarm);
- an unparseable supported config file is surfaced as a diagnostic, never a silent skip;
- YAML is intentionally NOT indexed — parsing it needs a third-party dependency and
  dorian's core has zero runtime deps;
- binding never proves truth — it only decides WHEN the claim is re-checked.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import commit_all, git, write
from dorian import cli, symbol_index
from dorian.model import Claim


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    return repo


def _claim(cid: str, text: str, program: str) -> Claim:
    from dorian.model import CheckerSpec

    return Claim(
        id=cid,
        text=text,
        kind="quantity",
        load_bearing=True,
        checkers=(CheckerSpec(type="C3", program=program),),
    )


def test_config_key_index_toml_and_json(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, "settings.toml", "[database]\nmax_connections = 5\n")
    write(repo, "feature.json", '{"flags": {"new_login": true}}\n')
    commit_all(repo, "config")
    index, unparseable = symbol_index.config_key_index(repo)
    assert index["max_connections"] == ("settings.toml",)
    assert index["database"] == ("settings.toml",)
    assert index["new_login"] == ("feature.json",)
    assert unparseable == ()


def test_claim_mentioning_config_key_binds_the_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, "settings.toml", "[database]\nmax_connections = 5\n")
    commit_all(repo, "config")
    claims = [_claim("c", "The `max_connections` pool size is 5.", "path:settings.toml")]
    watch = symbol_index.claim_config_watch_paths(repo, claims)
    assert watch == {"c": ("settings.toml",)}


def test_ambiguous_config_key_is_skipped_and_surfaced(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, "a.toml", "max_connections = 5\n")
    write(repo, "b.toml", "max_connections = 9\n")
    commit_all(repo, "two configs")
    claims = [_claim("c", "The `max_connections` value matters.", "path:a.toml")]
    # ambiguous (2 files) -> no guessed watch
    assert symbol_index.claim_config_watch_paths(repo, claims) == {}
    # ...but surfaced for the author to disambiguate
    amb = symbol_index.ambiguous_config_mentions(repo, claims)
    assert set(amb["c"]["max_connections"]) == {"a.toml", "b.toml"}


def test_unparseable_config_is_a_diagnostic_not_silent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, "broken.json", "{not valid json\n")
    write(repo, "ok.toml", "key_name = 1\n")
    commit_all(repo, "configs")
    index, unparseable = symbol_index.config_key_index(repo)
    assert "broken.json" in unparseable  # surfaced, not silently dropped
    assert index["key_name"] == ("ok.toml",)  # the parseable one still indexes


def test_yaml_is_not_indexed_zero_runtime_dep(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, "conf.yaml", "max_connections: 5\n")
    commit_all(repo, "yaml")
    index, unparseable = symbol_index.config_key_index(repo)
    assert "max_connections" not in index  # YAML excluded by design
    assert "conf.yaml" not in unparseable  # not even attempted


def test_claim_watch_paths_merges_symbol_and_config(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, "src/app.py", "def make_pool():\n    return 1\n")
    write(repo, "settings.toml", "[server]\nmax_workers = 4\n")
    commit_all(repo, "code + config")
    claims = [_claim("c", "`make_pool` reads `max_workers` from settings.", "path:settings.toml")]
    watch = symbol_index.claim_watch_paths(repo, claims)
    assert set(watch["c"]) == {"src/app.py", "settings.toml"}  # symbol + config union


# --- end to end: a config-key claim re-checks when the config file changes -----


def test_verify_binds_config_and_revalidate_rechecks(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, "settings.toml", "[server]\nmax_workers = 4\n")
    write(repo, "note.md", "# note\n\nThe server uses 4 max_workers.\n")
    commit_all(repo, "init")
    base = git(repo, "rev-parse", "HEAD")
    # the claim's CHECKER names note-adjacent text but the binding watches settings.toml
    claims = {
        "claims": [
            {
                "id": "workers",
                "text": "The server `max_workers` pool is 4.",
                "kind": "quantity",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "py-const:settings.toml::placeholder::0"}],
            }
        ]
    }
    # use a config-only checker that can't parse TOML as python -> would ERROR; instead
    # bind via a real checker on the toml. Simpler: a regex checker on the toml value.
    claims["claims"][0]["checkers"] = [
        {"type": "C3", "program": r"regex:settings.toml::max_workers\s*=\s*4"}
    ]
    cp = repo / "claims.json"
    cp.write_text(json.dumps(claims), encoding="utf-8")
    assert cli.main(["--repo", str(repo), "verify", "note.md", "--claims", str(cp)]) == 0

    # the symbol/config binding is moot here (checker already names settings.toml), so
    # assert the config index would bind it independently of the checker:
    parsed = [Claim.from_dict(c) for c in claims["claims"]]
    assert "settings.toml" in symbol_index.claim_watch_paths(repo, parsed).get("workers", ())

    write(repo, "settings.toml", "[server]\nmax_workers = 8\n")  # drift
    assert cli.main(["--repo", str(repo), "revalidate", "--since", base]) == cli.EXIT_REVOKED


def test_common_config_key_does_not_bind(tmp_path: Path) -> None:
    """A common PEP 621 / config word (dependencies, version, name, ...) is English prose,
    not a specific key to bind — it must NOT auto-watch the config file (over-binding noise,
    and it can pull a restricted config file into the scope-linted read-set)."""
    repo = _repo(tmp_path)
    write(repo, "pyproject.toml", '[project]\nname = "x"\nversion = "0"\ndependencies = []\n')
    commit_all(repo, "pyproject")
    claims = [_claim("c", "Updated the `dependencies` and `version`.", "path:pyproject.toml")]
    assert symbol_index.claim_config_watch_paths(repo, claims) == {}
    assert symbol_index.ambiguous_config_mentions(repo, claims) == {}


def test_specific_config_key_still_binds(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write(repo, "settings.toml", "[server]\nmax_workers = 4\n")
    commit_all(repo, "cfg")
    claims = [_claim("c", "`max_workers` is 4.", "path:settings.toml")]
    assert symbol_index.claim_config_watch_paths(repo, claims) == {"c": ("settings.toml",)}


def test_common_config_word_does_not_newly_refuse_a_clean_seal(tmp_path: Path) -> None:
    """Backward-compat regression (found by adversarial review): on a repo whose pyproject is
    under a restricted scope glob, a claim merely backticking `dependencies` must NOT newly
    refuse `verify` with exit 6 — the checker names note.md, not pyproject.toml."""
    repo = _repo(tmp_path)
    write(
        repo,
        "pyproject.toml",
        '[project]\nname = "x"\nversion = "0"\ndependencies = []\n\n'
        '[tool.dorian.scopes]\nrestricted = ["pyproject.toml"]\n',
    )
    write(repo, "note.md", "# n\n\nUpdated the dependencies list.\n")
    commit_all(repo, "restricted pyproject")
    claims = {
        "claims": [
            {
                "id": "c",
                "text": "Updated the `dependencies` list.",
                "kind": "reference",
                "load_bearing": False,
                "checkers": [{"type": "C3", "program": "path:note.md"}],
            }
        ]
    }
    cp = repo / "claims.json"
    cp.write_text(json.dumps(claims), encoding="utf-8")
    rc = cli.main(["--repo", str(repo), "verify", "note.md", "--claims", str(cp)])
    assert rc == 0  # `dependencies` must not pull restricted pyproject.toml into the read-set


def test_bind_suggest_shows_config_provenance(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    write(repo, "settings.toml", "[server]\nmax_workers = 4\n")
    write(repo, "broken.json", "{bad\n")
    commit_all(repo, "configs")
    claims = {
        "claims": [
            {
                "id": "w",
                "text": "The `max_workers` pool is 4.",
                "kind": "quantity",
                "load_bearing": True,
                "checkers": [{"type": "C3", "program": "path:settings.toml"}],
            }
        ]
    }
    cp = repo / "claims.json"
    cp.write_text(json.dumps(claims), encoding="utf-8")
    assert cli.main(["--repo", str(repo), "bind-suggest", "--claims", str(cp)]) == 0
    out = capsys.readouterr().out
    assert "config" in out  # provenance label for the config-key binding
    assert "broken.json" in out  # unparseable config surfaced as a diagnostic
