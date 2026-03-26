"""Parse DCS keyboard shortcuts from Lua input definition files."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

# Maps DCS key names to pynput-compatible names
_KEY_MAP: Dict[str, str] = {
    "LCtrl": "ctrl_l", "RCtrl": "ctrl_r",
    "LAlt": "alt_l", "RAlt": "alt_r",
    "LShift": "shift_l", "RShift": "shift_r",
    "LWin": "cmd_l", "RWin": "cmd_r",
    "Space": "space", "Enter": "enter", "Tab": "tab",
    "Back": "backspace", "Backspace": "backspace",
    "Delete": "delete", "Escape": "escape", "Pause": "pause",
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
    "Home": "home", "End": "end", "PgUp": "page_up", "PgDn": "page_down",
    "Insert": "insert",
    "Num+": "num_add", "Num-": "num_subtract", "Num*": "num_multiply",
    "Num/": "num_divide", "Num.": "num_decimal", "NumEnter": "num_enter",
    "Num0": "num0", "Num1": "num1", "Num2": "num2", "Num3": "num3",
    "Num4": "num4", "Num5": "num5", "Num6": "num6", "Num7": "num7",
    "Num8": "num8", "Num9": "num9",
}


@dataclass
class KeyboardEntry:
    """A raw keyboard shortcut entry parsed from DCS Lua files."""
    name: str
    category: str
    key_combo: str  # e.g. "LAlt + LCtrl + S"


# Regex to extract command entries from Lua files
_ENTRY_RE = re.compile(
    r"\{[^}]*?"
    r"(?:combos\s*=\s*\{\{key\s*=\s*'([^']+)'"  # group 1: key
    r"(?:,\s*reformers\s*=\s*\{([^}]*)\})?"  # group 2: reformers (optional)
    r"\}\})?"  # close combos
    r"[^}]*?"
    r"name\s*=\s*_\('([^']+)'\)"  # group 3: name
    r"[^}]*?"
    r"category\s*=\s*(?:_\('([^']+)'\)|\{_\('([^']+)'\))"  # group 4 or 5: category
    r"[^}]*?\}",
    re.DOTALL,
)


def _parse_reformers(reformers_str: str) -> List[str]:
    return re.findall(r"'([^']+)'", reformers_str)


def _build_combo_string(key: str, reformers: List[str]) -> str:
    parts = reformers + [key]
    return " + ".join(parts)


def parse_lua_commands(lua_content: str) -> List[KeyboardEntry]:
    """Extract keyboard entries from Lua input file content."""
    results: List[KeyboardEntry] = []

    for m in _ENTRY_RE.finditer(lua_content):
        key = m.group(1) or ""
        reformers_raw = m.group(2) or ""
        name = m.group(3)
        category = m.group(4) or m.group(5) or ""

        reformers = _parse_reformers(reformers_raw) if reformers_raw else []
        combo = _build_combo_string(key, reformers) if key else ""

        results.append(KeyboardEntry(name=name, category=category, key_combo=combo))

    return results


def load_keyboard_entries(
    dcs_install_dir: str,
    aircraft_module: str = "FA-18C",
    aircraft_input_name: str = "FA-18C",
) -> List[KeyboardEntry]:
    """Load all keyboard shortcut entries for an aircraft from the DCS install directory."""
    entries: List[KeyboardEntry] = []
    seen_names: Set[str] = set()

    files_to_parse: List[str] = [
        os.path.join(dcs_install_dir, "Config", "Input", "Aircrafts", "common_keyboard_binding.lua"),
        os.path.join(dcs_install_dir, "Config", "Input", "Supercarrier", "Input", "keyboard.lua"),
        os.path.join(dcs_install_dir, "Mods", "aircraft", aircraft_module, "Input",
                     aircraft_input_name, "keyboard", "default.lua"),
    ]

    for filepath in files_to_parse:
        if not os.path.exists(filepath):
            continue

        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read()

        for entry in parse_lua_commands(content):
            if entry.name.lower() in seen_names:
                continue
            seen_names.add(entry.name.lower())
            entries.append(entry)

    return entries


def normalize_key(dcs_key: str) -> str:
    """Convert a DCS key name to a pynput-compatible name."""
    key = dcs_key.strip()
    if key in _KEY_MAP:
        return _KEY_MAP[key]
    if re.match(r"^F\d+$", key):
        return key.lower()
    if len(key) == 1:
        return key.lower()
    return key.lower()


def parse_combo(combo_str: str) -> List[str]:
    """Parse 'LAlt + LCtrl + S' into ['alt_l', 'ctrl_l', 's']."""
    if not combo_str:
        return []
    parts = [p.strip() for p in combo_str.split(" + ") if p.strip()]
    return [normalize_key(p) for p in parts]
