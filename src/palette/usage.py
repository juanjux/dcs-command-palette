import json
import os
import time
from typing import Any, Dict

from src.config.settings import USAGE_DATA_PATH


class UsageTracker:
    def __init__(self, path: str = USAGE_DATA_PATH) -> None:
        self.path: str = path
        self._data: Dict[str, Dict[str, Any]] = {}
        self._dirty: bool = False
        self._last_save: float = 0.0
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._data = {}

    def record_use(self, identifier: str) -> None:
        entry = self._data.setdefault(identifier, {"count": 0, "last_used": 0.0})
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_used"] = time.time()
        self._dirty = True
        if time.time() - self._last_save > 5.0:
            self.save()

    def get_count(self, identifier: str) -> int:
        return int(self._data.get(identifier, {}).get("count", 0))

    def get_last_used(self, identifier: str) -> float:
        return float(self._data.get(identifier, {}).get("last_used", 0.0))

    def max_count(self) -> int:
        if not self._data:
            return 1
        return max((int(e.get("count", 0)) for e in self._data.values()), default=1) or 1

    def is_favorite(self, identifier: str) -> bool:
        return bool(self._data.get(identifier, {}).get("favorite", False))

    def set_favorite(self, identifier: str, value: bool) -> None:
        entry = self._data.setdefault(identifier, {"count": 0, "last_used": 0.0})
        if value:
            entry["favorite"] = True
        else:
            entry.pop("favorite", None)
        self._dirty = True
        # Bypass the 5s throttle: favoriting is a rare deliberate click.
        self._last_save = 0.0
        self.save()

    def toggle_favorite(self, identifier: str) -> bool:
        new_val = not self.is_favorite(identifier)
        self.set_favorite(identifier, new_val)
        return new_val

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            self._dirty = False
            self._last_save = time.time()
        except IOError:
            pass
