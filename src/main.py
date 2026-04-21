from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
from typing import List, Optional

import re
import socket
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal  # type: ignore[import-untyped]
from PyQt6.QtGui import QIcon  # type: ignore[import-untyped]
from PyQt6.QtWidgets import (  # type: ignore[import-untyped]
    QApplication, QSystemTrayIcon, QMenu, QInputDialog, QFileDialog, QMessageBox,
)

from src.bios.state import BiosStateReader
from src.palette.commands import Command, CommandSource, load_all_commands
from src.config import settings as cfg
from src.config.settings import DCS_BIOS_HOST, DCS_BIOS_PORT, DCS_SAVED_GAMES, PALETTE_LISTEN_PORT, PROJECT_DIR
from src.config.window import ConfigWindow
from src.bios.sender import DCSBiosSender
from src.installer.wizard import check_dcs_bios, install_hook, is_hook_installed
from src.palette.overlay import CommandPalette
from src.detection import (
    detect_dcs_install_dir,
    find_bios_json,
    get_aircraft_input_name,
    get_aircraft_saved_name,
    get_selected_aircraft,
    list_installed_aircraft,
    resolve_unit_type_to_module,
    save_dcs_install_dir,
    save_selected_aircraft,
    suggest_bios_aircraft,
    _read_settings,
    _save_settings,
)
from src.lib.logging_setup import setup_logging
from src.palette.usage import UsageTracker

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
        try:
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
        except Exception:
            # Never let exceptions (including KeyboardInterrupt) crash the hook
            pass

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
    # Fired by NavJoystickListener on a button edge.
    # Args: action_name ("up" | "down" | "activate"), is_press (True | False)
    # Consumed on the Qt thread and dispatched to the palette.
    nav_triggered = pyqtSignal(str, bool)


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


class JoystickHotkeyListener:
    """Polls for a specific joystick button press to toggle the palette.

    Only active when the configured hotkey starts with "Joy" (e.g. "Joy0_Button3").
    """

    _JOY_RE = re.compile(r"^Joy(\d+)_Button(\d+)$")

    def __init__(self, hotkey: str, callback: object) -> None:
        self._callback = callback
        self._joy_id: int = -1
        self._button: int = -1
        self._running = False
        self._thread: threading.Thread | None = None

        match = self._JOY_RE.match(hotkey)
        if match:
            self._joy_id = int(match.group(1))
            self._button = int(match.group(2))

    @property
    def is_joystick_hotkey(self) -> bool:
        return self._joy_id >= 0

    def start(self) -> bool:
        if not self.is_joystick_hotkey:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Joystick hotkey listener started for Joy%d Button%d",
            self._joy_id, self._button,
        )
        return True

    def _poll_loop(self) -> None:
        from src.lib.joystick import is_button_pressed

        was_pressed = False
        while self._running:
            try:
                pressed = is_button_pressed(self._joy_id, self._button)
                # Trigger on press edge (transition from not-pressed to pressed)
                if pressed and not was_pressed:
                    if callable(self._callback):
                        self._callback()  # type: ignore[operator]
                was_pressed = pressed
            except Exception:
                logger.exception("Joystick hotkey poll error")
            time.sleep(0.05)  # 50ms poll interval

    def stop(self) -> None:
        self._running = False


