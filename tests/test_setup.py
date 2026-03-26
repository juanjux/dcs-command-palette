"""Tests for setup.py helpers."""
import os

from setup import (
    find_bios_json,
    get_aircraft_saved_name,
    resolve_unit_type_to_module,
)

_DCS_SAVED_GAMES = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DCS_INSTALL_DIR = os.environ.get(
    "DCS_INSTALL_DIR", r"D:\SteamLibrary\steamapps\common\DCSWorld"
)


def test_resolve_unit_type_exact_match() -> None:
    """Module folder name that matches exactly should be returned."""
    result = resolve_unit_type_to_module(_DCS_INSTALL_DIR, "FA-18C")
    assert result == "FA-18C"


def test_resolve_unit_type_hornet_suffix() -> None:
    """DCS unit type 'FA-18C_hornet' should resolve to module 'FA-18C'."""
    result = resolve_unit_type_to_module(_DCS_INSTALL_DIR, "FA-18C_hornet")
    assert result == "FA-18C"


def test_resolve_unit_type_unknown() -> None:
    """Unknown unit type should return None."""
    result = resolve_unit_type_to_module(_DCS_INSTALL_DIR, "NONEXISTENT_PLANE_12345")
    assert result is None


def test_find_bios_json_fa18c() -> None:
    """Should find FA-18C_hornet.json for module FA-18C."""
    result = find_bios_json(_DCS_SAVED_GAMES, "FA-18C")
    assert result is not None
    assert "FA-18C_hornet.json" in result


def test_get_aircraft_saved_name_fa18c() -> None:
    """FA-18C module should find FA-18C_hornet in saved games."""
    result = get_aircraft_saved_name(_DCS_SAVED_GAMES, "FA-18C")
    assert result == "FA-18C_hornet"
