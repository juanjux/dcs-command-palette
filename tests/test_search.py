import os
import time

from commands import Command, CommandSource, load_all_commands, _control_to_command
from controls import load_controls
from search import search
from usage_tracker import UsageTracker

# Resolve the FA-18C_hornet.json path relative to the project
_DCS_SAVED_GAMES = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FA18C_JSON = os.path.join(
    _DCS_SAVED_GAMES, "Scripts", "DCS-BIOS", "doc", "json", "FA-18C_hornet.json"
)


def _make_tracker(tmp_path: object) -> UsageTracker:
    """Create a temporary usage tracker."""
    path = os.path.join(str(tmp_path), "test_usage.json")
    return UsageTracker(path=path)


def test_search_master_arm(tmp_path: object) -> None:
    controls = load_controls(_FA18C_JSON)
    usage = _make_tracker(tmp_path)
    results = search("master arm", controls, usage)
    identifiers = [r.identifier for r in results]
    assert "MASTER_ARM_SW" in identifiers
    assert identifiers[0] == "MASTER_ARM_SW"  # Should be first


def test_search_typo(tmp_path: object) -> None:
    controls = load_controls(_FA18C_JSON)
    usage = _make_tracker(tmp_path)
    results = search("mstr arm", controls, usage)
    identifiers = [r.identifier for r in results]
    assert "MASTER_ARM_SW" in identifiers


def test_search_gear(tmp_path: object) -> None:
    controls = load_controls(_FA18C_JSON)
    usage = _make_tracker(tmp_path)
    results = search("gear", controls, usage)
    identifiers = [r.identifier for r in results]
    assert any("GEAR" in i for i in identifiers)


def test_search_brightness(tmp_path: object) -> None:
    controls = load_controls(_FA18C_JSON)
    usage = _make_tracker(tmp_path)
    results = search("brt", controls, usage)
    identifiers = [r.identifier for r in results]
    assert any("BRT" in i for i in identifiers)


def test_search_empty_returns_nothing_initially(tmp_path: object) -> None:
    controls = load_controls(_FA18C_JSON)
    usage = _make_tracker(tmp_path)
    results = search("", controls, usage)
    # No usage data yet, so empty query returns nothing
    assert len(results) == 0


def test_search_empty_returns_most_used(tmp_path: object) -> None:
    controls = load_controls(_FA18C_JSON)
    usage = _make_tracker(tmp_path)
    # Record some usage
    usage.record_use("MASTER_ARM_SW")
    usage.record_use("MASTER_ARM_SW")
    usage.record_use("GEAR_LEVER")
    results = search("", controls, usage)
    identifiers = [r.identifier for r in results]
    assert "MASTER_ARM_SW" in identifiers
    assert identifiers[0] == "MASTER_ARM_SW"  # Most used should be first


def test_search_respects_max_results(tmp_path: object) -> None:
    from config import MAX_RESULTS
    controls = load_controls(_FA18C_JSON)
    usage = _make_tracker(tmp_path)
    results = search("switch", controls, usage)
    assert len(results) <= MAX_RESULTS


def test_search_prefix_bonus(tmp_path: object) -> None:
    controls = load_controls(_FA18C_JSON)
    usage = _make_tracker(tmp_path)
    results = search("AMPCD", controls, usage)
    identifiers = [r.identifier for r in results]
    # All AMPCD_ controls should rank highly
    assert identifiers[0].startswith("AMPCD")


def test_bios_category_not_misleading() -> None:
    """Category shown in the palette should not be completely unrelated to the control.

    Regression: FLAP_SW was showing category "BIOS: Select Jettison Button" because
    DCS-BIOS groups controls by physical panel, and the panel is named after a different
    control. The displayed category should be meaningful to the user.
    """
    controls = load_controls(_FA18C_JSON)
    flap = [c for c in controls if c.identifier == "FLAP_SW"][0]
    cmd = _control_to_command(flap)

    # The category should NOT contain completely unrelated control names
    cat_lower = cmd.category.lower()
    assert "jettison" not in cat_lower, (
        f"FLAP_SW category '{cmd.category}' is misleading — "
        f"it references an unrelated control"
    )
