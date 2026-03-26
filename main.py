from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
from typing import List, Optional

import socket
import threading

from PyQt6.QtCore import QObject, pyqtSignal  # type: ignore[import-untyped]
from PyQt6.QtWidgets import (  # type: ignore[import-untyped]
    QApplication, QSystemTrayIcon, QMenu, QInputDialog, QFileDialog, QMessageBox,
)

from commands import Command, CommandSource, load_all_commands
import config as cfg
from config import DCS_BIOS_HOST, DCS_BIOS_PORT, DCS_SAVED_GAMES, PALETTE_LISTEN_PORT, PROJECT_DIR
from config_window import ConfigWindow
from dcs_bios import DCSBiosSender
from overlay import CommandPalette
from setup import (
    detect_dcs_install_dir,
    find_bios_json,
    get_aircraft_input_name,
    get_aircraft_saved_name,
    get_selected_aircraft,
    list_installed_aircraft,
    resolve_unit_type_to_module,
    save_dcs_install_dir,
    save_selected_aircraft,
    _read_settings,
)
from logging_config import setup_logging
from usage_tracker import UsageTracker

logger = logging.getLogger(__name__)

# Win32 low-level keyboard hook constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
VK_SPACE = 0x20
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3

# LRESULT CALLBACK LowLevelKeyboardProc(int nCode, WPARAM wParam, LPARAM lParam)
LRESULT = ctypes.c_long
WPARAM = ctypes.c_ulonglong  # 64-bit on Win64
LPARAM = ctypes.c_longlong
_LLKeyboardProc = ctypes.CFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)

# Properly typed Win32 API calls
_SetWindowsHookExW = ctypes.windll.user32.SetWindowsHookExW
_SetWindowsHookExW.argtypes = [ctypes.c_int, _LLKeyboardProc, ctypes.c_void_p, ctypes.c_uint]
_SetWindowsHookExW.restype = ctypes.c_void_p

_UnhookWindowsHookEx = ctypes.windll.user32.UnhookWindowsHookEx
_UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_UnhookWindowsHookEx.restype = ctypes.c_bool

_CallNextHookEx = ctypes.windll.user32.CallNextHookEx
_CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, WPARAM, LPARAM]
_CallNextHookEx.restype = LRESULT


class LowLevelKeyboardHook:
    """Global keyboard hook that works even when DCS has focus.

    Uses SetWindowsHookExW with WH_KEYBOARD_LL which intercepts keys
    at a lower level than RegisterHotKey, working across all applications
    including fullscreen games.
    """

    def __init__(self, callback: object) -> None:
        self._callback = callback
        self._hook: ctypes.c_void_p | None = None
        self._ctrl_pressed = False
        # Must keep a reference to prevent garbage collection
        self._hook_proc = _LLKeyboardProc(self._ll_keyboard_proc)

    def _ll_keyboard_proc(self, nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0:
            # lParam points to KBDLLHOOKSTRUCT; first field is vkCode (DWORD)
            vk_code = ctypes.c_uint32.from_address(lParam).value

            if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                if vk_code in (VK_LCONTROL, VK_RCONTROL):
                    self._ctrl_pressed = True
                elif vk_code == VK_SPACE and self._ctrl_pressed:
                    self._ctrl_pressed = False
                    if callable(self._callback):
                        self._callback()  # type: ignore[operator]
                    # Return 1 to consume the key (don't pass Ctrl+Space to DCS)
                    return 1
            else:
                # Key up
                if vk_code in (VK_LCONTROL, VK_RCONTROL):
                    self._ctrl_pressed = False

        return _CallNextHookEx(self._hook, nCode, wParam, lParam)

    def install(self) -> bool:
        self._hook = _SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, None, 0)
        if not self._hook:
            logger.error("Failed to install low-level keyboard hook (error %d)",
                         ctypes.windll.kernel32.GetLastError())
            return False
        logger.info("Low-level keyboard hook installed (Ctrl+Space)")
        return True

    def uninstall(self) -> None:
        if self._hook:
            _UnhookWindowsHookEx(self._hook)
            self._hook = None


class HotkeyBridge(QObject):  # type: ignore[misc]
    triggered = pyqtSignal()


