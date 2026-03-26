"""Settings dialog for DCS Command Palette."""
from __future__ import annotations

import logging
import os
import shutil
from typing import Optional

from PyQt6.QtCore import Qt  # type: ignore[import-untyped]
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
        parent: object = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._dcs_dir = current_dcs_dir
        self._aircraft = current_aircraft
        self._on_aircraft_changed = on_aircraft_changed
        self._setup_window()
        self._build_ui()
        self._populate()

    def _setup_window(self) -> None:
        self.setWindowTitle("DCS Command Palette - Settings")
        self.setMinimumWidth(550)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog
        )

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

        # --- Info ---
        info_group = QGroupBox("Paths")
        info_layout = QVBoxLayout(info_group)

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

        settings = _read_settings()
        self._show_ids_checkbox.setChecked(bool(settings.get("show_identifiers", False)))
        self._autohide_edit.setText(str(settings.get("auto_hide_seconds", 5)))

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

    def _apply_and_close(self) -> None:
        settings = _read_settings()
        settings["dcs_install_dir"] = self._dcs_dir
        settings["aircraft"] = self._aircraft
        settings["show_identifiers"] = self._show_ids_checkbox.isChecked()
        try:
            settings["auto_hide_seconds"] = int(self._autohide_edit.text())
        except ValueError:
            settings["auto_hide_seconds"] = 5
        _save_settings(settings)
        logger.info("Settings saved: dcs_dir=%s, aircraft=%s", self._dcs_dir, self._aircraft)

        if callable(self._on_aircraft_changed):
            self._on_aircraft_changed(self._dcs_dir, self._aircraft)

        self.accept()
