"""Unified command abstraction for both DCS-BIOS controls and keyboard shortcuts."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.config.settings import AIRCRAFT_INPUT_NAME, AIRCRAFT_MODULE, DCS_INSTALL_DIR, DCS_SAVED_GAMES
from src.bios.controls import Control, load_controls
from src.lib.keyboard import KeyboardEntry, load_keyboard_entries


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

    # DCS-BIOS output (for reading current state)
    output_address: Optional[int] = None
    output_mask: Optional[int] = None
    output_shift: Optional[int] = None

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
    search_text = ctrl.search_text
    # Append position label values so users can search by label (e.g. "arm", "safe")
    if ctrl.position_labels:
        labels = " ".join(ctrl.position_labels.values()).lower()
        search_text = f"{search_text} {labels}"
    return Command(
        identifier=ctrl.identifier,
        description=ctrl.description,
        category=ctrl.category,
        source=CommandSource.DCS_BIOS,
        search_text=search_text,
        control_type=ctrl.control_type,
        inputs=ctrl.inputs,
        max_value=ctrl.max_value,
        has_toggle=ctrl.has_toggle,
        has_fixed_step=ctrl.has_fixed_step,
        has_variable_step=ctrl.has_variable_step,
        has_set_string=ctrl.has_set_string,
        suggested_step=ctrl.suggested_step,
        position_labels=ctrl.position_labels,
        output_address=ctrl.output_address,
        output_mask=ctrl.output_mask,
        output_shift=ctrl.output_shift,
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


@dataclass
class _PositionInfo:
    """Position name with optional DCS value_down for ordering."""
    name: str
    value_down: Optional[float] = None


def _enrich_position_labels(
    commands: List[Command], kb_entries: List[KeyboardEntry],
) -> None:
    """Fill in position_labels for BIOS selectors using keyboard entry names.

    Keyboard entries follow the pattern "{Description} - {PositionName}"
    (e.g., "FLIR Switch - OFF", "FLIR Switch - STBY", "FLIR Switch - ON").
    For BIOS selectors without position_labels, we collect these names and
    use value_down from the Lua file to determine the correct position index.

    Excludes directional entries like "CCW", "CW", "Up", "Down", "Pull", "Stow".
    """
    # Build a map of description -> list of (pos_name, value_down) from keyboard entries
    directional = {"ccw", "cw", "up", "down", "pull", "stow", "pull/stow", "cycle",
                    "toggle", "press", "release", "held left/down", "centered",
                    "held right/up", "aug pull", "ccw/left", "cw/right"}
    desc_positions: Dict[str, List[_PositionInfo]] = {}
    for entry in kb_entries:
        if " - " not in entry.name:
            continue
        base, pos_name = entry.name.rsplit(" - ", 1)
        if pos_name.lower() in directional:
            continue
        # Filter out toggle-style entries like "BARO/RDR", "ON/OFF", "ENABLE/NORM"
        # which contain "/" and represent cycling between states, not a specific position
        if "/" in pos_name and pos_name.lower() not in {"ccw/left", "cw/right"}:
            continue
        desc_positions.setdefault(base, []).append(
            _PositionInfo(name=pos_name, value_down=entry.value_down)
        )

    def _normalize_for_match(s: str) -> str:
        """Normalize a string for fuzzy base-name matching."""
        return s.lower().replace("-", " ").replace("_", " ").strip()

    # Apply to BIOS commands that lack labels
    for cmd in commands:
        if cmd.source != CommandSource.DCS_BIOS:
            continue
        if cmd.position_labels:
            continue  # already has labels from DCS-BIOS JSON
        if cmd.max_value is None or cmd.max_value < 1:
            continue

        # Generate candidate names to try matching against keyboard base names:
        # 1. Exact BIOS description
        # 2. Identifier-derived name (RADAR_SW -> "Radar Switch")
        id_as_desc = cmd.identifier.replace("_SW", " Switch").replace("_KNOB", " Knob").replace("_", " ").title()
        candidates = [cmd.description, id_as_desc]

        pos_infos: Optional[List[_PositionInfo]] = None
        for candidate in candidates:
            # Exact match
            pos_infos = desc_positions.get(candidate)
            if pos_infos:
                break

            # Prefix matching (both directions)
            for base_name, pos_list in desc_positions.items():
                if base_name.startswith(candidate) or candidate.startswith(base_name):
                    pos_infos = pos_list
                    break
            if pos_infos:
                break

            # Substring matching: BIOS desc is contained in keyboard base or vice versa
            # e.g., "ECM Mode Switch" in "ALQ-165 ECM Mode Switch"
            norm_cand = _normalize_for_match(candidate)
            for base_name, pos_list in desc_positions.items():
                norm_base = _normalize_for_match(base_name)
                if norm_cand in norm_base or norm_base in norm_cand:
                    pos_infos = pos_list
                    break
            if pos_infos:
                break

        if not pos_infos:
            continue

        # The number of positions should match max_value + 1
        if len(pos_infos) != cmd.max_value + 1:
            continue

        # Use value_down to determine correct position order.
        # DCS-BIOS position 0 = lowest physical switch position.
        # value_down maps to physical position, so ascending sort always works:
        #   ECM: OFF=0.0, STBY=0.1, BIT=0.2, REC=0.3, XMIT=0.4
        #   FLAP: FULL=-1.0, HALF=0.0, AUTO=1.0 -> BIOS 0=FULL, 1=HALF, 2=AUTO
        all_have_values = all(p.value_down is not None for p in pos_infos)
        if all_have_values:
            sorted_pos = sorted(
                pos_infos, key=lambda p: p.value_down or 0.0,
            )
            cmd.position_labels = {i: p.name for i, p in enumerate(sorted_pos)}
        else:
            # Fallback: assign in order of appearance (legacy behavior)
            cmd.position_labels = {i: p.name for i, p in enumerate(pos_infos)}


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

    # Enrich BIOS selectors that lack position labels using keyboard entry names.
    # Pattern: BIOS "FLIR Switch" (max_value=2, no labels) + keyboard entries
    # "FLIR Switch - OFF", "FLIR Switch - STBY", "FLIR Switch - ON"
    # -> extract {0: "OFF", 1: "STBY", 2: "ON"}
    _enrich_position_labels(commands, kb_entries)

    return commands
