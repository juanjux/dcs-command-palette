from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Tuple

from rapidfuzz import fuzz, process

from commands import Command
from config import (
    MAX_RESULTS,
    PREFIX_MATCH_BONUS,
    RECENCY_DECAY_HOURS,
    WEIGHT_FREQUENCY,
    WEIGHT_FUZZY,
    WEIGHT_RECENCY,
)
from usage_tracker import UsageTracker


def _recency_score(last_used: float) -> float:
    if last_used == 0.0:
        return 0.0
    hours_ago = (time.time() - last_used) / 3600.0
    return 100.0 * math.exp(-hours_ago / RECENCY_DECAY_HOURS)


def _frequency_score(count: int, max_count: int) -> float:
    return 100.0 * count / max_count


def search(
    query: str,
    commands: List[Command],
    usage: UsageTracker,
) -> List[Command]:
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

    query_lower = query.lower().replace(" ", "_")
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

        if cmd.identifier.lower().startswith(query_lower):
            final += PREFIX_MATCH_BONUS

        scored_results.append((final, cmd))

    scored_results.sort(key=lambda x: x[0], reverse=True)
    return [cmd for _, cmd in scored_results[:MAX_RESULTS]]
