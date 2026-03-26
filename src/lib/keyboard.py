"""Parse DCS keyboard shortcuts from Lua input definition files."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

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
    value_down: Optional[float] = None  # DCS value_down for position mapping


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


_VALUE_DOWN_RE = re.compile(r"value_down\s*=\s*([\-\d.]+)")


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

        # Extract value_down from the full block around this match.
        # Expand to find the enclosing {...} in the original content.
        block_start = lua_content.rfind("{", 0, m.start() + 1)
        # Find the matching closing brace (may be after the regex match end)
        block_end = m.end()
        brace_depth = 0
        for i in range(block_start, len(lua_content)):
            if lua_content[i] == "{":
                brace_depth += 1
            elif lua_content[i] == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    block_end = i + 1
                    break
        full_block = lua_content[block_start:block_end]

        value_down: Optional[float] = None
        vd_m = _VALUE_DOWN_RE.search(full_block)
        if vd_m:
            try:
                value_down = float(vd_m.group(1))
            except ValueError:
                pass

        results.append(KeyboardEntry(
            name=name, category=category, key_combo=combo, value_down=value_down,
        ))

    return results


@dataclass
class _DiffEntry:
    """A single entry from a Keyboard.diff.lua file."""
    name: str
    added_combo: str  # new key combo, or "" if only removing
    is_removal: bool  # True if this entry removes a binding (with no replacement)


# Simple Lua value type for the table parser
LuaValue = Any  # str, int, float, bool, None, or Dict/List


def _parse_lua_table(content: str) -> Dict[str, LuaValue]:
    """Parse a Lua table literal into a Python dict.

    Handles the subset of Lua used in DCS diff files:
    - String keys: ["key"] = value
    - Integer keys: [1] = value
    - String values: "text"
    - Nested tables: { ... }
    - Ignores: 'local diff =', 'return diff', comments
    """
    pos = 0
    length = len(content)

    def skip_ws() -> None:
        nonlocal pos
        while pos < length:
            if content[pos] in ' \t\r\n':
                pos += 1
            elif content[pos:pos + 2] == '--':
                # Skip Lua comment to end of line
                while pos < length and content[pos] != '\n':
                    pos += 1
            else:
                break

    def parse_string() -> str:
        nonlocal pos
        quote = content[pos]
        pos += 1  # skip opening quote
        start = pos
        while pos < length and content[pos] != quote:
            if content[pos] == '\\':
                pos += 1  # skip escaped char
            pos += 1
        result = content[start:pos]
        pos += 1  # skip closing quote
        return result

    def parse_number() -> LuaValue:
        nonlocal pos
        start = pos
        if content[pos] == '-':
            pos += 1
        while pos < length and (content[pos].isdigit() or content[pos] == '.'):
            pos += 1
        num_str = content[start:pos]
        if '.' in num_str:
            return float(num_str)
        return int(num_str)

    def parse_value() -> LuaValue:
        nonlocal pos
        skip_ws()
        if pos >= length:
            return None

        ch = content[pos]

        if ch == '{':
            return parse_table()
        elif ch == '"':
            return parse_string()
        elif ch == '-' or ch.isdigit():
            return parse_number()
        elif content[pos:pos + 4] == 'true':
            pos += 4
            return True
        elif content[pos:pos + 5] == 'false':
            pos += 5
            return False
        elif content[pos:pos + 3] == 'nil':
            pos += 3
            return None
        return None

    def parse_table() -> Dict[str, LuaValue]:
        nonlocal pos
        pos += 1  # skip '{'
        result: Dict[str, LuaValue] = {}
        auto_index = 1

        while pos < length:
            skip_ws()
            if pos >= length:
                break
            if content[pos] == '}':
                pos += 1
                break

            # Check for key = value
            if content[pos] == '[':
                pos += 1  # skip '['
                skip_ws()
                if content[pos] == '"':
                    key: str = parse_string()
                else:
                    # Integer key like [1]
                    num_start = pos
                    while pos < length and content[pos].isdigit():
                        pos += 1
                    key = content[num_start:pos]
                skip_ws()
                pos += 1  # skip ']'
                skip_ws()
                pos += 1  # skip '='
                val = parse_value()
                result[key] = val
            elif content[pos] == '{':
                # Anonymous table entry (array-style)
                val = parse_table()
                result[str(auto_index)] = val
                auto_index += 1
            else:
                # Skip unexpected characters
                pos += 1
                continue

            skip_ws()
            if pos < length and content[pos] == ',':
                pos += 1

        return result

    # Find the first '{' that starts the main table
    first_brace = content.find('{')
    if first_brace == -1:
        return {}
    pos = first_brace
    result = parse_table()
    return result


def parse_diff_lua(content: str) -> List[_DiffEntry]:
    """Parse a Keyboard.diff.lua file into diff entries.

    The file contains a Lua table with keyDiffs, where each entry has:
    - ["name"] = "Command Name"
    - optionally ["added"] = { {["key"] = "X", ["reformers"] = {...}} }
    - optionally ["removed"] = { {["key"] = "Y"} }
    """
    results: List[_DiffEntry] = []

    data = _parse_lua_table(content)
    key_diffs = data.get("keyDiffs", {})
    if not isinstance(key_diffs, dict):
        return results

    for _hash_key, entry in key_diffs.items():
        if not isinstance(entry, dict):
            continue

        name = entry.get("name", "")
        if not isinstance(name, str) or not name:
            continue

        # Extract added combo
        added_combo = ""
        added = entry.get("added", {})
        if isinstance(added, dict):
            # Get first added binding (key "1")
            first_added = added.get("1", {})
            if isinstance(first_added, dict):
                key = first_added.get("key", "")
                reformers_table = first_added.get("reformers", {})
                reformers_list: List[str] = []
                if isinstance(reformers_table, dict):
                    for i in sorted(reformers_table.keys(), key=lambda k: int(k) if k.isdigit() else 0):
                        val = reformers_table[i]
                        if isinstance(val, str):
                            reformers_list.append(val)
                if isinstance(key, str) and key:
                    added_combo = _build_combo_string(key, reformers_list)

        # Check for removed section
        has_removed = "removed" in entry and isinstance(entry["removed"], dict)

        is_removal = has_removed and not added_combo

        results.append(_DiffEntry(name=name, added_combo=added_combo, is_removal=is_removal))

    return results


def _apply_diff(
    entries: List[KeyboardEntry],
    diff_entries: List[_DiffEntry],
) -> List[KeyboardEntry]:
    """Apply diff overrides to a list of keyboard entries.

    Matches by name (case-insensitive). For each diff entry:
    - If it has an added_combo: update the matching entry's key_combo
    - If it's a pure removal: clear the matching entry's key_combo
    """
    by_name: Dict[str, KeyboardEntry] = {e.name.lower(): e for e in entries}

    for diff in diff_entries:
        key = diff.name.lower()
        if key in by_name:
            if diff.is_removal:
                by_name[key].key_combo = ""
            elif diff.added_combo:
                by_name[key].key_combo = diff.added_combo

    return entries


def load_keyboard_entries(
    dcs_install_dir: str,
    aircraft_module: str = "FA-18C",
    aircraft_input_name: str = "FA-18C",
    dcs_saved_games: Optional[str] = None,
    aircraft_saved_name: Optional[str] = None,
) -> List[KeyboardEntry]:
    """Load all keyboard shortcut entries for an aircraft.

    Merges three layers:
    1. Common keyboard bindings (from DCS install)
    2. Aircraft-specific defaults (from DCS install)
    3. User customizations from Keyboard.diff.lua (from saved games)
    """
    entries: List[KeyboardEntry] = []
    seen_names: Set[str] = set()

    # Layers 1 & 2: default bindings from DCS install dir
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

    # Layer 3: user customizations from saved games
    if dcs_saved_games and aircraft_saved_name:
        diff_path = os.path.join(
            dcs_saved_games, "Config", "Input", aircraft_saved_name,
            "keyboard", "Keyboard.diff.lua",
        )
        if os.path.exists(diff_path):
            with open(diff_path, encoding="utf-8", errors="replace") as f:
                diff_content = f.read()
            diff_entries = parse_diff_lua(diff_content)
            entries = _apply_diff(entries, diff_entries)

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
