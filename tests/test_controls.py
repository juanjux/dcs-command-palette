import os

from src.bios.controls import Control, load_controls

# Resolve the FA-18C_hornet.json path relative to the project
_DCS_SAVED_GAMES = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FA18C_JSON = os.path.join(
    _DCS_SAVED_GAMES, "Scripts", "DCS-BIOS", "doc", "json", "FA-18C_hornet.json"
)


def test_load_controls_count() -> None:
    controls = load_controls(_FA18C_JSON)
    assert len(controls) == 298, f"Expected 298 actionable controls, got {len(controls)}"


def test_all_controls_have_identifier() -> None:
    controls = load_controls(_FA18C_JSON)
    for ctrl in controls:
        assert ctrl.identifier, "Control must have an identifier"
        assert ctrl.description, "Control must have a description"
        assert ctrl.category, "Control must have a category"
        assert ctrl.search_text, "Control must have search_text"


def test_control_types_are_known() -> None:
    known_types = {
        "limited_dial", "selector", "action", "toggle_switch",
        "emergency_parking_brake", "mission_computer_switch",
        "analog_dial", "radio", "fixed_step_dial",
    }
    controls = load_controls(_FA18C_JSON)
    for ctrl in controls:
        assert ctrl.control_type in known_types, (
            f"Unknown control type '{ctrl.control_type}' for {ctrl.identifier}"
        )


def test_position_labels_parsed() -> None:
    controls = load_controls(_FA18C_JSON)
    by_id = {c.identifier: c for c in controls}

    # APU_CONTROL_SW should have {0: 'off', 1: 'on'}
    apu = by_id.get("APU_CONTROL_SW")
    assert apu is not None
    assert apu.position_labels is not None
    assert apu.position_labels[0] == "off"
    assert apu.position_labels[1] == "on"


def test_toggle_flags() -> None:
    controls = load_controls(_FA18C_JSON)
    by_id = {c.identifier: c for c in controls}

    # APU_CONTROL_SW has a TOGGLE action
    apu = by_id.get("APU_CONTROL_SW")
    assert apu is not None
    assert apu.has_toggle is True
    assert apu.has_fixed_step is True
    assert apu.max_value == 1


def test_limited_dial_properties() -> None:
    controls = load_controls(_FA18C_JSON)
    by_id = {c.identifier: c for c in controls}

    brt = by_id.get("AMPCD_BRT_CTL")
    assert brt is not None
    assert brt.control_type == "limited_dial"
    assert brt.has_variable_step is True
    assert brt.suggested_step == 3200
    assert brt.max_value == 65535


def test_radio_has_set_string() -> None:
    controls = load_controls(_FA18C_JSON)
    by_id = {c.identifier: c for c in controls}

    comm1 = by_id.get("COMM1")
    assert comm1 is not None
    assert comm1.has_set_string is True
    assert comm1.control_type == "radio"


def test_search_text_includes_identifier_and_description() -> None:
    controls = load_controls(_FA18C_JSON)
    by_id = {c.identifier: c for c in controls}

    gear = by_id.get("GEAR_LEVER")
    assert gear is not None
    assert "gear" in gear.search_text
    assert "lever" in gear.search_text
