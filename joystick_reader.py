"""Joystick reader using pygame/SDL2 for broad device support.

The Win32 Multimedia API (winmm) doesn't detect many modern joysticks
(e.g., VKB, Virpil). SDL2 via pygame handles DirectInput and HID devices.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Suppress pygame welcome message
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402


_initialized = False


def _ensure_init() -> None:
    """Initialize pygame joystick subsystem (only once)."""
    global _initialized
    if not _initialized:
        pygame.init()
        pygame.joystick.init()
        _initialized = True
        logger.debug("pygame joystick subsystem initialized")


def shutdown() -> None:
    """Clean up pygame resources."""
    global _initialized
    if _initialized:
        pygame.joystick.quit()
        pygame.quit()
        _initialized = False


@dataclass
class JoystickButton:
    """A detected joystick button press."""
    joy_id: int
    joy_name: str
    button: int  # 0-based button number


def get_joystick_names() -> Dict[int, str]:
    """Get names of all connected joysticks."""
    _ensure_init()
    names: Dict[int, str] = {}
    count = pygame.joystick.get_count()
    for i in range(count):
        try:
            js = pygame.joystick.Joystick(i)
            js.init()
            names[i] = js.get_name()
        except pygame.error:
            names[i] = f"Joystick {i}"
    return names


def poll_joystick_buttons() -> List[JoystickButton]:
    """Poll all joysticks and return any currently pressed buttons."""
    _ensure_init()
    # Must pump events for SDL to update joystick state
    pygame.event.pump()

    results: List[JoystickButton] = []
    count = pygame.joystick.get_count()
    for i in range(count):
        try:
            js = pygame.joystick.Joystick(i)
            js.init()
            name = js.get_name()
            for btn in range(js.get_numbuttons()):
                if js.get_button(btn):
                    results.append(JoystickButton(joy_id=i, joy_name=name, button=btn))
        except pygame.error:
            continue
    return results


def is_button_pressed(joy_id: int, button: int) -> bool:
    """Check if a specific joystick button is currently pressed."""
    _ensure_init()
    pygame.event.pump()
    try:
        js = pygame.joystick.Joystick(joy_id)
        js.init()
        return bool(js.get_button(button))
    except (pygame.error, IndexError):
        return False
