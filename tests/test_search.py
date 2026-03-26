import time

from controls import load_controls
from search import search
from usage_tracker import UsageTracker


def _make_tracker(tmp_path: object) -> UsageTracker:
    """Create a temporary usage tracker."""
    import os
    path = os.path.join(str(tmp_path), "test_usage.json")
    return UsageTracker(path=path)


def test_search_master_arm(tmp_path: object) -> None:
    controls = load_controls()
    usage = _make_tracker(tmp_path)
    results = search("master arm", controls, usage)
    identifiers = [r.identifier for r in results]
    assert "MASTER_ARM_SW" in identifiers
    assert identifiers[0] == "MASTER_ARM_SW"  # Should be first


def test_search_typo(tmp_path: object) -> None:
    controls = load_controls()
    usage = _make_tracker(tmp_path)
    results = search("mstr arm", controls, usage)
    identifiers = [r.identifier for r in results]
    assert "MASTER_ARM_SW" in identifiers


def test_search_gear(tmp_path: object) -> None:
    controls = load_controls()
    usage = _make_tracker(tmp_path)
    results = search("gear", controls, usage)
    identifiers = [r.identifier for r in results]
    assert any("GEAR" in i for i in identifiers)


def test_search_brightness(tmp_path: object) -> None:
    controls = load_controls()
    usage = _make_tracker(tmp_path)
    results = search("brt", controls, usage)
    identifiers = [r.identifier for r in results]
    assert any("BRT" in i for i in identifiers)


def test_search_empty_returns_nothing_initially(tmp_path: object) -> None:
    controls = load_controls()
    usage = _make_tracker(tmp_path)
    results = search("", controls, usage)
    # No usage data yet, so empty query returns nothing
    assert len(results) == 0


def test_search_empty_returns_most_used(tmp_path: object) -> None:
    controls = load_controls()
    usage = _make_tracker(tmp_path)
    # Record some usage
    usage.record_use("MASTER_ARM_SW")
    usage.record_use("MASTER_ARM_SW")
    usage.record_use("GEAR_LEVER")
    results = search("", controls, usage)
    identifiers = [r.identifier for r in results]
    assert "MASTER_ARM_SW" in identifiers
    assert identifiers[0] == "MASTER_ARM_SW"  # Most used should be first


def test_search_respects_max_results(tmp_path: object) -> None:
    from config import MAX_RESULTS
    controls = load_controls()
    usage = _make_tracker(tmp_path)
    results = search("switch", controls, usage)
    assert len(results) <= MAX_RESULTS


def test_search_prefix_bonus(tmp_path: object) -> None:
    controls = load_controls()
    usage = _make_tracker(tmp_path)
    results = search("AMPCD", controls, usage)
    identifiers = [r.identifier for r in results]
    # All AMPCD_ controls should rank highly
    assert identifiers[0].startswith("AMPCD")
