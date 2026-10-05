"""Tracking favorites use the same persistent stars as aircraft commands."""
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from src.lib.head_tracking import HEAD_TRACKING_COMMANDS
from src.lib.search import search
from src.main import _add_palette_commands
from src.palette.overlay import CommandPalette, ResultItem
from src.palette.usage import UsageTracker


@pytest.mark.parametrize("identifier", HEAD_TRACKING_COMMANDS)
def test_tracking_star_click_persists_without_executing(tmp_path, identifier):
    app = QApplication.instance() or QApplication([])
    commands = _add_palette_commands([])
    command = next(c for c in commands if c.identifier == identifier)
    path = str(tmp_path / "usage.json")
    usage = UsageTracker(path=path)
    palette = CommandPalette(commands, usage, Mock())
    palette._search.setText(command.description)
    palette._on_search_changed(command.description)
    index = palette._results.index(command)
    row = palette._item_widgets[index]
    assert row.star_label.text() == "☆"
    executed = Mock()
    palette.palette_command_triggered = executed
    palette._on_item_mouse_press(
        index, SimpleNamespace(pos=lambda: row.star_label.geometry().center())
    )
    executed.assert_not_called()
    assert usage.is_favorite(identifier)
    assert palette._item_widgets[palette._results.index(command)].star_label.text() == "★"
    usage.save()
    reloaded = UsageTracker(path=path)
    assert search("", commands, reloaded)[0] == command
    index = palette._results.index(command)
    row = palette._item_widgets[index]
    palette._on_item_mouse_press(
        index, SimpleNamespace(pos=lambda: row.star_label.geometry().center())
    )
    assert not usage.is_favorite(identifier)
    executed.assert_not_called()
    palette.close()
    palette.deleteLater()
    app.processEvents()
    ResultItem._usage = None


def test_settings_commands_still_have_no_favorites():
    commands = _add_palette_commands([])
    assert all(
        c.can_favorite == (c.identifier in HEAD_TRACKING_COMMANDS)
        for c in commands
    )
