"""Fixture battery for the binding-lifecycle benchmark.

Each domain is a self-contained, invented, public-safe fixture. Labels are
mechanical and frozen here, BEFORE any measurement:

  breaks_fact    : claims whose CHECKER-verifiable fact the edit falsifies.
  breaks_trigger : claims whose TRUE DEPENDENCY the edit touches (superset).

The generator `_binding_domain` builds the canonical binding shape: ONE symbol
defined in a library file, referenced by a consumer file, with two artifacts —
a TRUTH artifact whose checker reads the definer (`symbol:lib::S`) and a
TRIGGER artifact whose checker reads the consumer (`string:routes::/path`) while
its claim only MENTIONS the symbol. A definer change is then trigger-stale for
both but fact-stale only for the truth artifact — exactly the gap that separates
the false-TRUSTED trigger reduction (the binding fix's value) from a real BROKEN
verdict. Hand-authored domains cover the strata the generator cannot: ambiguous
symbols, pyproject scripts (good + ambiguous), C4 nodeid whitespace, the
gutted-body ceiling (existence vs behavior checker), invalid Python, backtick
precision, and prose-only / neutral controls.
"""

from __future__ import annotations

from pathlib import Path

from bench.binding_lifecycle import Artifact, BClaim, Domain, Mutation, _git
from dorian.model import CheckerSpec, Claim

# --- claim / checker builders ---------------------------------------------------


def _claim(
    cid: str, text: str, *checkers: CheckerSpec, kind: str = "fact", lb: bool = True
) -> Claim:
    return Claim(id=cid, text=text, kind=kind, load_bearing=lb, checkers=tuple(checkers))


def _sym(file: str, name: str) -> CheckerSpec:
    return CheckerSpec(type="C3", program=f"symbol:{file}::{name}")


def _string(file: str, literal: str) -> CheckerSpec:
    return CheckerSpec(type="C3", program=f"string:{file}::{literal}")


def _pytest(nodeid: str) -> CheckerSpec:
    return CheckerSpec(type="C4", program=f"pytest:{nodeid}")


# --- mutation apply builders (closures; bind values as defaults) ----------------


def _replace(rel: str, old: str, new: str):
    def apply(repo: Path, rel=rel, old=old, new=new) -> None:
        p = repo / rel
        body = p.read_text(encoding="utf-8")
        if old not in body:
            raise RuntimeError(f"mutation target {old!r} not found in {rel}")
        p.write_text(body.replace(old, new), encoding="utf-8")

    return apply


def _append(rel: str, text: str):
    def apply(repo: Path, rel=rel, text=text) -> None:
        p = repo / rel
        p.write_text(p.read_text(encoding="utf-8") + text, encoding="utf-8")

    return apply


def _set(rel: str, content: str):
    def apply(repo: Path, rel=rel, content=content) -> None:
        (repo / rel).write_text(content, encoding="utf-8")

    return apply


def _mv(old: str, new: str):
    def apply(repo: Path, old=old, new=new) -> None:
        _git(repo, "mv", old, new)

    return apply


# --- the canonical binding-domain generator -------------------------------------

_BT = {"func": "snake_function", "async": "async_function", "class": "camel_class"}


def _def_source(sym: str, kind: str) -> str:
    if kind == "class":
        return f'class {sym}:\n    """A {sym} component."""\n\n    def run(self, value):\n        return bool(value)\n'  # noqa: E501
    head = "async def" if kind == "async" else "def"
    return f'{head} {sym}(value):\n    """Validate a value."""\n    return bool(value)\n'


