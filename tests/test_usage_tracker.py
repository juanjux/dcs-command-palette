import json
import os
import time

from src.palette.usage import UsageTracker


def test_record_and_retrieve(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "usage.json")
    tracker = UsageTracker(path=path)

    tracker.record_use("MASTER_ARM_SW")
    assert tracker.get_count("MASTER_ARM_SW") == 1

    tracker.record_use("MASTER_ARM_SW")
    assert tracker.get_count("MASTER_ARM_SW") == 2

    assert tracker.get_last_used("MASTER_ARM_SW") > 0.0


def test_unknown_identifier_returns_zero(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "usage.json")
    tracker = UsageTracker(path=path)

    assert tracker.get_count("NONEXISTENT") == 0
    assert tracker.get_last_used("NONEXISTENT") == 0.0


def test_max_count(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "usage.json")
    tracker = UsageTracker(path=path)

    tracker.record_use("A")
    tracker.record_use("A")
    tracker.record_use("A")
    tracker.record_use("B")

    assert tracker.max_count() == 3


def test_save_and_reload(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "usage.json")
    tracker = UsageTracker(path=path)

    tracker.record_use("GEAR_LEVER")
    tracker.record_use("GEAR_LEVER")
    tracker.save()

    # Reload from disk
    tracker2 = UsageTracker(path=path)
    assert tracker2.get_count("GEAR_LEVER") == 2


def test_handles_missing_file(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "nonexistent.json")
    tracker = UsageTracker(path=path)
    assert tracker.max_count() == 1  # Default


def test_handles_corrupt_file(tmp_path: object) -> None:
    path = os.path.join(str(tmp_path), "bad.json")
    with open(path, "w") as f:
        f.write("not valid json{{{")
    tracker = UsageTracker(path=path)
    assert tracker.max_count() == 1  # Graceful fallback
