"""Binding-quality diagnostics (`dorian bindings`): the v0.0 false-negative class.

Matrix:
(a) token extraction classes: backtick spans, path-like tokens, snake_case and
    CamelCase identifiers (length >= 4)
(b) regression of the v0.0 FN shape: claim text mentions a token that lives in
    BOTH the watched file and an unwatched file -> 'unwatched-mention' with the
    unwatched path listed; re-sealing with a second checker watching that file
    clears the flag
(c) 'unbacked', 'single-file', 'short-literal' each with positive and negative
    cases (short-literal covers both C3 string: and C5 shell-grep programs)
(d) multi-file support binding end to end: a claim with two checkers watching
    DIFFERENT files — revalidate fires when either file changes alone (both
    directions)
(e) no file content in any diagnostic output: a planted distinctive source line
    never appears in the text or --json output (paths only)
(f) binary (null-byte) and oversized (> 1 MiB) tracked files are skipped
    without error
(g) cmd_bindings guards: missing repo / artifact outside repo / missing warrant
    sidecar are usage (exit 2); a tampered sidecar is integrity (exit 4);
    diagnostics themselves always exit 0
(h) scan caps bound the WORK, not just the report: candidate tokens are capped
    at extraction time and each file is scanned once with a combined pattern
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from conftest import CONFIG_PY, ROUTES_PY, commit_all, write
from dorian import bindings, cli, commands, gitio
from dorian.capture.manual import parse_manual
from dorian.model import CheckerSpec, Claim, Warrant
from dorian.revalidate import revalidate
from dorian.seal import seal_artifact

POLICY_PY = 'cert = "rotate-30d"\nWINDOW_DAYS = 30\n'
TLS_PY = 'def load_cert():\n    return read("cert")\n'

CERT_CLAIM_TEXT = "The `cert` rotation policy lives in src/policy.py."


def _ns(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def _cert_claim(*extra_checkers: CheckerSpec) -> Claim:
    return Claim(
        id="c-cert",
        text=CERT_CLAIM_TEXT,
        kind="fact",
        load_bearing=True,
        supports=("rs-0",),
        checkers=(
            CheckerSpec(type="C3", program="string:src/policy.py::rotate-30d"),
            *extra_checkers,
        ),
    )


def _seal_cert_repo(repo: Path, *extra_checkers: CheckerSpec) -> Warrant:
    """Fixture repo + the cert files, sealed with the cert claim."""
    return seal_artifact(
        repo,
        "docs/design.md",
        parse_manual(["src/policy.py"], repo),
        [_cert_claim(*extra_checkers)],
    )


# --- (a) token extraction ----------------------------------------------------------


def test_token_extraction_classes() -> None:
    toks = bindings._tokens("Uses `cert`, src/auth.py, parse_token and CertStore plus ab_c.")
    assert toks == ["cert", "src/auth.py", "parse_token", "ab_c", "CertStore"]
    # identifiers shorter than 4 chars are noise, not tokens
    assert bindings._tokens("a_b or AbC here") == []


# --- (b) the v0.0 false-negative regression ----------------------------------------


def test_unwatched_mention_regression_then_reseal_clears(fixture_repo: Path) -> None:
    write(fixture_repo, "src/policy.py", POLICY_PY)
    write(fixture_repo, "src/tls.py", TLS_PY)
    commit_all(fixture_repo, "add cert policy and tls helper")

    # checker watches src/policy.py only; 'cert' also lives in src/tls.py
    _seal_cert_repo(fixture_repo)
    (diag,) = bindings.analyze(fixture_repo, "docs/design.md")
    assert diag["claim_id"] == "c-cert"
    assert diag["watch"] == ["src/policy.py"]
    assert "unwatched-mention" in diag["flags"]
    assert diag["mentions"] == [{"token": "cert", "unwatched_files": ["src/tls.py"]}]

    # re-seal with a second checker watching the mentioned file: the flag clears
    _seal_cert_repo(fixture_repo, CheckerSpec(type="C3", program="string:src/tls.py::load_cert"))
    (diag2,) = bindings.analyze(fixture_repo, "docs/design.md")
    assert diag2["flags"] == []
    assert diag2["mentions"] == []
    assert diag2["watch"] == ["src/policy.py", "src/tls.py"]


# --- (h) scan caps bound the work, not just the report ------------------------------


def test_token_stuffed_claim_is_capped_and_fast(fixture_repo: Path) -> None:
    """The candidate cap bounds the SCAN itself: a claim stuffed with hundreds
    of backticked tokens analyzes quickly, considers only the first
    _MAX_CANDIDATES tokens in extraction order, and stays deterministic."""
    write(fixture_repo, "src/policy.py", POLICY_PY)
    write(fixture_repo, "src/tls.py", TLS_PY)
    commit_all(fixture_repo, "add cert policy and tls helper")
    noise = " ".join(f"`noise_token_{i:03d}`" for i in range(400))
    text = f"`cert` and `load_cert` rotate; {noise}; also `read`."
    claim = Claim(
        id="c-stuffed",
        text=text,
        kind="fact",
        load_bearing=True,
        supports=("rs-0",),
        checkers=(CheckerSpec(type="C3", program="string:src/policy.py::rotate-30d"),),
    )
    seal_artifact(
        fixture_repo, "docs/design.md", parse_manual(["src/policy.py"], fixture_repo), [claim]
    )
    start = time.monotonic()
    (diag,) = bindings.analyze(fixture_repo, "docs/design.md")
    assert time.monotonic() - start < 5.0  # generous CI bound; unbounded scan took minutes
    # `read` also lives in src/tls.py but sits past the candidate cap: never scanned
    assert [m["token"] for m in diag["mentions"]] == ["cert", "load_cert"]
    (diag2,) = bindings.analyze(fixture_repo, "docs/design.md")
    assert diag2 == diag


def test_scan_files_combined_pass_keeps_overlapping_token_hits(tmp_path: Path) -> None:
    """The single combined pass must equal per-token semantics: same-start
    prefixes and tokens inside longer matches all hit; word-internal
    substrings still do not."""
    write(tmp_path, "note.txt", "see src/auth.py here\n")
    tokens = ["src", "src/auth.py", "auth", "py", "ut"]
    hits = bindings._scan_files(tmp_path, ["note.txt"], tokens, skip=set())
    assert hits == {
        "src": ["note.txt"],
        "src/auth.py": ["note.txt"],
        "auth": ["note.txt"],
        "py": ["note.txt"],
        "ut": [],  # inside 'auth' with word-char boundaries: not a whole-word hit
    }


# --- (c) flag positive/negative cases ----------------------------------------------


def test_unbacked_and_single_file_flags(fixture_repo: Path) -> None:
    claims = [
        Claim(id="cu", text="An aspirational statement.", kind="fact", load_bearing=False),
        Claim(
            id="cb",
            text="A statement watched in one file.",
            kind="fact",
            load_bearing=False,
            checkers=(CheckerSpec(type="C3", program="string:src/config.py::TIMEOUT = 30"),),
        ),
        Claim(
            id="cm",
            text="A statement watched in two files.",
            kind="fact",
            load_bearing=False,
            checkers=(
                CheckerSpec(type="C3", program="string:src/config.py::TIMEOUT = 30"),
                CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),
            ),
        ),
    ]
    seal_artifact(fixture_repo, "docs/design.md", parse_manual([], fixture_repo), claims)
    by_id = {d["claim_id"]: d for d in bindings.analyze(fixture_repo, "docs/design.md")}
    assert by_id["cu"]["flags"] == ["unbacked"]  # positive; never also single-file
    assert "unbacked" not in by_id["cb"]["flags"]  # negative
    assert "single-file" in by_id["cb"]["flags"]  # positive
    assert by_id["cm"]["flags"] == []  # negative: two distinct watched files


def test_short_literal_flag(fixture_repo: Path) -> None:
    claims = [
        Claim(
            id="cs",
            text="A claim pinned to a tiny literal.",
            kind="fact",
            load_bearing=False,
            checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1"),),
        ),
        Claim(
            id="cl",
            text="A claim pinned to a real literal.",
            kind="fact",
            load_bearing=False,
            checkers=(CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),),
        ),
        Claim(
            id="cg",
            text="A claim grep-checked with a tiny pattern.",
            kind="fact",
            load_bearing=False,
            checkers=(
                CheckerSpec(
                    type="C5",
                    program="shell:grep -q TIMEO src/config.py",
                    watch=("src/config.py",),
                ),
            ),
        ),
        Claim(
            id="cg2",
            text="A claim grep-checked with a real pattern.",
            kind="fact",
            load_bearing=False,
            checkers=(
                CheckerSpec(
                    type="C5",
                    program='shell:grep -Eq "TIMEOUT *= *30" src/config.py',
                    watch=("src/config.py",),
                ),
            ),
        ),
    ]
    seal_artifact(fixture_repo, "docs/design.md", parse_manual([], fixture_repo), claims)
    by_id = {d["claim_id"]: d for d in bindings.analyze(fixture_repo, "docs/design.md")}
    assert "short-literal" in by_id["cs"]["flags"]  # C3 string positive (3 chars)
    assert "short-literal" not in by_id["cl"]["flags"]  # C3 string negative
    assert "short-literal" in by_id["cg"]["flags"]  # shell-grep positive (5 chars)
    assert "short-literal" not in by_id["cg2"]["flags"]  # shell-grep negative


# --- (d) multi-file binding end to end ----------------------------------------------


@pytest.mark.parametrize("break_file", ["src/config.py", "src/routes.py"])
def test_multi_file_binding_fires_on_either_file_alone(fixture_repo: Path, break_file: str) -> None:
    """A claim with two checkers watching DIFFERENT files must revalidate when
    either file changes alone — the binding shape whose absence caused the
    v0.0 recall miss."""
    claims = [
        Claim(
            id="cm",
            text="Timeout and login are both still as documented.",
            kind="fact",
            load_bearing=True,
            checkers=(
                CheckerSpec(type="C3", program="string:src/config.py::TIMEOUT = 30"),
                CheckerSpec(type="C3", program="string:src/routes.py::/v1/login"),
            ),
        )
    ]
    w = seal_artifact(fixture_repo, "docs/design.md", parse_manual([], fixture_repo), claims)
    (diag,) = bindings.analyze(fixture_repo, "docs/design.md")
    assert "single-file" not in diag["flags"]

    base = gitio.head_ref(fixture_repo)
    if break_file == "src/config.py":
        write(fixture_repo, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10"))
    else:
        write(
            fixture_repo,
            "src/routes.py",
            ROUTES_PY.replace('    "/v1/login": "auth.login",\n', ""),
        )

    res = revalidate(fixture_repo, since=base)
    assert res.candidates == 1  # selected via the one changed file alone
    assert [(wid, cid) for wid, cid, _ in res.broken] == [(w.id, "cm")]
    assert res.exit_code == 4  # load-bearing break folds REVOKED


# --- (e) content-free output ---------------------------------------------------------


def test_no_file_content_in_outputs(fixture_repo: Path, capsys) -> None:
    marker = "XYZZY_SECRET_SOURCE_LINE_7777"
    write(fixture_repo, "src/policy.py", POLICY_PY)
    write(fixture_repo, "src/tls.py", TLS_PY + f'secret = "{marker}"  # cert\n')
    commit_all(fixture_repo, "add cert files with a distinctive line")
    _seal_cert_repo(fixture_repo)

    args = _ns("--repo", str(fixture_repo), "bindings", "docs/design.md")
    assert commands.cmd_bindings(args) == 0
    out = capsys.readouterr().out
    assert "cert -> unwatched: src/tls.py" in out
    assert "1 claim(s), 1 flagged" in out
    assert marker not in out  # paths only, never matched content

    args = _ns("--json", "--repo", str(fixture_repo), "bindings", "docs/design.md")
    assert commands.cmd_bindings(args) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert marker not in out
    (diag,) = data["claims"]
    assert diag["mentions"] == [{"token": "cert", "unwatched_files": ["src/tls.py"]}]
    assert "unwatched-mention" in diag["flags"]


# --- (f) binary and oversized files skipped -----------------------------------------


def test_binary_and_oversized_files_skipped(fixture_repo: Path) -> None:
    write(fixture_repo, "src/policy.py", POLICY_PY)
    write(fixture_repo, "src/tls.py", TLS_PY)
    (fixture_repo / "data" / "blob.bin").write_bytes(b"\x00cert\x00binary\x00")
    write(fixture_repo, "data/big.txt", "cert\n" + "x" * (1 << 20))
    commit_all(fixture_repo, "add cert files plus binary and oversized noise")
    _seal_cert_repo(fixture_repo)

    (diag,) = bindings.analyze(fixture_repo, "docs/design.md")  # no error raised
    assert diag["mentions"] == [{"token": "cert", "unwatched_files": ["src/tls.py"]}]


# --- (g) cmd_bindings guards ---------------------------------------------------------


def test_cmd_bindings_missing_repo_is_usage(tmp_path: Path, capsys) -> None:
    args = _ns("--repo", str(tmp_path / "nope"), "bindings", "docs/design.md")
    assert commands.cmd_bindings(args) == 2
    assert "dorian bindings:" in capsys.readouterr().err


def test_cmd_bindings_artifact_outside_repo_is_usage(fixture_repo: Path, capsys) -> None:
    args = _ns("--repo", str(fixture_repo), "bindings", "/etc/hosts")
    assert commands.cmd_bindings(args) == 2
    err = capsys.readouterr().err
    assert "dorian bindings:" in err
    assert "outside repo" in err


def test_cmd_bindings_missing_warrant_is_usage(fixture_repo: Path, capsys) -> None:
    args = _ns("--repo", str(fixture_repo), "bindings", "docs/design.md")
    assert commands.cmd_bindings(args) == 2
    err = capsys.readouterr().err
    assert "dorian bindings:" in err
    assert "no warrant" in err


def test_cmd_bindings_tampered_sidecar_is_integrity(fixture_repo: Path, capsys) -> None:
    write(fixture_repo, "src/policy.py", POLICY_PY)
    commit_all(fixture_repo, "add cert policy")
    _seal_cert_repo(fixture_repo)
    sidecar = fixture_repo / "docs" / "design.md.warrant"
    sidecar.write_text(sidecar.read_text().replace('"kind": "fact"', '"kind": "quantity"'))

    args = _ns("--repo", str(fixture_repo), "bindings", "docs/design.md")
    assert commands.cmd_bindings(args) == 4
    assert "corrupt warrant sidecar" in capsys.readouterr().err


def test_cmd_bindings_exits_zero_even_when_flagged(fixture_repo: Path, capsys) -> None:
    """Diagnostics, not a gate: a fully flagged warrant still exits 0."""
    claims = [Claim(id="cu", text="An unbacked statement.", kind="fact", load_bearing=True)]
    seal_artifact(fixture_repo, "docs/design.md", parse_manual([], fixture_repo), claims)
    args = _ns("--repo", str(fixture_repo), "bindings", "docs/design.md")
    assert commands.cmd_bindings(args) == 0
    out = capsys.readouterr().out
    assert "flags: unbacked" in out
    assert "1 claim(s), 1 flagged" in out


# --- Phase-0 nit 1: C4 nodeid whitespace parity with seal._derive_watch -----------------


def test_checker_named_files_strips_c4_nodeid_whitespace() -> None:
    """seal._derive_watch strips the C4 nodeid's file part; _checker_named_files
    must strip it too. A whitespace-padded pytest nodeid otherwise yields
    named=' tests/x.py' != watch='tests/x.py', a spurious 'trigger-only-symbol'
    advisory flag. Content-free: asserts the path string only."""
    spec = CheckerSpec(
        type="C4",
        program="pytest: tests/test_auth.py::test_login ",
        watch=("tests/test_auth.py",),  # what _derive_watch stores (stripped)
    )
    claim = Claim(id="c", text="x", kind="behavior", load_bearing=True, checkers=(spec,))
    named = bindings._checker_named_files(claim, {})
    assert named == {"tests/test_auth.py"}  # stripped, not ' tests/test_auth.py'
    # parity with the stored watch => the trigger-only-symbol predicate cannot fire
    assert all(w in named for s in claim.checkers for w in s.watch)


# --- Phase-0 nit 2: backticked common words are not binding tokens -----------------------


def test_backticked_common_word_is_not_a_token() -> None:
    """A bare common word in backticks ('`config`', '`list`', '`token`', '`handler`')
    is markup, not a symbol reference: it must not become a candidate token, or it would
    bind a one-definer symbol and risk a false BROKEN. Real identifiers — snake_case,
    CamelCase, and non-common bare idents like 'cert' — still tokenize."""
    assert bindings._tokens("The `config` and `list` and `token` and `handler`.") == []
    assert bindings._tokens("Login uses `verify_token` and `TokenVerifier`.") == [
        "verify_token",
        "TokenVerifier",
    ]
    assert bindings._tokens("The `cert` rotates.") == ["cert"]  # not common: still a token


def test_checker_named_files_counts_c5_shell_explicit_watch() -> None:
    """A C5 shell checker derives no data path (_c5_data_paths returns [] for shell),
    so its EXPLICIT watch is what it exercises. _checker_named_files must count that
    watch, or a load-bearing shell claim gets a spurious 'trigger-only-symbol' flag."""
    spec = CheckerSpec(
        type="C5",
        program="shell:grep -q rotate data/policy.csv",
        watch=("data/policy.csv",),
        expect="exit:0",
    )
    claim = Claim(id="c", text="x", kind="fact", load_bearing=True, checkers=(spec,))
    named = bindings._checker_named_files(claim, {})
    assert named == {"data/policy.csv"}  # the shell checker's explicit watch is named
    assert all(w in named for s in claim.checkers for w in s.watch)  # => no spurious flag