def _binding_domain(name: str, sym: str, kind: str, *, quick: bool = False) -> Domain:
    lib = f"lib/{name}_lib.py"
    con = f"app/{name}_routes.py"
    oth = f"lib/{name}_other.py"
    route = f"/{name}"
    truth_id, trig_id = f"{name}-truth", f"{name}-trigger"

    files = {
        lib: _def_source(sym, kind),
        con: f'ROUTES = {{\n    "{route}": "{sym}",  # gated by {sym}\n}}\n',
        oth: "UNRELATED = 1\n",
    }
    truth = Artifact(
        uri=f"docs/{name}_truth.md",
        claims=(
            BClaim(
                _claim(truth_id, f"`{sym}` is defined in the {name} library.", _sym(lib, sym)),
                binding_type=_BT[kind],
                style="C3",
                symbols=(sym,),
            ),
        ),
        note=f"checker reads the definer ({kind})",
    )
    trigger = Artifact(
        uri=f"docs/{name}_trigger.md",
        claims=(
            BClaim(
                _claim(trig_id, f"The {route} route is gated by `{sym}`.", _string(con, route)),
                binding_type="trigger_only",
                style="C3",
                symbols=(sym,),
            ),
        ),
        note="checker reads a consumer; claim only mentions the symbol",
    )

    both = frozenset({truth_id, trig_id})
    just_truth = frozenset({truth_id})
    just_trig = frozenset({trig_id})
    rename_to = sym + ("Renamed" if kind == "class" else "_renamed")
    muts = (
        Mutation(
            f"{name}-rename",
            "rename_definer",
            "rename the symbol in its definer",
            breaks_fact=just_truth,
            breaks_trigger=both,
            apply=_replace(lib, sym, rename_to),
        ),
        Mutation(
            f"{name}-delete",
            "delete_definer",
            "delete the symbol's definition",
            breaks_fact=just_truth,
            breaks_trigger=both,
            apply=_set(lib, "PLACEHOLDER = 1\n"),
        ),
        Mutation(
            f"{name}-move",
            "move_definer",
            "git mv the definer file (relocation, not a break)",
            breaks_fact=frozenset(),
            breaks_trigger=both,
            apply=_mv(lib, f"lib/{name}_lib_moved.py"),
            expect_rename=True,
        ),
        Mutation(
            f"{name}-comment",
            "benign_comment",
            "append a comment to the definer",
            breaks_fact=frozenset(),
            breaks_trigger=both,
            apply=_append(lib, "\n# benign comment\n"),
        ),
        Mutation(
            f"{name}-edit",
            "benign_edit",
            "tweak the body, keep the symbol",
            breaks_fact=frozenset(),
            breaks_trigger=both,
            apply=_replace(lib, "bool(value)", "bool(value)  # validated"),
        ),
        Mutation(
            f"{name}-neutral",
            "neutral_unrelated",
            "edit an unrelated file",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset(),
            apply=_append(oth, "EXTRA = 2\n"),
        ),
        Mutation(
            f"{name}-route-break",
            "checker_fact_break",
            "remove the consumer route literal",
            breaks_fact=just_trig,
            breaks_trigger=just_trig,
            apply=_replace(con, f'    "{route}": "{sym}",  # gated by {sym}\n', ""),
        ),
    )
    return Domain(name=name, files=files, artifacts=(truth, trigger), mutations=muts, quick=quick)


# --- hand-authored strata the generator cannot express --------------------------


def _ambiguous_domain() -> Domain:
    """A symbol defined in TWO files -> deliberately NOT auto-watched. A change to
    one definer must NOT select the claim (conservative low-FP), and never alarm."""
    a, b = "lib/amb_a.py", "lib/amb_b.py"
    con = "app/amb_routes.py"
    files = {
        a: "def handle(value):\n    return value\n",
        b: "def handle(value):\n    return value\n",
        con: 'ROUTES = {"/amb": "handle"}  # gated by handle\n',
    }
    art = Artifact(
        uri="docs/amb.md",
        claims=(
            BClaim(
                _claim("amb-claim", "The /amb route is gated by `handle`.", _string(con, "/amb")),
                binding_type="ambiguous_symbol",
                style="C3",
                symbols=("handle",),
            ),
        ),
        note="`handle` defined in two files -> unbound (no false precision)",
    )
    muts = (
        Mutation(
            "amb-change-one",
            "ambiguous_definer_change",
            "change ONE of the two definers — handle IS the claim's subject (a real dependency), "
            "but ambiguous, so dorian deliberately does NOT watch it: an HONEST trigger-coverage "
            "sacrifice surfaced as a bound_candidate miss (limitation A), not hidden",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset({"amb-claim"}),  # SHOULD re-check; the skip is the cost
            apply=_replace(a, "return value", "return bool(value)"),
        ),
        Mutation(
            "amb-route-break",
            "checker_fact_break",
            "remove the consumer route",
            breaks_fact=frozenset({"amb-claim"}),
            breaks_trigger=frozenset({"amb-claim"}),
            apply=_replace(con, '{"/amb": "handle"}', "{}"),
        ),
    )
    return Domain(name="ambiguous", files=files, artifacts=(art,), mutations=muts, quick=True)


