"""Simulate keyboard input to send DCS keyboard shortcuts."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Union

from pynput.keyboard import Controller, Key  # type: ignore[import-untyped]

from keyboard_commands import parse_combo

_keyboard = Controller()

# Map string key names to pynput Key objects
_SPECIAL_KEYS: Dict[str, Any] = {
    "ctrl_l": Key.ctrl_l, "ctrl_r": Key.ctrl_r,
    "alt_l": Key.alt_l, "alt_r": Key.alt_r,
    "shift_l": Key.shift_l, "shift_r": Key.shift_r,
    "cmd_l": Key.cmd_l, "cmd_r": Key.cmd_r,
    "space": Key.space, "enter": Key.enter, "tab": Key.tab,
    "backspace": Key.backspace, "delete": Key.delete,
    "escape": Key.esc, "pause": Key.pause,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "home": Key.home, "end": Key.end,
    "page_up": Key.page_up, "page_down": Key.page_down,
    "insert": Key.insert,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
    "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
    "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
    "num_add": Key.num_lock,  # pynput doesn't have numpad ops directly
}


def _resolve_key(name: str) -> Any:
    """Convert a normalized key name to a pynput Key or character."""
    if name in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[name]
    # Single character
    if len(name) == 1:
        return name
    return name


def send_key_combo(combo_str: str) -> None:
    """Simulate a key combo like 'LAlt - LCtrl - LShift - S'.

    Presses all modifier keys, then the final key, then releases all.
    """
    keys = parse_combo(combo_str)
    if not keys:
        return

    resolved = [_resolve_key(k) for k in keys]

    # All keys except the last are modifiers, last is the action key
    modifiers = resolved[:-1]
    action_key = resolved[-1]

    # Press modifiers
    for mod in modifiers:
        _keyboard.press(mod)

    # Small delay to ensure DCS registers the modifiers
    time.sleep(0.02)

    # Press and release action key
    _keyboard.press(action_key)
    time.sleep(0.02)
    _keyboard.release(action_key)

    # Release modifiers in reverse
    for mod in reversed(modifiers):
        _keyboard.release(mod)
