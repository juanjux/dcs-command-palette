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


def test_bios_category_uses_panel_name() -> None:
    """Category should use the original DCS-BIOS panel name.

    The panel name is the physical cockpit location, which is useful context
    even when the panel is named after a different control on the same panel.
    The description (shown as primary text) is always the control's own name.
    """
    controls = load_controls(_FA18C_JSON)
    flap = [c for c in controls if c.identifier == "FLAP_SW"][0]
    cmd = _control_to_command(flap)

    # Category is the raw DCS-BIOS panel name
    assert cmd.category == "Select Jettison Button"
    # Description is the control's own user-friendly name (shown in white)
    assert cmd.description == "FLAP Switch"
    # Identifier is the DCS-BIOS ID (shown in gray only if enabled)
    assert cmd.identifier == "FLAP_SW"