def _pyproject_domain() -> Domain:
    """Console-script binding. A claim mentioning an UNAMBIGUOUS script name binds
    its target file (selection win, checker reads a consumer); a claim mentioning
    an AMBIGUOUS script name (target resolves to two modules) is left unbound."""
    files = {
        "tools/runner.py": "def go():\n    return 0\n",  # goodtool -> here (unambiguous)
        "pkg/cli.py": "def main():\n    return 0\n",  # ambtool candidate #1
        "src/pkg/cli.py": "def main():\n    return 0\n",  # ambtool candidate #2 -> ambiguous
        "app/main.py": 'GOOD = "goodtool"\nAMB = "ambtool"\n',  # consumer (checker surface)
        "lib/unrelated.py": "UNUSED = 1\n",
        "pyproject.toml": (
            '[project]\nname = "demo"\nversion = "0"\n\n'
            "[project.scripts]\n"
            'goodtool = "tools.runner:go"\n'  # unambiguous -> bound
            'ambtool = "pkg.cli:main"\n'  # two candidate modules -> NOT bound
        ),
    }
    good = Artifact(
        uri="docs/pp_good.md",
        claims=(
            BClaim(
                _claim(
                    "pp-good",
                    "The `goodtool` command is the entry point.",
                    _string("app/main.py", "goodtool"),
                ),
                binding_type="pyproject_script",
                style="C3",
                symbols=("goodtool",),
            ),
        ),
        note="checker reads app/main.py; 'goodtool' binds tools/runner.py (script target)",
    )
    amb = Artifact(
        uri="docs/pp_amb.md",
        claims=(
            BClaim(
                _claim(
                    "pp-amb",
                    "The `ambtool` command runs the CLI.",
                    _string("app/main.py", "ambtool"),
                ),
                binding_type="ambiguous_pyproject_script",
                style="C3",
                symbols=("ambtool",),
            ),
        ),
        note="'ambtool' target resolves to two files -> unbound (no false precision)",
    )
    muts = (
        Mutation(
            "pp-edit-runner",
            "binding_definer_change",
            "edit the goodtool target -> bound claim re-checked, checker (app/main.py) passes",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset({"pp-good"}),
            apply=_replace("tools/runner.py", "return 0", "return 1"),
        ),
        Mutation(
            "pp-edit-ambtarget",
            "ambiguous_definer_change",
            "edit one ambiguous-target candidate -> the target IS the claim's subject, but "
            "ambiguous, so unbound: an HONEST trigger-coverage sacrifice (a bound_candidate miss)",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset({"pp-amb"}),  # SHOULD re-check; the skip is the cost
            apply=_replace("src/pkg/cli.py", "return 0", "return 1"),
        ),
        Mutation(
            "pp-neutral",
            "neutral_unrelated",
            "edit a file no claim depends on",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset(),
            apply=_append("lib/unrelated.py", "MORE = 2\n"),
        ),
        Mutation(
            "pp-break-good",
            "checker_fact_break",
            "remove goodtool -> pp-good's checker fails; pp-amb shares the file, re-checks, passes",
            breaks_fact=frozenset({"pp-good"}),
            # both checkers read app/main.py, so pp-amb re-checks too (and passes)
            breaks_trigger=frozenset({"pp-good", "pp-amb"}),
            apply=_replace("app/main.py", 'GOOD = "goodtool"\n', "GOOD = None\n"),
        ),
    )
    return Domain(name="pyproject", files=files, artifacts=(good, amb), mutations=muts, quick=True)


