"""First-run setup and DCS installation detection."""
from __future__ import annotations

import json
import os
import re
import winreg
from typing import Dict, List, Optional, Set

from config import DCS_SAVED_GAMES, PROJECT_DIR

SETTINGS_PATH = os.path.join(PROJECT_DIR, "settings.json")


def _read_settings() -> Dict[str, object]:
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_settings(settings: Dict[str, object]) -> None:
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def detect_dcs_install_dir() -> Optional[str]:
    """Try to find DCS World installation directory automatically.

    Checks:
    1. Saved settings from a previous run
    2. Steam registry entries
    3. DCS standalone registry entries
    4. Common installation paths
    """
    # Check saved settings first
    settings = _read_settings()
    saved_path = settings.get("dcs_install_dir")
    if isinstance(saved_path, str) and os.path.isdir(saved_path):
        return saved_path

    # Try Steam registry
    steam_path = _find_steam_dcs()
    if steam_path:
        return steam_path

    # Try DCS standalone registry
    standalone_path = _find_standalone_dcs()
    if standalone_path:
        return standalone_path

    # Try common paths
    common_paths = [
        r"C:\Program Files\Eagle Dynamics\DCS World",
        r"C:\Program Files\Eagle Dynamics\DCS World OpenBeta",
        r"D:\SteamLibrary\steamapps\common\DCSWorld",
        r"E:\SteamLibrary\steamapps\common\DCSWorld",
        r"C:\SteamLibrary\steamapps\common\DCSWorld",
    ]
    for path in common_paths:
        if os.path.isdir(path) and _is_dcs_dir(path):
            return path

    return None


def _find_steam_dcs() -> Optional[str]:
    """Find DCS via Steam registry and library folders."""
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")
        steam_path = winreg.QueryValueEx(key, "InstallPath")[0]
        winreg.CloseKey(key)
    except (OSError, FileNotFoundError):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")
            steam_path = winreg.QueryValueEx(key, "InstallPath")[0]
            winreg.CloseKey(key)
        except (OSError, FileNotFoundError):
            return None

    # Check main Steam directory
    dcs_path = os.path.join(steam_path, "steamapps", "common", "DCSWorld")
    if os.path.isdir(dcs_path) and _is_dcs_dir(dcs_path):
        return dcs_path

    # Parse libraryfolders.vdf for additional Steam library locations
    vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    if os.path.exists(vdf_path):
        try:
            with open(vdf_path, encoding="utf-8") as f:
                content = f.read()
            # Extract all "path" values
            paths = re.findall(r'"path"\s+"([^"]+)"', content)
            for lib_path in paths:
                candidate = os.path.join(lib_path, "steamapps", "common", "DCSWorld")
                if os.path.isdir(candidate) and _is_dcs_dir(candidate):
                    return candidate
        except IOError:
            pass

    return None


def _find_standalone_dcs() -> Optional[str]:
    """Find DCS standalone via registry."""
    registry_paths = [
        r"SOFTWARE\Eagle Dynamics\DCS World",
        r"SOFTWARE\Eagle Dynamics\DCS World OpenBeta",
        r"SOFTWARE\WOW6432Node\Eagle Dynamics\DCS World",
        r"SOFTWARE\WOW6432Node\Eagle Dynamics\DCS World OpenBeta",
    ]
    for reg_path in registry_paths:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
            install_path = winreg.QueryValueEx(key, "Path")[0]
            winreg.CloseKey(key)
            if os.path.isdir(install_path) and _is_dcs_dir(install_path):
                return install_path
        except (OSError, FileNotFoundError):
            continue
    return None


def _is_dcs_dir(path: str) -> bool:
    """Verify this is actually a DCS installation directory."""
    return (
        os.path.exists(os.path.join(path, "bin", "DCS.exe"))
        or os.path.exists(os.path.join(path, "bin-mt", "DCS.exe"))
        or os.path.exists(os.path.join(path, "Mods", "aircraft"))
    )


def save_dcs_install_dir(path: str) -> None:
    """Save the DCS install directory to settings."""
    settings = _read_settings()
    settings["dcs_install_dir"] = path
    _save_settings(settings)


def get_selected_aircraft() -> Optional[str]:
    """Get the currently selected aircraft from settings."""
    settings = _read_settings()
    aircraft = settings.get("aircraft")
    return aircraft if isinstance(aircraft, str) else None


def save_selected_aircraft(aircraft: str) -> None:
    """Save the selected aircraft to settings."""
    settings = _read_settings()
    settings["aircraft"] = aircraft
    _save_settings(settings)


