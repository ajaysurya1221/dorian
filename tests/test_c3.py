"""C3 referential checker acceptance: path/symbol/string/regex grammars on fixture_repo."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from conftest import apply_three_change_commit
from dorian.checkers.base import CheckContext, CheckResult, Verdict, run_checker
from dorian.model import CheckerSpec, Claim

RENAMED = {"src/auth.py": "src/tokens.py"}


def run_c3(repo: Path, program: str, rename_map: dict[str, str] | None = None) -> CheckResult:
    spec = CheckerSpec(type="C3", program=program)
    claim = Claim(id="cl1", text="ref claim", kind="reference", load_bearing=True, checkers=(spec,))
    ctx = CheckContext(repo=repo, claim=claim, rename_map=rename_map or {})
    return run_checker(ctx, 0)


# --- path: ---------------------------------------------------------------------


def test_path_file_exists_pass(fixture_repo):
    assert run_c3(fixture_repo, "path:src/auth.py").verdict is Verdict.PASS


def test_path_directory_exists_pass(fixture_repo):
    assert run_c3(fixture_repo, "path:src").verdict is Verdict.PASS


def test_path_missing_fail_ref_missing(fixture_repo):
    res = run_c3(fixture_repo, "path:src/gone.py")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "ref_missing"


def test_path_through_rename_map_pass(fixture_repo):
    apply_three_change_commit(fixture_repo)
    assert run_c3(fixture_repo, "path:src/auth.py", RENAMED).verdict is Verdict.PASS


# --- symbol: -------------------------------------------------------------------


def test_symbol_present_pass(fixture_repo):
    assert run_c3(fixture_repo, "symbol:src/auth.py::verify_token").verdict is Verdict.PASS


def test_symbol_after_rename_pass_against_new_path(fixture_repo):
    apply_three_change_commit(fixture_repo)
    res = run_c3(fixture_repo, "symbol:src/auth.py::verify_token", RENAMED)
    assert res.verdict is Verdict.PASS


def test_symbol_nonexistent_fail(fixture_repo):
    assert run_c3(fixture_repo, "symbol:src/auth.py::nonexistent").verdict is Verdict.FAIL


def test_symbol_file_gone_fail(fixture_repo):
    apply_three_change_commit(fixture_repo)  # no rename_map: src/auth.py is gone
    res = run_c3(fixture_repo, "symbol:src/auth.py::verify_token")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "file_gone"


# --- string: -------------------------------------------------------------------


def test_string_present_pass_then_route_deleted_fail(fixture_repo):
    program = "string:src/routes.py::/v1/login"
    assert run_c3(fixture_repo, program).verdict is Verdict.PASS
    apply_three_change_commit(fixture_repo)  # route deleted; routes.py not renamed
    assert run_c3(fixture_repo, program).verdict is Verdict.FAIL


def test_string_literal_may_contain_colons(fixture_repo):
    res = run_c3(fixture_repo, "string:src/config.py::https://api.example.test")
    assert res.verdict is Verdict.PASS


def test_string_file_gone_fail(fixture_repo):
    apply_three_change_commit(fixture_repo)
    res = run_c3(fixture_repo, "string:src/auth.py::RS256")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "file_gone"


def test_string_through_rename_map_pass(fixture_repo):
    apply_three_change_commit(fixture_repo)
    res = run_c3(fixture_repo, "string:src/auth.py::RS256", RENAMED)
    assert res.verdict is Verdict.PASS


def test_symbol_requires_left_word_boundary(fixture_repo):
    # 'undef verify_token' must not satisfy (def|class)\s+verify_token
    (fixture_repo / "src" / "odd.py").write_text("undef verify_token\n")
    res = run_c3(fixture_repo, "symbol:src/odd.py::verify_token")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "symbol_missing"


# --- bad programs --------------------------------------------------------------


def test_unknown_prefix_error_bad_program(fixture_repo):
    res = run_c3(fixture_repo, "bogus:xyz")
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_symbol_missing_separator_error(fixture_repo):
    res = run_c3(fixture_repo, "symbol:src/auth.py")
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_string_missing_separator_error(fixture_repo):
    res = run_c3(fixture_repo, "string:src/auth.py")
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_empty_operands_error_not_vacuous_pass(fixture_repo):
    for program in ("path:", "symbol:src/auth.py::", "string:src/auth.py::", "symbol:::name"):
        res = run_c3(fixture_repo, program)
        assert res.verdict is Verdict.ERROR, program
        assert res.detail == "bad_program", program


# --- repo containment -----------------------------------------------------------


def test_path_dotdot_escape_error(fixture_repo):
    (fixture_repo.parent / "secret.txt").write_text("root\n")
    res = run_c3(fixture_repo, "path:../secret.txt")
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_path_absolute_escape_error(fixture_repo):
    outside = fixture_repo.parent / "secret.txt"
    outside.write_text("root\n")
    res = run_c3(fixture_repo, f"path:{outside}")
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_string_escape_error_not_content_oracle(fixture_repo):
    (fixture_repo.parent / "secret.txt").write_text("root\n")
    res = run_c3(fixture_repo, "string:../secret.txt::root")
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


# --- regex: ----------------------------------------------------------------------


def reformat_config(repo: Path) -> None:
    """The v0.0 false-positive shape: reflow 'TIMEOUT = 30' to 'TIMEOUT=30' —
    the stated fact (timeout is 30) survives, only the literal's shape changes."""
    config = repo / "src" / "config.py"
    config.write_text(config.read_text().replace("TIMEOUT = 30", "TIMEOUT=30"))