def _c4_whitespace_domain() -> Domain:
    """A C4 pytest checker with whitespace around the nodeid path. The Phase-0 fix
    makes bindings._checker_named_files strip it to match seal._derive_watch, so no
    spurious trigger-only-symbol flag — and the watch resolves the file correctly."""
    test_src = (
        "def test_login_ok():\n    from svc.auth import verify\n    assert verify('t') is True\n"
    )
    files = {
        "svc/auth.py": "def verify(token):\n    return bool(token)\n",
        "tests/test_login.py": test_src,
    }
    art = Artifact(
        uri="docs/c4ws.md",
        claims=(
            BClaim(
                _claim(
                    "c4ws-claim",
                    "Login is covered by a test of `verify`.",
                    _pytest(" tests/test_login.py::test_login_ok "),  # whitespace around nodeid
                ),
                binding_type="c4_whitespace",
                style="C4",
                symbols=("verify",),
            ),
        ),
        note="C4 nodeid padded with whitespace; binding must strip to match the watch",
    )
    muts = (
        Mutation(
            "c4ws-break-impl",
            "checker_fact_break",
            "break verify so the test fails",
            breaks_fact=frozenset({"c4ws-claim"}),
            breaks_trigger=frozenset({"c4ws-claim"}),
            apply=_set("svc/auth.py", "def verify(token):\n    return False\n"),
        ),
        Mutation(
            "c4ws-benign",
            "benign_comment",
            "comment the implementation; test still passes",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset({"c4ws-claim"}),
            apply=_append("svc/auth.py", "\n# unchanged behavior\n"),
        ),
    )
    return Domain(name="c4_whitespace", files=files, artifacts=(art,), mutations=muts, quick=True)


def _gutted_body_domain() -> Domain:
    """The semantic ceiling. SAME gutted-body edit, two checkers: an existence
    checker (symbol:) fires the TRIGGER but cannot prove the behavior change (no
    BROKEN); a behavior checker (C4 pytest) DOES catch it."""
    files = {
        "svc/rate.py": "def rate_limit(n):\n    return n <= 5\n",
        "tests/test_rate.py": (
            "def test_rate_blocks_over_limit():\n"
            "    from svc.rate import rate_limit\n"
            "    assert rate_limit(9) is False\n"
        ),
    }
    existence = Artifact(
        uri="docs/gut_exists.md",
        claims=(
            BClaim(
                _claim(
                    "gut-exists",
                    "`rate_limit` enforces the request cap.",
                    _sym("svc/rate.py", "rate_limit"),
                ),
                binding_type="semantic_ceiling",
                style="C3",
                symbols=("rate_limit",),
            ),
        ),
        note="existence checker: cannot prove behavior",
    )
    behavior = Artifact(
        uri="docs/gut_behavior.md",
        claims=(
            BClaim(
                _claim(
                    "gut-behavior",
                    "`rate_limit` blocks requests over the cap.",
                    _pytest("tests/test_rate.py::test_rate_blocks_over_limit"),
                ),
                binding_type="behavior_checked",
                style="C4",
                symbols=("rate_limit",),
            ),
        ),
        note="behavior checker: catches the gutted body",
    )
    # gutted body: symbol still exists, behavior inverted. ONE edit scored against
    # both artifacts: the existence checker fires the trigger but cannot prove the
    # break (the ceiling); the behavior (C4) checker on the SAME edit DOES break.
    gut = "def rate_limit(n):\n    return True\n"
    muts = (
        Mutation(
            "gut",
            "gutted_body",
            "gut the body; existence checker can't prove it, behavior (C4) checker can",
            breaks_fact=frozenset({"gut-behavior"}),  # only the behavior checker catches it
            breaks_trigger=frozenset({"gut-exists", "gut-behavior"}),
            apply=_set("svc/rate.py", gut),
        ),
        Mutation(
            "gut-benign",
            "benign_comment",
            "comment the impl; behavior unchanged -> both re-check and pass",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset({"gut-exists", "gut-behavior"}),
            apply=_append("svc/rate.py", "\n# unchanged behavior\n"),
        ),
    )
    return Domain(
        name="gutted_body",
        files=files,
        artifacts=(existence, behavior),
        mutations=muts,
        quick=True,
    )