class UDPToggleListener:
    """Listens for TOGGLE_PALETTE UDP packets from the DCS Lua hook."""

    def __init__(self, port: int, callback: object) -> None:
        self._port = port
        self._callback = callback
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.settimeout(1.0)
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            self._sock.bind(("127.0.0.1", self._port))
        except OSError as e:
            logger.error("Failed to bind UDP listener on port %d: %s", self._port, e)
            return False
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        logger.info("UDP toggle listener on port %d", self._port)
        return True

    def _listen(self) -> None:
        while self._running:
            try:
                data, _addr = self._sock.recvfrom(256)
                msg = data.decode("ascii", errors="ignore").strip()
                if msg == "TOGGLE_PALETTE":
                    logger.debug("Received TOGGLE_PALETTE via UDP")
                    if callable(self._callback):
                        self._callback()  # type: ignore[operator]
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.exception("UDP listener error")
                break

    def stop(self) -> None:
        self._running = False
        self._sock.close()


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
    aircraft_list = list_installed_aircraft(dcs_dir)
    if not aircraft_list:
        logger.warning("No aircraft found.")
        return None

    # Check if the saved aircraft is still valid (installed)
    saved = get_selected_aircraft()
    if saved and saved in aircraft_list:
        return saved

    if saved:
        logger.warning("Saved aircraft %r not found in installed modules, re-selecting.", saved)

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
        Command(
            identifier="__RESTART_PALETTE__",
            description="Restart Palette",
            category="Palette",
            source=CommandSource.KEYBOARD,
            search_text="restart reload palette refresh",
            key_combo="",
        ),
        Command(
            identifier="__EXIT_PALETTE__",
            description="Exit Palette",
            category="Palette",
            source=CommandSource.KEYBOARD,
            search_text="exit quit close palette stop shutdown",
            key_combo="",
        ),
    ]
    return builtins + commands


SHUTDOWN_FILE = os.path.join(PROJECT_DIR, ".shutdown")


