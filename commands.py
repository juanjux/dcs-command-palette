"""Unified command abstraction for both DCS-BIOS controls and keyboard shortcuts."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from config import AIRCRAFT_INPUT_NAME, AIRCRAFT_MODULE, DCS_INSTALL_DIR, DCS_SAVED_GAMES
from controls import Control, load_controls
from keyboard_commands import KeyboardEntry, load_keyboard_entries


class CommandSource(Enum):
    DCS_BIOS = "dcs_bios"
    KEYBOARD = "keyboard"


@dataclass
class Command:
    identifier: str
    description: str
    category: str
    source: CommandSource
    search_text: str = ""

    # DCS-BIOS specific
    control_type: str = ""
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    max_value: Optional[int] = None
    has_toggle: bool = False
    has_fixed_step: bool = False
    has_variable_step: bool = False
    has_set_string: bool = False
    suggested_step: Optional[int] = None
    position_labels: Optional[Dict[int, str]] = None

    # Keyboard shortcut specific
    key_combo: str = ""

    @property
    def is_simple_action(self) -> bool:
        if self.source == CommandSource.KEYBOARD:
            return bool(self.key_combo)
        if self.max_value is not None and self.max_value <= 1:
            return True
        return False


def _control_to_command(ctrl: Control) -> Command:
    return Command(
        identifier=ctrl.identifier,
        description=ctrl.description,
        category=ctrl.category,
        source=CommandSource.DCS_BIOS,
        search_text=ctrl.search_text,
        control_type=ctrl.control_type,
        inputs=ctrl.inputs,
        max_value=ctrl.max_value,
        has_toggle=ctrl.has_toggle,
        has_fixed_step=ctrl.has_fixed_step,
        has_variable_step=ctrl.has_variable_step,
        has_set_string=ctrl.has_set_string,
        suggested_step=ctrl.suggested_step,
        position_labels=ctrl.position_labels,
    )


def _entry_to_command(entry: KeyboardEntry) -> Command:
    identifier = re.sub(r"[^a-zA-Z0-9]+", "_", entry.name).strip("_").upper()
    id_spaced = identifier.replace("_", " ").lower()
    search_text = f"{id_spaced} {entry.name} {entry.category}".lower()
    return Command(
        identifier=identifier,
        description=entry.name,
        category=f"Key: {entry.category}" if entry.category else "Key",
        source=CommandSource.KEYBOARD,
        search_text=search_text,
        key_combo=entry.key_combo,
    )


def load_all_commands(
    dcs_install_dir: str = DCS_INSTALL_DIR,
    aircraft_module: str = AIRCRAFT_MODULE,
    aircraft_input_name: str = AIRCRAFT_INPUT_NAME,
    dcs_saved_games: str = DCS_SAVED_GAMES,
    aircraft_saved_name: Optional[str] = None,
    controls_json_path: Optional[str] = None,
) -> List[Command]:
    """Load all commands from both DCS-BIOS and keyboard shortcuts.

    Args:
        dcs_install_dir: Path to DCS World installation.
        aircraft_module: Module folder name (e.g. "FA-18C").
        aircraft_input_name: Input subfolder name (e.g. "FA-18C").
        dcs_saved_games: Path to DCS Saved Games folder.
        aircraft_saved_name: Saved games folder name for user keybinds (e.g. "FA-18C_hornet").
        controls_json_path: Path to the DCS-BIOS JSON file for this aircraft. If None, skips BIOS controls.
    """
    commands: List[Command] = []

    # DCS-BIOS controls
    if controls_json_path and os.path.exists(controls_json_path):
        bios_controls = load_controls(controls_json_path)
        for ctrl in bios_controls:
            commands.append(_control_to_command(ctrl))

    # Keyboard shortcuts from DCS install directory + user customizations
    kb_entries = load_keyboard_entries(
        dcs_install_dir=dcs_install_dir,
        aircraft_module=aircraft_module,
        aircraft_input_name=aircraft_input_name,
        dcs_saved_games=dcs_saved_games,
        aircraft_saved_name=aircraft_saved_name,
    )
    for entry in kb_entries:
        commands.append(_entry_to_command(entry))

    return commands
