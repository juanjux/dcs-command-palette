from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional



@dataclass
class Control:
    identifier: str
    description: str
    category: str
    control_type: str
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    max_value: Optional[int] = None
    has_toggle: bool = False
    has_fixed_step: bool = False
    has_variable_step: bool = False
    has_set_string: bool = False
    suggested_step: Optional[int] = None
    position_labels: Optional[Dict[int, str]] = None
    search_text: str = ""
    # DCS-BIOS output metadata for reading current state
    output_address: Optional[int] = None
    output_mask: Optional[int] = None
    output_shift: Optional[int] = None


# Pattern: "0 = off, 1 = on" or "0 = emergency, 1 = park, 2 = release"
_POSITION_RE = re.compile(r"(\d+)\s*=\s*([^,)]+)")


def _parse_position_labels(inputs: List[Dict[str, Any]]) -> Optional[Dict[int, str]]:
    for inp in inputs:
        if inp.get("interface") == "set_state":
            desc = inp.get("description", "")
            matches = _POSITION_RE.findall(desc)
            if matches:
                return {int(pos): label.strip() for pos, label in matches}
    return None


def load_controls(json_path: str) -> list[Control]:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    controls = []
    for category_name, category_controls in data.items():
        for ctrl_id, ctrl in category_controls.items():
            inputs = ctrl.get("inputs", [])
            if not inputs:
                continue

            max_value = None
            has_toggle = False
            has_fixed_step = False
            has_variable_step = False
            has_set_string = False
            suggested_step = None

            for inp in inputs:
                iface = inp.get("interface", "")
                if iface == "action" and inp.get("argument") == "TOGGLE":
                    has_toggle = True
                elif iface == "fixed_step":
                    has_fixed_step = True
                elif iface == "variable_step":
                    has_variable_step = True
                    suggested_step = inp.get("suggested_step")
                elif iface == "set_state":
                    max_value = inp.get("max_value")
                elif iface == "set_string":
                    has_set_string = True

            position_labels = _parse_position_labels(inputs)

            # Fall back to the top-level "positions" array if present
            if not position_labels:
                raw_positions = ctrl.get("positions")
                if raw_positions and isinstance(raw_positions, list) and len(raw_positions) > 1:
                    position_labels = {i: str(p) for i, p in enumerate(raw_positions)}

            # Parse first integer output for state reading
            output_address: Optional[int] = None
            output_mask: Optional[int] = None
            output_shift: Optional[int] = None
            for out in ctrl.get("outputs", []):
                if out.get("type") == "integer":
                    output_address = out.get("address")
                    output_mask = out.get("mask")
                    output_shift = out.get("shift_by")
                    break

            # Build searchable text: identifier (with underscores as spaces) + description + category
            id_spaced = ctrl_id.replace("_", " ")
            search_text = f"{id_spaced} {ctrl.get('description', '')} {category_name}".lower()

            controls.append(Control(
                identifier=ctrl_id,
                description=ctrl.get("description", ""),
                category=category_name,
                control_type=ctrl.get("control_type", ""),
                inputs=inputs,
                max_value=max_value,
                has_toggle=has_toggle,
                has_fixed_step=has_fixed_step,
                has_variable_step=has_variable_step,
                has_set_string=has_set_string,
                suggested_step=suggested_step,
                position_labels=position_labels,
                search_text=search_text,
                output_address=output_address,
                output_mask=output_mask,
                output_shift=output_shift,
            ))

    return controls
