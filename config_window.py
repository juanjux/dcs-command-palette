"""Settings dialog for DCS Command Palette."""
from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
from typing import Optional

from PyQt6.QtCore import Qt, QTimer  # type: ignore[import-untyped]
from PyQt6.QtWidgets import (  # type: ignore[import-untyped]
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from bios_installer import (
    backup_scripts,
    download_zip,
    ensure_export_lua,
    get_latest_release_url,
    install_bios,
    is_bios_installed,
)
from config import DCS_SAVED_GAMES, PROJECT_DIR
from setup import (
    _read_settings,
    _save_settings,
    detect_dcs_install_dir,
    find_bios_json,
    get_aircraft_saved_name,
    list_installed_aircraft,
)

logger = logging.getLogger(__name__)

def _get_version_string() -> str:
    """Get version and git commit for display."""
    version = "unknown"
    try:
        toml_path = os.path.join(PROJECT_DIR, "pyproject.toml")
        with open(toml_path, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("version"):
                    version = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    except (OSError, IndexError):
        pass

    commit = "unknown"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=PROJECT_DIR,
        )
        if result.returncode == 0:
            commit = result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass

    return f"v{version} ({commit})"


HOOK_FILENAME = "dcs_command_palette_hook.lua"
HOOK_SOURCE = os.path.join(PROJECT_DIR, HOOK_FILENAME)
HOOKS_DIR = os.path.join(DCS_SAVED_GAMES, "Scripts", "Hooks")
HOOK_DEST = os.path.join(HOOKS_DIR, HOOK_FILENAME)


class ConfigWindow(QDialog):  # type: ignore[misc]
    """Settings window for configuring the palette."""

    def __init__(
        self,
        current_dcs_dir: str,
        current_aircraft: str,
        on_aircraft_changed: object,
        bios_connected: bool = False,
        parent: object = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._dcs_dir = current_dcs_dir
        self._aircraft = current_aircraft
        self._on_aircraft_changed = on_aircraft_changed
        self._bios_connected = bios_connected
        self._setup_window()
        self._build_ui()
        self._populate()

    def _setup_window(self) -> None:
        self.setWindowTitle("DCS Command Palette - Settings")
        self.setMinimumWidth(550)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog
        )

    def showEvent(self, event: object) -> None:
        """Force the window to foreground when shown."""
        super().showEvent(event)  # type: ignore[arg-type]
        from PyQt6.QtCore import QTimer  # type: ignore[import-untyped]
        QTimer.singleShot(50, self._force_foreground)

    def _force_foreground(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = int(self.winId())
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
        our_thread = kernel32.GetCurrentThreadId()
        attached = False
        if fg_thread != our_thread:
            attached = bool(user32.AttachThreadInput(our_thread, fg_thread, True))
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        self.activateWindow()
        self.raise_()
        if attached:
            user32.AttachThreadInput(our_thread, fg_thread, False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- DCS Install Directory ---
        dcs_group = QGroupBox("DCS World Installation")
        dcs_layout = QVBoxLayout(dcs_group)

        dir_row = QHBoxLayout()
        self._dir_edit = QLineEdit()
        self._dir_edit.setReadOnly(True)
        dir_row.addWidget(self._dir_edit, stretch=1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_dcs_dir)
        dir_row.addWidget(browse_btn)

        detect_btn = QPushButton("Auto-detect")
        detect_btn.clicked.connect(self._auto_detect_dcs)
        dir_row.addWidget(detect_btn)

        dcs_layout.addLayout(dir_row)
        layout.addWidget(dcs_group)

        # --- Aircraft Selection ---
        aircraft_group = QGroupBox("Aircraft")
        aircraft_layout = QVBoxLayout(aircraft_group)

        combo_row = QHBoxLayout()
        self._aircraft_combo = QComboBox()
        self._aircraft_combo.setMinimumWidth(300)
        combo_row.addWidget(self._aircraft_combo, stretch=1)

        aircraft_layout.addLayout(combo_row)

        # Info labels
        self._bios_label = QLabel()
        self._bios_label.setStyleSheet("color: gray; font-size: 11px;")
        aircraft_layout.addWidget(self._bios_label)

        self._keybinds_label = QLabel()
        self._keybinds_label.setStyleSheet("color: gray; font-size: 11px;")
        aircraft_layout.addWidget(self._keybinds_label)

        self._aircraft_combo.currentTextChanged.connect(self._on_aircraft_combo_changed)

        layout.addWidget(aircraft_group)

        # --- Display Options ---
        display_group = QGroupBox("Display")
        display_layout = QVBoxLayout(display_group)

        self._show_ids_checkbox = QCheckBox("Show DCS-BIOS identifiers (e.g., FLAP_SW) below command names")
        display_layout.addWidget(self._show_ids_checkbox)

        autohide_row = QHBoxLayout()
        autohide_row.addWidget(QLabel("Auto-hide after inactivity (seconds, 0 = disabled):"))
        self._autohide_edit = QLineEdit()
        self._autohide_edit.setMaximumWidth(60)
        autohide_row.addWidget(self._autohide_edit)
        autohide_row.addStretch()
        display_layout.addLayout(autohide_row)

        layout.addWidget(display_group)

        # --- Hotkey ---
        hotkey_group = QGroupBox("Palette Shortcut")
        hotkey_layout = QHBoxLayout(hotkey_group)

        hotkey_layout.addWidget(QLabel("Toggle palette:"))
        self._hotkey_label = QLabel()
        self._hotkey_label.setStyleSheet(
            "font-weight: bold; font-size: 13px; padding: 4px 8px; "
            "background: rgba(50,50,70,200); border: 1px solid rgba(100,100,140,150); "
            "border-radius: 4px; min-width: 120px;"
        )
        self._hotkey_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hotkey_layout.addWidget(self._hotkey_label, stretch=1)

        self._set_hotkey_btn = QPushButton("Set Shortcut...")
        self._set_hotkey_btn.clicked.connect(self._capture_hotkey)
        hotkey_layout.addWidget(self._set_hotkey_btn)

        reset_hotkey_btn = QPushButton("Reset")
        reset_hotkey_btn.clicked.connect(self._reset_hotkey)
        hotkey_layout.addWidget(reset_hotkey_btn)

        layout.addWidget(hotkey_group)

        # --- Lua Hook ---
        hook_group = QGroupBox("DCS Lua Hook (auto-start/stop)")
        hook_layout = QVBoxLayout(hook_group)

        self._hook_status = QLabel()
        hook_layout.addWidget(self._hook_status)

        hook_btn_row = QHBoxLayout()
        self._install_hook_btn = QPushButton("Install Hook")
        self._install_hook_btn.clicked.connect(self._install_hook)
        hook_btn_row.addWidget(self._install_hook_btn)

        self._uninstall_hook_btn = QPushButton("Uninstall Hook")
        self._uninstall_hook_btn.clicked.connect(self._uninstall_hook)
        hook_btn_row.addWidget(self._uninstall_hook_btn)

        hook_btn_row.addStretch()
        hook_layout.addLayout(hook_btn_row)

        layout.addWidget(hook_group)

        # --- DCS-BIOS ---
        bios_group = QGroupBox("DCS-BIOS")
        bios_layout = QVBoxLayout(bios_group)

        self._bios_install_status = QLabel()
        bios_layout.addWidget(self._bios_install_status)

        self._bios_conn_status = QLabel()
        bios_layout.addWidget(self._bios_conn_status)

        self._bios_port_label = QLabel()
        self._bios_port_label.setStyleSheet("font-size: 11px; color: gray;")
        bios_layout.addWidget(self._bios_port_label)

        ip_port_row = QHBoxLayout()
        ip_port_row.addWidget(QLabel("DCS-BIOS IP:"))
        self._bios_ip_edit = QLineEdit()
        self._bios_ip_edit.setMaximumWidth(150)
        ip_port_row.addWidget(self._bios_ip_edit)
        ip_port_row.addWidget(QLabel("Port:"))
        self._bios_port_edit = QLineEdit()
        self._bios_port_edit.setMaximumWidth(80)
        ip_port_row.addWidget(self._bios_port_edit)
        ip_port_row.addStretch()
        bios_layout.addLayout(ip_port_row)

        bios_btn_row = QHBoxLayout()
        self._install_bios_btn = QPushButton("Install / Update DCS-BIOS")
        self._install_bios_btn.clicked.connect(self._install_or_update_bios)
        bios_btn_row.addWidget(self._install_bios_btn)
        bios_btn_row.addStretch()
        bios_layout.addLayout(bios_btn_row)

        layout.addWidget(bios_group)

        # --- Info ---
        info_group = QGroupBox("Info")
        info_layout = QVBoxLayout(info_group)

        version_label = QLabel(f"Version: {_get_version_string()}")
        version_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        info_layout.addWidget(version_label)

        self._saved_games_label = QLabel(f"DCS Saved Games: {DCS_SAVED_GAMES}")
        self._saved_games_label.setStyleSheet("font-size: 11px;")
        info_layout.addWidget(self._saved_games_label)

        self._project_label = QLabel(f"Palette directory: {PROJECT_DIR}")
        self._project_label.setStyleSheet("font-size: 11px;")
        info_layout.addWidget(self._project_label)

        log_path = os.path.join(PROJECT_DIR, "dcs_command_palette.log")
        self._log_label = QLabel(f"Log file: {log_path}")
        self._log_label.setStyleSheet("font-size: 11px;")
        info_layout.addWidget(self._log_label)

        layout.addWidget(info_group)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        apply_btn = QPushButton("Apply && Close")
        apply_btn.clicked.connect(self._apply_and_close)
        btn_row.addWidget(apply_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

    def _populate(self) -> None:
        """Fill the UI with current values."""
        self._dir_edit.setText(self._dcs_dir)
        self._refresh_aircraft_list()
        self._update_hook_status()
        self._update_bios_status()

        settings = _read_settings()
        self._show_ids_checkbox.setChecked(bool(settings.get("show_identifiers", False)))
        self._autohide_edit.setText(str(settings.get("auto_hide_seconds", 5)))

        self._pending_hotkey = str(settings.get("hotkey", "Ctrl+Space"))
        self._hotkey_label.setText(self._pending_hotkey)

        # DCS-BIOS connection status
        self._update_bios_connection()

        # DCS-BIOS IP/port
        self._bios_ip_edit.setText(str(settings.get("dcs_bios_host", "127.0.0.1")))
        self._bios_port_edit.setText(str(settings.get("dcs_bios_port", 7778)))
        port = settings.get("dcs_bios_port", 7778)
        self._bios_port_label.setText(
            f"Send port: {port} | Receive: multicast 239.255.50.10:5010"
        )

    def _refresh_aircraft_list(self) -> None:
        self._aircraft_combo.blockSignals(True)
        self._aircraft_combo.clear()

        aircraft_list = list_installed_aircraft(self._dcs_dir)
        self._aircraft_combo.addItems(aircraft_list)

        if self._aircraft in aircraft_list:
            self._aircraft_combo.setCurrentText(self._aircraft)
        elif aircraft_list:
            self._aircraft = aircraft_list[0]

        self._aircraft_combo.blockSignals(False)
        self._update_aircraft_info()

    def _on_aircraft_combo_changed(self, text: str) -> None:
        self._aircraft = text
        self._update_aircraft_info()

    def _update_aircraft_info(self) -> None:
        bios = find_bios_json(DCS_SAVED_GAMES, self._aircraft)
        saved = get_aircraft_saved_name(DCS_SAVED_GAMES, self._aircraft)

        if bios:
            self._bios_label.setText(f"DCS-BIOS JSON: {os.path.basename(bios)}")
        else:
            self._bios_label.setText("DCS-BIOS JSON: not found (BIOS controls will be unavailable)")

        if saved:
            self._keybinds_label.setText(f"User keybinds folder: Config/Input/{saved}/")
        else:
            self._keybinds_label.setText("User keybinds folder: not found (using defaults only)")

    def _update_hook_status(self) -> None:
        if os.path.isfile(HOOK_DEST):
            self._hook_status.setText("Status: Installed")
            self._hook_status.setStyleSheet("color: green; font-weight: bold;")
            self._install_hook_btn.setText("Reinstall Hook")
            self._uninstall_hook_btn.setEnabled(True)
        else:
            self._hook_status.setText("Status: Not installed")
            self._hook_status.setStyleSheet("color: orange; font-weight: bold;")
            self._install_hook_btn.setText("Install Hook")
            self._uninstall_hook_btn.setEnabled(False)

    def _browse_dcs_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Select DCS World Installation Directory", self._dcs_dir or "C:\\",
        )
        if path:
            self._dcs_dir = path
            self._dir_edit.setText(path)
            self._refresh_aircraft_list()

    def _auto_detect_dcs(self) -> None:
        detected = detect_dcs_install_dir()
        if detected:
            self._dcs_dir = detected
            self._dir_edit.setText(detected)
            self._refresh_aircraft_list()
        else:
            QMessageBox.warning(
                self, "Auto-detect",
                "Could not auto-detect DCS installation.\n"
                "Please use Browse to select the folder manually.",
            )

    def _install_hook(self) -> None:
        if not os.path.isfile(HOOK_SOURCE):
            QMessageBox.warning(
                self, "Install Hook",
                f"Hook source file not found:\n{HOOK_SOURCE}",
            )
            return

        os.makedirs(HOOKS_DIR, exist_ok=True)
        try:
            shutil.copy2(HOOK_SOURCE, HOOK_DEST)
            logger.info("Lua hook installed to %s", HOOK_DEST)
            QMessageBox.information(
                self, "Install Hook",
                f"Hook installed successfully to:\n{HOOK_DEST}\n\n"
                "The palette will auto-start when you enter a mission in DCS.",
            )
        except OSError as e:
            logger.error("Failed to install hook: %s", e)
            QMessageBox.critical(self, "Install Hook", f"Failed to install hook:\n{e}")

        self._update_hook_status()

    def _uninstall_hook(self) -> None:
        try:
            os.remove(HOOK_DEST)
            logger.info("Lua hook removed from %s", HOOK_DEST)
            QMessageBox.information(
                self, "Uninstall Hook", "Hook removed successfully.",
            )
        except OSError as e:
            logger.error("Failed to remove hook: %s", e)
            QMessageBox.critical(self, "Uninstall Hook", f"Failed to remove hook:\n{e}")

        self._update_hook_status()

    def _update_bios_status(self) -> None:
        if is_bios_installed(DCS_SAVED_GAMES):
            self._bios_install_status.setText("Status: Installed")
            self._bios_install_status.setStyleSheet("color: green; font-weight: bold;")
            self._install_bios_btn.setText("Update DCS-BIOS")
        else:
            self._bios_install_status.setText("Status: Not installed")
            self._bios_install_status.setStyleSheet("color: orange; font-weight: bold;")
            self._install_bios_btn.setText("Install DCS-BIOS")

    def _update_bios_connection(self) -> None:
        if self._bios_connected:
            self._bios_conn_status.setText("Connection: Connected (receiving state data)")
            self._bios_conn_status.setStyleSheet("color: green; font-size: 11px;")
        else:
            self._bios_conn_status.setText("Connection: Not connected (start a DCS mission)")
            self._bios_conn_status.setStyleSheet("color: orange; font-size: 11px;")

    def _install_or_update_bios(self) -> None:
        reply = QMessageBox.question(
            self,
            "Install / Update DCS-BIOS",
            "This will:\n"
            "1. Download the latest DCS-BIOS release from GitHub\n"
            "2. Back up your current Scripts/DCS-BIOS folder and Export.lua\n"
            "3. Extract the new DCS-BIOS into Scripts/\n"
            "4. Ensure Export.lua loads DCS-BIOS\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Fetch latest release URL
        self._install_bios_btn.setEnabled(False)
        self._bios_install_status.setText("Checking latest release...")
        self._bios_install_status.setStyleSheet("color: gray; font-weight: bold;")
        from PyQt6.QtWidgets import QApplication  # type: ignore[import-untyped]
        QApplication.processEvents()

        url, tag = get_latest_release_url()
        if not url:
            self._install_bios_btn.setEnabled(True)
            self._update_bios_status()
            QMessageBox.critical(
                self, "DCS-BIOS Install",
                "Could not find a DCS-BIOS download URL.\n"
                "Check your internet connection and try again.",
            )
            return

        # Download
        self._bios_install_status.setText(f"Downloading {tag}...")
        QApplication.processEvents()

        zip_data = download_zip(url)
        if not zip_data:
            self._install_bios_btn.setEnabled(True)
            self._update_bios_status()
            QMessageBox.critical(
                self, "DCS-BIOS Install",
                "Failed to download DCS-BIOS.\n"
                "Check your internet connection and try again.",
            )
            return

        # Backup
        self._bios_install_status.setText("Backing up current installation...")
        QApplication.processEvents()

        backup_dir = backup_scripts(DCS_SAVED_GAMES)

        # Install
        self._bios_install_status.setText("Installing...")
        QApplication.processEvents()

        if not install_bios(DCS_SAVED_GAMES, zip_data):
            self._install_bios_btn.setEnabled(True)
            self._update_bios_status()
            QMessageBox.critical(
                self, "DCS-BIOS Install",
                "Failed to extract DCS-BIOS zip.\n"
                "Check the log file for details.",
            )
            return

        # Ensure Export.lua
        lua_ok = ensure_export_lua(DCS_SAVED_GAMES)

        self._install_bios_btn.setEnabled(True)
        self._update_bios_status()

        backup_msg = f"Backup saved to:\n{backup_dir}\n\n" if backup_dir else ""
        lua_msg = "" if lua_ok else "\nWarning: Could not update Export.lua. Check manually."

        QMessageBox.information(
            self,
            "DCS-BIOS Install",
            f"DCS-BIOS {tag} installed successfully!\n\n"
            f"{backup_msg}"
            f"DCS-BIOS files are in:\n"
            f"{os.path.join(DCS_SAVED_GAMES, 'Scripts', 'DCS-BIOS')}"
            f"{lua_msg}",
        )

    def _capture_hotkey(self) -> None:
        """Open a dialog that waits for a key/button press to assign as hotkey."""
        dialog = _HotkeyCaptureDialog(self)
        if dialog.exec():
            self._pending_hotkey = dialog.captured_combo
            self._hotkey_label.setText(self._pending_hotkey or "Ctrl+Space")

    def _reset_hotkey(self) -> None:
        self._pending_hotkey = "Ctrl+Space"
        self._hotkey_label.setText("Ctrl+Space")

    def _apply_and_close(self) -> None:
        settings = _read_settings()
        settings["dcs_install_dir"] = self._dcs_dir
        settings["aircraft"] = self._aircraft
        settings["show_identifiers"] = self._show_ids_checkbox.isChecked()
        try:
            settings["auto_hide_seconds"] = int(self._autohide_edit.text())
        except ValueError:
            settings["auto_hide_seconds"] = 5
        settings["hotkey"] = self._pending_hotkey
        settings["dcs_bios_host"] = self._bios_ip_edit.text().strip() or "127.0.0.1"
        try:
            settings["dcs_bios_port"] = int(self._bios_port_edit.text())
        except ValueError:
            settings["dcs_bios_port"] = 7778
        _save_settings(settings)
        logger.info("Settings saved: dcs_dir=%s, aircraft=%s, hotkey=%s",
                     self._dcs_dir, self._aircraft, self._pending_hotkey)

        if callable(self._on_aircraft_changed):
            self._on_aircraft_changed(self._dcs_dir, self._aircraft)

        self.accept()


class _HotkeyCaptureDialog(QDialog):  # type: ignore[misc]
    """Modal dialog that captures a key combination or joystick button."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self.captured_combo: str = ""
        self.setWindowTitle("Set Shortcut")
        self.setMinimumSize(350, 120)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog
        )

        layout = QVBoxLayout(self)
        self._label = QLabel(
            "Press a key combination or joystick button...\n\n"
            "(Press Escape to cancel)"
        )
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("font-size: 14px; padding: 16px;")
        layout.addWidget(self._label)

        self._modifiers: list[str] = []

        # Start joystick polling timer
        self._joy_timer = QTimer(self)
        self._joy_timer.timeout.connect(self._poll_joystick)
        self._joy_timer.start(100)

    def _poll_joystick(self) -> None:
        """Check for joystick button presses."""
        try:
            from joystick_reader import poll_joystick_buttons
        except Exception:
            # If joystick_reader fails to import (e.g. not on Windows), just skip
            self._joy_timer.stop()
            return

        pressed = poll_joystick_buttons()
        if pressed:
            btn = pressed[0]  # Take the first pressed button
            self.captured_combo = f"Joy{btn.joy_id}_Button{btn.button}"
            self._label.setText(
                f"Captured: {self.captured_combo}\n({btn.joy_name})"
            )
            self._joy_timer.stop()
            QTimer.singleShot(400, self.accept)

    def keyPressEvent(self, event: object) -> None:
        from PyQt6.QtGui import QKeyEvent  # type: ignore[import-untyped]
        if not isinstance(event, QKeyEvent):
            return

        key = event.key()

        # Escape cancels
        if key == Qt.Key.Key_Escape:
            self._joy_timer.stop()
            self.reject()
            return

        # Collect modifiers
        mods = event.modifiers()
        parts: list[str] = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")

        # Skip if only a modifier key was pressed (wait for the actual key)
        modifier_keys = {
            Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift,
            Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
        }
        if key in modifier_keys:
            self._label.setText(f"{'+'.join(parts)}+...\n\n(Press Escape to cancel)")
            return

        # Map the key to a readable name
        key_name = _qt_key_to_name(key)
        if key_name:
            parts.append(key_name)

        if parts:
            self.captured_combo = "+".join(parts)
            self._label.setText(f"Captured: {self.captured_combo}")
            self._joy_timer.stop()
            QTimer.singleShot(400, self.accept)

    def reject(self) -> None:
        self._joy_timer.stop()
        super().reject()


def _qt_key_to_name(key: int) -> str:
    """Convert a Qt key code to a human-readable name."""
    from PyQt6.QtCore import Qt as QtKeys  # type: ignore[import-untyped]

    _SPECIAL: dict[int, str] = {
        QtKeys.Key.Key_Space: "Space",
        QtKeys.Key.Key_Return: "Enter",
        QtKeys.Key.Key_Enter: "Enter",
        QtKeys.Key.Key_Tab: "Tab",
        QtKeys.Key.Key_Backspace: "Backspace",
        QtKeys.Key.Key_Delete: "Delete",
        QtKeys.Key.Key_Insert: "Insert",
        QtKeys.Key.Key_Home: "Home",
        QtKeys.Key.Key_End: "End",
        QtKeys.Key.Key_PageUp: "PageUp",
        QtKeys.Key.Key_PageDown: "PageDown",
        QtKeys.Key.Key_Up: "Up",
        QtKeys.Key.Key_Down: "Down",
        QtKeys.Key.Key_Left: "Left",
        QtKeys.Key.Key_Right: "Right",
        QtKeys.Key.Key_Pause: "Pause",
    }
    if key in _SPECIAL:
        return _SPECIAL[key]

    # F1-F24
    if QtKeys.Key.Key_F1 <= key <= QtKeys.Key.Key_F24:
        return f"F{key - QtKeys.Key.Key_F1 + 1}"

    # Regular character
    char = chr(key) if 0x20 <= key <= 0x7E else ""
    return char.upper() if char else f"Key_{key}"