class App:
    """Main application class managing the palette lifecycle."""

    def __init__(self, aircraft_override: Optional[str] = None) -> None:
        self.qapp = QApplication(sys.argv)
        self.qapp.setQuitOnLastWindowClosed(False)

        # Setup
        self.dcs_dir = _ensure_dcs_install_dir(self.qapp)
        if not self.dcs_dir:
            logger.error("No DCS installation directory. Exiting.")
            sys.exit(1)

        # Use CLI-provided aircraft if given, otherwise interactive selection
        if aircraft_override:
            # Resolve DCS unit type (e.g., "FA-18C_hornet") to module name ("FA-18C")
            resolved = resolve_unit_type_to_module(self.dcs_dir, aircraft_override)
            if resolved:
                logger.info("Resolved unit type %r to module %r", aircraft_override, resolved)
                self.aircraft: Optional[str] = resolved
            else:
                # Show what's available so the user can fix their --aircraft arg
                available = list_installed_aircraft(self.dcs_dir)
                logger.error(
                    "Could not resolve aircraft %r. Available modules: %s",
                    aircraft_override, ", ".join(available) if available else "(none found)",
                )
                self.aircraft = aircraft_override
            save_selected_aircraft(self.aircraft)
            logger.info("Aircraft set from command line: %s", self.aircraft)
        else:
            self.aircraft = _ensure_aircraft(self.dcs_dir)
        if not self.aircraft:
            logger.error("No aircraft selected. Exiting.")
            sys.exit(1)

        self._load_display_settings()
        self.usage = UsageTracker()
        self.sender = DCSBiosSender()
        self.palette: Optional[CommandPalette] = None
        self._load_commands()

        # Clean up any leftover shutdown file
        self._cleanup_shutdown_file()

    @staticmethod
    def _load_display_settings() -> None:
        """Load display preferences from settings.json into config module."""
        settings = _read_settings()
        cfg.SHOW_IDENTIFIERS = bool(settings.get("show_identifiers", False))
        cfg.AUTO_HIDE_SECONDS = int(settings.get("auto_hide_seconds", 5))

    def _load_commands(self) -> None:
        """Load (or reload) commands for the current aircraft."""
        logger.info("Loading commands for %s...", self.aircraft)

        input_name = get_aircraft_input_name(self.dcs_dir, self.aircraft) if self.dcs_dir else None
        bios_json = find_bios_json(DCS_SAVED_GAMES, self.aircraft or "")
        saved_name = get_aircraft_saved_name(DCS_SAVED_GAMES, self.aircraft or "")

        if bios_json:
            logger.info("DCS-BIOS JSON: %s", bios_json)
        else:
            logger.warning("No DCS-BIOS JSON found for %s", self.aircraft)
        if saved_name:
            logger.info("User keybinds: Config/Input/%s/", saved_name)

        commands = load_all_commands(
            dcs_install_dir=self.dcs_dir or "",
            aircraft_module=self.aircraft or "",
            aircraft_input_name=input_name or self.aircraft or "",
            dcs_saved_games=DCS_SAVED_GAMES,
            aircraft_saved_name=saved_name,
            controls_json_path=bios_json,
        )
        commands = _add_palette_commands(commands)

        bios_count = sum(1 for c in commands if c.source == CommandSource.DCS_BIOS)
        kb_count = sum(1 for c in commands if c.source == CommandSource.KEYBOARD)
        logger.info("%d commands loaded (%d BIOS, %d keyboard/palette)", len(commands), bios_count, kb_count)

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
        elif identifier == "__EXIT_PALETTE__":
            logger.info("Exit requested from palette command.")
            self.qapp.quit()
        elif identifier == "__RESTART_PALETTE__":
            self._restart()

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
            logger.info("Switched to %s", choice)

    def _on_config_changed(self, new_dcs_dir: str, new_aircraft: str) -> None:
        """Called when the config window applies changes."""
        self._load_display_settings()
        changed = False
        if new_dcs_dir != self.dcs_dir:
            self.dcs_dir = new_dcs_dir
            changed = True
        if new_aircraft != self.aircraft:
            self.aircraft = new_aircraft
            changed = True
        if changed:
            self._load_commands()

    def _open_config(self) -> None:
        """Show the settings dialog."""
        dialog = ConfigWindow(
            current_dcs_dir=self.dcs_dir or "",
            current_aircraft=self.aircraft or "",
            on_aircraft_changed=self._on_config_changed,
        )
        dialog.exec()

    def _restart(self) -> None:
        """Restart the palette by re-launching the same process."""
        import subprocess
        logger.info("Restarting palette...")
        subprocess.Popen(
            [sys.executable] + sys.argv,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        self.qapp.quit()

    def _cleanup_shutdown_file(self) -> None:
        """Remove any leftover shutdown file from a previous run."""
        try:
            os.remove(SHUTDOWN_FILE)
        except FileNotFoundError:
            pass

    def _check_shutdown(self) -> None:
        """Check if the Lua hook has requested a shutdown."""
        if os.path.exists(SHUTDOWN_FILE):
            logger.info("Shutdown signal received from DCS hook.")
            self._cleanup_shutdown_file()
            self.qapp.quit()

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

        # UDP toggle listener (for triggering from inside DCS via Lua hook)
        udp_listener = UDPToggleListener(
            PALETTE_LISTEN_PORT,
            lambda: bridge.triggered.emit(),
        )
        udp_listener.start()

        # Low-level keyboard hook (works even when DCS has focus)
        kb_hook = LowLevelKeyboardHook(lambda: bridge.triggered.emit())
        if not kb_hook.install():
            logger.warning("Falling back to RegisterHotKey (won't work in fullscreen DCS)")
            ctypes.windll.user32.RegisterHotKey(None, 1, 0x0002 | 0x4000, VK_SPACE)

        # System tray
        tray = QSystemTrayIcon()
        tray.setToolTip("DCS Command Palette (Ctrl+Space)")
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show Palette")
        show_action.triggered.connect(self.palette.show_palette)
        change_action = tray_menu.addAction("Change Aircraft")
        change_action.triggered.connect(self._change_aircraft)
        settings_action = tray_menu.addAction("Settings")
        settings_action.triggered.connect(self._open_config)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.qapp.quit)
        tray.setContextMenu(tray_menu)
        tray.show()

        # Clean up any leftover shutdown file RIGHT BEFORE starting the watcher,
        # so we don't immediately self-kill from a stale file
        self._cleanup_shutdown_file()

        # Periodically check for shutdown signal from Lua hook (every 2 seconds)
        from PyQt6.QtCore import QTimer  # type: ignore[import-untyped]
        shutdown_timer = QTimer()
        shutdown_timer.timeout.connect(self._check_shutdown)
        shutdown_timer.start(2000)

        logger.info("DCS Command Palette running. Press Ctrl+Space to open.")

        ret = self.qapp.exec()

        kb_hook.uninstall()
        udp_listener.stop()
        self._cleanup_shutdown_file()
        self.usage.save()
        self.sender.close()
        sys.exit(ret)


def _get_version() -> str:
    """Read version from pyproject.toml."""
    try:
        toml_path = os.path.join(PROJECT_DIR, "pyproject.toml")
        with open(toml_path, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("version"):
                    # version = "0.1.0"
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except (OSError, IndexError):
        pass
    return "unknown"


def _get_git_commit() -> str:
    """Get the current git short commit hash."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=PROJECT_DIR,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="DCS Command Palette")
    parser.add_argument(
        "--aircraft",
        help="Aircraft module name (e.g. FA-18C_hornet). "
             "Normally set automatically by the DCS Lua hook.",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    setup_logging(level=logging.DEBUG if args.debug else logging.INFO)
    logger.info("DCS Command Palette v%s (%s)", _get_version(), _get_git_commit())

    app = App(aircraft_override=args.aircraft)
    app.run()


if __name__ == "__main__":
    main()
