"""Tests for keyboard command parsing including user diff overrides."""
from keyboard_commands import (
    KeyboardEntry,
    _DiffEntry,
    _apply_diff,
    _build_combo_string,
    normalize_key,
    parse_combo,
    parse_diff_lua,
    parse_lua_commands,
)


def test_parse_lua_commands_basic() -> None:
    lua = """
    {combos = {{key = 'G', reformers = {'LCtrl'}}}, name = _('Landing Gear'), category = _('Flight')},
    """
    entries = parse_lua_commands(lua)
    assert len(entries) == 1
    assert entries[0].name == "Landing Gear"
    assert entries[0].category == "Flight"
    assert entries[0].key_combo == "LCtrl + G"


def test_parse_lua_commands_no_combo() -> None:
    lua = """
    {name = _('Eject'), category = _('Flight')},
    """
    entries = parse_lua_commands(lua)
    assert len(entries) == 1
    assert entries[0].key_combo == ""


def test_build_combo_string() -> None:
    assert _build_combo_string("G", ["LCtrl", "LAlt"]) == "LCtrl + LAlt + G"
    assert _build_combo_string("Space", []) == "Space"


def test_normalize_key() -> None:
    assert normalize_key("LCtrl") == "ctrl_l"
    assert normalize_key("Space") == "space"
    assert normalize_key("F1") == "f1"
    assert normalize_key("A") == "a"


def test_parse_combo() -> None:
    result = parse_combo("LAlt + LCtrl + S")
    assert result == ["alt_l", "ctrl_l", "s"]
    assert parse_combo("") == []


# --- Diff parser tests ---

SAMPLE_DIFF = """\
local diff = {
	["keyDiffs"] = {
		["d3002pnilu3002cd13vd1vpnilvu0"] = {
			["name"] = "Gun Trigger - SECOND DETENT (Press to shoot)",
			["removed"] = {
				[1] = {
					["key"] = "Space",
				},
			},
		},
		["d3018pnilu3018cd40vd1vpnilvu0"] = {
			["added"] = {
				[1] = {
					["key"] = "S",
					["reformers"] = {
						[1] = "LAlt",
					},
				},
			},
			["name"] = "Warning Tone Silence Button",
		},
	},
}
return diff
"""


def test_parse_diff_lua_removal() -> None:
    diffs = parse_diff_lua(SAMPLE_DIFF)
    gun = [d for d in diffs if "Gun Trigger" in d.name]
    assert len(gun) == 1
    assert gun[0].is_removal is True
    assert gun[0].added_combo == ""


def test_parse_diff_lua_added() -> None:
    diffs = parse_diff_lua(SAMPLE_DIFF)
    warn = [d for d in diffs if "Warning Tone" in d.name]
    assert len(warn) == 1
    assert warn[0].is_removal is False
    assert warn[0].added_combo == "LAlt + S"


def test_apply_diff_removal() -> None:
    entries = [
        KeyboardEntry(name="Gun Trigger - SECOND DETENT (Press to shoot)", category="Weapons", key_combo="Space"),
        KeyboardEntry(name="Other Command", category="Flight", key_combo="G"),
    ]
    diffs = [_DiffEntry(name="Gun Trigger - SECOND DETENT (Press to shoot)", added_combo="", is_removal=True)]
    result = _apply_diff(entries, diffs)
    assert result[0].key_combo == ""
    assert result[1].key_combo == "G"  # unchanged


def test_apply_diff_rebind() -> None:
    entries = [
        KeyboardEntry(name="Warning Tone Silence Button", category="Systems", key_combo=""),
    ]
    diffs = [_DiffEntry(name="Warning Tone Silence Button", added_combo="LAlt + S", is_removal=False)]
    result = _apply_diff(entries, diffs)
    assert result[0].key_combo == "LAlt + S"


def test_apply_diff_case_insensitive() -> None:
    entries = [
        KeyboardEntry(name="Landing Gear", category="Flight", key_combo="G"),
    ]
    diffs = [_DiffEntry(name="landing gear", added_combo="LCtrl + G", is_removal=False)]
    result = _apply_diff(entries, diffs)
    assert result[0].key_combo == "LCtrl + G"