class NavJoystickListener:
    """Polls optional joystick bindings for palette navigation (up/down).

    Each binding is a string in the same format accepted by the palette
    toggle hotkey (``Joy<id>_Button<num>``); non-joystick or empty strings
    are ignored.  Fires the given callback on each rising edge only while
    ``is_active()`` returns True — so bindings don't eat joystick inputs
    when the palette is hidden.
    """

    _JOY_RE = re.compile(r"^Joy(\d+)_Button(\d+)$")

    def __init__(
        self,
        bindings: dict[str, str],
        on_action: "callable",  # type: ignore[valid-type]
        is_active: "callable",  # type: ignore[valid-type]
        repeat_actions: Optional[set] = None,
    ) -> None:
        # bindings: {"up": "Joy0_Button5", "down": "", "activate": "Joy0_Button7"}
        # repeat_actions: names that auto-repeat while held (e.g. {"up","down"}).
        # Actions not in this set fire once per press edge.
        self._entries: list[tuple[str, int, int]] = []
        for action_name, combo in bindings.items():
            if not combo:
                continue
            m = self._JOY_RE.match(combo)
            if m:
                self._entries.append(
                    (action_name, int(m.group(1)), int(m.group(2))),
                )
        self._on_action = on_action
        self._is_active = is_active
        self._repeat_actions: set = set(repeat_actions or ())
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def has_joystick_bindings(self) -> bool:
        return bool(self._entries)

    def start(self) -> bool:
        if not self.has_joystick_bindings:
            return False
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, name="NavJoystickListener", daemon=True,
        )
        self._thread.start()
        logger.info(
            "Nav joystick listener started for %d binding(s)",
            len(self._entries),
        )
        return True

    def stop(self) -> None:
        self._running = False

    # Key-repeat timing — matches Windows default "slow" for arrow keys.
    # Initial delay before the first repeat; then fire every REPEAT_INTERVAL
    # until the button is released.  12 Hz feels natural for list nav.
    _INITIAL_DELAY = 0.4
    _REPEAT_INTERVAL = 0.08

    def _poll_loop(self) -> None:
        from src.lib.joystick import is_button_pressed

        # Per-button state: (currently_pressed, first_press_time, last_fire_time)
        state: dict[tuple[int, int], tuple[bool, float, float]] = {}

        def _fire(action_name: str, is_press: bool) -> None:
            try:
                if self._is_active():
                    self._on_action(action_name, is_press)
            except Exception:  # noqa: BLE001
                logger.exception("nav callback failed")

        while self._running:
            try:
                now = time.time()
                for action_name, joy_id, button in self._entries:
                    key = (joy_id, button)
                    pressed = is_button_pressed(joy_id, button)
                    was_pressed, first_press, last_fire = state.get(
                        key, (False, 0.0, 0.0),
                    )
                    if pressed and not was_pressed:
                        # Initial press edge — fire once.
                        _fire(action_name, True)
                        state[key] = (True, now, now)
                    elif pressed and was_pressed:
                        # Button held — only repeat if this action opted in.
                        # Activate / select shouldn't auto-fire.
                        if (action_name in self._repeat_actions
                                and now - first_press >= self._INITIAL_DELAY
                                and now - last_fire >= self._REPEAT_INTERVAL):
                            _fire(action_name, True)
                            state[key] = (True, first_press, now)
                    elif not pressed and was_pressed:
                        # Release edge — fire so the palette can finish any
                        # hold state (momentary release / spring-loaded recenter).
                        _fire(action_name, False)
                        state[key] = (False, 0.0, 0.0)
            except Exception:  # noqa: BLE001
                logger.exception("Nav joystick poll error")
            time.sleep(0.05)


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