def _bad_python_domain() -> Domain:
    """A syntactically invalid Python file is present. The index must skip it and
    never crash; valid claims still bind and revalidate normally."""
    files = {
        "lib/good.py": "def compute_total(x):\n    return x + 1\n",
        "lib/broken.py": "def oops(:\n    pass\n",  # unparseable
        "app/r.py": 'ROUTES = {"/total": "compute_total"}\n',
    }
    art = Artifact(
        uri="docs/badpy.md",
        claims=(
            BClaim(
                _claim(
                    "badpy-claim",
                    "`compute_total` exists despite a broken sibling.",
                    _sym("lib/good.py", "compute_total"),
                ),
                binding_type="bad_python_present",
                style="C3",
                symbols=("compute_total",),
            ),
        ),
        note="invalid lib/broken.py present; index must not crash",
    )
    muts = (
        Mutation(
            "badpy-rename",
            "rename_definer",
            "rename the good symbol -> BROKEN, index still safe",
            breaks_fact=frozenset({"badpy-claim"}),
            breaks_trigger=frozenset({"badpy-claim"}),
            apply=_replace("lib/good.py", "compute_total", "compute_sum"),
        ),
        Mutation(
            "badpy-edit-broken",
            "neutral_unrelated",
            "edit the broken file -> no claim depends on it",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset(),
            apply=_append("lib/broken.py", "\n# still broken\n"),
        ),
    )
    return Domain(name="bad_python", files=files, artifacts=(art,), mutations=muts, quick=True)


def _backtick_domain() -> Domain:
    """Backtick precision. A real backticked identifier binds its definer; a
    backticked COMMON word (`config`) defined as a one-definer symbol must NOT
    bind (the Phase-0 guard) — so changing config's file does not select the claim."""
    files = {
        "lib/auth.py": "def verify_token(t):\n    return bool(t)\n",
        "lib/settings.py": "def config():\n    return {}\n",  # 'config' is a one-definer symbol
        "app/r.py": 'ROUTES = {"/login": "verify_token"}  # config loaded here\n',
    }
    real = Artifact(
        uri="docs/bt_real.md",
        claims=(
            BClaim(
                _claim("bt-real", "Login uses `verify_token`.", _string("app/r.py", "/login")),
                binding_type="backtick_ident",
                style="C3",
                symbols=("verify_token",),
            ),
        ),
        note="backticked real identifier -> binds its definer",
    )
    common = Artifact(
        uri="docs/bt_common.md",
        claims=(
            BClaim(
                # 'config' must NOT bind lib/settings.py despite being a one-definer symbol
                _claim(
                    "bt-common",
                    "The `config` value is read at startup.",
                    _string("app/r.py", "config loaded"),
                ),
                binding_type="backtick_common_word",
                style="C3",
                symbols=(),  # intentionally no overbroad target: a common word is not a reference
            ),
        ),
        note="backticked common word -> NOT bound (Phase-0 guard)",
    )
    muts = (
        Mutation(
            "bt-rename-real",
            "rename_definer",
            "rename verify_token -> trigger-stale for bt-real",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset({"bt-real"}),
            apply=_replace("lib/auth.py", "verify_token", "verify_jwt"),
        ),
        Mutation(
            "bt-change-config",
            "backtick_common_word_change",
            "change config()'s file -> bt-common must NOT be selected (common word unbound)",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset(),  # `config` is not bound
            apply=_replace("lib/settings.py", "return {}", "return {'x': 1}"),
        ),
    )
    return Domain(
        name="backtick", files=files, artifacts=(real, common), mutations=muts, quick=True
    )


