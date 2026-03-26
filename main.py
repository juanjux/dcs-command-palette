from __future__ import annotations

import ctypes
import sys
from typing import List, Optional

from PyQt6.QtCore import QObject, pyqtSignal, QAbstractNativeEventFilter, QByteArray  # type: ignore[import-untyped]
from PyQt6.QtWidgets import (  # type: ignore[import-untyped]
    QApplication, QSystemTrayIcon, QMenu, QInputDialog, QFileDialog, QMessageBox,
)

from commands import Command, CommandSource, load_all_commands
from config import DCS_BIOS_HOST, DCS_BIOS_PORT
from dcs_bios import DCSBiosSender
from overlay import CommandPalette
from setup import (
    detect_dcs_install_dir,
    get_aircraft_input_name,
    get_selected_aircraft,
    list_installed_aircraft,
    save_dcs_install_dir,
    save_selected_aircraft,
    _read_settings,
)
from usage_tracker import UsageTracker

# Win32 constants
MOD_CTRL = 0x0002
MOD_NOREPEAT = 0x4000
VK_SPACE = 0x20
HOTKEY_ID = 1
WM_HOTKEY = 0x0312


class HotkeyFilter(QAbstractNativeEventFilter):  # type: ignore[misc]
    def __init__(self, callback: object) -> None:
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type: object, message: object) -> object:
        if event_type == b"windows_generic_MSG" or event_type == QByteArray(b"windows_generic_MSG"):
            msg_ptr = int(message)  # type: ignore[arg-type]
            msg_id = ctypes.c_uint32.from_address(msg_ptr + ctypes.sizeof(ctypes.c_void_p)).value
            if msg_id == WM_HOTKEY:
                self._callback()  # type: ignore[operator]
                return True, 0
        return False, 0


class HotkeyBridge(QObject):  # type: ignore[misc]
    triggered = pyqtSignal()


def _ensure_dcs_install_dir(app: QApplication) -> Optional[str]:
    """Find or ask the user for the DCS install directory."""
    dcs_dir = detect_dcs_install_dir()
    if dcs_dir:
        save_dcs_install_dir(dcs_dir)
        return dcs_dir

    # Ask user
    QMessageBox.information(
        None,
        "DCS Command Palette - Setup",
        "Could not find DCS World installation automatically.\n"
        "Please select the DCS World installation folder.",
    )
    path = QFileDialog.getExistingDirectory(
        None,
        "Select DCS World Installation Directory",
        "C:\\",
    )
    if path:
        save_dcs_install_dir(path)
        return path
    return None


def _ensure_aircraft(dcs_dir: str) -> Optional[str]:
    """Get selected aircraft, or ask user to pick one."""
    aircraft = get_selected_aircraft()
    if aircraft:
        return aircraft

    aircraft_list = list_installed_aircraft(dcs_dir)
    if not aircraft_list:
        print("WARNING: No aircraft found.")
        return None

    # Default to FA-18C if available
    if "FA-18C" in aircraft_list:
        save_selected_aircraft("FA-18C")
        return "FA-18C"

    choice, ok = QInputDialog.getItem(
        None,
        "DCS Command Palette - Select Aircraft",
        "Select your aircraft:",
        aircraft_list,
        0,
        False,
    )
    if ok and choice:
        save_selected_aircraft(choice)
        return choice
    return aircraft_list[0] if aircraft_list else None


def _add_palette_commands(commands: List[Command]) -> List[Command]:
    """Add built-in palette commands like Config, Change Aircraft."""
    builtins = [
        Command(
            identifier="__PALETTE_CONFIG__",
            description="Open Palette Settings",
            category="Palette",
            source=CommandSource.KEYBOARD,
            search_text="config settings palette configuration setup change aircraft plane",
            key_combo="",  # handled specially
        ),
        Command(
            identifier="__CHANGE_AIRCRAFT__",
            description="Change Aircraft",
            category="Palette",
            source=CommandSource.KEYBOARD,
            search_text="change aircraft plane switch module select",
            key_combo="",
        ),
    ]
    return builtins + commands


