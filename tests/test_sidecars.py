"""Tests for dorian.sidecars — safe, atomic, deterministic local sidecar writes."""

import json
from pathlib import Path

import pytest

from dorian import sidecars


def test_write_sidecar_roundtrip_and_deterministic(tmp_path):
    p = sidecars.write_sidecar(tmp_path, ".dorian/goals/g-1.goal.json", {"b": 2, "a": 1})
    assert p == (tmp_path / ".dorian/goals/g-1.goal.json").resolve()
    assert p.exists()
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1, "b": 2}
    text = p.read_text(encoding="utf-8")
    assert text.index('"a"') < text.index('"b"')  # sorted keys on disk
    assert text.endswith("\n")


def test_write_sidecar_deterministic_bytes(tmp_path):
    # same payload, different key order -> byte-identical file (deterministic serialization)
    b1 = sidecars.write_sidecar(tmp_path, "x.json", {"a": 1, "b": 2}).read_bytes()
    b2 = sidecars.write_sidecar(tmp_path, "x.json", {"b": 2, "a": 1}).read_bytes()
    assert b1 == b2


def test_creates_parent_directories(tmp_path):
    p = sidecars.write_sidecar(tmp_path, "a/b/c/deep.json", {"x": 1})
    assert p.exists()
    assert p.parent == (tmp_path / "a/b/c").resolve()


def test_returns_final_path(tmp_path):
    p = sidecars.write_sidecar(tmp_path, "x.json", {"k": "v"})
    assert isinstance(p, Path)
    assert p.name == "x.json"


def test_no_leftover_tmp_file(tmp_path):
    sidecars.write_sidecar(tmp_path, "x.json", {"k": "v"})
    assert list(tmp_path.rglob("*.tmp")) == []


def test_refuses_dotdot_traversal(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(ValueError):
        sidecars.write_sidecar(root, "../escape.json", {"x": 1})
    assert not (tmp_path / "escape.json").exists()  # nothing written outside the root


def test_refuses_absolute_path(tmp_path):
    with pytest.raises(ValueError):
        sidecars.write_sidecar(tmp_path, "/etc/whatever.json", {"x": 1})


def test_refuses_empty_and_dot(tmp_path):
    with pytest.raises(ValueError):
        sidecars.write_sidecar(tmp_path, "", {"x": 1})
    with pytest.raises(ValueError):
        sidecars.write_sidecar(tmp_path, ".", {"x": 1})


def test_ensure_within_accepts_inside_rejects_outside(tmp_path):
    root = tmp_path / "repo"
    (root / "sub").mkdir(parents=True)
    assert sidecars.ensure_within(root, Path("sub/f.json")) == (root / "sub/f.json").resolve()
    assert sidecars.ensure_within(root, root / "sub/f.json") == (root / "sub/f.json").resolve()
    with pytest.raises(ValueError):
        sidecars.ensure_within(root, tmp_path / "outside.json")  # absolute outside root
    with pytest.raises(ValueError):
        sidecars.ensure_within(root, Path("../outside.json"))  # traversal


def test_refuses_symlink_escape(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(ValueError):
        sidecars.write_sidecar(root, "link/evil.json", {"x": 1})
    assert not (outside / "evil.json").exists()


def test_overwrites_existing_atomically(tmp_path):
    p1 = sidecars.write_sidecar(tmp_path, "x.json", {"v": 1})
    p2 = sidecars.write_sidecar(tmp_path, "x.json", {"v": 2})
    assert p1 == p2
    assert json.loads(p2.read_text(encoding="utf-8")) == {"v": 2}
    assert list(tmp_path.rglob("*.tmp")) == []
