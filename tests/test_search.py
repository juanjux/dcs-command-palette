import os
import time

from src.palette.commands import Command, CommandSource, load_all_commands, _control_to_command
from src.bios.controls import load_controls
from src.lib.search import search
from src.palette.usage import UsageTracker

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
    from src.config.settings import MAX_RESULTS
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


def test_search_multi_word_all_tokens_match(tmp_path: object) -> None:
    """Searching 'radar off' should prioritize results containing both words.

    Regression: 'radar off' was showing unrelated OFF results because WRatio
    scored them equally to results with both 'radar' and 'off'.
    """
    controls = load_controls(_FA18C_JSON)
    usage = _make_tracker(tmp_path)
    results = search("radar off", controls, usage)
    # The top result should contain both 'radar' and 'off' in some form
    if results:
        top = results[0]
        text = f"{top.identifier} {top.description}".lower()
        assert "radar" in text, (
            f"Top result for 'radar off' should contain 'radar', got: {top.identifier} - {top.description}"
        )


def test_search_multi_word_with_category(tmp_path: object) -> None:
    """Searching 'bright right' should prioritize Right DDI brightness controls.

    The category 'Right DDI' should boost results containing both 'bright' and 'right'.
    """
    controls = load_controls(_FA18C_JSON)
    commands = [_control_to_command(c) for c in controls]
    usage = _make_tracker(tmp_path)
    results = search("bright right", commands, usage)
    if results:
        top = results[0]
        text = f"{top.identifier} {top.category}".lower()
        assert "right" in text, (
            f"Top result for 'bright right' should be from Right DDI, got: {top.identifier} ({top.category})"
        )


def test_position_labels_order_rotary() -> None:
    """Rotary selectors use ascending value_down order.

    ECM Mode Switch: OFF(0.0) → STBY(0.1) → BIT(0.2) → REC(0.3) → XMIT(0.4)
    DCS-BIOS position 0=OFF, 4=XMIT.
    """
    commands = load_all_commands(
        dcs_install_dir=r"D:\SteamLibrary\steamapps\common\DCSWorld",
        aircraft_module="FA-18C", aircraft_input_name="FA-18C",
        controls_json_path=_FA18C_JSON,
    )
    ecm = [c for c in commands if c.identifier == "ECM_MODE_SW"][0]
    assert ecm.position_labels is not None
    assert ecm.position_labels[0] == "OFF"
    assert ecm.position_labels[1] == "STBY"
    assert ecm.position_labels[2] == "BIT"
    assert ecm.position_labels[3] == "REC"
    assert ecm.position_labels[4] == "XMIT"


def test_position_labels_order_toggle() -> None:
    """Toggle switches use ascending value_down order.

    FLAP Switch: FULL(-1.0) → HALF(0.0) → AUTO(1.0)
    DCS-BIOS position 0=FULL (bottom), 1=HALF (middle), 2=AUTO (top).
    """
    commands = load_all_commands(
        dcs_install_dir=r"D:\SteamLibrary\steamapps\common\DCSWorld",
        aircraft_module="FA-18C", aircraft_input_name="FA-18C",
        controls_json_path=_FA18C_JSON,
    )
    flap = [c for c in commands if c.identifier == "FLAP_SW"][0]
    assert flap.position_labels is not None
    assert flap.position_labels[0] == "FULL"
    assert flap.position_labels[1] == "HALF"
    assert flap.position_labels[2] == "AUTO"


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