def _create_tray_icon() -> QIcon:
    """Create a simple tray icon: a blue/white command palette symbol."""
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPen
    from PyQt6.QtCore import Qt, QRect

    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))  # transparent

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Blue rounded rectangle background
    painter.setBrush(QColor(60, 120, 220))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 12, 12)

    # White ">_" prompt symbol
    painter.setPen(QPen(QColor(255, 255, 255), 4))
    font = QFont("Consolas", 32, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(QRect(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, ">_")

    painter.end()
    return QIcon(pixmap)


class App:
    """Main application class managing the palette lifecycle."""

    def __init__(self, aircraft_override: Optional[str] = None) -> None:
        self.qapp = QApplication(sys.argv)
        self.qapp.setQuitOnLastWindowClosed(False)

        # First-run setup (installs hook, offers DCS-BIOS)
        self._first_run_setup()

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
        self.sender = DCSBiosSender(host=cfg.DCS_BIOS_HOST, port=cfg.DCS_BIOS_PORT)
        self.state_reader = BiosStateReader()
        self.state_reader.start()
        self.palette: Optional[CommandPalette] = None
        self._bios_missing = False  # True if no BIOS JSON found for current aircraft
        self._bios_fallback_offered = False  # True after we've shown the fallback dialog
        self._load_commands()

        # Clean up any leftover shutdown file
        self._cleanup_shutdown_file()

    def _first_run_setup(self) -> None:
        """On first run (no settings.json), guide the user through setup.

        Installs the Lua hook and offers to install DCS-BIOS via Qt dialogs.
        """
        settings = _read_settings()
        if settings.get("setup_complete"):
            return

        logger.info("First run detected, running setup wizard.")

        QMessageBox.information(
            None,
            "DCS Command Palette - Welcome",
            "Welcome to DCS Command Palette!\n\n"
            "This appears to be the first launch. "
            "The setup wizard will help you configure the palette.",
        )

        # Install Lua hook
        if not is_hook_installed(DCS_SAVED_GAMES):
            answer = QMessageBox.question(
                None,
                "Install Lua Hook",
                "The Lua hook allows DCS to communicate with the palette.\n"
                "It will be installed to:\n"
                f"  {DCS_SAVED_GAMES}/Scripts/Hooks/\n\n"
                "Install the Lua hook now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                palette_dir = PROJECT_DIR
                if install_hook(palette_dir, DCS_SAVED_GAMES):
                    QMessageBox.information(
                        None,
                        "Hook Installed",
                        "Lua hook installed successfully.\n"
                        "The palette will auto-start when you begin a DCS mission.",
                    )
                else:
                    QMessageBox.warning(
                        None,
                        "Hook Installation Failed",
                        "Could not install the Lua hook.\n"
                        "You can install it later from Settings.",
                    )
        else:
            logger.info("Lua hook already installed, skipping.")

        # Check DCS-BIOS
        if not check_dcs_bios(DCS_SAVED_GAMES):
            answer = QMessageBox.question(
                None,
                "Install DCS-BIOS",
                "DCS-BIOS is not installed.\n\n"
                "DCS-BIOS provides cockpit control integration "
                "(switches, dials, etc.).\n"
                "Without it, only keyboard shortcuts will be available.\n\n"
                "Download and install DCS-BIOS now?\n"
                "(Requires internet connection, ~10 MB download)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    from src.bios.installer import (
                        backup_scripts,
                        download_zip,
                        ensure_export_lua,
                        get_latest_release_url,
                        install_bios,
                    )

                    QMessageBox.information(
                        None,
                        "Downloading DCS-BIOS",
                        "Downloading DCS-BIOS from GitHub...\n"
                        "This may take a moment. Click OK to start.",
                    )

                    url, tag = get_latest_release_url()
                    if url:
                        zip_data = download_zip(url)
                        if zip_data:
                            backup_scripts(DCS_SAVED_GAMES)
                            if install_bios(DCS_SAVED_GAMES, zip_data):
                                ensure_export_lua(DCS_SAVED_GAMES)
                                QMessageBox.information(
                                    None,
                                    "DCS-BIOS Installed",
                                    f"DCS-BIOS {tag} installed successfully!",
                                )
                            else:
                                QMessageBox.warning(
                                    None,
                                    "DCS-BIOS Error",
                                    "Failed to extract DCS-BIOS.\n"
                                    "You can install it later from Settings.",
                                )
                        else:
                            QMessageBox.warning(
                                None,
                                "Download Failed",
                                "Could not download DCS-BIOS.\n"
                                "Check your internet connection and try again from Settings.",
                            )
                    else:
                        QMessageBox.warning(
                            None,
                            "DCS-BIOS Error",
                            "Could not find DCS-BIOS release.\n"
                            "You can install it later from Settings.",
                        )
                except Exception as e:
                    logger.exception("DCS-BIOS installation failed")
                    QMessageBox.warning(
                        None,
                        "DCS-BIOS Error",
                        f"Installation failed: {e}\n"
                        "You can install DCS-BIOS later from Settings.",
                    )
        else:
            logger.info("DCS-BIOS already installed, skipping.")

        # Mark setup as complete
        settings["setup_complete"] = True
        from src.detection import _save_settings
        _save_settings(settings)
        logger.info("First-run setup complete.")

    @staticmethod
    def _load_display_settings() -> None:
        """Load display preferences from settings.json into config module."""
        settings = _read_settings()
        cfg.SHOW_IDENTIFIERS = bool(settings.get("show_identifiers", False))
        cfg.SHOW_UNBOUND = bool(settings.get("show_unbound", False))
        cfg.AUTO_HIDE_SECONDS = int(settings.get("auto_hide_seconds", 5))
        cfg.OVERLAY_POSITION = str(settings.get("overlay_position", "top-center"))
        cfg.DCS_BIOS_HOST = str(settings.get("dcs_bios_host", "127.0.0.1"))
        cfg.DCS_BIOS_PORT = int(settings.get("dcs_bios_port", 7778))
        cfg.MAX_RESULTS = max(3, min(30, int(settings.get("max_results", 12))))

        # Text size: scale base font constants by preset multiplier
        _TEXT_SCALES = {
            "tiny": 0.70, "small": 0.85, "normal": 1.0, "big": 1.2, "huge": 1.5,
        }
        _TEXT_BASE = {
            "SEARCH_FONT_SIZE": 18,
            "IDENTIFIER_FONT_SIZE": 14,
            "DESCRIPTION_FONT_SIZE": 12,
            "CATEGORY_FONT_SIZE": 11,
            "COMBO_FONT_SIZE": 10,
            "SUBMENU_BUTTON_FONT_SIZE": 13,
            "SUBMENU_HEADER_FONT_SIZE": 12,
            "STRING_INPUT_FONT_SIZE": 14,
            "RESULT_ITEM_HEIGHT": 52,
        }
        text_size = str(settings.get("text_size", "normal"))
        scale = _TEXT_SCALES.get(text_size, 1.0)
        for name, base in _TEXT_BASE.items():
            setattr(cfg, name, max(1, int(round(base * scale))))
        cfg.TEXT_SIZE_PRESET = text_size

    def _load_commands(self) -> None:
        """Load (or reload) commands for the current aircraft."""
        logger.info("Loading commands for %s...", self.aircraft)

        input_name = get_aircraft_input_name(self.dcs_dir, self.aircraft) if self.dcs_dir else None

        # Check for a BIOS aircraft override (set when user accepted a fallback suggestion)
        settings = _read_settings()
        bios_override = settings.get("bios_aircraft_override")
        if isinstance(bios_override, str) and bios_override:
            bios_json = find_bios_json(DCS_SAVED_GAMES, bios_override)
            if bios_json:
                logger.info("Using BIOS override aircraft: %s", bios_override)
        else:
            bios_json = find_bios_json(DCS_SAVED_GAMES, self.aircraft or "")
        saved_name = get_aircraft_saved_name(DCS_SAVED_GAMES, self.aircraft or "")

        if bios_json:
            logger.info("DCS-BIOS JSON: %s", bios_json)
            self._bios_missing = False
        else:
            logger.warning("No DCS-BIOS JSON found for %s", self.aircraft)
            self._bios_missing = True
            self._bios_fallback_offered = False
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
            self.palette = CommandPalette(commands, self.usage, self.sender, self.state_reader)

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
            # Clear any BIOS override when explicitly changing aircraft
            settings = _read_settings()
            settings.pop("bios_aircraft_override", None)
            _save_settings(settings)
            self._load_commands()
            logger.info("Switched to %s", choice)

    def _offer_bios_fallback(self) -> None:
        """Show a dialog suggesting a similar aircraft for DCS-BIOS controls."""
        self._bios_fallback_offered = True
        suggestion = suggest_bios_aircraft(DCS_SAVED_GAMES, self.aircraft or "")

        if suggestion:
            answer = QMessageBox.question(
                None,
                "DCS-BIOS - Aircraft Not Found",
                f"No DCS-BIOS definition found for '{self.aircraft}'.\n\n"
                f"Would you like to use '{suggestion}' instead?\n"
                f"(This is common for mod aircraft based on a stock plane.)\n\n"
                f"Choose 'No' to open Settings and select manually.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                logger.info("User accepted BIOS fallback: %s -> %s", self.aircraft, suggestion)
                # Save the BIOS override but keep the aircraft name
                settings = _read_settings()
                settings["bios_aircraft_override"] = suggestion
                _save_settings(settings)
                # Reload with the fallback BIOS JSON
                self._load_commands()
                return
        else:
            QMessageBox.warning(
                None,
                "DCS-BIOS - Aircraft Not Found",
                f"No DCS-BIOS definition found for '{self.aircraft}',\n"
                f"and no similar aircraft could be suggested.\n\n"
                f"Opening Settings so you can select one manually.",
            )

        # Open settings if user declined or no suggestion
        self._open_config()

    def _apply_nav_bindings(self, settings: dict) -> None:
        """Install optional palette navigation bindings (up / down / activate).

        Each binding can be either a keyboard combo (e.g. ``Ctrl+J``) —
        registered as a QShortcut on the palette — or a joystick button
        (``Joy<id>_Button<num>``) — polled in a background thread.

        Bindings only fire while the palette is visible so they don't eat
        stick inputs during flight.  Up/Down auto-repeat while held;
        Activate fires once per press edge.
        """
        up = str(settings.get("hotkey_nav_up", ""))
        down = str(settings.get("hotkey_nav_down", ""))
        activate = str(settings.get("hotkey_nav_activate", ""))

        # Keyboard shortcuts — handled by Qt directly
        if self.palette is not None:
            self.palette.apply_keyboard_nav_bindings(up, down, activate)

        # Tear down any existing joystick listener
        if self._nav_joy_listener is not None:
            self._nav_joy_listener.stop()
            self._nav_joy_listener = None

        # Joystick polling — only if at least one is a joystick binding
        def _on_action(name: str, is_press: bool) -> None:
            # Bridge back to the Qt thread via a queued signal
            self._bridge.nav_triggered.emit(name, is_press)

        def _is_active() -> bool:
            return bool(self.palette is not None and self.palette.isVisible())

        self._nav_joy_listener = NavJoystickListener(
            bindings={"up": up, "down": down, "activate": activate},
            on_action=_on_action,
            is_active=_is_active,
            repeat_actions={"up", "down"},  # activate doesn't auto-repeat
        )
        if self._nav_joy_listener.has_joystick_bindings:
            self._nav_joy_listener.start()

    def _install_hotkey(self, hotkey: str) -> None:
        """Set up the hotkey listener (joystick or keyboard) for the given combo."""
        # Joystick hotkey listener (if hotkey is a joystick button)
        self._joy_listener = JoystickHotkeyListener(
            hotkey, lambda: self._bridge.triggered.emit(),
        )
        if self._joy_listener.is_joystick_hotkey:
            self._joy_listener.start()

        # Low-level keyboard hook (works even when DCS has focus)
        self._kb_hook = LowLevelKeyboardHook(lambda: self._bridge.triggered.emit())
        if not self._joy_listener.is_joystick_hotkey:
            if not self._kb_hook.install():
                logger.warning("Falling back to RegisterHotKey (won't work in fullscreen DCS)")
                ctypes.windll.user32.RegisterHotKey(None, 1, 0x0002 | 0x4000, VK_SPACE)

        self._configured_hotkey = hotkey

    def _reload_hotkey(self) -> None:
        """Re-read the hotkey from settings and swap listeners if changed."""
        settings = _read_settings()
        new_hotkey = str(settings.get("hotkey", "Ctrl+Space"))
        if new_hotkey == self._configured_hotkey:
            return

        logger.info("Hotkey changed: %s → %s", self._configured_hotkey, new_hotkey)

        # Tear down old listeners
        if self._joy_listener:
            self._joy_listener.stop()
            self._joy_listener = None
        if self._kb_hook:
            self._kb_hook.uninstall()
            self._kb_hook = None

        # Install new ones
        self._install_hotkey(new_hotkey)

        # Update tray tooltip
        if hasattr(self, "_tray") and self._tray:
            self._tray.setToolTip(f"DCS Command Palette ({new_hotkey})")

    def _on_config_changed(self, new_dcs_dir: str, new_aircraft: str) -> None:
        """Called when the config window applies changes."""
        self._load_display_settings()
        self._reload_hotkey()
        # Re-create sender with potentially updated BIOS host/port
        self.sender.close()
        self.sender = DCSBiosSender(host=cfg.DCS_BIOS_HOST, port=cfg.DCS_BIOS_PORT)
        if self.palette:
            self.palette._sender = self.sender
            # Live-reapply font sizes / result count / row heights
            self.palette._apply_display_settings()
        # Apply (or reapply) navigation bindings — user may have changed them
        self._apply_nav_bindings(_read_settings())
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
        from src.config.window import ConfigWindow as CW
        dialog = CW(
            current_dcs_dir=self.dcs_dir or "",
            current_aircraft=self.aircraft or "",
            on_aircraft_changed=self._on_config_changed,
            bios_connected=self.state_reader.connected,
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
                # On first open with missing BIOS, offer a fallback
                if self._bios_missing and not self._bios_fallback_offered:
                    self._offer_bios_fallback()
                self.palette.show_palette()

        bridge.triggered.connect(toggle_palette)

        def dispatch_nav(action: str, is_press: bool) -> None:
            if not self.palette or not self.palette.isVisible():
                return
            if not is_press:
                # Release edge — only Activate cares (to end a hold).
                if action == "activate":
                    self.palette.nav_deactivate()
                return
            # Press edge
            if action == "up":
                self.palette.nav_select_up()
            elif action == "down":
                self.palette.nav_select_down()
            elif action == "activate":
                self.palette.nav_activate()

        bridge.nav_triggered.connect(dispatch_nav)

        # UDP toggle listener (for triggering from inside DCS via Lua hook)
        udp_listener = UDPToggleListener(
            PALETTE_LISTEN_PORT,
            lambda: bridge.triggered.emit(),
        )
        udp_listener.start()

        # Read configured hotkey
        settings = _read_settings()
        configured_hotkey = str(settings.get("hotkey", "Ctrl+Space"))

        # Store references for hotkey reloading
        self._bridge = bridge
        self._joy_listener: Optional[JoystickHotkeyListener] = None
        self._kb_hook: Optional[LowLevelKeyboardHook] = None
        self._configured_hotkey = configured_hotkey
        self._install_hotkey(configured_hotkey)

        # Optional user-configured navigation bindings (up / down).
        self._nav_joy_listener: Optional[NavJoystickListener] = None
        self._apply_nav_bindings(settings)

        # System tray
        self._tray = tray = QSystemTrayIcon(_create_tray_icon())
        tray.setToolTip(f"DCS Command Palette ({configured_hotkey})")
        tray.activated.connect(
            lambda reason: self.palette.show_palette()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
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

        # Pre-warm ConfigWindow import in background so first settings open is instant
        def _preimport_config() -> None:
            import threading
            def _do_import() -> None:
                try:
                    from src.config.window import ConfigWindow  # noqa: F401
                    logger.debug("ConfigWindow pre-imported")
                except Exception:
                    pass
            threading.Thread(target=_do_import, daemon=True).start()

        QTimer.singleShot(2000, _preimport_config)

        logger.info("DCS Command Palette running. Press %s to open.", configured_hotkey)

        ret = self.qapp.exec()

        if self._joy_listener:
            self._joy_listener.stop()
        if self._nav_joy_listener is not None:
            self._nav_joy_listener.stop()
        if self._kb_hook:
            self._kb_hook.uninstall()
        udp_listener.stop()
        self._cleanup_shutdown_file()
        self.usage.save()
        self.state_reader.stop()
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


def _ensure_single_instance() -> bool:
    """Ensure only one instance of the palette is running.

    Uses a Windows named mutex. Returns True if this is the only instance,
    False if another is already running.
    """
    ERROR_ALREADY_EXISTS = 183
    mutex_name = "DCSCommandPalette_SingleInstance_Mutex"
    # CreateMutexW returns a handle; if the mutex already exists, GetLastError == 183
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    # Keep the handle alive for the lifetime of the process (it's freed on exit)
    _ensure_single_instance._handle = handle  # type: ignore[attr-defined]
    return True


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

    if not _ensure_single_instance():
        logger.warning("Another instance is already running. Exiting.")
        sys.exit(0)

    logger.info("DCS Command Palette v%s (%s)", _get_version(), _get_git_commit())

    # Allow Ctrl+C to cleanly quit
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = App(aircraft_override=args.aircraft)
    app.run()


if __name__ == "__main__":
    main()
