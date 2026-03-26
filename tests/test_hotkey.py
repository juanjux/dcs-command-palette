"""Smoke tests for the low-level keyboard hook."""
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_keyboard_hook_installs_and_uninstalls() -> None:
    """Verify the low-level keyboard hook can be installed and removed."""
    from main import LowLevelKeyboardHook

    calls: list[bool] = []
    hook = LowLevelKeyboardHook(callback=lambda: calls.append(True))

    assert hook.install(), "Failed to install low-level keyboard hook"
    assert hook._hook is not None
    hook.uninstall()
    assert hook._hook is None
