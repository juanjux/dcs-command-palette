"""Simulate keyboard input to send DCS keyboard shortcuts."""
from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from typing import Any, Dict, List, Union

from pynput.keyboard import Controller, Key  # type: ignore[import-untyped]

from src.lib.keyboard import parse_combo

logger = logging.getLogger(__name__)

_keyboard = Controller()


# ── Win32 SendInput fallback for the Windows / Meta key ─────────────
# pynput's cmd/cmd_l implementation is not reliably picked up by DCS
# (or by some other apps that use raw input).  Using SendInput directly
# with the proper extended-key flag and explicit scancodes lets DCS
# treat LWin+Home and similar combos exactly like a physical keypress.

_INPUT_KEYBOARD = 1
_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_SCANCODE = 0x0008

# Virtual-key codes we care about.  Map covers everything our existing
# _KEY_MAP can produce after normalization.
_VK_CODES: Dict[str, int] = {
    "ctrl_l": 0xA2, "ctrl_r": 0xA3,
    "alt_l": 0xA4, "alt_r": 0xA5,
    "shift_l": 0xA0, "shift_r": 0xA1,
    "cmd_l": 0x5B, "cmd_r": 0x5C,  # LWin / RWin
    "space": 0x20, "enter": 0x0D, "tab": 0x09,
    "backspace": 0x08, "delete": 0x2E,
    "escape": 0x1B, "pause": 0x13,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23,
    "page_up": 0x21, "page_down": 0x22,
    "insert": 0x2D,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

# Keys that need the extended-key flag for SendInput.  The extended set
# corresponds to the right-side modifiers, the cursor block, and the
# Win keys — anything originally on the IBM "extended" keyboard.
_EXTENDED_VKS: set = {
    0xA3, 0xA5,  # ctrl_r, alt_r
    0x5B, 0x5C,  # LWin, RWin
    0x24, 0x23,  # home, end
    0x21, 0x22,  # page_up, page_down
    0x2D, 0x2E,  # insert, delete
    0x26, 0x28, 0x25, 0x27,  # arrows
}


# SendInput structures (must match Windows SDK)
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_SendInput = _user32.SendInput
_SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
_SendInput.restype = wintypes.UINT
_MapVirtualKeyW = _user32.MapVirtualKeyW
_MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
_MapVirtualKeyW.restype = wintypes.UINT


def _make_keyboard_event(vk: int, key_up: bool) -> _INPUT:
    flags = 0
    if vk in _EXTENDED_VKS:
        flags |= _KEYEVENTF_EXTENDEDKEY
    if key_up:
        flags |= _KEYEVENTF_KEYUP
    # Always include scancode for max compatibility with games that
    # use DirectInput / raw input (DCS does for some modes).
    scan = _MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
    ki = _KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=None)
    inp = _INPUT(type=_INPUT_KEYBOARD)
    inp.ki = ki
    return inp


def _send_inputs(events: List[_INPUT]) -> bool:
    arr_type = _INPUT * len(events)
    arr = arr_type(*events)
    sent = _SendInput(len(events), arr, ctypes.sizeof(_INPUT))
    if sent != len(events):
        err = ctypes.get_last_error()
        logger.warning("SendInput sent %d/%d events (last error %d)",
                       sent, len(events), err)
        return False
    return True


def _vk_for(name: str) -> int:
    """Resolve a normalized key name to a Win32 virtual-key code, or 0."""
    if name in _VK_CODES:
        return _VK_CODES[name]
    # Single-character keys: ord('A') maps directly for letters/digits
    if len(name) == 1:
        ch = name.upper()
        return ord(ch)
    return 0


def _send_combo_via_sendinput(keys: List[str]) -> bool:
    """Send a normalized key combo via Win32 SendInput.

    Returns True on success, False if any key couldn't be resolved
    (caller falls back to pynput).  Splits into three phases (press
    modifiers / press+release action / release modifiers) with a small
    sleep between phases — back-to-back input batches without spacing
    aren't reliably processed by DCS.
    """
    vks = [_vk_for(k) for k in keys]
    if not all(vks):
        return False

    modifiers = vks[:-1]
    action = vks[-1]

    # Phase 1: press modifiers
    if modifiers:
        if not _send_inputs([
            _make_keyboard_event(vk, key_up=False) for vk in modifiers
        ]):
            return False
        time.sleep(0.02)

    # Phase 2: press + release action key
    if not _send_inputs([
        _make_keyboard_event(action, key_up=False),
        _make_keyboard_event(action, key_up=True),
    ]):
        return False
    time.sleep(0.02)

    # Phase 3: release modifiers in reverse
    if modifiers:
        if not _send_inputs([
            _make_keyboard_event(vk, key_up=True) for vk in reversed(modifiers)
        ]):
            return False

    return True

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

    Tries Win32 SendInput first (more reliable for DCS, especially for
    Win-key combos like LWin+Home for FA-18C aircraft auto-start).
    Falls back to pynput if any key can't be resolved to a VK code.
    """
    keys = parse_combo(combo_str)
    if not keys:
        return

    if _send_combo_via_sendinput(keys):
        logger.debug("Sent combo via SendInput: %s", combo_str)
        return

    logger.debug("Falling back to pynput for combo: %s", combo_str)

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
