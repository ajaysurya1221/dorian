"""Fixture domains for the v0.7.0 large controlled-mutation benchmark.

Each Domain is invented and public-safe. Every `MutationSpec.breaks` set is the
KNOWN-TRUTH label: the claim ids whose underlying FACT the edit falsifies, fixed
by the edit itself before any measurement. dorian's behavior is measured against
these labels, never assumed to match them.

Authoring rule enforced by the harness: every claim must seal green at t0 (the
seal pipeline refuses on any FAIL/ERROR), so a mis-authored fixture fails loudly
rather than scoring a vacuous PASS.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bench.large_mutation import (
    ArtifactSpec,
    ClaimEntry,
    Domain,
    MutationSpec,
    _c3,
    _c5,
    _delete_file,
    _git_mv,
    _set_file,
)
from dorian.model import Anchor, CheckerSpec, Claim

# ================================================================================
# Domain 1: python_service  (C1 span + C3 symbol/regex/string/path)
# ================================================================================

AUTH_PY = '''"""Auth helpers."""


def verify_token(token: str) -> bool:
    """Verify an RS256-signed JWT."""
    algo = "RS256"
    return _check(token, algo)


def _check(token: str, algo: str) -> bool:
    return bool(token) and algo == "RS256"
'''

CONFIG_PY = """TIMEOUT = 30
RETRIES = 3
BASE_URL = "https://api.example.test"
"""

ROUTES_PY = """ROUTES = {
    "/v1/login": "auth.login",
    "/v2/items": "items.list",
}
"""


def _auth_span_claim() -> Claim:
    return Claim(
        id="py_auth_span",
        text="Token verification lives in src/auth.py and uses RS256.",
        kind="fact",
        load_bearing=True,
        anchor=Anchor(line_start=4, line_end=7, quote="RS256"),
        supports=("rs-0",),
        checkers=(CheckerSpec(type="C1", program="rs-0", watch=("src/auth.py",)),),
    )


_PY_A1 = ArtifactSpec(
    uri="docs/service.md",
    readset_specs=("src/auth.py:L4-7",),
    note="shape-tolerant claims (regex/symbol/span)",
    claims=(
        # C1 span
        ClaimEntry(
            claim=_auth_span_claim(),
            style="C1-span",
            level="line",
            anchor_file="src/auth.py",
            lines=frozenset({4, 5, 6, 7}),
        ),
        _c3(
            "py_auth_symbol",
            "verify_token() implements verification.",
            "symbol:src/auth.py::verify_token",
            "src/auth.py",
            style="C3-symbol",
            level="line",
            lines=frozenset({4}),
            kind="reference",
        ),
        _c3(
            "py_cfg_timeout",
            "The default request timeout is 30 seconds.",
            r"regex:src/config.py::TIMEOUT\s*=\s*30",
            "src/config.py",
            style="C3-regex",
            level="line",
            lines=frozenset({1}),
            kind="quantity",
        ),
        _c3(
            "py_cfg_retries",
            "The client retries 3 times.",
            r"regex:src/config.py::RETRIES\s*=\s*3",
            "src/config.py",
            style="C3-regex",
            level="line",
            lines=frozenset({2}),
            kind="quantity",
        ),
        _c3(
            "py_route_login",
            "Login is served at /v1/login.",
            "string:src/routes.py::/v1/login",
            "src/routes.py",
            style="C3-string",
            level="line",
            lines=frozenset({2}),
            kind="reference",
        ),
        _c3(
            "py_cfg_path",
            "Configuration lives in src/config.py.",
            "path:src/config.py",
            "src/config.py",
            style="C3-path",
            level="file",
            kind="reference",
        ),
    ),
)

_PY_A2 = ArtifactSpec(
    uri="docs/service-brittle.md",
    readset_specs=(),
    note="brittle exact-string claims (anti-pattern)",
    claims=(
        _c3(
            "py_b_timeout",
            "The default request timeout is 30 seconds.",
            "string:src/config.py::TIMEOUT = 30",
            "src/config.py",
            style="C3-string-brittle",
            level="line",
            lines=frozenset({1}),
            kind="quantity",
        ),
        _c3(
            "py_b_baseurl",
            "The base URL is https://api.example.test.",
            "string:src/config.py::https://api.example.test",
            "src/config.py",
            style="C3-string",
            level="line",
            lines=frozenset({3}),
            kind="fact",
        ),
    ),
)

_PY_A3 = ArtifactSpec(
    uri="docs/service-api.md",
    readset_specs=(),
    note="route/endpoint claims",
    claims=(
        _c3(
            "py_api_login",
            "Login is served at /v1/login.",
            "regex:src/routes.py::/v1/login",
            "src/routes.py",
            style="C3-regex",
            level="line",
            lines=frozenset({2}),
            kind="reference",
        ),
        _c3(
            "py_api_items",
            "Items are served at /v2/items.",
            "string:src/routes.py::/v2/items",
            "src/routes.py",
            style="C3-string",
            level="line",
            lines=frozenset({3}),
            kind="reference",
        ),
        _c3(
            "py_api_routespath",
            "Routes live in src/routes.py.",
            "path:src/routes.py",
            "src/routes.py",
            style="C3-path",
            level="file",
            kind="reference",
        ),
    ),
)


def _py_mut() -> tuple[MutationSpec, ...]:
    s = _set_file
    return (
        # --- true-stale --------------------------------------------------------
        MutationSpec(
            "py_auth_algo",
            "value_change",
            "auth.py: RS256 -> HS256",
            frozenset({"py_auth_span"}),
            lambda r: s(r, "src/auth.py", AUTH_PY.replace("RS256", "HS256")),
        ),
        MutationSpec(
            "py_auth_rename",
            "symbol_rename",
            "auth.py: verify_token -> issue_token",
            frozenset({"py_auth_span", "py_auth_symbol"}),
            lambda r: s(r, "src/auth.py", AUTH_PY.replace("verify_token", "issue_token")),
        ),
        MutationSpec(
            "py_auth_deleted",
            "file_deleted",
            "delete src/auth.py",
            frozenset({"py_auth_span", "py_auth_symbol"}),
            lambda r: _delete_file(r, "src/auth.py"),
        ),
        MutationSpec(
            "py_cfg_timeout_change",
            "value_change",
            "config.py: TIMEOUT 30 -> 10",
            frozenset({"py_cfg_timeout", "py_b_timeout"}),
            lambda r: s(r, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT = 10")),
        ),
        MutationSpec(
            "py_cfg_retries_change",
            "value_change",
            "config.py: RETRIES 3 -> 5",
            frozenset({"py_cfg_retries"}),
            lambda r: s(r, "src/config.py", CONFIG_PY.replace("RETRIES = 3", "RETRIES = 5")),
        ),
        MutationSpec(
            "py_baseurl_change",
            "value_change",
            "config.py: BASE_URL host change",
            frozenset({"py_b_baseurl"}),
            lambda r: s(
                r, "src/config.py", CONFIG_PY.replace("api.example.test", "api.changed.test")
            ),
        ),
        MutationSpec(
            "py_cfg_deleted",
            "file_deleted",
            "delete src/config.py",
            frozenset(
                {"py_cfg_timeout", "py_cfg_retries", "py_cfg_path", "py_b_timeout", "py_b_baseurl"}
            ),
            lambda r: _delete_file(r, "src/config.py"),
        ),
        MutationSpec(
            "py_route_login_removed",
            "route_change",
            "routes.py: drop /v1/login",
            frozenset({"py_route_login", "py_api_login"}),
            lambda r: s(
                r, "src/routes.py", ROUTES_PY.replace('    "/v1/login": "auth.login",\n', "")
            ),
        ),
        MutationSpec(
            "py_routes_deleted",
            "file_deleted",
            "delete src/routes.py",
            frozenset({"py_route_login", "py_api_login", "py_api_items", "py_api_routespath"}),
            lambda r: _delete_file(r, "src/routes.py"),
        ),
        MutationSpec(
            "py_route_items_removed",
            "route_change",
            "routes.py: drop /v2/items",
            frozenset({"py_api_items"}),
            lambda r: s(
                r, "src/routes.py", ROUTES_PY.replace('    "/v2/items": "items.list",\n', "")
            ),
        ),
        # --- adversarial true-stale (substring survives) -----------------------
        MutationSpec(
            "py_login_to_comment",
            "adversarial_comment_survival",
            "routes.py: /v1/login -> /v1/signin, old path left in a comment",
            frozenset({"py_route_login", "py_api_login"}),
            lambda r: s(
                r,
                "src/routes.py",
                ROUTES_PY.replace(
                    '"/v1/login": "auth.login",', '"/v1/signin": "auth.login",  # was /v1/login'
                ),
            ),
        ),
        MutationSpec(
            "py_items_to_docstring",
            "adversarial_docstring_survival",
            "routes.py: drop /v2/items, old path survives in a docstring",
            frozenset({"py_api_items"}),
            lambda r: s(
                r,
                "src/routes.py",
                '"""Route table; /v2/items was retired."""\n'
                + ROUTES_PY.replace('    "/v2/items": "items.list",\n', ""),
            ),
        ),
        MutationSpec(
            "py_login_to_constant",
            "adversarial_constant_survival",
            "routes.py: drop /v1/login, old path survives in an unused constant",
            frozenset({"py_route_login", "py_api_login"}),
            lambda r: s(
                r,
                "src/routes.py",
                ROUTES_PY.replace('    "/v1/login": "auth.login",\n', "")
                + '_LEGACY = "/v1/login"  # retired, unused\n',
            ),
        ),
        # --- benign ------------------------------------------------------------
        MutationSpec(
            "py_auth_comment_top",
            "comment_added",
            "auth.py: prepend a comment",
            frozenset(),
            lambda r: s(r, "src/auth.py", "# module: authentication helpers\n" + AUTH_PY),
        ),
        MutationSpec(
            "py_auth_comment_bottom",
            "comment_added",
            "auth.py: append a comment",
            frozenset(),
            lambda r: s(r, "src/auth.py", AUTH_PY + "\n# end of module\n"),
        ),
        MutationSpec(
            "py_cfg_whitespace",
            "whitespace_reformat",
            "config.py: TIMEOUT = 30 -> TIMEOUT  =  30",
            frozenset(),
            lambda r: s(r, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT  =  30")),
        ),
        MutationSpec(
            "py_cfg_type_annotation",
            "type_annotation",
            "config.py: TIMEOUT = 30 -> TIMEOUT: int = 30",
            frozenset(),
            lambda r: s(r, "src/config.py", CONFIG_PY.replace("TIMEOUT = 30", "TIMEOUT: int = 30")),
        ),
        MutationSpec(
            "py_cfg_constant_added",
            "constant_added",
            "config.py: add DEBUG constant",
            frozenset(),
            lambda r: s(r, "src/config.py", CONFIG_PY + "DEBUG = False\n"),
        ),
        MutationSpec(
            "py_routes_reordered",
            "reorder",
            "routes.py: swap the two entries",
            frozenset(),
            lambda r: s(
                r,
                "src/routes.py",
                'ROUTES = {\n    "/v2/items": "items.list",\n    "/v1/login": "auth.login",\n}\n',
            ),
        ),
        MutationSpec(
            "py_cfg_renamed",
            "file_renamed",
            "git mv config.py -> settings.py",
            frozenset(),
            lambda r: _git_mv(r, "src/config.py", "src/settings.py"),
            expect_rename=True,
        ),
        MutationSpec(
            "py_routes_renamed",
            "file_renamed",
            "git mv routes.py -> endpoints.py",
            frozenset(),
            lambda r: _git_mv(r, "src/routes.py", "src/endpoints.py"),
            expect_rename=True,
        ),
        # --- neutral (unrelated file) ------------------------------------------
        MutationSpec(
            "py_util_added",
            "unrelated_file",
            "add an unrelated src/util2.py",
            frozenset(),
            lambda r: s(r, "src/util2.py", "def helper():\n    return 42\n"),
        ),
        MutationSpec(
            "py_notes_added",
            "unrelated_file",
            "add an unrelated docs/notes.md",
            frozenset(),
            lambda r: s(r, "docs/notes.md", "# notes\n\nunrelated.\n"),
        ),
    )


PYTHON_SERVICE = Domain(
    name="python_service",
    files={"src/auth.py": AUTH_PY, "src/config.py": CONFIG_PY, "src/routes.py": ROUTES_PY},
    artifacts=(_PY_A1, _PY_A2, _PY_A3),
    mutations=_py_mut(),
)


# ================================================================================
# Domain 2: csv_data  (C5 rowcount/schema/domain/nullrate/freshness/reconcile + snapshot)
# ================================================================================

LOTS_CSV = """lot_id,site,status,loaded_at
L001,athens,open,2026-01-01
L002,berlin,closed,2026-01-02
L003,athens,open,2026-01-03
L004,cairo,open,2026-01-04
"""

LOTS_MIRROR_CSV = LOTS_CSV  # same 4 rows -> reconcile counts match at t0

EVENTS_CSV = """event_id,ts
E1,2026-01-02
E2,2026-01-03
E3,2026-01-04
"""


def _snapshot_claim() -> Claim:
    return Claim(
        id="csv_snapshot",
        text="The lots dataset is byte-identical to the sealed snapshot.",
        kind="fact",
        load_bearing=True,
        checkers=(
            CheckerSpec(type="C5", program="snapshot:data/lots.csv", watch=("data/lots.csv",)),
        ),
    )


_CSV_D1 = ArtifactSpec(
    uri="docs/data.md",
    readset_specs=(),
    note="shape-tolerant typed data claims",
    claims=(
        _c5(
            "csv_rowcount",
            "The lots dataset has 4 rows.",
            "rowcount:data/lots.csv::== 4",
            ("data/lots.csv",),
            style="C5-rowcount",
            kind="quantity",
        ),
        _c5(
            "csv_schema",
            "lots has columns lot_id, site, status, loaded_at.",
            "schema:data/lots.csv::lot_id,site,status,loaded_at",
            ("data/lots.csv",),
            style="C5-schema",
        ),
        _c5(
            "csv_domain",
            "Lot status is open or closed.",
            "domain:data/lots.csv::status::{open,closed}",
            ("data/lots.csv",),
            style="C5-domain",
            lb=False,
        ),
        _c5(
            "csv_nullrate",
            "Every lot has a site (no nulls).",
            "nullrate:data/lots.csv::site::== 0",
            ("data/lots.csv",),
            style="C5-nullrate",
        ),
        _c5(
            "csv_freshness",
            "The events dataset has data on or after 2026-01-01.",
            "freshness:data/events.csv::ts::>= 2026-01-01",
            ("data/events.csv",),
            style="C5-freshness",
        ),
        _c5(
            "csv_reconcile",
            "lots and its mirror have equal row counts.",
            "reconcile:csv:data/lots.csv~~csv:data/lots_mirror.csv",
            ("data/lots.csv", "data/lots_mirror.csv"),
            style="C5-reconcile",
        ),
    ),
)

_CSV_D2 = ArtifactSpec(
    uri="docs/data-brittle.md",
    readset_specs=("data/lots.csv",),
    note="byte-exact snapshot + brittle header string",
    claims=(
        ClaimEntry(claim=_snapshot_claim(), style="C5-snapshot", level="file"),
        _c3(
            "csv_b_header",
            "The lots header is lot_id,site,status,loaded_at.",
            "string:data/lots.csv::lot_id,site,status,loaded_at",
            "data/lots.csv",
            style="C3-string",
            level="line",
            lines=frozenset({1}),
        ),
    ),
)

_CSV_D3 = ArtifactSpec(
    uri="docs/data-summary.md",
    readset_specs=(),
    note="loose data claims",
    claims=(
        _c5(
            "csv3_lots_min",
            "lots has at least 3 rows.",
            "rowcount:data/lots.csv::>= 3",
            ("data/lots.csv",),
            style="C5-rowcount",
            lb=False,
        ),
        _c5(
            "csv3_events_schema",
            "events has columns event_id, ts.",
            "schema:data/events.csv::event_id,ts",
            ("data/events.csv",),
            style="C5-schema",
        ),
        _c3(
            "csv3_lots_path",
            "The lots dataset lives at data/lots.csv.",
            "path:data/lots.csv",
            "data/lots.csv",
            style="C3-path",
            level="file",
        ),
    ),
)


def _drop_last_row(csv: str) -> str:
    lines = csv.splitlines(keepends=True)
    return "".join(lines[:-1])


def _csv_mut() -> tuple[MutationSpec, ...]:
    s = _set_file
    return (
        # --- true-stale --------------------------------------------------------
        # NB: drops to 3 rows, so csv3_lots_min ('>= 3') still HOLDS - not broken.
        MutationSpec(
            "csv_row_dropped",
            "data_row_dropped",
            "lots.csv: drop a row (4 -> 3)",
            frozenset({"csv_rowcount", "csv_snapshot", "csv_reconcile"}),
            lambda r: s(r, "data/lots.csv", _drop_last_row(LOTS_CSV)),
        ),
        MutationSpec(
            "csv_two_rows_dropped",
            "data_row_dropped",
            "lots.csv: drop 2 rows (4 -> 2)",
            frozenset({"csv_rowcount", "csv_snapshot", "csv_reconcile", "csv3_lots_min"}),
            lambda r: s(r, "data/lots.csv", "".join(LOTS_CSV.splitlines(keepends=True)[:3])),
        ),
        MutationSpec(
            "csv_col_renamed",
            "schema_field_renamed",
            "lots.csv: status -> state header",
            frozenset({"csv_schema", "csv_domain", "csv_snapshot", "csv_b_header"}),
            lambda r: s(r, "data/lots.csv", LOTS_CSV.replace("status", "state", 1)),
        ),
        MutationSpec(
            "csv_out_of_domain",
            "data_value_change",
            "lots.csv: one open -> pending",
            frozenset({"csv_domain", "csv_snapshot"}),
            lambda r: s(r, "data/lots.csv", LOTS_CSV.replace("athens,open", "athens,pending", 1)),
        ),
        MutationSpec(
            "csv_null_site",
            "data_value_change",
            "lots.csv: blank a site cell",
            frozenset({"csv_nullrate", "csv_snapshot"}),
            lambda r: s(r, "data/lots.csv", LOTS_CSV.replace("L002,berlin", "L002,", 1)),
        ),
        MutationSpec(
            "csv_emptied",
            "data_emptied",
            "lots.csv: truncate to header (0 rows)",
            frozenset(
                {
                    "csv_rowcount",
                    "csv_domain",
                    "csv_nullrate",
                    "csv_snapshot",
                    "csv_reconcile",
                    "csv3_lots_min",
                }
            ),
            lambda r: s(r, "data/lots.csv", LOTS_CSV.splitlines(keepends=True)[0]),
        ),
        MutationSpec(
            "csv_events_stale",
            "data_value_change",
            "events.csv: all dates -> 2025-12-01",
            frozenset({"csv_freshness"}),
            lambda r: s(
                r, "data/events.csv", "event_id,ts\nE1,2025-12-01\nE2,2025-12-01\nE3,2025-12-01\n"
            ),
        ),
        MutationSpec(
            "csv_mirror_drift",
            "data_reconcile_break",
            "lots_mirror.csv: drop a row",
            frozenset({"csv_reconcile"}),
            lambda r: s(r, "data/lots_mirror.csv", _drop_last_row(LOTS_MIRROR_CSV)),
        ),
        MutationSpec(
            "csv_mirror_added_row",
            "data_reconcile_break",
            "lots_mirror.csv: add a row",
            frozenset({"csv_reconcile"}),
            lambda r: s(
                r, "data/lots_mirror.csv", LOTS_MIRROR_CSV + "L005,delhi,open,2026-01-05\n"
            ),
        ),
        MutationSpec(
            "csv_status_all_active",
            "data_value_change",
            "lots.csv: all status -> active",
            frozenset({"csv_domain", "csv_snapshot"}),
            lambda r: s(
                r,
                "data/lots.csv",
                LOTS_CSV.replace(",open,", ",active,").replace(",closed,", ",active,"),
            ),
        ),
        MutationSpec(
            "csv_loaded_at_dropped",
            "schema_field_dropped",
            "lots.csv: drop the loaded_at column",
            frozenset({"csv_schema", "csv_snapshot", "csv_b_header"}),
            lambda r: s(r, "data/lots.csv", _drop_col4(LOTS_CSV)),
        ),
        # --- benign ------------------------------------------------------------
        MutationSpec(
            "csv_mirror_cell",
            "benign_data_value",
            "lots_mirror.csv: change a cell (row count unchanged)",
            frozenset(),
            lambda r: s(r, "data/lots_mirror.csv", LOTS_MIRROR_CSV.replace("athens", "sparta", 1)),
        ),
        MutationSpec(
            "csv_events_append",
            "data_append",
            "events.csv: append a newer row",
            frozenset(),
            lambda r: s(r, "data/events.csv", EVENTS_CSV + "E4,2026-01-05\n"),
        ),
        MutationSpec(
            "csv_mirror_reorder",
            "reorder",
            "lots_mirror.csv: reorder rows",
            frozenset(),
            lambda r: s(r, "data/lots_mirror.csv", _reorder_lots(LOTS_MIRROR_CSV)),
        ),
        # --- neutral -----------------------------------------------------------
        MutationSpec(
            "csv_unrelated",
            "unrelated_file",
            "add an unrelated data/notes.txt",
            frozenset(),
            lambda r: s(r, "data/notes.txt", "unrelated\n"),
        ),
    )


def _reorder_lots(csv: str) -> str:
    lines = csv.splitlines(keepends=True)
    return lines[0] + "".join([lines[3], lines[1], lines[4], lines[2]])


def _drop_col4(csv: str) -> str:
    rows = [line.split(",")[:3] for line in csv.splitlines()]
    return "".join(",".join(cells) + "\n" for cells in rows)


CSV_DATA = Domain(
    name="csv_data",
    files={
        "data/lots.csv": LOTS_CSV,
        "data/lots_mirror.csv": LOTS_MIRROR_CSV,
        "data/events.csv": EVENTS_CSV,
    },
    artifacts=(_CSV_D1, _CSV_D2, _CSV_D3),
    mutations=_csv_mut(),
)


# ================================================================================
# Domain 3: json_config  (C3 regex/string/path on JSON)
# ================================================================================

SETTINGS_JSON = """{
  "timeout_seconds": 30,
  "retries": 3,
  "base_url": "https://api.example.test",
  "feature_flags": {
    "beta": false
  }
}
"""

SECRETS_JSON = """{
  "api_key": "REDACTED-EXAMPLE",
  "region": "eu-west-1"
}
"""

_JSON_J1 = ArtifactSpec(
    uri="docs/settings.md",
    readset_specs=(),
    note="shape-tolerant JSON claims",
    claims=(
        _c3(
            "json_timeout",
            "timeout_seconds is 30.",
            r'regex:config/settings.json::"timeout_seconds":\s*30',
            "config/settings.json",
            style="C3-regex",
            level="line",
            lines=frozenset({2}),
            kind="quantity",
        ),
        _c3(
            "json_retries",
            "retries is 3.",
            r'regex:config/settings.json::"retries":\s*3',
            "config/settings.json",
            style="C3-regex",
            level="line",
            lines=frozenset({3}),
            kind="quantity",
        ),
        _c3(
            "json_baseurl",
            "base_url is https://api.example.test.",
            "string:config/settings.json::https://api.example.test",
            "config/settings.json",
            style="C3-string",
            level="line",
            lines=frozenset({4}),
        ),
        _c3(
            "json_flag",
            "The beta feature flag is off.",
            r'regex:config/settings.json::"beta":\s*false',
            "config/settings.json",
            style="C3-regex",
            level="line",
            lines=frozenset({6}),
        ),
        _c3(
            "json_path",
            "Settings live at config/settings.json.",
            "path:config/settings.json",
            "config/settings.json",
            style="C3-path",
            level="file",
            kind="reference",
        ),
    ),
)

_JSON_J2 = ArtifactSpec(
    uri="docs/secrets.md",
    readset_specs=(),
    note="claims over a second file (region)",
    claims=(
        _c3(
            "json_secret_region",
            "The example region is eu-west-1.",
            "string:config/secrets.example.json::eu-west-1",
            "config/secrets.example.json",
            style="C3-string",
            level="line",
            lines=frozenset({3}),
        ),
        _c3(
            "json_secret_path",
            "Example secrets live at config/secrets.example.json.",
            "path:config/secrets.example.json",
            "config/secrets.example.json",
            style="C3-path",
            level="file",
            kind="reference",
        ),
    ),
)

_JSON_J3 = ArtifactSpec(
    uri="docs/settings-summary.md",
    readset_specs=(),
    note="presence claims",
    claims=(
        _c3(
            "json3_retries_present",
            "settings declares retries.",
            "string:config/settings.json::retries",
            "config/settings.json",
            style="C3-string",
            level="line",
            lines=frozenset({3}),
        ),
        _c3(
            "json3_flags_block",
            "settings has a feature_flags block.",
            r'regex:config/settings.json::"feature_flags":\s*\{',
            "config/settings.json",
            style="C3-regex",
            level="line",
            lines=frozenset({5}),
        ),
        _c3(
            "json3_path",
            "Settings live at config/settings.json.",
            "path:config/settings.json",
            "config/settings.json",
            style="C3-path",
            level="file",
            kind="reference",
        ),
    ),
)


def _json_mut() -> tuple[MutationSpec, ...]:
    s = _set_file
    return (
        # --- true-stale --------------------------------------------------------
        MutationSpec(
            "json_timeout_change",
            "value_change",
            "settings: timeout 30 -> 45",
            frozenset({"json_timeout"}),
            lambda r: s(
                r,
                "config/settings.json",
                SETTINGS_JSON.replace('"timeout_seconds": 30', '"timeout_seconds": 45'),
            ),
        ),
        MutationSpec(
            "json_flag_flip",
            "value_change",
            "settings: beta false -> true",
            frozenset({"json_flag"}),
            lambda r: s(
                r, "config/settings.json", SETTINGS_JSON.replace('"beta": false', '"beta": true')
            ),
        ),
        MutationSpec(
            "json_baseurl_change",
            "value_change",
            "settings: base_url host change",
            frozenset({"json_baseurl"}),
            lambda r: s(
                r,
                "config/settings.json",
                SETTINGS_JSON.replace("api.example.test", "api.changed.test"),
            ),
        ),
        MutationSpec(
            "json_retries_change",
            "value_change",
            "settings: retries 3 -> 7",
            frozenset({"json_retries"}),
            lambda r: s(
                r, "config/settings.json", SETTINGS_JSON.replace('"retries": 3', '"retries": 7')
            ),
        ),
        MutationSpec(
            "json_settings_deleted",
            "file_deleted",
            "delete config/settings.json",
            frozenset(
                {
                    "json_timeout",
                    "json_retries",
                    "json_baseurl",
                    "json_flag",
                    "json_path",
                    "json3_retries_present",
                    "json3_flags_block",
                    "json3_path",
                }
            ),
            lambda r: _delete_file(r, "config/settings.json"),
        ),
        MutationSpec(
            "json_secret_region_change",
            "value_change",
            "secrets: region change",
            frozenset({"json_secret_region"}),
            lambda r: s(
                r, "config/secrets.example.json", SECRETS_JSON.replace("eu-west-1", "us-east-1")
            ),
        ),
        MutationSpec(
            "json_flag_removed",
            "key_removed",
            "settings: drop the beta flag line",
            frozenset({"json_flag"}),
            lambda r: s(
                r, "config/settings.json", SETTINGS_JSON.replace('    "beta": false\n', "")
            ),
        ),
        MutationSpec(
            "json_retries_removed",
            "key_removed",
            "settings: drop the retries key",
            frozenset({"json_retries", "json3_retries_present"}),
            lambda r: s(r, "config/settings.json", SETTINGS_JSON.replace('  "retries": 3,\n', "")),
        ),
        MutationSpec(
            "json_secret_deleted",
            "file_deleted",
            "delete config/secrets.example.json",
            frozenset({"json_secret_region", "json_secret_path"}),
            lambda r: _delete_file(r, "config/secrets.example.json"),
        ),
        # --- benign ------------------------------------------------------------
        MutationSpec(
            "json_reformat_ws",
            "whitespace_reformat",
            "settings: extra spaces around values",
            frozenset(),
            lambda r: s(
                r,
                "config/settings.json",
                SETTINGS_JSON.replace('"timeout_seconds": 30', '"timeout_seconds":   30').replace(
                    '"retries": 3', '"retries":   3'
                ),
            ),
        ),
        MutationSpec(
            "json_comment_field",
            "constant_added",
            "settings: add a _comment field",
            frozenset(),
            lambda r: s(
                r,
                "config/settings.json",
                SETTINGS_JSON.replace("{\n", '{\n  "_comment": "managed by ops",\n', 1),
            ),
        ),
        MutationSpec(
            "json_secret_added",
            "constant_added",
            "secrets: add an unrelated key",
            frozenset(),
            lambda r: s(
                r,
                "config/secrets.example.json",
                SECRETS_JSON.replace(
                    '"region": "eu-west-1"\n', '"region": "eu-west-1",\n  "tier": "free"\n'
                ),
            ),
        ),
        # --- neutral -----------------------------------------------------------
        MutationSpec(
            "json_unrelated",
            "unrelated_file",
            "add an unrelated config/notes.txt",
            frozenset(),
            lambda r: s(r, "config/notes.txt", "unrelated\n"),
        ),
    )


JSON_CONFIG = Domain(
    name="json_config",
    files={"config/settings.json": SETTINGS_JSON, "config/secrets.example.json": SECRETS_JSON},
    artifacts=(_JSON_J1, _JSON_J2, _JSON_J3),
    mutations=_json_mut(),
)


# ================================================================================
# Domain 4: yaml_config  (C3 regex/string/path on YAML)
# ================================================================================

CONFIG_YAML = """service: gateway
timeout_seconds: 30
replicas: 3
endpoints:
  - /v1/login
  - /v2/items
