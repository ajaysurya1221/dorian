"""Every governance template ships as readable package data (resolves via importlib.resources),
so the adapter scaffolds correctly from an installed wheel — mirrors test_loop_packaging.py.
"""

from dorian import claude_code, governance


def test_every_governance_template_is_readable_package_data():
    for t in governance.GOVERNANCE_MANIFEST:
        assert claude_code._read_template(t.src), f"empty/missing governance template: {t.src}"


def test_manifest_covers_hooks_settings_and_docs():
    groups = {t.group for t in governance.GOVERNANCE_MANIFEST}
    assert {"hook", "settings", "skill"} <= groups
    dests = {t.dest for t in governance.GOVERNANCE_MANIFEST}
    assert any(d.endswith("dorian_preflight_veto.py") for d in dests)
    assert any(d.endswith("dorian_loop_preflight.py") for d in dests)