def _prose_domain() -> Domain:
    """Controls: a prose-only claim (no bindable symbol) and a neutral change.
    Nothing should be selected from prose; neutral changes select nothing."""
    files = {
        "lib/core.py": "def process(x):\n    return x\n",
        "notes/extra.txt": "freeform\n",
    }
    art = Artifact(
        uri="docs/prose.md",
        claims=(
            BClaim(
                _claim(
                    "prose-claim",
                    "The system is generally reliable and well tested.",
                    _sym("lib/core.py", "process"),
                ),
                binding_type="prose_only",
                style="C3",
                symbols=(),  # prose mentions no code identifier
            ),
        ),
        note="prose claim; only its explicit checker binds, nothing inferred from prose",
    )
    muts = (
        Mutation(
            "prose-neutral",
            "neutral_unrelated",
            "edit an unrelated text file",
            breaks_fact=frozenset(),
            breaks_trigger=frozenset(),
            apply=_append("notes/extra.txt", "more\n"),
        ),
        Mutation(
            "prose-break",
            "checker_fact_break",
            "rename the checked symbol -> BROKEN",
            breaks_fact=frozenset({"prose-claim"}),
            breaks_trigger=frozenset({"prose-claim"}),
            apply=_replace("lib/core.py", "process", "handle"),
        ),
    )
    return Domain(name="prose", files=files, artifacts=(art,), mutations=muts, quick=True)


# --- the suite ------------------------------------------------------------------

# Hand-named binding domains (readable, varied) across the three symbol kinds; each
# contributes 2 artifacts x 7 mutations = 14 (artifact, mutation) pairs.
_NAMED_SPECS = [
    ("svc_login", "verify_token", "func"),
    ("svc_ratelimit", "rate_guard", "func"),
    ("svc_cache", "CacheStore", "class"),
    ("svc_session", "SessionManager", "class"),
    ("svc_fetch", "fetch_user", "async"),
    ("svc_sync", "sync_records", "async"),
    ("svc_parse", "parse_payload", "func"),
    ("svc_render", "TemplateEngine", "class"),
    ("svc_queue", "enqueue_job", "func"),
    ("svc_index", "IndexBuilder", "class"),
    ("svc_stream", "stream_events", "async"),
    ("svc_audit", "audit_log", "func"),
    ("svc_token", "RotatingKey", "class"),
    ("svc_notify", "notify_user", "func"),
    ("svc_export", "export_batch", "async"),
    ("svc_policy", "PolicyEngine", "class"),
]

# Systematic replication: the same binding shape across MANY distinct one-definer
# symbols of every kind, so the result is not a property of a few cherry-picked
# names. Each row is a real sealed warrant, mutated + revalidated; labels stay
# mechanical. Deterministic (index-derived names, no clock/randomness).
_KINDS = ("func", "async", "class")
_BASES = {"func": "process", "async": "load", "class": "Handler"}


def _generated_specs(n: int) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for i in range(n):
        kind = _KINDS[i % 3]
        base = _BASES[kind]
        sym = f"{base}{i:03d}" if kind == "class" else f"{base}_{i:03d}"
        out.append((f"gen_{i:03d}", sym, kind))
    return out


def domains() -> list[Domain]:
    quick_gen = {"svc_login", "svc_cache", "svc_fetch"}
    specs = _NAMED_SPECS + _generated_specs(40)  # 56 binding domains -> 784 pairs
    gens = [
        _binding_domain(name, sym, kind, quick=(name in quick_gen)) for (name, sym, kind) in specs
    ]
    hand = [
        _ambiguous_domain(),
        _pyproject_domain(),
        _c4_whitespace_domain(),
        _gutted_body_domain(),
        _bad_python_domain(),
        _backtick_domain(),
        _prose_domain(),
    ]
    return gens + hand
