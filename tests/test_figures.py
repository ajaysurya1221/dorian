"""The README hero is generated, not drawn.

`docs/assets/src/make_figures.py --check` regenerates `docs/assets/hero-{light,dark}.svg` in
memory and fails if a committed file differs, or if the README recipe and its black-box test no
longer contain the strings the hero's evidence card restates. These tests run that check and pin
the README to the generated files.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "docs" / "assets" / "src" / "make_figures.py"
HEROES = ("hero-light.svg", "hero-dark.svg")


def test_committed_hero_matches_its_generator_and_sources() -> None:
    r = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "figures are current" in r.stdout


def test_hero_svgs_are_self_contained_text() -> None:
    for name in HEROES:
        svg = (REPO_ROOT / "docs" / "assets" / name).read_text(encoding="utf-8")
        assert "<title" in svg and "<desc" in svg, name
        assert "<text" in svg, name
        for banned in ("<script", "<image", "<style", "href=", "url(", "@import"):
            assert banned not in svg, f"{name} contains {banned!r}"


def test_readme_shows_the_generated_hero() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert 'srcset="docs/assets/hero-dark.svg"' in readme
    assert 'src="docs/assets/hero-light.svg"' in readme
    assert "dorian-hero" not in readme  # the retired raster portrait
