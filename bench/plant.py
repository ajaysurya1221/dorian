"""Planted-truth document generator for the extraction gate (docs/EXTRACT_GATE.md).

Generates markdown documents FROM a known claim inventory, so ground truth for
"which lines are checkable claims" exists by construction. Deterministic: the
same (seed, target_lines) always yields byte-identical doc + manifest.

Separation rule (mechanically testable): every planted claim line contains a
digit or a path token; every distractor line contains neither. Selecting a
distractor is therefore an unambiguous false positive.

Usage:
    python -m bench.plant --tiers 40,120,240 --per-tier 5 --seed-base 1 --out DIR

Writes DIR/t<tier>-s<seed>/doc.md and manifest.json ({seed, tier, doc_sha256,
total_lines, claims: [{line, kind, text}]}).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

PARAMS = ["request", "connection", "upload", "retry", "session", "queue"]
DIMS = ["timeout", "limit", "budget", "window", "depth"]
UNITS = ["seconds", "attempts", "megabytes", "items", "entries"]
SERVICES = ["login", "billing", "search", "export", "status", "ingest"]
NAMES = ["gateway", "worker", "scheduler", "replica", "courier"]
CODES = [408, 413, 429, 503]

# (kind, template) — every rendering carries a digit or a path token
CLAIM_TEMPLATES = [
    ("quantity", "The default {param} {dim} is {n} {unit}."),
    ("quantity", "Batch processing handles {n} records per cycle."),
    ("quantity", "The report schema is version {a}.{b}."),
    ("reference", "The {svc} endpoint is served at /v{v}/{svc}."),
    ("reference", "Runtime settings load from config/{name}.toml."),
    ("behavior", "Requests over the {param} limit return HTTP {code} without retry."),
    ("behavior", "Failed {svc} jobs move to the dead-letter queue after {n} attempts."),
    ("decision", "We pinned the {name} library to major version {n2}."),
    ("fact", "The {svc} cache holds {n} entries at steady state."),
]

# distractors: no digits, no path tokens, deliberately unverifiable
DISTRACTORS = [
    "This section gives a broad overview of the design.",
    "We believe this approach balances simplicity and flexibility.",
    "The team found the migration smoother than expected.",
    "Future iterations may refine these ideas further.",
    "Readers familiar with the architecture can skim ahead.",
    "Feedback from early adopters has been encouraging.",
    "The naming here follows the conventions used elsewhere.",
    "Most of the complexity lives at the edges, not the core.",
    "This part of the system rarely surprises anyone.",
    "A fuller discussion appears later in the appendix.",
]

HEADINGS = [
    "Overview",
    "Request handling",
    "Background processing",
    "Configuration",
    "Reporting",
    "Operational notes",
    "Caching",
    "Error handling",
    "Rollout",
    "Open questions",
]

TABLE_BLOCK = [
    "| area | impression |",
    "| --- | --- |",
    "| onboarding | pleasantly smooth |",
    "| ergonomics | feels natural |",
]

CODE_BLOCK = [
    "```text",
    "# example elided for brevity",
    "```",
]

CLAIM_DENSITY = 0.35  # claim share of section content items


def _render_claim(rng: random.Random, used: set[str]) -> tuple[str, str]:
    """One unique single-line claim; deterministic retry on text collision."""
    for _ in range(50):
        kind, template = rng.choice(CLAIM_TEMPLATES)
        text = template.format(
            param=rng.choice(PARAMS),
            dim=rng.choice(DIMS),
            n=rng.randint(5, 900),
            n2=rng.randint(2, 9),
            unit=rng.choice(UNITS),
            svc=rng.choice(SERVICES),
            name=rng.choice(NAMES),
            v=rng.randint(1, 4),
            code=rng.choice(CODES),
            a=rng.randint(1, 4),
            b=rng.randint(0, 9),
        )
        if text not in used:
            used.add(text)
            return kind, text
    raise RuntimeError("could not render a unique claim in 50 tries")


def generate(seed: int, target_lines: int) -> tuple[str, dict]:
    """Build (doc_text, manifest) deterministically from (seed, target_lines)."""
    rng = random.Random(f"{seed}:{target_lines}")
    rows: list[tuple[str, str | None]] = []  # (line, claim kind | None)
    used: set[str] = set()

    def put(line: str, kind: str | None = None) -> None:
        rows.append((line, kind))

    put(f"# {rng.choice(NAMES).title()} service notes")
    put("")
    put(rng.choice(DISTRACTORS))
    put("")

    headings = list(HEADINGS)
    table_done = code_done = False
    while len(rows) < target_lines - 2:
        heading = headings.pop(0) if headings else rng.choice(HEADINGS)
        put(f"## {heading}")
        put("")
        for _ in range(rng.randint(5, 8)):
            if len(rows) >= target_lines - 2:
                break
            roll = rng.random()
            if roll < CLAIM_DENSITY:
                kind, text = _render_claim(rng, used)
                put(text, kind)
            elif roll < CLAIM_DENSITY + 0.08 and not table_done:
                for line in TABLE_BLOCK:
                    put(line)
                table_done = True
            elif roll < CLAIM_DENSITY + 0.16 and not code_done:
                for line in CODE_BLOCK:
                    put(line)
                code_done = True
            else:
                put(rng.choice(DISTRACTORS))
            put("")

    text = "\n".join(line for line, _ in rows) + "\n"
    claims = [
        {"line": i + 1, "kind": kind, "text": line}
        for i, (line, kind) in enumerate(rows)
        if kind is not None
    ]
    manifest = {
        "seed": seed,
        "tier": target_lines,
        "doc_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "total_lines": len(text.split("\n")),
        "claims": claims,
    }
    return text, manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bench.plant", description=__doc__)
    ap.add_argument("--tiers", default="40,120,240", help="comma list of target line counts")
    ap.add_argument("--per-tier", type=int, default=5)
    ap.add_argument("--seed-base", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    out = Path(args.out)
    count = 0
    for tier in (int(t) for t in args.tiers.split(",")):
        for s in range(args.per_tier):
            seed = args.seed_base + s
            text, manifest = generate(seed, tier)
            doc_dir = out / f"t{tier}-s{seed}"
            doc_dir.mkdir(parents=True, exist_ok=True)
            (doc_dir / "doc.md").write_text(text, encoding="utf-8")
            (doc_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            count += 1
    print(f"plant: wrote {count} documents under {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
