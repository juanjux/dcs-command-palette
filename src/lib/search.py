from __future__ import annotations

import math
import re
import time
from typing import Any, Dict, List, Tuple

from rapidfuzz import fuzz, process

from src.palette.commands import Command, CommandSource
import src.config.settings as cfg
from src.config.settings import (
    MAX_RESULTS,
    PREFIX_MATCH_BONUS,
    RECENCY_DECAY_HOURS,
    WEIGHT_FREQUENCY,
    WEIGHT_FUZZY,
    WEIGHT_RECENCY,
)
from src.palette.usage import UsageTracker


def _recency_score(last_used: float) -> float:
    if last_used == 0.0:
        return 0.0
    hours_ago = (time.time() - last_used) / 3600.0
    return 100.0 * math.exp(-hours_ago / RECENCY_DECAY_HOURS)


def _frequency_score(count: int, max_count: int) -> float:
    return 100.0 * count / max_count


def _is_unbound_keyboard(cmd: Any) -> bool:
    """Check if a command is an unbound keyboard shortcut (not a palette builtin)."""
    return (
        getattr(cmd, "source", None) == CommandSource.KEYBOARD
        and not getattr(cmd, "key_combo", "")
        and not cmd.identifier.startswith("__")
    )


def search(
    query: str,
    commands: List[Command],
    usage: UsageTracker,
) -> List[Command]:
    # Filter out unbound keyboard shortcuts unless the setting is enabled
    if not cfg.SHOW_UNBOUND:
        commands = [c for c in commands if not _is_unbound_keyboard(c)]

    max_count = usage.max_count()

    if not query.strip():
        scored: List[Tuple[float, Command]] = []
        for cmd in commands:
            freq = _frequency_score(usage.get_count(cmd.identifier), max_count)
            rec = _recency_score(usage.get_last_used(cmd.identifier))
            score = WEIGHT_FREQUENCY * freq + WEIGHT_RECENCY * rec
            if score > 0:
                scored.append((score, cmd))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [cmd for _, cmd in scored[:MAX_RESULTS]]

    choices: Dict[int, str] = {i: cmd.search_text for i, cmd in enumerate(commands)}

    results: Any = process.extract(
        query.lower(),
        choices,
        scorer=fuzz.WRatio,
        limit=MAX_RESULTS * 3,
    )

    query_lower = query.lower()
    query_words = query_lower.split()
    query_as_id = query_lower.replace(" ", "_")
    scored_results: List[Tuple[float, Command]] = []
    for _match_text, fuzzy_score, idx in results:
        cmd = commands[idx]
        freq = _frequency_score(usage.get_count(cmd.identifier), max_count)
        rec = _recency_score(usage.get_last_used(cmd.identifier))

        final = (
            WEIGHT_FUZZY * float(fuzzy_score)
            + WEIGHT_FREQUENCY * freq
            + WEIGHT_RECENCY * rec
        )

        if cmd.identifier.lower().startswith(query_as_id):
            final += PREFIX_MATCH_BONUS

        # Bonus when ALL query words appear in the search text.
        # This prevents "radar off" from matching "master arm off" equally.
        if len(query_words) > 1:
            if all(w in cmd.search_text for w in query_words):
                final += 15

        # Literal substring match bonus: "Night" matches "Night/Day" exactly
        if query_lower in cmd.search_text:
            final += 12

        # Deprioritize pushbuttons (e.g. AMPCD_PB_01, LEFT_DDI_PB_01)
        if "_PB" in cmd.identifier:
            final -= 10

        # Deprioritize unbound keyboard commands
        if (
            getattr(cmd, "source", None) == CommandSource.KEYBOARD
            and not getattr(cmd, "key_combo", "")
        ):
            final -= 8

        # Deprioritize UFC numeric keyboard (UFC_0 .. UFC_9)
        if re.match(r"^UFC_[0-9]$", cmd.identifier):
            final -= 5

        scored_results.append((final, cmd))

    scored_results.sort(key=lambda x: x[0], reverse=True)
    return [cmd for _, cmd in scored_results[:MAX_RESULTS]]
