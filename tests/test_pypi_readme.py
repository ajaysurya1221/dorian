"""The PyPI long description resolves its links and images.

PyPI renders README.md without the repository around it, so a relative link or image source is a
404 there. `pyproject.toml` builds the long description with hatch-fancy-pypi-readme: the README
fragment plus regex substitutions that rewrite every repository-relative target to a GitHub URL
pinned to `v$HFPR_VERSION`. These tests apply the configured substitutions the way the plugin does
(each `re.sub` in order, then `$HFPR_VERSION` is replaced by the package version) and check the
result, so a README edit that adds a link form the substitutions miss fails here, offline, before
a release. The release itself is checked by building the distributions and reading their metadata.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
VERSION = PYPROJECT["project"]["version"]
HOOK = PYPROJECT["tool"]["hatch"]["metadata"]["hooks"]["fancy-pypi-readme"]

FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
SCHEME_OR_ANCHOR = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:|//|#")
RAW = f"https://raw.githubusercontent.com/ajaysurya1221/dorian/v{VERSION}/"
PAGES = (
    f"https://github.com/ajaysurya1221/dorian/blob/v{VERSION}/",
    f"https://github.com/ajaysurya1221/dorian/tree/v{VERSION}/",
)


def _render(text: str) -> str:
    for sub in HOOK["substitutions"]:
        text = re.compile(sub["pattern"]).sub(sub["replacement"], text)
    return text.replace("$HFPR_VERSION", VERSION)


DESCRIPTION = _render(README)


def test_readme_is_dynamic_and_built_from_the_readme_fragment() -> None:
    assert "readme" in PYPROJECT["project"]["dynamic"]
    assert "readme" not in PYPROJECT["project"]
    assert any(
        req.startswith("hatch-fancy-pypi-readme") for req in PYPROJECT["build-system"]["requires"]
    )
    assert HOOK["content-type"] == "text/markdown"
    assert HOOK["fragments"] == [{"path": "README.md"}]


def test_no_repository_relative_target_is_left() -> None:
    prose = FENCE.sub("", DESCRIPTION)
    targets = re.findall(r"\]\(([^)\s]+)\)", prose)
    targets += re.findall(r'\b(?:src|srcset|href)="([^"]+)"', prose)
    relative = [t for t in targets if not SCHEME_OR_ANCHOR.match(t)]
    assert not relative, f"relative targets left in the PyPI description: {relative}"
    for leftover in ("](docs/", "](action/", 'src="docs/', "<picture", "<source"):
        assert leftover not in DESCRIPTION, leftover


def test_hero_is_one_img_with_a_version_pinned_raw_source() -> None:
    imgs = re.findall(r"<img [^>]*>", DESCRIPTION)
    assert len(imgs) == 1, imgs
    assert f'src="{RAW}docs/assets/hero-light.svg"' in imgs[0]


def test_rewritten_targets_are_pinned_to_this_version() -> None:
    pins = re.findall(
        r"https://(?:github\.com/ajaysurya1221/dorian/(?:blob|tree)|"
        r"raw\.githubusercontent\.com/ajaysurya1221/dorian)/([^/]+)/",
        DESCRIPTION,
    )
    assert pins
    assert set(pins) == {f"v{VERSION}"}


def test_only_relative_targets_change() -> None:
    """Undo the URL prefixes and the <picture> unwrap: what is left is the README, unchanged.

    So absolute URLs, pure anchors, anchors on rewritten links and fenced code blocks all survive.
    """
    undone = DESCRIPTION
    for prefix in (RAW, *PAGES):
        undone = undone.replace(prefix, "")
    picture = re.search(r"<picture>\s*<source [^>]*>\s*(<img [^>]*>)\s*</picture>", README)
    assert picture, "README.md hero <picture> not found"
    assert undone == README.replace(picture.group(0), picture.group(1))
    assert FENCE.findall(DESCRIPTION) == FENCE.findall(README)


def test_fenced_code_is_never_rewritten() -> None:
    sample = (
        "[doc](docs/A.md)\n"
        "```bash\n"
        'echo "[in](docs/code.md)" \'<img src="docs/code.png">\'\n'
        "```\n"
        "[after](CHANGELOG.md#top) [anchor](#try-it) [web](https://example.com/x)\n"
    )
    out = _render(sample)
    assert "[in](docs/code.md)" in out and '<img src="docs/code.png">' in out
    assert f"[doc]({PAGES[0]}docs/A.md)" in out
    assert f"[after]({PAGES[0]}CHANGELOG.md#top)" in out
    assert "[anchor](#try-it)" in out and "[web](https://example.com/x)" in out
