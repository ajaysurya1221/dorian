"""Generate the README hero: ``docs/assets/hero-{light,dark}.svg``.

Standard library only, deterministic, no network. ``--write`` regenerates both files;
``--check`` regenerates them in memory and exits 1 if a committed file is missing or differs.

The SVGs are plain ``<text>`` and ``<rect>`` elements: no ``<style>`` blocks, no scripts, no
raster images, no external fonts. Text uses system font stacks so GitHub renders it without web
fonts, and every line leaves room for font-metric differences between platforms. ``<title>`` and
``<desc>`` carry the full text of the figure.

The evidence card restates the README "Try it" recipe, and both modes first confirm that the
exact strings below are still present in the committed files (``SOURCES``), so the hero cannot
drift from the runnable demo silently:

- ``README.md`` (the recipe): the claim ``handler-exists`` with the text
  ``handler() lives in app.py.``; ``dorian verify`` annotated ``verified 1/1 claim(s)  (exit 0)``;
  the refactor that rewrites ``app.py`` as ``def renamed()``; ``dorian revalidate --since HEAD``
  annotated ``handler-exists BROKEN; WARRANTED -> REVOKED  (exit 4)``; and the sentence that
  ``note.md`` never changed.
- ``tests/test_readme_example.py`` (the black-box test that runs the recipe out of process):
  verify exits 0 and prints ``verified 1/1 claim(s)``; after the same rename, revalidate exits 4
  and prints ``handler-exists``, ``BROKEN`` and ``REVOKED``.
- ``src/dorian/commands.py``: the ``verified N/M claim(s)`` output line.

The hero contains no benchmark numbers.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent
REPO = ASSETS.parent.parent

SOURCES: tuple[tuple[str, str], ...] = (
    ("README.md", '{"id": "handler-exists", "text": "handler() lives in app.py.",'),
    (
        "README.md",
        "dorian verify note.md --claims claims.json     # -> verified 1/1 claim(s)  (exit 0)",
    ),
    ("README.md", "printf 'def renamed():\\n    return 200\\n' > app.py"),
    (
        "README.md",
        "dorian revalidate --since HEAD                 "
        "# -> handler-exists BROKEN; WARRANTED -> REVOKED  (exit 4)",
    ),
    ("README.md", "`note.md` never changed"),
    (
        "tests/test_readme_example.py",
        'r = _dorian("verify", "note.md", "--claims", "claims.json", repo=repo)\n'
        "    assert r.returncode == 0, r.stderr\n"
        '    assert "verified 1/1 claim(s)" in r.stdout',
    ),
    (
        "tests/test_readme_example.py",
        '(repo / "app.py").write_text("def renamed():\\n    return 200\\n")',
    ),
    (
        "tests/test_readme_example.py",
        '    assert r.returncode == 4, f"{r.returncode}\\n{r.stdout}\\n{r.stderr}"\n'
        '    assert "handler-exists" in r.stdout\n'
        '    assert "BROKEN" in r.stdout\n'
        '    assert "REVOKED" in r.stdout',
    ),
    (
        "src/dorian/commands.py",
        'f"verified {backed}/{len(claims)} claim(s) against current sources"',
    ),
)

SERIF = "Georgia, 'Times New Roman', serif"
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"
SANS = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO_ADVANCE = 0.62  # em; SF Mono is the widest of the stack (Menlo, DejaVu ~0.60)

ARROW = chr(0x2192)
DOT = chr(0x00B7)  # middle dot


@dataclass(frozen=True)
class Theme:
    name: str
    ground: str
    thesis: str
    soft: str
    muted: str
    accent: str
    card: str
    card_text: str
    card_muted: str
    good: str
    bad: str


LIGHT = Theme(
    name="light",
    ground="#F4F1EA",
    thesis="#16211D",
    soft="#3E3D38",
    muted="#6B6A65",
    accent="#8C2F2F",
    card="#16211D",
    card_text="#E9E4D8",
    card_muted="#A8A397",
    good="#7FD1A8",
    bad="#E06A6A",
)

DARK = Theme(
    name="dark",
    ground="#0F1512",
    thesis="#F0ECE2",
    soft="#CFCBC1",
    muted="#9A978E",
    accent="#E06A6A",
    card="#F4F1EA",
    card_text="#16211D",
    card_muted="#6B6A65",
    good="#1F7A4D",
    bad="#8C2F2F",
)


@dataclass(frozen=True)
class Span:
    text: str
    fill: str | None = None
    weight: int | None = None
    x: int | None = None


class Canvas:
    def __init__(self, width: int, height: int, title: str, desc: str) -> None:
        self.width = width
        self.height = height
        self.title = title
        self.desc = desc
        self.body: list[str] = []

    def rect(self, x: int, y: int, w: int, h: int, fill: str, rx: int = 0) -> None:
        radius = f' rx="{rx}"' if rx else ""
        self.body.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"{radius} fill="{fill}"/>')

    def text(
        self,
        x: int,
        y: int,
        spans: Sequence[Span] | str,
        *,
        size: int,
        family: str,
        fill: str,
        weight: int = 400,
        spacing: str | None = None,
    ) -> None:
        items = [Span(spans)] if isinstance(spans, str) else list(spans)
        attrs = [
            f'x="{x}"',
            f'y="{y}"',
            f'font-family="{family}"',
            f'font-size="{size}"',
            f'fill="{fill}"',
        ]
        if weight != 400:
            attrs.append(f'font-weight="{weight}"')
        if spacing is not None:
            attrs.append(f'letter-spacing="{spacing}"')
        inner: list[str] = []
        for span in items:
            span_attrs: list[str] = []
            if span.x is not None:
                span_attrs.append(f'x="{span.x}"')
            if span.fill is not None:
                span_attrs.append(f'fill="{span.fill}"')
            if span.weight is not None:
                span_attrs.append(f'font-weight="{span.weight}"')
            content = escape(span.text, quote=False)
            if span_attrs:
                inner.append(f"<tspan {' '.join(span_attrs)}>{content}</tspan>")
            else:
                inner.append(content)
        self.body.append(f"<text {' '.join(attrs)}>{''.join(inner)}</text>")

    def render(self) -> str:
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}"'
            f' height="{self.height}" viewBox="0 0 {self.width} {self.height}"'
            ' role="img" aria-labelledby="title desc">'
        )
        lines = [
            head,
            f'<title id="title">{escape(self.title, quote=False)}</title>',
            f'<desc id="desc">{escape(self.desc, quote=False)}</desc>',
            *self.body,
            "</svg>",
        ]
        return "\n".join(lines) + "\n"


def baseline(top: int, line_height: int, size: int) -> int:
    """Baseline of a single text line centred in a line box (cap height about 0.7 em)."""
    return round(top + line_height / 2 + size * 0.35)


def mono_width(text: str, size: int, spacing: float = 0.0) -> int:
    return round(len(text) * (size * MONO_ADVANCE + spacing))


# ---------------------------------------------------------------------------------------------
# Hero, 1600 x 520
# ---------------------------------------------------------------------------------------------

HERO_W, HERO_H = 1600, 520
EYEBROW = ("dorian", DOT, "claim warrants for code changes")
THESIS = ("Does the code still", "satisfy what the agent", "claimed it did?")
SUBLINE = (
    "Claims become executable checks sealed beside",
    "the code and re-run on every commit.",
    "No model is called at check time.",
)
CARD_CLAIM = f'CLAIM {DOT} "handler() lives in app.py"'
CARD_VERIFY = (f"dorian verify {ARROW} verified 1/1 claim(s)", f"{ARROW} ", "WARRANTED (exit 0)")
CARD_EDIT = ("a refactor renames handler();", "the note never changes")
CARD_REVALIDATE = (
    f"dorian revalidate {ARROW} handler-exists BROKEN",
    f"{ARROW} ",
    "REVOKED (exit 4)",
)
CARD_FOOT = f'README "Try it" {DOT} a black-box test pins this recipe'

# Layout (the 1600 x 520 artboard): 56/72 padding, a 660-wide card, a 56 gap.
PAD_Y, PAD_X, GAP, CARD_W = 56, 72, 56, 660
CARD_X = HERO_W - PAD_X - CARD_W
COL_W = CARD_X - GAP - PAD_X
CARD_H = HERO_H - 2 * PAD_Y
CARD_PAD = 34
CARD_INNER = CARD_W - 2 * CARD_PAD

EYEBROW_SIZE, EYEBROW_LH, EYEBROW_SPACING = 22, 30, 0.44
THESIS_SIZE, THESIS_LH = 60, 66
SUB_SIZE, SUB_LH = 27, 38
BLOCK_GAP = 22
LABEL_SIZE, LABEL_LH, LABEL_SPACING = 17, 24, 1.36
CMD_SIZE, CMD_LH = 22, 34
EDIT_SIZE, EDIT_LH = 19, 28
FOOT_SIZE, FOOT_LH = 16, 22
ROW_GAP = 18


def _card_lines_fit() -> None:
    """Guard: every card line fits the card at the widest monospace advance in the stack."""
    lines = [
        (CARD_CLAIM, LABEL_SIZE, LABEL_SPACING),
        (CARD_VERIFY[0], CMD_SIZE, 0.0),
        ("  " + CARD_VERIFY[1] + CARD_VERIFY[2], CMD_SIZE, 0.0),
        (CARD_EDIT[0], EDIT_SIZE, 0.0),
        (CARD_EDIT[1], EDIT_SIZE, 0.0),
        (CARD_REVALIDATE[0], CMD_SIZE, 0.0),
        ("  " + CARD_REVALIDATE[1] + CARD_REVALIDATE[2], CMD_SIZE, 0.0),
        (CARD_FOOT, FOOT_SIZE, 0.0),
    ]
    for text, size, spacing in lines:
        width = mono_width(text, size, spacing)
        if width > CARD_INNER:
            raise ValueError(f"card line too wide ({width} > {CARD_INNER}): {text!r}")


def hero(theme: Theme) -> str:
    _card_lines_fit()
    desc = " ".join(
        [
            f"{EYEBROW[0]}: {EYEBROW[2]}.",
            " ".join(THESIS),
            " ".join(SUBLINE),
            "Evidence card, from the README Try it recipe:",
            "claim handler-exists, 'handler() lives in app.py'.",
            f"dorian verify: verified 1/1 claim(s), {CARD_VERIFY[2]}.",
            "A refactor renames handler(); the note never changes.",
            f"dorian revalidate: handler-exists BROKEN, {CARD_REVALIDATE[2]}.",
            "A black-box test pins this recipe.",
        ]
    )
    canvas = Canvas(HERO_W, HERO_H, " ".join(THESIS), desc)
    canvas.rect(0, 0, HERO_W, HERO_H, theme.ground)

    # Left column: eyebrow, thesis (3 lines), subline (3 lines), vertically centred.
    total = EYEBROW_LH + BLOCK_GAP + 3 * THESIS_LH + BLOCK_GAP + 3 * SUB_LH
    top = PAD_Y + (CARD_H - total) // 2
    # explicit x per span: whitespace inside SVG text collapses differently across renderers
    char_w = mono_width(" ", EYEBROW_SIZE, EYEBROW_SPACING)
    dot_x = PAD_X + mono_width(EYEBROW[0], EYEBROW_SIZE, EYEBROW_SPACING) + char_w
    canvas.text(
        PAD_X,
        baseline(top, EYEBROW_LH, EYEBROW_SIZE),
        [
            Span(EYEBROW[0], fill=theme.accent, weight=600),
            Span(EYEBROW[1], x=dot_x),
            Span(EYEBROW[2], x=dot_x + 2 * char_w),
        ],
        size=EYEBROW_SIZE,
        family=MONO,
        fill=theme.muted,
        spacing=str(EYEBROW_SPACING),
    )
    top += EYEBROW_LH + BLOCK_GAP
    for index, line in enumerate(THESIS):
        canvas.text(
            PAD_X,
            baseline(top + index * THESIS_LH, THESIS_LH, THESIS_SIZE),
            line,
            size=THESIS_SIZE,
            family=SERIF,
            fill=theme.thesis,
            weight=600,
        )
    top += 3 * THESIS_LH + BLOCK_GAP
    for index, line in enumerate(SUBLINE):
        canvas.text(
            PAD_X,
            baseline(top + index * SUB_LH, SUB_LH, SUB_SIZE),
            line,
            size=SUB_SIZE,
            family=SANS,
            fill=theme.soft,
        )

    # Evidence card: one recorded run of the README recipe, verdicts and exit codes verbatim.
    canvas.rect(CARD_X, PAD_Y, CARD_W, CARD_H, theme.card, rx=16)
    inner_x = CARD_X + CARD_PAD
    indent_x = inner_x + mono_width("  ", CMD_SIZE)
    rows = [
        (0, LABEL_LH, LABEL_SIZE),
        (ROW_GAP, CMD_LH, CMD_SIZE),
        (0, CMD_LH, CMD_SIZE),
        (ROW_GAP, EDIT_LH, EDIT_SIZE),
        (0, EDIT_LH, EDIT_SIZE),
        (ROW_GAP, CMD_LH, CMD_SIZE),
        (0, CMD_LH, CMD_SIZE),
        (ROW_GAP, FOOT_LH, FOOT_SIZE),
    ]
    content_h = sum(gap_before + lh for gap_before, lh, _ in rows)
    y = PAD_Y + (CARD_H - content_h) // 2
    baselines: list[int] = []
    for gap_before, lh, size in rows:
        y += gap_before
        baselines.append(baseline(y, lh, size))
        y += lh

    canvas.text(
        inner_x,
        baselines[0],
        CARD_CLAIM,
        size=LABEL_SIZE,
        family=MONO,
        fill=theme.card_muted,
        spacing=str(LABEL_SPACING),
    )

    def command(first: int, line: tuple[str, str, str], color: str) -> None:
        head, arrow, verdict = line
        canvas.text(
            inner_x, baselines[first], head, size=CMD_SIZE, family=MONO, fill=theme.card_text
        )
        canvas.text(
            indent_x,
            baselines[first + 1],
            [Span(arrow), Span(verdict, fill=color, weight=600)],
            size=CMD_SIZE,
            family=MONO,
            fill=theme.card_text,
        )

    command(1, CARD_VERIFY, theme.good)
    for offset, line in enumerate(CARD_EDIT):
        canvas.text(
            inner_x,
            baselines[3 + offset],
            line,
            size=EDIT_SIZE,
            family=MONO,
            fill=theme.card_muted,
        )
    command(5, CARD_REVALIDATE, theme.bad)
    canvas.text(
        inner_x,
        baselines[7],
        CARD_FOOT,
        size=FOOT_SIZE,
        family=MONO,
        fill=theme.card_muted,
    )
    return canvas.render()


# ---------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------


def figures() -> dict[str, str]:
    return {
        "hero-light.svg": hero(LIGHT),
        "hero-dark.svg": hero(DARK),
    }


def check_sources() -> list[str]:
    problems: list[str] = []
    for relative, needle in SOURCES:
        path = REPO / relative
        if not path.is_file():
            problems.append(f"missing source file {relative}")
        elif needle not in path.read_text("utf-8"):
            problems.append(f"{relative} no longer contains {needle!r}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the README hero.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate docs/assets/hero-*.svg")
    mode.add_argument("--check", action="store_true", help="fail if a committed SVG is stale")
    args = parser.parse_args(argv)

    problems = check_sources()
    if problems:
        for problem in problems:
            print(f"source check failed: {problem}", file=sys.stderr)
        return 1

    stale: list[str] = []
    for name, content in figures().items():
        path = ASSETS / name
        data = content.encode("utf-8")
        if args.write:
            path.write_bytes(data)
            print(f"wrote {path.relative_to(REPO)}")
        elif not path.is_file() or path.read_bytes() != data:
            stale.append(str(path.relative_to(REPO)))
    if stale:
        for name in stale:
            print(f"stale or missing: {name}", file=sys.stderr)
        print("run: python docs/assets/src/make_figures.py --write", file=sys.stderr)
        return 1
    if args.check:
        print("figures are current: " + ", ".join(sorted(figures())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
