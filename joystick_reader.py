"""Simple Windows joystick reader using Win32 Multimedia API."""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

# Win32 Multimedia Joystick API
winmm = ctypes.windll.winmm

MAXPNAMELEN = 32


class JOYCAPS(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.wintypes.WORD),
        ("wPid", ctypes.wintypes.WORD),
        ("szPname", ctypes.c_char * MAXPNAMELEN),
        ("wXmin", ctypes.wintypes.UINT),
        ("wXmax", ctypes.wintypes.UINT),
        ("wYmin", ctypes.wintypes.UINT),
        ("wYmax", ctypes.wintypes.UINT),
        ("wZmin", ctypes.wintypes.UINT),
        ("wZmax", ctypes.wintypes.UINT),
        ("wNumButtons", ctypes.wintypes.UINT),
        ("wPeriodMin", ctypes.wintypes.UINT),
        ("wPeriodMax", ctypes.wintypes.UINT),
        ("wRmin", ctypes.wintypes.UINT),
        ("wRmax", ctypes.wintypes.UINT),
        ("wUmin", ctypes.wintypes.UINT),
        ("wUmax", ctypes.wintypes.UINT),
        ("wVmin", ctypes.wintypes.UINT),
        ("wVmax", ctypes.wintypes.UINT),
        ("wCaps", ctypes.wintypes.UINT),
        ("wMaxAxes", ctypes.wintypes.UINT),
        ("wNumAxes", ctypes.wintypes.UINT),
        ("wMaxButtons", ctypes.wintypes.UINT),
        ("szRegKey", ctypes.c_char * MAXPNAMELEN),
        ("szOEMVxD", ctypes.c_char * MAXPNAMELEN),
    ]


class JOYINFOEX(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("dwXpos", ctypes.wintypes.DWORD),
        ("dwYpos", ctypes.wintypes.DWORD),
        ("dwZpos", ctypes.wintypes.DWORD),
        ("dwRpos", ctypes.wintypes.DWORD),
        ("dwUpos", ctypes.wintypes.DWORD),
        ("dwVpos", ctypes.wintypes.DWORD),
        ("dwButtons", ctypes.wintypes.DWORD),
        ("dwButtonNumber", ctypes.wintypes.DWORD),
        ("dwPOV", ctypes.wintypes.DWORD),
        ("dwReserved1", ctypes.wintypes.DWORD),
        ("dwReserved2", ctypes.wintypes.DWORD),
    ]


JOYERR_NOERROR = 0
JOY_RETURNBUTTONS = 0x00000080
JOY_RETURNALL = 0x000000FF

MAX_JOYSTICKS = 16


@dataclass
class JoystickButton:
    """A detected joystick button press."""

    joy_id: int
    joy_name: str
    button: int  # 0-based button number


def get_joystick_names() -> Dict[int, str]:
    """Get names of all connected joysticks."""
    names: Dict[int, str] = {}
    caps = JOYCAPS()
    for joy_id in range(MAX_JOYSTICKS):
        result = winmm.joyGetDevCapsA(
            joy_id, ctypes.byref(caps), ctypes.sizeof(JOYCAPS)
        )
        if result == JOYERR_NOERROR:
            name = caps.szPname.decode("ascii", errors="replace").strip("\x00")
            names[joy_id] = name if name else f"Joystick {joy_id}"
    return names


def poll_joystick_buttons() -> List[JoystickButton]:
    """Poll all joysticks and return any currently pressed buttons."""
    results: List[JoystickButton] = []
    names = get_joystick_names()
    info = JOYINFOEX()
    info.dwSize = ctypes.sizeof(JOYINFOEX)
    info.dwFlags = JOY_RETURNBUTTONS

    for joy_id, joy_name in names.items():
        err = winmm.joyGetPosEx(joy_id, ctypes.byref(info))
        if err != JOYERR_NOERROR:
            continue
        buttons = info.dwButtons
        for btn in range(32):
            if buttons & (1 << btn):
                results.append(
                    JoystickButton(joy_id=joy_id, joy_name=joy_name, button=btn)
                )
    return results