def test_regex_match_pass(fixture_repo):
    assert run_c3(fixture_repo, r"regex:src/config.py::TIMEOUT\s*=\s*30").verdict is Verdict.PASS


def test_regex_survives_reformat_v0_fp_fix(fixture_repo):
    # the documented fix for the v0.0 FP class: regex passes before AND after reflow
    program = r"regex:src/config.py::TIMEOUT\s*=\s*30"
    assert run_c3(fixture_repo, program).verdict is Verdict.PASS
    reformat_config(fixture_repo)
    assert run_c3(fixture_repo, program).verdict is Verdict.PASS


def test_regex_absent_fail_regex_missing(fixture_repo):
    res = run_c3(fixture_repo, r"regex:src/config.py::TIMEOUT\s*=\s*99")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "regex_missing"


def test_regex_multiline_anchors_bind_per_line(fixture_repo):
    # re.MULTILINE: ^/$ anchor per line, so anchored facts match mid-file
    assert run_c3(fixture_repo, r"regex:src/config.py::^RETRIES = 3$").verdict is Verdict.PASS


def test_regex_invalid_pattern_error(fixture_repo):
    res = run_c3(fixture_repo, "regex:src/config.py::[unclosed")
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_regex_empty_pattern_error(fixture_repo):
    res = run_c3(fixture_repo, "regex:src/config.py::")
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_regex_oversized_pattern_error(fixture_repo):
    res = run_c3(fixture_repo, "regex:src/config.py::" + "a" * 501)
    assert res.verdict is Verdict.ERROR
    assert res.detail == "bad_program"


def test_regex_pattern_at_length_bound_still_runs(fixture_repo):
    res = run_c3(fixture_repo, "regex:src/config.py::" + "a" * 500)
    assert res.verdict is Verdict.FAIL
    assert res.detail == "regex_missing"


def test_regex_through_rename_map_pass(fixture_repo):
    apply_three_change_commit(fixture_repo)
    res = run_c3(fixture_repo, "regex:src/auth.py::RS256", RENAMED)
    assert res.verdict is Verdict.PASS


def test_regex_file_gone_fail(fixture_repo):
    apply_three_change_commit(fixture_repo)  # no rename_map: src/auth.py is gone
    res = run_c3(fixture_repo, "regex:src/auth.py::RS256")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "file_gone"


# --- string: near-miss hints ------------------------------------------------------

_NEAR_MISS_DETAIL_RE = re.compile(
    r"string_missing \(near-miss: line (\d+), ratio (\d\.\d{2})"
    r" — literal may have changed shape; consider regex:\)"
)