class App:
    """Main application class managing the palette lifecycle."""

    def __init__(self) -> None:
        self.qapp = QApplication(sys.argv)
        self.qapp.setQuitOnLastWindowClosed(False)

        # Setup
        self.dcs_dir = _ensure_dcs_install_dir(self.qapp)
        if not self.dcs_dir:
            print("ERROR: No DCS installation directory. Exiting.")
            sys.exit(1)

        self.aircraft = _ensure_aircraft(self.dcs_dir)
        if not self.aircraft:
            print("ERROR: No aircraft selected. Exiting.")
            sys.exit(1)

        self.usage = UsageTracker()
        self.sender = DCSBiosSender()
        self.palette: Optional[CommandPalette] = None
        self._load_commands()

    def _load_commands(self) -> None:
        """Load (or reload) commands for the current aircraft."""
        print(f"Loading commands for {self.aircraft}...")

        input_name = get_aircraft_input_name(self.dcs_dir, self.aircraft) if self.dcs_dir else None

        commands = load_all_commands(
            dcs_install_dir=self.dcs_dir or "",
            aircraft_module=self.aircraft or "",
            aircraft_input_name=input_name or self.aircraft or "",
        )
        commands = _add_palette_commands(commands)

        bios_count = sum(1 for c in commands if c.source == CommandSource.DCS_BIOS)
        kb_count = sum(1 for c in commands if c.source == CommandSource.KEYBOARD)
        print(f"  {len(commands)} commands ({bios_count} BIOS, {kb_count} keyboard/palette)")

        if self.palette:
            self.palette._commands = commands
        else:
            self.palette = CommandPalette(commands, self.usage, self.sender)

        # Hook palette commands
        self.palette.palette_command_triggered = self._on_palette_command  # type: ignore[attr-defined]

    def _on_palette_command(self, identifier: str) -> None:
        if identifier == "__CHANGE_AIRCRAFT__":
            self._change_aircraft()
        elif identifier == "__PALETTE_CONFIG__":
            self._open_config()

    def _change_aircraft(self) -> None:
        if not self.dcs_dir:
            return
        aircraft_list = list_installed_aircraft(self.dcs_dir)
        choice, ok = QInputDialog.getItem(
            None,
            "Change Aircraft",
            "Select aircraft:",
            aircraft_list,
            aircraft_list.index(self.aircraft) if self.aircraft in aircraft_list else 0,
            False,
        )
        if ok and choice and choice != self.aircraft:
            self.aircraft = choice
            save_selected_aircraft(choice)
            self._load_commands()
            print(f"Switched to {choice}")

    def _open_config(self) -> None:
        """Show a simple config dialog."""
        settings = _read_settings()
        msg = (
            f"DCS Install Dir: {settings.get('dcs_install_dir', 'Not set')}\n"
            f"Aircraft: {settings.get('aircraft', 'Not set')}\n"
            f"DCS Saved Games: {settings.get('dcs_saved_games', 'Auto-detected')}\n\n"
            f"Use 'Change Aircraft' command to switch planes.\n"
            f"Delete settings.json to re-run setup."
        )
        QMessageBox.information(None, "DCS Command Palette - Settings", msg)

    def run(self) -> None:
        assert self.palette is not None

        bridge = HotkeyBridge()

        def toggle_palette() -> None:
            assert self.palette is not None
            if self.palette.isVisible():
                self.palette.hide_palette()
            else:
                self.palette.show_palette()

        bridge.triggered.connect(toggle_palette)

        # Register Ctrl+Space
        registered = ctypes.windll.user32.RegisterHotKey(
            None, HOTKEY_ID, MOD_CTRL | MOD_NOREPEAT, VK_SPACE
        )
        if not registered:
            print("WARNING: Failed to register Ctrl+Space hotkey.")
        else:
            print("Hotkey: Ctrl+Space")

        hotkey_filter = HotkeyFilter(lambda: bridge.triggered.emit())
        self.qapp.installNativeEventFilter(hotkey_filter)

        # System tray
        tray = QSystemTrayIcon()
        tray.setToolTip("DCS Command Palette (Ctrl+Space)")
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show Palette")
        show_action.triggered.connect(self.palette.show_palette)
        change_action = tray_menu.addAction("Change Aircraft")
        change_action.triggered.connect(self._change_aircraft)
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.qapp.quit)
        tray.setContextMenu(tray_menu)
        tray.show()

        print("DCS Command Palette running. Press Ctrl+Space to open.")

        ret = self.qapp.exec()

        ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        self.usage.save()
        self.sender.close()
        sys.exit(ret)


def main() -> None:
    app = App()
    app.run()


if __name__ == "__main__":
    main()