"""

LIMITS_YAML = """max_connections: 100
rate_limit_per_min: 600
"""

_YAML_Y1 = ArtifactSpec(
    uri="docs/deploy.md",
    readset_specs=(),
    note="shape-tolerant YAML claims",
    claims=(
        _c3(
            "yaml_timeout",
            "timeout_seconds is 30.",
            r"regex:deploy/config.yaml::timeout_seconds:\s*30",
            "deploy/config.yaml",
            style="C3-regex",
            level="line",
            lines=frozenset({2}),
            kind="quantity",
        ),
        _c3(
            "yaml_replicas",
            "replicas is 3.",
            r"regex:deploy/config.yaml::replicas:\s*3",
            "deploy/config.yaml",
            style="C3-regex",
            level="line",
            lines=frozenset({3}),
            kind="quantity",
        ),
        _c3(
            "yaml_login",
            "An endpoint /v1/login is configured.",
            "string:deploy/config.yaml::/v1/login",
            "deploy/config.yaml",
            style="C3-string",
            level="line",
            lines=frozenset({5}),
        ),
        _c3(
            "yaml_path",
            "Deploy config lives at deploy/config.yaml.",
            "path:deploy/config.yaml",
            "deploy/config.yaml",
            style="C3-path",
            level="file",
            kind="reference",
        ),
    ),
)

_YAML_Y2 = ArtifactSpec(
    uri="docs/limits.md",
    readset_specs=(),
    note="claims over a second file; one brittle",
    claims=(
        _c3(
            "yaml_maxconn",
            "max_connections is 100.",
            r"regex:deploy/limits.yaml::max_connections:\s*100",
            "deploy/limits.yaml",
            style="C3-regex",
            level="line",
            lines=frozenset({1}),
            kind="quantity",
        ),
        _c3(
            "yaml_rate",
            "rate_limit_per_min is 600.",
            "string:deploy/limits.yaml::rate_limit_per_min: 600",
            "deploy/limits.yaml",
            style="C3-string-brittle",
            level="line",
            lines=frozenset({2}),
            kind="quantity",
        ),
    ),
)

_YAML_Y3 = ArtifactSpec(
    uri="docs/deploy-summary.md",
    readset_specs=(),
    note="presence claims",
    claims=(
        _c3(
            "yaml3_service",
            "The service is named gateway.",
            "string:deploy/config.yaml::service: gateway",
            "deploy/config.yaml",
            style="C3-string",
            level="line",
            lines=frozenset({1}),
        ),
        _c3(
            "yaml3_items",
            "An endpoint /v2/items is configured.",
            "string:deploy/config.yaml::/v2/items",
            "deploy/config.yaml",
            style="C3-string",
            level="line",
            lines=frozenset({6}),
        ),
        _c3(
            "yaml3_path",
            "Deploy config lives at deploy/config.yaml.",
            "path:deploy/config.yaml",
            "deploy/config.yaml",
            style="C3-path",
            level="file",
            kind="reference",
        ),
    ),
)


def _yaml_mut() -> tuple[MutationSpec, ...]:
    s = _set_file
    return (
        MutationSpec(
            "yaml_timeout_change",
            "value_change",
            "config.yaml: timeout 30 -> 60",
            frozenset({"yaml_timeout"}),
            lambda r: s(
                r,
                "deploy/config.yaml",
                CONFIG_YAML.replace("timeout_seconds: 30", "timeout_seconds: 60"),
            ),
        ),
        MutationSpec(
            "yaml_replicas_change",
            "value_change",
            "config.yaml: replicas 3 -> 5",
            frozenset({"yaml_replicas"}),
            lambda r: s(r, "deploy/config.yaml", CONFIG_YAML.replace("replicas: 3", "replicas: 5")),
        ),
        MutationSpec(
            "yaml_login_removed",
            "route_change",
            "config.yaml: drop /v1/login",
            frozenset({"yaml_login"}),
            lambda r: s(r, "deploy/config.yaml", CONFIG_YAML.replace("  - /v1/login\n", "")),
        ),
        MutationSpec(
            "yaml_config_deleted",
            "file_deleted",
            "delete deploy/config.yaml",
            frozenset(
                {
                    "yaml_timeout",
                    "yaml_replicas",
                    "yaml_login",
                    "yaml_path",
                    "yaml3_service",
                    "yaml3_items",
                    "yaml3_path",
                }
            ),
            lambda r: _delete_file(r, "deploy/config.yaml"),
        ),
        MutationSpec(
            "yaml_maxconn_change",
            "value_change",
            "limits.yaml: max_connections -> 200",
            frozenset({"yaml_maxconn"}),
            lambda r: s(
                r,
                "deploy/limits.yaml",
                LIMITS_YAML.replace("max_connections: 100", "max_connections: 200"),
            ),
        ),
        MutationSpec(
            "yaml_rate_change",
            "value_change",
            "limits.yaml: rate 600 -> 900",
            frozenset({"yaml_rate"}),
            lambda r: s(
                r,
                "deploy/limits.yaml",
                LIMITS_YAML.replace("rate_limit_per_min: 600", "rate_limit_per_min: 900"),
            ),
        ),
        MutationSpec(
            "yaml_items_removed",
            "route_change",
            "config.yaml: drop /v2/items",
            frozenset({"yaml3_items"}),
            lambda r: s(r, "deploy/config.yaml", CONFIG_YAML.replace("  - /v2/items\n", "")),
        ),
        MutationSpec(
            "yaml_service_renamed",
            "value_change",
            "config.yaml: service gateway -> portal",
            frozenset({"yaml3_service"}),
            lambda r: s(
                r, "deploy/config.yaml", CONFIG_YAML.replace("service: gateway", "service: portal")
            ),
        ),
        # --- benign ------------------------------------------------------------
        MutationSpec(
            "yaml_whitespace",
            "whitespace_reformat",
            "config.yaml: extra space after timeout colon",
            frozenset(),
            lambda r: s(
                r,
                "deploy/config.yaml",
                CONFIG_YAML.replace("timeout_seconds: 30", "timeout_seconds:  30"),
            ),
        ),
        MutationSpec(
            "yaml_comment",
            "comment_added",
            "config.yaml: prepend a comment",
            frozenset(),
            lambda r: s(r, "deploy/config.yaml", "# managed by ops\n" + CONFIG_YAML),
        ),
        MutationSpec(
            "yaml_reorder",
            "reorder",
            "config.yaml: swap timeout and replicas",
            frozenset(),
            lambda r: s(
                r,
                "deploy/config.yaml",
                "service: gateway\nreplicas: 3\ntimeout_seconds: 30\n"
                "endpoints:\n  - /v1/login\n  - /v2/items\n",
            ),
        ),
        MutationSpec(
            "yaml_rate_reformat",
            "whitespace_reformat",
            "limits.yaml: extra space before 600 (fact holds, brittle claim breaks)",
            frozenset(),
            lambda r: s(
                r,
                "deploy/limits.yaml",
                LIMITS_YAML.replace("rate_limit_per_min: 600", "rate_limit_per_min:  600"),
            ),
        ),
        # --- neutral -----------------------------------------------------------
        MutationSpec(
            "yaml_unrelated",
            "unrelated_file",
            "add an unrelated deploy/notes.txt",
            frozenset(),
            lambda r: s(r, "deploy/notes.txt", "unrelated\n"),
        ),
    )


YAML_CONFIG = Domain(
    name="yaml_config",
    files={"deploy/config.yaml": CONFIG_YAML, "deploy/limits.yaml": LIMITS_YAML},
    artifacts=(_YAML_Y1, _YAML_Y2, _YAML_Y3),
    mutations=_yaml_mut(),
)


# ================================================================================
# Domain 5: package_metadata  (C3 regex/string/path on package manifests)
# ================================================================================

PACKAGE_JSON = """{
  "name": "gateway",
  "version": "1.4.0",
  "dependencies": {
    "fastjson": "^2.1.0",
    "httpx": "^0.27.0"
  }
}
"""

VERSION_PY = '__version__ = "1.4.0"\n'

_PKG_P1 = ArtifactSpec(
    uri="docs/release.md",
    readset_specs=(),
    note="shape-tolerant package claims",
    claims=(
        _c3(
            "pkg_version",
            "The package version is 1.4.0.",
            r'regex:package.json::"version":\s*"1\.4\.0"',
            "package.json",
            style="C3-regex",
            level="line",
            lines=frozenset({3}),
            kind="quantity",
        ),
        _c3(
            "pkg_dep_fastjson",
            "The package depends on fastjson.",
            "string:package.json::fastjson",
            "package.json",
            style="C3-string",
            level="line",
            lines=frozenset({5}),
        ),
        _c3(
            "pkg_dep_httpx",
            "The package depends on httpx.",
            "string:package.json::httpx",
            "package.json",
            style="C3-string",
            level="line",
            lines=frozenset({6}),
        ),
        _c3(
            "pkg_path",
            "Package metadata lives at package.json.",
            "path:package.json",
            "package.json",
            style="C3-path",
            level="file",
            kind="reference",
        ),
    ),
)

_PKG_P2 = ArtifactSpec(
    uri="docs/version.md",
    readset_specs=(),
    note="brittle version-string claim over a second file",
    claims=(
        _c3(
            "pkg_py_version",
            "The Python package version is 1.4.0.",
            'string:pkg/version.py::__version__ = "1.4.0"',
            "pkg/version.py",
            style="C3-string-brittle",
            level="line",
            lines=frozenset({1}),
            kind="quantity",
        ),
        _c3(
            "pkg_py_path",
            "The version module lives at pkg/version.py.",
            "path:pkg/version.py",
            "pkg/version.py",
            style="C3-path",
            level="file",
            kind="reference",
        ),
    ),
)


def _pkg_mut() -> tuple[MutationSpec, ...]:
    s = _set_file
    return (
        MutationSpec(
            "pkg_version_bump",
            "value_change",
            "package.json: version 1.4.0 -> 1.5.0",
            frozenset({"pkg_version"}),
            lambda r: s(r, "package.json", PACKAGE_JSON.replace('"1.4.0"', '"1.5.0"')),
        ),
        MutationSpec(
            "pkg_dep_removed",
            "dependency_change",
            "package.json: drop fastjson",
            frozenset({"pkg_dep_fastjson"}),
            lambda r: s(r, "package.json", PACKAGE_JSON.replace('    "fastjson": "^2.1.0",\n', "")),
        ),
        MutationSpec(
            "pkg_dep_renamed",
            "dependency_change",
            "package.json: httpx -> httpcore",
            frozenset({"pkg_dep_httpx"}),
            lambda r: s(r, "package.json", PACKAGE_JSON.replace("httpx", "httpcore")),
        ),
        MutationSpec(
            "pkg_dep_fastjson_swapped",
            "dependency_change",
            "package.json: fastjson -> quickjson",
            frozenset({"pkg_dep_fastjson"}),
            lambda r: s(r, "package.json", PACKAGE_JSON.replace("fastjson", "quickjson")),
        ),
        MutationSpec(
            "pkg_json_deleted",
            "file_deleted",
            "delete package.json",
            frozenset({"pkg_version", "pkg_dep_fastjson", "pkg_dep_httpx", "pkg_path"}),
            lambda r: _delete_file(r, "package.json"),
        ),
        MutationSpec(
            "pkg_py_version_bump",
            "value_change",
            "version.py: 1.4.0 -> 1.5.0",
            frozenset({"pkg_py_version"}),
            lambda r: s(r, "pkg/version.py", VERSION_PY.replace("1.4.0", "1.5.0")),
        ),
        MutationSpec(
            "pkg_py_deleted",
            "file_deleted",
            "delete pkg/version.py",
            frozenset({"pkg_py_version", "pkg_py_path"}),
            lambda r: _delete_file(r, "pkg/version.py"),
        ),
        # --- benign ------------------------------------------------------------
        MutationSpec(
            "pkg_dep_version_bump",
            "dependency_version_bump",
            "package.json: bump httpx range (dep still present)",
            frozenset(),
            lambda r: s(r, "package.json", PACKAGE_JSON.replace('"^0.27.0"', '"^0.28.0"')),
        ),
        MutationSpec(
            "pkg_dep_added",
            "constant_added",
            "package.json: add a dependency",
            frozenset(),
            lambda r: s(
                r,
                "package.json",
                PACKAGE_JSON.replace(
                    '"httpx": "^0.27.0"\n', '"httpx": "^0.27.0",\n    "tenacity": "^8.0.0"\n'
                ),
            ),
        ),
        MutationSpec(
            "pkg_whitespace",
            "whitespace_reformat",
            "package.json: extra spaces around version (fact holds)",
            frozenset(),
            lambda r: s(
                r,
                "package.json",
                PACKAGE_JSON.replace('"version": "1.4.0"', '"version":   "1.4.0"'),
            ),
        ),
        MutationSpec(
            "pkg_py_whitespace",
            "whitespace_reformat",
            "version.py: extra spaces (fact holds, brittle claim breaks)",
            frozenset(),
            lambda r: s(r, "pkg/version.py", '__version__  =  "1.4.0"\n'),
        ),
        # --- neutral -----------------------------------------------------------
        MutationSpec(
            "pkg_unrelated",
            "unrelated_file",
            "add an unrelated CHANGELOG.md",
            frozenset(),
            lambda r: s(r, "CHANGELOG.md", "# changelog\n"),
        ),
    )


PACKAGE_METADATA = Domain(
    name="package_metadata",
    files={"package.json": PACKAGE_JSON, "pkg/version.py": VERSION_PY},
    artifacts=(_PKG_P1, _PKG_P2),
    mutations=_pkg_mut(),
)


# ================================================================================
# Domain 6: sql_data  (C5 reconcile csv~~sqlite + C3 on DDL)
# ================================================================================

SCHEMA_SQL = """CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL
);
"""

ORDERS_CSV = """order_id,customer,amount,status
1,acme,100.0,paid
2,globex,250.0,pending
3,initech,75.0,paid
"""


def _build_orders_db(repo: Path) -> None:
    """Create db/orders.sqlite with rows mirroring data/orders.csv (3 rows)."""
    (repo / "db").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(repo / "db" / "orders.sqlite")
    try:
        con.execute(
            "CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer TEXT, "
            "amount REAL, status TEXT)"
        )
        con.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?)",
            [
                (1, "acme", 100.0, "paid"),
                (2, "globex", 250.0, "pending"),
                (3, "initech", 75.0, "paid"),
            ],
        )
        con.commit()
    finally:
        con.close()


_SQL_S1 = ArtifactSpec(
    uri="docs/orders.md",
    readset_specs=(),
    note="data reconciliation + typed data claims",
    claims=(
        _c5(
            "sql_reconcile",
            "orders.csv and the orders table agree on row count.",
            "reconcile:csv:data/orders.csv~~sqlite:db/orders.sqlite::SELECT COUNT(*) FROM orders",
            ("data/orders.csv", "db/orders.sqlite"),
            style="C5-reconcile",
        ),
        _c5(
            "sql_rowcount",
            "orders.csv has 3 rows.",
            "rowcount:data/orders.csv::== 3",
            ("data/orders.csv",),
            style="C5-rowcount",
            kind="quantity",
        ),
        _c5(
            "sql_status_domain",
            "Order status is paid or pending.",
            "domain:data/orders.csv::status::{paid,pending}",
            ("data/orders.csv",),
            style="C5-domain",
            lb=False,
        ),
    ),
)

_SQL_S2 = ArtifactSpec(
    uri="docs/orders-schema.md",
    readset_specs=(),
    note="DDL claims over the schema file",
    claims=(
        _c3(
            "sql_table",
            "The schema defines a table orders.",
            "string:db/schema.sql::CREATE TABLE orders",
            "db/schema.sql",
            style="C3-string",
            level="line",
            lines=frozenset({1}),
        ),
        _c3(
            "sql_col_amount",
            "orders has an amount REAL column.",
            r"regex:db/schema.sql::amount\s+REAL",
            "db/schema.sql",
            style="C3-regex",
            level="line",
            lines=frozenset({4}),
        ),
        _c3(
            "sql_schema_path",
            "The schema lives at db/schema.sql.",
            "path:db/schema.sql",
            "db/schema.sql",
            style="C3-path",
            level="file",
            kind="reference",
        ),
    ),
)


def _sql_mut() -> tuple[MutationSpec, ...]:
    s = _set_file
    return (
        MutationSpec(
            "sql_csv_row_dropped",
            "data_row_dropped",
            "orders.csv: drop a row (3 -> 2)",
            frozenset({"sql_reconcile", "sql_rowcount"}),
            lambda r: s(r, "data/orders.csv", "".join(ORDERS_CSV.splitlines(keepends=True)[:-1])),
        ),
        MutationSpec(
            "sql_csv_out_of_domain",
            "data_value_change",
            "orders.csv: pending -> refunded",
            frozenset({"sql_status_domain"}),
            lambda r: s(r, "data/orders.csv", ORDERS_CSV.replace("pending", "refunded")),
        ),
        MutationSpec(
            "sql_col_renamed",
            "schema_field_renamed",
            "schema.sql: amount -> total",
            frozenset({"sql_col_amount"}),
            lambda r: s(r, "db/schema.sql", SCHEMA_SQL.replace("amount REAL", "total REAL")),
        ),
        MutationSpec(
            "sql_table_renamed",
            "schema_object_renamed",
            "schema.sql: orders -> purchases",
            frozenset({"sql_table"}),
            lambda r: s(
                r,
                "db/schema.sql",
                SCHEMA_SQL.replace("CREATE TABLE orders", "CREATE TABLE purchases"),
            ),
        ),
        MutationSpec(
            "sql_schema_deleted",
            "file_deleted",
            "delete db/schema.sql",
            frozenset({"sql_table", "sql_col_amount", "sql_schema_path"}),
            lambda r: _delete_file(r, "db/schema.sql"),
        ),
        MutationSpec(
            "sql_csv_deleted",
            "file_deleted",
            "delete data/orders.csv",
            frozenset({"sql_reconcile", "sql_rowcount", "sql_status_domain"}),
            lambda r: _delete_file(r, "data/orders.csv"),
        ),
        MutationSpec(
            "sql_amount_type",
            "schema_field_retyped",
            "schema.sql: amount REAL -> INTEGER",
            frozenset({"sql_col_amount"}),
            lambda r: s(r, "db/schema.sql", SCHEMA_SQL.replace("amount REAL", "amount INTEGER")),
        ),
        MutationSpec(
            "sql_csv_emptied",
            "data_emptied",
            "orders.csv: truncate to header (0 rows)",
            frozenset({"sql_reconcile", "sql_rowcount", "sql_status_domain"}),
            lambda r: s(r, "data/orders.csv", ORDERS_CSV.splitlines(keepends=True)[0]),
        ),
        # --- benign ------------------------------------------------------------
        MutationSpec(
            "sql_schema_comment",
            "comment_added",
            "schema.sql: prepend a comment",
            frozenset(),
            lambda r: s(r, "db/schema.sql", "-- managed by ops\n" + SCHEMA_SQL),
        ),
        MutationSpec(
            "sql_csv_unclaimed",
            "benign_data_value",
            "orders.csv: change a customer name (counts/domain hold)",
            frozenset(),
            lambda r: s(r, "data/orders.csv", ORDERS_CSV.replace("acme", "acme-corp")),
        ),
        MutationSpec(
            "sql_schema_whitespace",
            "whitespace_reformat",
            "schema.sql: extra spaces in amount column",
            frozenset(),
            lambda r: s(r, "db/schema.sql", SCHEMA_SQL.replace("amount REAL", "amount   REAL")),
        ),
        # --- neutral -----------------------------------------------------------
        MutationSpec(
            "sql_unrelated",
            "unrelated_file",
            "add an unrelated db/README.md",
            frozenset(),
            lambda r: s(r, "db/README.md", "# db\n"),
        ),
    )


SQL_DATA = Domain(
    name="sql_data",
    files={"db/schema.sql": SCHEMA_SQL, "data/orders.csv": ORDERS_CSV},
    artifacts=(_SQL_S1, _SQL_S2),
    mutations=_sql_mut(),
    build_extra=_build_orders_db,
)


# ================================================================================

DOMAINS: tuple[Domain, ...] = (
    PYTHON_SERVICE,
    CSV_DATA,
    JSON_CONFIG,
    YAML_CONFIG,
    PACKAGE_METADATA,
    SQL_DATA,
)