def list_installed_aircraft(
    dcs_install_dir: str,
    dcs_saved_games: str = DCS_SAVED_GAMES,
) -> List[str]:
    """List all installed aircraft modules from both install dir and saved games.

    Scans:
    1. DCS_INSTALL_DIR/Mods/aircraft/ (official + purchased modules)
    2. DCS_SAVED_GAMES/Mods/aircraft/ (community mods)
    """
    aircraft: Set[str] = set()

    # Official modules
    install_mods = os.path.join(dcs_install_dir, "Mods", "aircraft")
    if os.path.isdir(install_mods):
        for name in os.listdir(install_mods):
            full = os.path.join(install_mods, name)
            if os.path.isdir(full):
                aircraft.add(name)

    # Community mods in saved games
    saved_mods = os.path.join(dcs_saved_games, "Mods", "aircraft")
    if os.path.isdir(saved_mods):
        for name in os.listdir(saved_mods):
            full = os.path.join(saved_mods, name)
            if os.path.isdir(full):
                aircraft.add(name)

    return sorted(aircraft)


def resolve_unit_type_to_module(
    dcs_install_dir: str, unit_type: str,
    dcs_saved_games: str = DCS_SAVED_GAMES,
) -> Optional[str]:
    """Resolve a DCS unit type name to an aircraft module folder name.

    DCS.getPlayerUnitType() returns names like 'FA-18C_hornet', but the module
    folder is 'FA-18C'. This function finds the matching module.

    Tries:
    1. Exact match (unit_type == module folder name)
    2. Module folder is a prefix of the unit type (FA-18C matches FA-18C_hornet)
    3. Fuzzy: strip common suffixes and compare
    """
    installed = list_installed_aircraft(dcs_install_dir, dcs_saved_games)

    # Exact match
    if unit_type in installed:
        return unit_type

    # Module is a prefix of unit_type (e.g., "FA-18C" is prefix of "FA-18C_hornet")
    # Pick the longest matching prefix
    best: Optional[str] = None
    for module in installed:
        if unit_type.startswith(module) and (best is None or len(module) > len(best)):
            best = module
    if best:
        return best

    # Unit type is a prefix of module (e.g., unit type "F-14" matches "F-14A-135-GR")
    for module in installed:
        if module.startswith(unit_type):
            return module

    return None


def get_aircraft_input_name(dcs_install_dir: str, aircraft_module: str) -> Optional[str]:
    """Find the Input folder name for an aircraft module.

    E.g., FA-18C module has Input/FA-18C/ subfolder.
    """
    input_dir = os.path.join(dcs_install_dir, "Mods", "aircraft", aircraft_module, "Input")
    if not os.path.isdir(input_dir):
        return None
    for name in os.listdir(input_dir):
        if os.path.isdir(os.path.join(input_dir, name)):
            return name
    return None


def find_bios_json(dcs_saved_games: str, aircraft_module: str) -> Optional[str]:
    """Find the DCS-BIOS JSON file for an aircraft module.

    Looks in Scripts/DCS-BIOS/doc/json/ for a file matching the module name.
    Tries exact match first, then case-insensitive search.
    """
    json_dir = os.path.join(dcs_saved_games, "Scripts", "DCS-BIOS", "doc", "json")
    if not os.path.isdir(json_dir):
        return None

    # Try common naming patterns
    candidates = [
        f"{aircraft_module}.json",  # exact match (e.g. "FA-18C.json")
    ]

    # List all JSON files for fuzzy matching
    try:
        available = os.listdir(json_dir)
    except OSError:
        return None

    for candidate in candidates:
        full = os.path.join(json_dir, candidate)
        if os.path.isfile(full):
            return full

    # Case-insensitive search and partial matching
    module_lower = aircraft_module.lower().replace("-", "").replace("_", "")
    for filename in available:
        if not filename.endswith(".json"):
            continue
        stem = filename[:-5].lower().replace("-", "").replace("_", "")
        if stem == module_lower or module_lower in stem or stem in module_lower:
            return os.path.join(json_dir, filename)

    return None


def get_aircraft_saved_name(
    dcs_saved_games: str, aircraft_module: str,
) -> Optional[str]:
    """Find the Config/Input folder name for user keybind customizations.

    The saved games folder name can differ from the module name
    (e.g., module "FA-18C" -> saved games "FA-18C_hornet").
    """
    input_dir = os.path.join(dcs_saved_games, "Config", "Input")
    if not os.path.isdir(input_dir):
        return None

    # Exact match first
    if os.path.isdir(os.path.join(input_dir, aircraft_module)):
        return aircraft_module

    # Search for folder that starts with the module name
    try:
        for name in os.listdir(input_dir):
            if not os.path.isdir(os.path.join(input_dir, name)):
                continue
            if name.startswith(aircraft_module):
                return name
    except OSError:
        pass

    return None
