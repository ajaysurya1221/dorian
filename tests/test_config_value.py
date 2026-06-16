"""`config-value:` C3 structural checker — type-aware TOML/JSON value assertion.

Turns config-key binding from trigger-only into trigger+truth. Grammar:
    config-value:<path>:<dotted.key.path>:<json-literal>
Stdlib only (`tomllib`/`json`), no execution, no YAML, no coercion. ERROR (file/parse/
grammar) is kept distinct from FAIL/BROKEN (key absent or value/type mismatch).
"""

from __future__ import annotations

from pathlib import Path

from dorian.checkers import c3_ref
from dorian.checkers.base import CheckContext, Verdict
from dorian.model import CheckerSpec, Claim


def _w(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")


def _check(repo: Path, program: str) -> tuple[Verdict, str]:
    spec = CheckerSpec(type="C3", program=program)
    claim = Claim(id="c", text="x", kind="fact", load_bearing=True, checkers=(spec,))
    res = c3_ref.check(CheckContext(repo=repo, claim=claim), spec)
    return res.verdict, res.detail


PYPROJECT = (
    '[project]\nrequires-python = ">=3.11"\n\n'
    "[tool.ruff]\nline-length = 100\nfix = true\n\n"
    "[tool.x]\nitems = [1, 2, 3]\n\n[tool.obj]\na = 1\nb = 2\n"
)
SETTINGS = (
    '{"scripts": {"test": "pytest"}, "feature": {"enabled": true}, '
    '"limits": {"max_items": 30}, "ratio": 0.5, "as_str": "30", "as_int": 30, '
    '"flag": 1, "nested": {"object": {"a": 1, "b": [true, "x"]}}, '
    '"cmd": "echo HACKED > pwned.txt"}'
)


# --- PASS cases (1-10) ---


def test_toml_string_pass(tmp_path: Path) -> None:
    _w(tmp_path, "pyproject.toml", PYPROJECT)
    assert (
        _check(tmp_path, 'config-value:pyproject.toml:project.requires-python:">=3.11"')[0]
        is Verdict.PASS
    )


def test_toml_integer_pass(tmp_path: Path) -> None:
    _w(tmp_path, "pyproject.toml", PYPROJECT)
    assert (
        _check(tmp_path, "config-value:pyproject.toml:tool.ruff.line-length:100")[0] is Verdict.PASS
    )


def test_toml_bool_pass(tmp_path: Path) -> None:
    _w(tmp_path, "pyproject.toml", PYPROJECT)
    assert _check(tmp_path, "config-value:pyproject.toml:tool.ruff.fix:true")[0] is Verdict.PASS


def test_toml_nested_dotted_path_pass(tmp_path: Path) -> None:
    _w(tmp_path, "pyproject.toml", PYPROJECT)
    # tool.obj.a is two tables deep
    assert _check(tmp_path, "config-value:pyproject.toml:tool.obj.a:1")[0] is Verdict.PASS


def test_toml_array_and_object_pass(tmp_path: Path) -> None:
    _w(tmp_path, "pyproject.toml", PYPROJECT)
    assert _check(tmp_path, "config-value:pyproject.toml:tool.x.items:[1, 2, 3]")[0] is Verdict.PASS
    # object equality is structural (key order does not matter)
    assert (
        _check(tmp_path, 'config-value:pyproject.toml:tool.obj:{"b": 2, "a": 1}')[0] is Verdict.PASS
    )


def test_json_string_pass(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert _check(tmp_path, 'config-value:settings.json:scripts.test:"pytest"')[0] is Verdict.PASS


def test_json_integer_pass(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert _check(tmp_path, "config-value:settings.json:limits.max_items:30")[0] is Verdict.PASS


def test_json_bool_pass(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert _check(tmp_path, "config-value:settings.json:feature.enabled:true")[0] is Verdict.PASS


def test_json_nested_path_pass(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert _check(tmp_path, "config-value:settings.json:nested.object.a:1")[0] is Verdict.PASS


def test_json_array_object_pass(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert (
        _check(tmp_path, 'config-value:settings.json:nested.object:{"a": 1, "b": [true, "x"]}')[0]
        is Verdict.PASS
    )


# --- type-aware mismatch -> FAIL (11-13) ---


def test_type_mismatch_int_vs_float_fails(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    v, d = _check(tmp_path, "config-value:settings.json:limits.max_items:30.0")
    assert v is Verdict.FAIL and "mismatch" in d


def test_type_mismatch_int_vs_bool_fails(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert _check(tmp_path, "config-value:settings.json:flag:true")[0] is Verdict.FAIL  # 1 != true


def test_type_mismatch_str_vs_int_fails(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert _check(tmp_path, "config-value:settings.json:as_str:30")[0] is Verdict.FAIL  # "30" != 30


# --- key/value mismatch -> FAIL/BROKEN (14-15) ---


def test_missing_key_fails(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    v, d = _check(tmp_path, "config-value:settings.json:limits.nope:1")
    assert v is Verdict.FAIL and "missing" in d


def test_changed_value_fails(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert _check(tmp_path, "config-value:settings.json:limits.max_items:31")[0] is Verdict.FAIL


# --- file/parse/grammar -> ERROR, never BROKEN (16-21) ---


def test_missing_file_errors(tmp_path: Path) -> None:
    assert _check(tmp_path, "config-value:nope.json:a:1")[0] is Verdict.ERROR


def test_invalid_toml_errors(tmp_path: Path) -> None:
    _w(tmp_path, "bad.toml", "x = = =\n")
    v, d = _check(tmp_path, "config-value:bad.toml:x:1")
    assert v is Verdict.ERROR and "config_unparseable" in d


def test_invalid_json_errors(tmp_path: Path) -> None:
    _w(tmp_path, "bad.json", "{not valid json")
    v, d = _check(tmp_path, "config-value:bad.json:x:1")
    assert v is Verdict.ERROR and "config_unparseable" in d


def test_unsupported_extension_errors(tmp_path: Path) -> None:
    _w(tmp_path, "conf.yaml", "x: 1\n")
    v, d = _check(tmp_path, "config-value:conf.yaml:x:1")
    assert v is Verdict.ERROR and "unsupported" in d


def test_invalid_expected_json_literal_errors(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert _check(tmp_path, "config-value:settings.json:as_int:notjson")[0] is Verdict.ERROR


def test_empty_key_segment_errors(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert _check(tmp_path, "config-value:settings.json::1")[0] is Verdict.ERROR  # empty key path
    assert (
        _check(tmp_path, "config-value:settings.json:a..b:1")[0] is Verdict.ERROR
    )  # empty segment


def test_too_few_segments_errors(tmp_path: Path) -> None:
    _w(tmp_path, "settings.json", SETTINGS)
    assert _check(tmp_path, "config-value:settings.json:as_int")[0] is Verdict.ERROR  # no literal


def test_ambiguous_literal_dot_key_errors(tmp_path: Path) -> None:
    _w(tmp_path, "conf.json", '{"a.b": 5}')
    v, d = _check(tmp_path, "config-value:conf.json:a.b:5")
    assert v is Verdict.ERROR and "ambiguous" in d


def test_ambiguous_when_both_nested_and_literal_dot_key_exist_errors(tmp_path: Path) -> None:
    # `a.b` could mean nested a->b (=1) OR the literal key "a.b" (=999): cannot disambiguate
    _w(tmp_path, "both.json", '{"a": {"b": 1}, "a.b": 999}')
    v, d = _check(tmp_path, "config-value:both.json:a.b:1")
    assert v is Verdict.ERROR and "ambiguous" in d  # never silently pick the nested value


def test_nan_infinity_expected_literal_errors(tmp_path: Path) -> None:
    # NaN/Infinity/-Infinity are not RFC-8259 JSON -> ERROR (not a usable comparison)
    _w(tmp_path, "settings.json", SETTINGS)
    for tok in ("Infinity", "-Infinity", "NaN"):
        assert _check(tmp_path, f"config-value:settings.json:as_int:{tok}")[0] is Verdict.ERROR


def test_path_escape_errors(tmp_path: Path) -> None:
    assert _check(tmp_path, "config-value:../../etc/hosts:a:1")[0] is Verdict.ERROR


# --- no code execution (22) ---


def test_no_code_execution(tmp_path: Path) -> None:
    """A config value that looks like a shell command is compared as a string, never run."""
    _w(tmp_path, "settings.json", SETTINGS)
    v, _ = _check(tmp_path, 'config-value:settings.json:cmd:"echo HACKED > pwned.txt"')
    assert v is Verdict.PASS
    assert not (tmp_path / "pwned.txt").exists()  # the command was NOT executed


# --- documented limitation: TOML date is not a JSON literal -> FAIL (not crash) ---


def test_toml_date_value_fails_not_errors(tmp_path: Path) -> None:
    _w(tmp_path, "d.toml", "released = 2020-01-01\n")
    # a TOML date has no JSON literal; it can never equal a string/number -> FAIL (documented)
    assert _check(tmp_path, 'config-value:d.toml:released:"2020-01-01"')[0] is Verdict.FAIL


# --- strength + binding integration (23-25) ---


def test_config_value_strength_is_structural() -> None:
    from dorian import strength

    spec = CheckerSpec(type="C3", program="config-value:pyproject.toml:tool.ruff.line-length:100")
    s = strength.checker_strength(spec)
    assert s == "structural"
    # stronger than the trigger-only / weak forms (config-key binding is just a trigger)
    assert strength._RANK[s] > strength._RANK["existence"]
    assert strength._RANK[s] > strength._RANK["raw_text"]


def test_config_value_binds_its_file_for_recheck() -> None:
    from dorian.model import ProducedBy, ReadSet
    from dorian.seal import _derive_watch, referenced_paths

    spec = CheckerSpec(type="C3", program="config-value:pyproject.toml:tool.ruff.line-length:100")
    rs = ReadSet(
        produced_by=ProducedBy(runner="manual", captured_at="2026-01-01T00:00:00Z"), entries=[]
    )
    # the watched file is the config path -> a change to pyproject.toml re-checks the claim
    assert _derive_watch(spec, rs).watch == ("pyproject.toml",)
    claim = Claim(id="c", text="x", kind="fact", load_bearing=True, checkers=(spec,))
    assert "pyproject.toml" in referenced_paths([claim])


def test_spec_documents_config_value() -> None:
    spec_md = (Path(__file__).resolve().parents[1] / "spec" / "checkers.md").read_text()
    assert "config-value:" in spec_md