def test_string_fail_after_reformat_carries_near_miss_hint(fixture_repo):
    # regression of the v0.0 FP shape: literal absent after reflow, fact intact
    reformat_config(fixture_repo)
    res = run_c3(fixture_repo, "string:src/config.py::TIMEOUT = 30")
    assert res.verdict is Verdict.FAIL
    m = _NEAR_MISS_DETAIL_RE.fullmatch(res.detail)
    assert m, res.detail
    assert int(m.group(1)) == 1  # TIMEOUT is line 1 of config.py
    assert float(m.group(2)) >= 0.8
    assert "TIMEOUT" not in res.detail  # line number + ratio only, never content


def test_near_miss_reports_one_based_line_number(fixture_repo):
    (fixture_repo / "src" / "near.py").write_text("alpha\nbeta\nWIDGET_LIMIT=250\n")
    res = run_c3(fixture_repo, "string:src/near.py::WIDGET_LIMIT = 250")
    assert res.verdict is Verdict.FAIL
    m = _NEAR_MISS_DETAIL_RE.fullmatch(res.detail)
    assert m, res.detail
    assert int(m.group(1)) == 3


def test_near_miss_ratio_below_threshold_plain_detail(fixture_repo):
    line, literal = "value_x = 11", "value_y = 99"
    sm = difflib.SequenceMatcher(None, line, literal, autojunk=False)
    assert 0.7 <= sm.ratio() < 0.8  # guard: similar, but below the 0.8 threshold
    (fixture_repo / "src" / "near.py").write_text(line + "\n")
    res = run_c3(fixture_repo, f"string:src/near.py::{literal}")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "string_missing"


def test_near_miss_quick_ratio_prefilter_is_pass_through(fixture_repo):
    # an anagram line maxes quick_ratio() (same character counts) but its true
    # ratio() is below threshold: the cheap prefilter must hand such lines to
    # the exact ratio() and the result must stay a plain string_missing
    line, literal = "052 = TUOEMIT", "TIMEOUT = 250"
    sm = difflib.SequenceMatcher(None, line, literal, autojunk=False)
    assert sm.quick_ratio() == 1.0 and sm.ratio() < 0.8  # guard
    (fixture_repo / "src" / "near.py").write_text(line + "\n")
    res = run_c3(fixture_repo, f"string:src/near.py::{literal}")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "string_missing"


def test_near_miss_skips_tiny_literal(fixture_repo):
    (fixture_repo / "src" / "near.py").write_text("ab 1\n")
    # 'ab1' vs the 'ab 1' line is ratio ~0.86, but literals under 4 chars skip the scan
    res = run_c3(fixture_repo, "string:src/near.py::ab1")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "string_missing"


def test_near_miss_skips_file_over_one_mib(fixture_repo):
    filler = "x" * 100
    lines = [filler] * ((1 << 20) // 101 + 16)  # comfortably > 1 MiB of filler
    lines.append("TIMEOUT=30")
    big = fixture_repo / "src" / "big.py"
    big.write_text("\n".join(lines) + "\n")
    assert big.stat().st_size > (1 << 20)
    res = run_c3(fixture_repo, "string:src/big.py::TIMEOUT = 30")
    assert res.verdict is Verdict.FAIL
    assert res.detail == "string_missing"


def test_details_never_leak_file_content(fixture_repo):
    # audit export must stay content-free: a planted distinctive line must never
    # appear in any detail string, near-miss hints included
    planted = "XyZZy_PLANTED_SECRET_LINE = 'do-not-leak'"
    (fixture_repo / "src" / "leak.py").write_text(f"alpha\nbeta\n{planted}\n")
    programs = [
        "string:src/leak.py::XyZZy_PLANTED_SECRET_LINE = 'do not leak'",  # near-miss FAIL
        "string:src/leak.py::absent literal nowhere near",  # plain FAIL
        "regex:src/leak.py::nothing_matches_here",  # regex FAIL
        "symbol:src/leak.py::missing_symbol",  # symbol FAIL
    ]
    for program in programs:
        detail = run_c3(fixture_repo, program).detail
        for token in ("XyZZy", "PLANTED", "do-not-leak", planted):
            assert token not in detail, (program, detail)
    # the near-miss case did produce a hint (line + ratio), just no content
    hint = run_c3(fixture_repo, programs[0]).detail
    m = _NEAR_MISS_DETAIL_RE.fullmatch(hint)
    assert m, hint
    assert int(m.group(1)) == 3
