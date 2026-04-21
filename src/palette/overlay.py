from __future__ import annotations

import logging
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

from PyQt6.QtCore import Qt, QEvent, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer  # type: ignore[import-untyped]
from PyQt6.QtGui import QKeyEvent  # type: ignore[import-untyped]
from PyQt6.QtWidgets import (  # type: ignore[import-untyped]
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSlider,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import ctypes

from src.palette.commands import Command, CommandSource
from src.config import settings as cfg
from src.config.settings import (
    ACCENT_COLOR,
    BG_COLOR,
    CATEGORY_COLOR,
    HIGHLIGHT_COLOR,
    IDENTIFIER_COLOR,
    OVERLAY_MAX_HEIGHT,
    OVERLAY_WIDTH,
    SEARCH_BG_COLOR,
    TEXT_COLOR,
    TEXT_MUTED_COLOR,
)
from src.bios.state import BiosStateReader
from src.bios.sender import DCSBiosSender
from src.lib.key_sender import send_key_combo
from src.lib.search import search
from src.palette.usage import UsageTracker  # noqa: F401 — used as type hint


class ResultItem(QWidget):  # type: ignore[misc]
    _state_reader: Optional[BiosStateReader] = None
    _usage: Optional[UsageTracker] = None

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.command: Optional[Command] = None
        self._selected: bool = False
        self.setFixedHeight(cfg.RESULT_ITEM_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(0)

        left = QVBoxLayout()
        left.setSpacing(1)
        left.setContentsMargins(0, 0, 0, 0)

        self.id_label = QLabel()
        self.id_label.setStyleSheet(
            f"color: {IDENTIFIER_COLOR}; font-size: {cfg.IDENTIFIER_FONT_SIZE}px; "
            f"font-family: 'Consolas', 'Courier New', monospace; font-weight: bold;"
        )
        left.addWidget(self.id_label)

        self.desc_label = QLabel()
        self.desc_label.setStyleSheet(
            f"color: {TEXT_MUTED_COLOR}; font-size: {cfg.DESCRIPTION_FONT_SIZE}px;"
        )
        left.addWidget(self.desc_label)

        layout.addLayout(left, stretch=1)

        # Right side: category tag + key combo
        right = QVBoxLayout()
        right.setSpacing(1)
        right.setContentsMargins(0, 0, 0, 0)

        self.cat_label = QLabel()
        self.cat_label.setStyleSheet(
            f"color: {CATEGORY_COLOR}; font-size: {cfg.CATEGORY_FONT_SIZE}px; "
            f"padding: 2px 8px; border: 1px solid {CATEGORY_COLOR}; border-radius: 3px;"
        )
        self.cat_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(self.cat_label)

        self.combo_label = QLabel()
        self.combo_label.setStyleSheet(
            f"color: {TEXT_MUTED_COLOR}; font-size: {cfg.COMBO_FONT_SIZE}px;"
        )
        self.combo_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(self.combo_label)

        layout.addLayout(right)

        # Favorite star — far right. Direct child of self so geometry() is
        # in ResultItem coordinates for hit-testing in mousePressEvent.
        self.star_label = QLabel("☆")
        self.star_label.setFixedWidth(28)
        self.star_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.star_label.setStyleSheet(
            "color: #666666; font-size: 18px; background: transparent;"
        )
        layout.addWidget(self.star_label)

    def set_command(self, cmd: Command) -> None:
        self.command = cmd
        # Keyboard commands with no binding are dimmed
        unbound = (cmd.source == CommandSource.KEYBOARD and not cmd.key_combo
                   and not cmd.identifier.startswith("__"))
        # DCS-BIOS commands are dimmed when not connected
        bios_offline = (cmd.source == CommandSource.DCS_BIOS
                        and ResultItem._state_reader is not None
                        and not ResultItem._state_reader.connected)
        dim = "#555555" if (unbound or bios_offline) else IDENTIFIER_COLOR
        dim_desc = "#444444" if (unbound or bios_offline) else TEXT_MUTED_COLOR

        self.id_label.setText(cmd.description)
        self.id_label.setStyleSheet(
            f"color: {dim}; font-size: {cfg.IDENTIFIER_FONT_SIZE}px; "
            f"font-family: 'Consolas', 'Courier New', monospace; font-weight: bold;"
        )
        if cfg.SHOW_IDENTIFIERS:
            self.desc_label.setText(cmd.identifier)
            self.desc_label.setStyleSheet(
                f"color: {dim_desc}; font-size: {cfg.DESCRIPTION_FONT_SIZE}px;"
            )
            self.desc_label.show()
        else:
            self.desc_label.setText("")
            self.desc_label.hide()
        cat = cmd.category if len(cmd.category) <= 30 else cmd.category[:27] + "..."
        self.cat_label.setText(cat)
        self.cat_label.setStyleSheet(
            f"color: {CATEGORY_COLOR}; font-size: {cfg.CATEGORY_FONT_SIZE}px; "
            f"padding: 2px 8px; border: 1px solid {CATEGORY_COLOR}; border-radius: 3px;"
        )
        if bios_offline:
            self.combo_label.setText("DCS-BIOS offline")
            self.combo_label.setStyleSheet(
                f"color: #cc3333; font-size: {cfg.COMBO_FONT_SIZE}px; font-style: italic;"
            )
        elif unbound:
            self.combo_label.setText("no key")
            self.combo_label.setStyleSheet(
                f"color: #cc3333; font-size: {cfg.COMBO_FONT_SIZE}px; font-style: italic;"
            )
        else:
            # For simple BIOS toggles (max_value <= 1), show current state inline
            state_text = self._get_toggle_state_text(cmd)
            if state_text:
                self.combo_label.setText(state_text)
                self.combo_label.setStyleSheet(
                    f"color: #88bbff; font-size: {cfg.COMBO_FONT_SIZE}px; font-weight: bold;"
                )
            else:
                self.combo_label.setText(cmd.key_combo if cmd.key_combo else "")
                self.combo_label.setStyleSheet(
                    f"color: {TEXT_MUTED_COLOR}; font-size: {cfg.COMBO_FONT_SIZE}px;"
                )

        # Favorite star. Built-in palette commands (identifier starts with __)
        # don't get a star — they can't be meaningfully favorited.
        if cmd.identifier.startswith("__") and cmd.identifier.endswith("__"):
            self.star_label.setText("")
        elif ResultItem._usage is not None and ResultItem._usage.is_favorite(cmd.identifier):
            self.star_label.setText("★")
            self.star_label.setStyleSheet(
                "color: #ffcc33; font-size: 18px; background: transparent;"
            )
        else:
            self.star_label.setText("☆")
            self.star_label.setStyleSheet(
                "color: #666666; font-size: 18px; background: transparent;"
            )

    @staticmethod
    def _get_toggle_state_text(cmd: Command) -> str:
        """Return current state text for simple BIOS toggles, or '' if not applicable."""
        if cmd.source != CommandSource.DCS_BIOS:
            return ""
        if ResultItem._state_reader is None or not ResultItem._state_reader.connected:
            return ""
        # Only for stateful switches (max_value <= 1), not momentary pushbuttons
        if not cmd.is_simple_action or cmd.is_momentary:
            return ""
        if cmd.output_address is None or cmd.output_mask is None or cmd.output_shift is None:
            return ""

        value = ResultItem._state_reader.get_value(
            cmd.output_address, cmd.output_mask, cmd.output_shift,
        )
        if cmd.position_labels and value in cmd.position_labels:
            return cmd.position_labels[value]
        return "ON" if value else "OFF"

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        if selected:
            r, g, b, a = HIGHLIGHT_COLOR
            self.setStyleSheet(f"background-color: rgba({r},{g},{b},{a}); border-radius: 4px;")
        else:
            self.setStyleSheet("background-color: transparent;")


class SubMenuWidget(QWidget):  # type: ignore[misc]
    """Sub-menu for multi-position selectors and dials."""

    action_requested = pyqtSignal(str, str)
    close_requested = pyqtSignal()
    spring_hold_requested = pyqtSignal(str, int)  # identifier, center_position — hold mode for spring-loaded switches

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.command: Optional[Command] = None
        self._sender: Optional[DCSBiosSender] = None
        self._state_reader: Optional[BiosStateReader] = None
        self._slider: Optional[QSlider] = None
        self._step_generation: int = 0  # incremented on each position select to cancel stale timers
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 8, 12, 8)
        self._layout.setSpacing(6)

    def set_command(self, cmd: Command, sender: DCSBiosSender,
                    current_value: Optional[int] = None,
                    state_reader: Optional[BiosStateReader] = None) -> None:
        self.command = cmd
        self._sender = sender
        self._state_reader = state_reader
        self._slider = None
        self._current_value = current_value
        self._buttons: List[QPushButton] = []
        self._clear()

        if cfg.SHOW_IDENTIFIERS:
            header = QLabel(f"  {cmd.identifier}")
            header.setStyleSheet(
                f"color: {ACCENT_COLOR}; font-size: {cfg.SUBMENU_HEADER_FONT_SIZE}px;"
            )
            self._layout.addWidget(header)

        if cmd.has_set_string:
            self._add_string_input(cmd)
            return

        if cmd.max_value is not None and cmd.max_value <= 10:
            if cmd.position_labels:
                self._add_position_buttons(cmd)
            elif cmd.max_value > 1:
                self._add_generic_positions(cmd)

        if cmd.has_fixed_step or cmd.has_variable_step:
            self._add_inc_dec(cmd)

        if cmd.control_type in ("limited_dial", "analog_dial") and cmd.max_value is not None:
            self._add_slider(cmd)

        # Focus the current position button, or the first button
        focus_idx = current_value if current_value is not None and current_value < len(self._buttons) else 0
        if self._buttons:
            self._buttons[focus_idx].setFocus()

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, layout: object) -> None:
        while layout.count():  # type: ignore[union-attr]
            item = layout.takeAt(0)  # type: ignore[union-attr]
            w = item.widget()
            if w:
                w.deleteLater()

    def _make_btn_style(self, is_current: bool) -> str:
        if is_current:
            return (
                f"QPushButton {{ color: #ffffff; background: rgba(60,120,220,180); "
                f"border: 2px solid {ACCENT_COLOR}; border-radius: 4px; "
                f"padding: 8px 16px; text-align: left; font-size: {cfg.SUBMENU_BUTTON_FONT_SIZE}px; font-weight: bold; }}"
                f"QPushButton:hover, QPushButton:focus {{ background: rgba(60,120,220,220); }}"
            )
        return (
            f"QPushButton {{ color: {TEXT_COLOR}; background: rgba(50,50,70,200); "
            f"border: 1px solid rgba(100,100,140,150); border-radius: 4px; "
            f"padding: 8px 16px; text-align: left; font-size: {cfg.SUBMENU_BUTTON_FONT_SIZE}px; }}"
            f"QPushButton:hover, QPushButton:focus {{ background: rgba(60,120,220,120); }}"
        )

    def _add_position_buttons(self, cmd: Command) -> None:
        if not cmd.position_labels:
            return
        for pos, label in sorted(cmd.position_labels.items()):
            is_current = self._current_value is not None and pos == self._current_value
            marker = " ◄" if is_current else ""
            btn = QPushButton(f"  {label}{marker}")
            btn.setStyleSheet(self._make_btn_style(is_current))
            btn.clicked.connect(lambda checked, p=pos: self._on_position(p))
            self._buttons.append(btn)
            self._layout.addWidget(btn)

    def _add_generic_positions(self, cmd: Command) -> None:
        """Add numbered position buttons for selectors without named labels."""
        if cmd.max_value is None:
            return
        for pos in range(cmd.max_value + 1):
            is_current = self._current_value is not None and pos == self._current_value
            marker = " ◄" if is_current else ""
            btn = QPushButton(f"  Position {pos}{marker}")
            btn.setStyleSheet(self._make_btn_style(is_current))
            btn.clicked.connect(lambda checked, p=pos: self._on_position(p))
            self._buttons.append(btn)
            self._layout.addWidget(btn)

    def _on_position(self, pos: int) -> None:
        if not self.command:
            return
        # Cancel any pending step/close timers from a previous selection
        self._step_generation += 1
        gen = self._step_generation

        # Visually update: highlight the selected button, dim the old one
        for i, btn in enumerate(self._buttons):
            is_new = (i == pos)
            btn.setStyleSheet(self._make_btn_style(is_new))
            text = btn.text().rstrip(" ◄")
            btn.setText(f"{text} ◄" if is_new else text)

        cmd = self.command
        self._current_value = pos

        # ── Spring-loaded switches (engine crank, HDG, CRS) ──
        # Send target position directly (no stepping — the switch accepts
        # any position via set_state).  Off-center positions (0, 2) enter
        # hold mode so the switch stays there until the user releases.
        if cmd.is_spring_loaded:
            self.action_requested.emit(cmd.identifier, str(pos))
            if pos != 1:
                # Off-center: enter hold mode (recenter on release)
                logger.info("Spring-loaded hold: %s → position %d (center=1)", cmd.identifier, pos)
                self.spring_hold_requested.emit(cmd.identifier, 1)
            else:
                # Center position: just send and close
                QTimer.singleShot(300, self.close_requested.emit)
            return

        # ── Regular multi-position switches ──
        # Re-read the actual BIOS value instead of using cached _current_value.
        start = self._current_value if self._current_value is not None else 0
        if (self._state_reader and self._state_reader.connected
                and cmd.output_address is not None
                and cmd.output_mask is not None
                and cmd.output_shift is not None):
            bios_val = self._state_reader.get_value(
                cmd.output_address, cmd.output_mask, cmd.output_shift,
            )
            if bios_val is not None:
                start = bios_val
                logger.debug("_on_position: BIOS value for %s = %d (cached was %s)",
                             cmd.identifier, bios_val, self._current_value)

        # Step through each position one at a time with delays.
        # Some DCS switches only accept single-step movement per command cycle.
        distance = abs(pos - start)
        if distance == 0:
            self.action_requested.emit(cmd.identifier, str(pos))
        else:
            step = 1 if pos > start else -1
            positions = list(range(start + step, pos + step, step))
            for i, val in enumerate(positions):
                QTimer.singleShot(
                    50 + i * 200,
                    lambda v=val, g=gen: (
                        self.action_requested.emit(cmd.identifier, str(v))
                        if self._step_generation == g else None
                    ),
                )
        # Delay close: allow time for all steps to complete
        close_delay = max(300, distance * 200 + 200)
        QTimer.singleShot(
            close_delay,
            lambda g=gen: self.close_requested.emit() if self._step_generation == g else None,
        )

    def _add_inc_dec(self, cmd: Command) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)

        dec_btn = QPushButton("  DEC")
        inc_btn = QPushButton("INC  ")
        for btn in (dec_btn, inc_btn):
            btn.setStyleSheet(
                f"QPushButton {{ color: {TEXT_COLOR}; background: rgba(50,50,70,200); "
                f"border: 1px solid rgba(100,100,140,150); border-radius: 4px; "
                f"padding: 8px 24px; font-size: {cfg.SUBMENU_BUTTON_FONT_SIZE}px; font-weight: bold; }}"
                f"QPushButton:hover, QPushButton:focus {{ background: rgba(60,120,220,120); }}"
            )

        if cmd.has_variable_step and cmd.suggested_step:
            step = cmd.suggested_step
            dec_btn.clicked.connect(lambda: (
                self.action_requested.emit(cmd.identifier, f"-{step}"),
                QTimer.singleShot(200, self._refresh_slider_from_bios),
            ))
            inc_btn.clicked.connect(lambda: (
                self.action_requested.emit(cmd.identifier, f"+{step}"),
                QTimer.singleShot(200, self._refresh_slider_from_bios),
            ))
        else:
            dec_btn.clicked.connect(lambda: (
                self.action_requested.emit(cmd.identifier, "DEC"),
                QTimer.singleShot(200, self._refresh_slider_from_bios),
            ))
            inc_btn.clicked.connect(lambda: (
                self.action_requested.emit(cmd.identifier, "INC"),
                QTimer.singleShot(200, self._refresh_slider_from_bios),
            ))

        self._buttons.append(dec_btn)
        self._buttons.append(inc_btn)
        row.addWidget(dec_btn)
        row.addWidget(inc_btn)
        self._layout.addLayout(row)

    def _refresh_slider_from_bios(self) -> None:
        """Re-read BIOS value after INC/DEC and update the slider."""
        if self._slider and self.command and self._state_reader:
            cmd = self.command
            if cmd.output_address is not None and cmd.output_mask is not None and cmd.output_shift is not None:
                val = self._state_reader.get_value(cmd.output_address, cmd.output_mask, cmd.output_shift)
                if val is not None:
                    self._slider.blockSignals(True)
                    self._slider.setValue(val)
                    self._slider.blockSignals(False)

    def _add_slider(self, cmd: Command) -> None:
        slider_row = QHBoxLayout()
        slider = self._slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, cmd.max_value or 65535)
        slider.setStyleSheet(
            "QSlider::groove:horizontal { background: rgba(50,50,70,200); height: 8px; border-radius: 4px; }"
            "QSlider::handle:horizontal { background: #4a9eff; width: 16px; margin: -4px 0; border-radius: 8px; }"
        )
        # Set slider to current BIOS value
        initial = self._current_value if self._current_value is not None else 0
        slider.setValue(initial)
        value_label = QLabel(str(initial))
        value_label.setStyleSheet(
            f"color: {TEXT_COLOR}; font-size: {cfg.SUBMENU_HEADER_FONT_SIZE}px; min-width: 50px;"
        )
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def on_value(v: int) -> None:
            value_label.setText(str(v))

        def on_release() -> None:
            self.action_requested.emit(cmd.identifier, str(slider.value()))

        slider.valueChanged.connect(on_value)
        slider.sliderReleased.connect(on_release)

        slider_row.addWidget(slider, stretch=1)
        slider_row.addWidget(value_label)
        self._layout.addLayout(slider_row)

    def _add_string_input(self, cmd: Command) -> None:
        row = QHBoxLayout()
        text_input = QLineEdit()
        text_input.setPlaceholderText("Enter value (e.g., 251.000)...")
        text_input.setStyleSheet(
            f"color: {TEXT_COLOR}; background: rgba(50,50,70,200); "
            f"border: 1px solid rgba(100,100,140,150); border-radius: 4px; "
            f"padding: 8px; font-size: {cfg.STRING_INPUT_FONT_SIZE}px;"
        )
        send_btn = QPushButton("Send")
        send_btn.setStyleSheet(
            f"QPushButton {{ color: {TEXT_COLOR}; background: rgba(60,120,220,180); "
            f"border-radius: 4px; padding: 8px 16px; font-size: {cfg.SUBMENU_BUTTON_FONT_SIZE}px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: rgba(60,120,220,255); }}"
        )

        def on_send() -> None:
            val = text_input.text().strip()
            if val and self.command:
                self.action_requested.emit(self.command.identifier, val)
                self.close_requested.emit()

        send_btn.clicked.connect(on_send)
        text_input.returnPressed.connect(on_send)

        row.addWidget(text_input, stretch=1)
        row.addWidget(send_btn)
        self._layout.addLayout(row)


class CommandPalette(QWidget):  # type: ignore[misc]
    """The main command palette overlay."""

    def __init__(
        self,
        commands: List[Command],
        usage: UsageTracker,
        sender: DCSBiosSender,
        state_reader: Optional[BiosStateReader] = None,
    ) -> None:
        super().__init__()
        self._commands = commands
        self._usage = usage
        self._state_reader = state_reader
        ResultItem._state_reader = state_reader
        ResultItem._usage = usage
        self._sender = sender
        self._results: List[Command] = []
        self._selected_index: int = 0
        self._in_submenu: bool = False
        self._show_time: float = 0.0  # timestamp of last show_palette() call

        # Callback for built-in palette commands (set by main.py)
        self.palette_command_triggered: Optional[object] = None

        # Hold detection: press a switch and hold Enter/Space/mouse to keep it held
        self._hold_active: bool = False
        self._hold_confirmed: bool = False  # True once auto-repeat detected (real hold)
        self._hold_is_momentary: bool = False  # True for pushbuttons (release on key-up)
        self._hold_press_time: float = 0.0
        self._hold_cmd: Optional[Command] = None
        self._hold_original_value: Optional[int] = None  # value to revert to on release
        self._hold_threshold: float = 0.6  # seconds — visual "HOLDING" indicator delay
        self._action_cooldown: float = 0.0  # blocks re-execution during visual feedback
        self._spring_hold_identifier: Optional[str] = None  # spring-loaded switch identifier

        self._setup_window()
        self._build_ui()

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Auto-hide timer
        self._inactivity_timer = QTimer()
        self._inactivity_timer.setSingleShot(True)
        self._inactivity_timer.timeout.connect(self.hide_palette)

        # Search debounce timer (40ms) — avoids redundant searches while typing
        self._pending_query: str = ""
        self._search_debounce = QTimer()
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(40)
        self._search_debounce.timeout.connect(self._run_debounced_search)

        # Pre-warm: compute default results and populate widgets while hidden
        self._on_search_changed("")

        # Periodic BIOS connection status check — refresh results if status changes
        self._last_bios_connected = False
        self._bios_check_timer = QTimer()
        self._bios_check_timer.timeout.connect(self._check_bios_status)
        self._bios_check_timer.start(2000)  # check every 2 seconds

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(OVERLAY_WIDTH)

    def _build_ui(self) -> None:
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        self._container = QWidget()
        self._container.setStyleSheet(
            f"background-color: rgba({BG_COLOR[0]},{BG_COLOR[1]},{BG_COLOR[2]},{BG_COLOR[3]}); "
            f"border-radius: 10px;"
        )
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(0)

        self._search = QLineEdit()
        self._search.setPlaceholderText("  Search cockpit controls & shortcuts...")
        self._search.setStyleSheet(
            f"QLineEdit {{ color: {TEXT_COLOR}; "
            f"background-color: rgba({SEARCH_BG_COLOR[0]},{SEARCH_BG_COLOR[1]},{SEARCH_BG_COLOR[2]},{SEARCH_BG_COLOR[3]}); "
            f"border: none; border-bottom: 1px solid rgba(80,80,120,150); "
            f"border-top-left-radius: 10px; border-top-right-radius: 10px; "
            f"padding: 12px 16px; font-size: {cfg.SEARCH_FONT_SIZE}px; }}"
        )
        self._search.textChanged.connect(self._on_text_changed)
        self._search.installEventFilter(self)
        self._container_layout.addWidget(self._search)

        self._results_widget = QWidget()
        self._results_layout = QVBoxLayout(self._results_widget)
        self._results_layout.setContentsMargins(4, 4, 4, 4)
        self._results_layout.setSpacing(2)
        self._results_layout.addStretch()

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._results_widget)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { width: 6px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(100,100,140,120); border-radius: 3px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self._scroll.setMaximumHeight(OVERLAY_MAX_HEIGHT - 50)
        self._container_layout.addWidget(self._scroll)

        self._submenu = SubMenuWidget()
        self._submenu.action_requested.connect(self._on_submenu_action)
        self._submenu.close_requested.connect(self._close_submenu_and_hide)
        self._submenu.spring_hold_requested.connect(self._on_spring_hold)
        self._submenu.hide()
        self._container_layout.addWidget(self._submenu)

        self._main_layout.addWidget(self._container)

        # Pre-create result item widgets to avoid allocation on first show.
        # More widgets are created on demand if cfg.MAX_RESULTS grows at runtime
        # (see _ensure_item_widgets()).
        self._item_widgets: List[ResultItem] = []
        self._ensure_item_widgets(cfg.MAX_RESULTS)

        # Enable mouse tracking so movement over the palette restarts the
        # auto-hide timer (gives users time to click small star targets).
        self._enable_hover_tracking()

    def _ensure_item_widgets(self, count: int) -> None:
        """Grow the pre-created result-item pool to at least `count` widgets."""
        grew = False
        while len(self._item_widgets) < count:
            i = len(self._item_widgets)
            item_widget = ResultItem(self._results_widget)
            item_widget.mousePressEvent = (  # type: ignore[assignment]
                lambda e, idx=i: self._on_item_mouse_press(idx, e)
            )
            item_widget.hide()
            self._item_widgets.append(item_widget)
            grew = True
        if grew and hasattr(self, "_inactivity_timer"):
            # New widgets need mouse tracking / event filter wired up too.
            self._enable_hover_tracking()

    def _force_focus(self) -> None:
        """Force the palette window to the foreground and focus the search box.

        Uses AttachThreadInput trick to bypass Windows focus-stealing prevention.
        SetForegroundWindow alone fails when another app (DCS) has focus.
        """
        hwnd = int(self.winId())
        if not hwnd:
            return

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Get the foreground window's thread and our thread
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
        our_thread = kernel32.GetCurrentThreadId()

        # Attach our thread to the foreground thread's input queue
        attached = False
        if fg_thread != our_thread:
            attached = bool(user32.AttachThreadInput(our_thread, fg_thread, True))

        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        self.activateWindow()
        self.raise_()

        # Detach
        if attached:
            user32.AttachThreadInput(our_thread, fg_thread, False)

        self._search.setFocus()
        logger.debug("Focus forced: search.hasFocus=%s, isActiveWindow=%s",
                      self._search.hasFocus(), self.isActiveWindow())

    def _check_bios_status(self) -> None:
        """Refresh result items if BIOS connection status changed."""
        if not self._state_reader:
            return
        connected = self._state_reader.connected
        if connected != self._last_bios_connected:
            self._last_bios_connected = connected
            logger.info("DCS-BIOS connection status changed: %s",
                        "connected" if connected else "disconnected")
            # Re-render visible results so dimming/warnings update
            if self.isVisible() and not self._in_submenu:
                self._on_search_changed(self._search.text())

    def _calc_position(self, screen_w: int, screen_h: int) -> tuple[int, int]:
        """Calculate overlay position based on OVERLAY_POSITION setting.

        Format: "vertical-horizontal" where:
        - vertical: top (20%), center (50%), bottom (80%)
        - horizontal: left (10%), center (50%), right (90%)
        """
        pos = cfg.OVERLAY_POSITION.lower().strip()
        parts = pos.split("-", 1)
        v = parts[0] if parts else "top"
        h = parts[1] if len(parts) > 1 else "center"

        # Horizontal
        if h == "left":
            x = int(screen_w * 0.05)
        elif h == "right":
            x = int(screen_w * 0.95) - self.width()
        else:  # center
            x = (screen_w - self.width()) // 2

        # Vertical — estimate overlay height (~60px search + results), capped
        # to available screen height so bottom-aligned overlays stay on-screen.
        overlay_h = min(
            max(cfg.RESULT_ITEM_HEIGHT, screen_h - 90),
            60 + len(self._results) * cfg.RESULT_ITEM_HEIGHT,
        )
        if v == "top":
            y = int(screen_h * 0.10)
        elif v == "bottom":
            y = int(screen_h * 0.85) - overlay_h
        else:  # center
            y = (screen_h - overlay_h) // 2

        return x, y

    def _restart_inactivity_timer(self) -> None:
        timeout = cfg.AUTO_HIDE_SECONDS
        if timeout > 0:
            self._inactivity_timer.start(timeout * 1000)
            logger.debug("Inactivity timer restarted (%ds)", timeout)
        else:
            self._inactivity_timer.stop()

    def _enable_hover_tracking(self) -> None:
        """Enable mouse tracking on the palette and all descendant widgets so
        any mouse movement over the palette restarts the auto-hide timer.
        Gives the user time to aim for small targets like the favorite star.
        """
        self.setMouseTracking(True)
        for w in self.findChildren(QWidget):
            w.setMouseTracking(True)
            # Install event filter so we catch MouseMove events that child
            # widgets consume before they'd ever reach our mouseMoveEvent.
            w.installEventFilter(self)

    def mouseMoveEvent(self, event: object) -> None:  # type: ignore[override]
        self._restart_inactivity_timer()
        super().mouseMoveEvent(event)  # type: ignore[misc]

    def show_palette(self) -> None:
        self._show_time = time.time()  # guard against ghost keypresses
        self._in_submenu = False
        self._submenu.hide()
        self._scroll.show()
        self._search.clear()
        self._search.setReadOnly(False)
        self._selected_index = 0

        self._on_search_changed("")
        self._restart_inactivity_timer()

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            x, y = self._calc_position(geo.width(), geo.height())
            self.move(x, y)

        self.setWindowOpacity(0.0)
        self.show()
        self.activateWindow()
        self.raise_()
        self._search.setFocus()
        # Aggressive focus grab — needed when DCS has focus
        QTimer.singleShot(50, self._force_focus)
        QTimer.singleShot(150, self._force_focus)

        self._fade_anim.stop()
        self._fade_anim.setDuration(100)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def hide_palette(self) -> None:
        # Always clean up hold state when hiding to prevent stale state
        if self._hold_active:
            logger.debug("hide_palette: clearing stale hold state")
        self._hold_active = False
        self._hold_confirmed = False
        self._hold_is_momentary = False
        self._hold_cmd = None
        self._hold_original_value = None
        self._spring_hold_identifier = None

        self._fade_anim.stop()
        self._fade_anim.setDuration(80)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_out_done)
        self._fade_anim.start()

    def _on_fade_out_done(self) -> None:
        self._fade_anim.finished.disconnect(self._on_fade_out_done)
        self.hide()
        self._usage.save()

    def _on_text_changed(self, text: str) -> None:
        """Restart debounce timer on each keystroke."""
        self._pending_query = text
        self._search_debounce.start()
        self._restart_inactivity_timer()

    def _run_debounced_search(self) -> None:
        """Execute search after debounce timer expires."""
        self._results = search(self._pending_query, self._commands, self._usage)
        self._selected_index = 0
        self._update_results_display()

    def _on_search_changed(self, text: str) -> None:
        """Direct (non-debounced) search — used by show_palette() and pre-warm."""
        self._results = search(text, self._commands, self._usage)
        self._selected_index = 0
        self._update_results_display()

    def _update_results_display(self) -> None:
        while self._results_layout.count() > 0:
            item = self._results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()

        for i, cmd in enumerate(self._results):
            widget = self._item_widgets[i]
            widget.set_command(cmd)
            widget.set_selected(i == self._selected_index)
            widget.show()
            self._results_layout.addWidget(widget)

        self._results_layout.addStretch()

        item_count = len(self._results)
        # Cap the results area at the available screen height (minus search bar
        # + margins) so we show as many rows as physically fit, not the legacy
        # OVERLAY_MAX_HEIGHT limit.
        screen = QApplication.primaryScreen()
        if screen:
            avail_h = screen.availableGeometry().height()
        else:
            avail_h = OVERLAY_MAX_HEIGHT
        # ~90px reserved for search bar, margins, and screen edge padding
        max_results_h = max(cfg.RESULT_ITEM_HEIGHT, avail_h - 90)
        results_height = min(item_count * cfg.RESULT_ITEM_HEIGHT, max_results_h)
        self._scroll.setMaximumHeight(max_results_h + 10)
        self._scroll.setFixedHeight(results_height + 10)
        self.adjustSize()

    def _apply_display_settings(self) -> None:
        """Re-apply font sizes, row heights, and max_results without restart.

        Called from App._on_config_changed() after _load_display_settings()
        has mutated cfg.* values from the new settings.json.
        """
        # Grow widget pool if user increased cfg.MAX_RESULTS.
        self._ensure_item_widgets(cfg.MAX_RESULTS)

        # Update row heights on every pooled widget.
        for w in self._item_widgets:
            w.setFixedHeight(cfg.RESULT_ITEM_HEIGHT)

        # Rebuild the search bar stylesheet with the new font size.
        self._search.setStyleSheet(
            f"QLineEdit {{ color: {TEXT_COLOR}; "
            f"background-color: rgba({SEARCH_BG_COLOR[0]},{SEARCH_BG_COLOR[1]},{SEARCH_BG_COLOR[2]},{SEARCH_BG_COLOR[3]}); "
            f"border: none; border-bottom: 1px solid rgba(80,80,120,150); "
            f"border-top-left-radius: 10px; border-top-right-radius: 10px; "
            f"padding: 12px 16px; font-size: {cfg.SEARCH_FONT_SIZE}px; }}"
        )

        # Re-run search so each visible ResultItem rebuilds its internal
        # labels with the new cfg.*_FONT_SIZE values in set_command().
        self._on_search_changed(self._search.text() or "")
        self.adjustSize()

    def _on_item_clicked(self, index: int) -> None:
        self._selected_index = index
        self._update_results_display()
        self._execute_selected()

    def _on_item_mouse_press(self, idx: int, event: object) -> None:
        """Dispatch a click on a result row: star toggles favorite, body executes."""
        if idx >= len(self._results):
            return
        widget = self._item_widgets[idx]
        cmd = self._results[idx]
        # Star is a direct child of the row; geometry() is in row coords,
        # matching event.pos() (which Qt delivers in the widget's coord system).
        star_rect = widget.star_label.geometry()
        try:
            pos = event.pos()  # type: ignore[attr-defined]
        except AttributeError:
            pos = None
        if pos is not None and star_rect.contains(pos):
            # Built-in palette commands don't have a star — fall through to execute
            if cmd.identifier.startswith("__") and cmd.identifier.endswith("__"):
                self._on_item_clicked(idx)
                return
            new_state = self._usage.toggle_favorite(cmd.identifier)
            logger.info("Favorite %s: %s", cmd.identifier, "on" if new_state else "off")
            # Re-render so star icon updates and favorites reorder
            self._on_search_changed(self._search.text() or "")
            return
        self._on_item_clicked(idx)

    def mouseReleaseEvent(self, event: object) -> None:
        """Detect mouse release for hold actions (momentary buttons + spring-loaded switches)."""
        if self._hold_active:
            held_duration = time.time() - self._hold_press_time
            logger.info("Mouse hold release after %.2fs", held_duration)
            if getattr(self, "_spring_hold_identifier", None):
                self._finish_spring_hold()
            else:
                self._finish_hold()
            return
        super().mouseReleaseEvent(event)  # type: ignore[arg-type]

    def _execute_selected(self) -> None:
        if not self._results or self._selected_index >= len(self._results):
            return

        cmd = self._results[self._selected_index]
        logger.info("Execute: %s (is_momentary=%s, max_value=%s, api_variant=%r, control_type=%r)",
                     cmd.identifier, cmd.is_momentary, cmd.max_value,
                     cmd.api_variant, cmd.control_type)
        self._usage.record_use(cmd.identifier)

        # DCS-BIOS command while not connected
        if (cmd.source == CommandSource.DCS_BIOS
                and self._state_reader is not None
                and not self._state_reader.connected):
            self._search.setStyleSheet(
                f"QLineEdit {{ color: #ff6666; "
                f"background-color: rgba({SEARCH_BG_COLOR[0]},{SEARCH_BG_COLOR[1]},{SEARCH_BG_COLOR[2]},{SEARCH_BG_COLOR[3]}); "
                f"border: none; border-bottom: 1px solid #ff4444; "
                f"border-top-left-radius: 10px; border-top-right-radius: 10px; "
                f"padding: 12px 16px; font-size: {cfg.SEARCH_FONT_SIZE}px; }}"
            )
            self._search.setText("DCS-BIOS not connected - open Settings to install")
            self._search.setReadOnly(True)
            QTimer.singleShot(1500, self._reset_search_style)
            return

        # Built-in palette commands
        if cmd.identifier.startswith("__") and cmd.identifier.endswith("__"):
            self.hide_palette()
            if callable(self.palette_command_triggered):
                self.palette_command_triggered(cmd.identifier)
            return

        # Keyboard shortcut: simulate key combo
        if cmd.source == CommandSource.KEYBOARD:
            if cmd.key_combo:
                self.hide_palette()
                # Small delay so the overlay hides before keys are sent to DCS
                QTimer.singleShot(150, lambda: send_key_combo(cmd.key_combo))
            else:
                # No keybinding assigned — flash the search bar to indicate
                self._search.setStyleSheet(
                    f"QLineEdit {{ color: #ff6666; "
                    f"background-color: rgba({SEARCH_BG_COLOR[0]},{SEARCH_BG_COLOR[1]},{SEARCH_BG_COLOR[2]},{SEARCH_BG_COLOR[3]}); "
                    f"border: none; border-bottom: 1px solid #ff4444; "
                    f"border-top-left-radius: 10px; border-top-right-radius: 10px; "
                    f"padding: 12px 16px; font-size: {cfg.SEARCH_FONT_SIZE}px; }}"
                )
                self._search.setText("No keybinding assigned for this command")
                self._search.setReadOnly(True)
                QTimer.singleShot(1500, self._reset_search_style)
            return

        # DCS-BIOS: momentary pushbutton (press now, release on key/mouse-up)
        if cmd.is_momentary and cmd.max_value is not None and cmd.max_value <= 1:
            self._sender.set_state(cmd.identifier, 1)
            logger.info("Momentary press: %s (is_momentary=True)", cmd.identifier)
            self._action_cooldown = time.time()
            # Set up hold tracking — release happens on key/mouse release
            self._hold_active = True
            self._hold_confirmed = False
            self._hold_is_momentary = True
            self._hold_press_time = time.time()
            self._hold_cmd = cmd
            self._hold_original_value = None  # not used for momentary
            self._animate_momentary_press(cmd)
            return

        # DCS-BIOS: simple toggle (max_value <= 1, stateful switch)
        # No hold tracking — toggles are permanent. Just toggle, animate, hide.
        if cmd.max_value is not None and cmd.max_value <= 1:
            old_state = ResultItem._get_toggle_state_text(cmd)
            original_value = self._get_current_bios_value(cmd)
            new_value = 0 if original_value else 1
            self._sender.set_state(cmd.identifier, new_value)
            logger.info("Toggle %s: %s → %s", cmd.identifier, original_value, new_value)
            self._action_cooldown = time.time()
            self._animate_toggle(cmd, old_state)
            return

        # DCS-BIOS: complex control -> sub-menu
        if (cmd.has_fixed_step or cmd.has_variable_step
                or (cmd.max_value is not None and cmd.max_value > 1)
                or cmd.has_set_string):
            self._show_submenu(cmd)
            return

        # Fallback
        if cmd.has_toggle:
            self._sender.toggle(cmd.identifier)
        elif cmd.has_fixed_step:
            self._sender.inc(cmd.identifier)
        self.hide_palette()

    def _animate_toggle(self, cmd: Command, old_state: str) -> None:
        """Show state transition on the selected result item, then hide.

        Toggle switches are permanent — no hold detection, no revert.
        """
        if self._selected_index >= len(self._item_widgets):
            self.hide_palette()
            return

        widget = self._item_widgets[self._selected_index]
        label = widget.combo_label

        if not old_state:
            old_state = "OFF"

        # Predict the new state (toggle flips the value)
        if cmd.position_labels:
            labels = list(cmd.position_labels.values())
            new_state = labels[1] if old_state == labels[0] else labels[0]
        else:
            new_state = "OFF" if old_state == "ON" else "ON"

        # Show "OLD → NEW" with highlight, then green confirmation, then hide
        label.setText(f"{old_state}  →  {new_state}")
        label.setStyleSheet(
            f"color: #ffcc00; font-size: {cfg.COMBO_FONT_SIZE}px; font-weight: bold;"
        )

        def _show_confirmed() -> None:
            label.setText(new_state)
            label.setStyleSheet(
                f"color: #44dd44; font-size: {cfg.COMBO_FONT_SIZE}px; font-weight: bold;"
            )

        QTimer.singleShot(300, _show_confirmed)
        QTimer.singleShot(700, self.hide_palette)

    def _animate_momentary_press(self, cmd: Command) -> None:
        """Show press animation for a momentary pushbutton.

        Shows "PRESSED" immediately.  After 1 second (if still held),
        transitions to "HOLDING...".  Release is handled by _finish_hold.
        """
        if self._selected_index >= len(self._item_widgets):
            self._finish_hold(was_held=False)
            return

        widget = self._item_widgets[self._selected_index]
        label = widget.combo_label

        # Show "PRESSED" with highlight
        label.setText("PRESSED")
        label.setStyleSheet(
            f"color: #ffcc00; font-size: {cfg.COMBO_FONT_SIZE}px; font-weight: bold;"
        )

        # After 500ms, if still held show HOLDING indicator (time-based)
        def _check_still_held() -> None:
            if self._hold_active and time.time() - self._hold_press_time >= 0.5:
                label.setText("HOLDING...")
                label.setStyleSheet(
                    f"color: #ff8844; font-size: {cfg.COMBO_FONT_SIZE}px; font-weight: bold;"
                )

        QTimer.singleShot(500, _check_still_held)

    def _finish_hold(self, _was_held: bool = False) -> None:
        """Complete a momentary hold: always release the button (set_state 0)."""
        cmd = self._hold_cmd
        elapsed = time.time() - self._hold_press_time
        genuinely_held = elapsed >= 0.5  # match the visual threshold

        if cmd is not None:
            # Always release the button on key/mouse-up.
            # Ensure a minimum 150ms press so DCS registers it.
            min_press = 0.15
            if elapsed < min_press:
                remaining_ms = int((min_press - elapsed) * 1000)
                identifier = cmd.identifier  # capture for lambda
                QTimer.singleShot(remaining_ms, lambda: self._sender.set_state(identifier, 0))
                logger.info("Momentary release (delayed %dms): %s after %.2fs",
                            remaining_ms, cmd.identifier, elapsed)
            else:
                self._sender.set_state(cmd.identifier, 0)
                logger.info("Momentary release: %s after %.2fs", cmd.identifier, elapsed)

        # Show brief visual feedback
        if self._selected_index < len(self._item_widgets):
            label = self._item_widgets[self._selected_index].combo_label
            if genuinely_held:
                label.setText("RELEASED")
                label.setStyleSheet(
                    f"color: #aaaaaa; font-size: {cfg.COMBO_FONT_SIZE}px; font-weight: bold;"
                )
            else:
                label.setText("PRESSED")
                label.setStyleSheet(
                    f"color: #44dd44; font-size: {cfg.COMBO_FONT_SIZE}px; font-weight: bold;"
                )

        # Clean up hold state
        self._hold_active = False
        self._hold_confirmed = False
        self._hold_is_momentary = False
        self._hold_cmd = None
        self._hold_original_value = None
        self._action_cooldown = time.time()  # block re-execution during feedback

        QTimer.singleShot(400, self.hide_palette)

    def _get_current_bios_value(self, cmd: Command) -> Optional[int]:
        """Get the current integer value of a BIOS command from the live state."""
        if (self._state_reader is None
                or not self._state_reader.connected
                or cmd.output_address is None
                or cmd.output_mask is None
                or cmd.output_shift is None):
            return None
        return self._state_reader.get_value(cmd.output_address, cmd.output_mask, cmd.output_shift)

    def _show_submenu(self, cmd: Command) -> None:
        # Block submenu if DCS-BIOS is not connected
        if (cmd.source == CommandSource.DCS_BIOS
                and self._state_reader is not None
                and not self._state_reader.connected):
            self._search.setStyleSheet(
                f"QLineEdit {{ color: #ff6666; "
                f"background-color: rgba({SEARCH_BG_COLOR[0]},{SEARCH_BG_COLOR[1]},{SEARCH_BG_COLOR[2]},{SEARCH_BG_COLOR[3]}); "
                f"border: none; border-bottom: 1px solid #ff4444; "
                f"border-top-left-radius: 10px; border-top-right-radius: 10px; "
                f"padding: 12px 16px; font-size: {cfg.SEARCH_FONT_SIZE}px; }}"
            )
            self._search.setText("DCS-BIOS not connected - open Settings to install")
            self._search.setReadOnly(True)
            QTimer.singleShot(1500, self._reset_search_style)
            return
        self._in_submenu = True
        self._scroll.hide()
        self._search.setReadOnly(True)
        self._search.setText(f"{cmd.description}")
        current_value = self._get_current_bios_value(cmd)
        self._submenu.set_command(cmd, self._sender, current_value=current_value,
                                  state_reader=self._state_reader)
        # Install event filter on all submenu buttons so Tab is intercepted
        for btn in self._submenu._buttons:
            btn.installEventFilter(self)
        self._submenu.show()
        self.adjustSize()

    def _on_submenu_action(self, identifier: str, argument: str) -> None:
        logger.info("Sending DCS-BIOS: %s %s", identifier, argument)
        self._sender.send(identifier, argument)
        self._restart_inactivity_timer()

    def _on_spring_hold(self, identifier: str, center_pos: int) -> None:
        """Enter hold mode for a spring-loaded switch (engine crank, HDG, CRS).

        The switch has been moved to an off-center position.  When the user
        releases Enter/Space/mouse, we send set_state(center_pos) to recenter.
        """
        self._hold_active = True
        self._hold_confirmed = False
        self._hold_is_momentary = False
        self._hold_press_time = time.time()
        self._hold_cmd = None  # not used — we store identifier directly
        self._hold_original_value = center_pos
        self._spring_hold_identifier = identifier
        self._action_cooldown = time.time()

        # Show "HOLDING..." indicator on the selected submenu button
        if self._submenu._buttons:
            for btn in self._submenu._buttons:
                if "◄" in btn.text():
                    btn.setText(btn.text().rstrip(" ◄") + " — HOLDING...")
                    btn.setStyleSheet(
                        f"QPushButton {{ color: #ff8844; background: rgba(60,80,40,200); "
                        f"border: 2px solid #ff8844; border-radius: 4px; "
                        f"padding: 8px 16px; text-align: left; font-size: {cfg.SUBMENU_BUTTON_FONT_SIZE}px; font-weight: bold; }}"
                    )
                    break

    def _finish_spring_hold(self) -> None:
        """Release a spring-loaded switch back to center."""
        identifier = getattr(self, "_spring_hold_identifier", None)
        center_pos = self._hold_original_value
        if identifier is not None and center_pos is not None:
            elapsed = time.time() - self._hold_press_time
            self._sender.set_state(identifier, center_pos)
            logger.info("Spring-loaded release: %s → center(%d) after %.2fs",
                        identifier, center_pos, elapsed)

        # Clean up hold state
        self._hold_active = False
        self._hold_confirmed = False
        self._hold_is_momentary = False
        self._hold_cmd = None
        self._hold_original_value = None
        self._spring_hold_identifier = None
        self._action_cooldown = time.time()

        # Close submenu and hide
        self._close_submenu_and_hide()

    def _close_submenu_and_hide(self) -> None:
        self._in_submenu = False
        self._submenu.hide()
        self.hide_palette()

    def _back_from_submenu(self) -> None:
        self._in_submenu = False
        self._submenu.hide()
        self._scroll.show()
        self._search.setReadOnly(False)
        self._search.clear()
        self._search.setFocus()
        self._on_search_changed("")
        self.adjustSize()

    def eventFilter(self, obj: object, event: object) -> bool:
        """Intercept key events on child widgets (search bar, submenu buttons)."""
        # Any mouse movement over the palette or its children restarts the
        # auto-hide timer so the user has time to aim for the favorite star.
        if hasattr(event, "type") and event.type() == QEvent.Type.MouseMove:  # type: ignore[attr-defined]
            self._restart_inactivity_timer()
            # Don't consume — let child widget handle normally
            return False

        # ── Submenu button Enter/Space: call click() synchronously ──
        # QPushButton.animateClick() introduces a ~100ms delay between the
        # physical key-press and the clicked() signal.  For spring-loaded
        # switches this means the key-release arrives *before* _hold_active
        # is set, so the hold never finishes.  By calling click() directly
        # from the event filter we guarantee _hold_active is True before
        # any release event can arrive.
        if (isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress
                and self._in_submenu and isinstance(obj, QPushButton)):
            key = event.key()  # type: ignore[attr-defined]
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                if self._hold_active:
                    return True  # consume during hold — don't re-execute
                if not event.isAutoRepeat():  # type: ignore[attr-defined]
                    obj.click()  # type: ignore[attr-defined]
                return True  # consumed — prevent animateClick

        # Forward keyRelease to overlay during spring-loaded hold so release is detected
        if (isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyRelease
                and self._hold_active and not event.isAutoRepeat()):
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self.keyReleaseEvent(event)
                return True

        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                reverse = (event.key() == Qt.Key.Key_Backtab
                           or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                self._restart_inactivity_timer()

                if self._in_submenu:
                    # Cycle through submenu buttons
                    self._submenu_navigate(reverse=reverse)
                    return True

                if obj is self._search and self._results:
                    # Move through results list (wrapping)
                    n = len(self._results)
                    if reverse:
                        self._selected_index = (self._selected_index - 1) % n
                    else:
                        self._selected_index = (self._selected_index + 1) % n
                    self._update_results_display()
                    self._ensure_visible()
                return True  # always consume Tab/Backtab
        return super().eventFilter(obj, event)  # type: ignore[arg-type]

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        logger.debug("keyPressEvent: key=%s (0x%x), in_submenu=%s, hold=%s, autoRepeat=%s",
                      event.text(), key, self._in_submenu, self._hold_active, event.isAutoRepeat())
        self._restart_inactivity_timer()

        # ── Hold guard: while a momentary hold is active, consume ALL Enter/Space.
        # Auto-repeat events are noted but never re-execute the command.
        if self._hold_active and key in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space,
        ):
            return  # always consume — never re-execute during hold

        # ── Global auto-repeat guard: NEVER re-execute on auto-repeat Enter/Space.
        # This prevents toggle switches from flipping back when the user
        # holds Enter slightly too long (Windows auto-repeat starts at ~250ms).
        if event.isAutoRepeat() and key in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space,
        ):
            return

        if key == Qt.Key.Key_Escape:
            if self._hold_active:
                # Cancel hold — for spring-loaded, recenter; for momentary, release
                if getattr(self, "_spring_hold_identifier", None):
                    self._finish_spring_hold()
                else:
                    self._finish_hold()
                return
            if self._in_submenu:
                self._back_from_submenu()
            else:
                self.hide_palette()
            return

        if self._in_submenu:
            # Enter/Return activates the focused button in the submenu
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                focused = QApplication.focusWidget()
                if isinstance(focused, QPushButton):
                    focused.click()
                    return
            # Tab/Shift+Tab cycles through submenu buttons
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                self._submenu_navigate(reverse=(key == Qt.Key.Key_Backtab
                                                or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)))
                return
            super().keyPressEvent(event)
            return

        if key == Qt.Key.Key_Down:
            self.nav_select_down()
            return

        if key == Qt.Key.Key_Up:
            self.nav_select_up()
            return

        # Tab/Shift+Tab also navigate results (like Down/Up)
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            if self._results:
                reverse = (key == Qt.Key.Key_Backtab
                           or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                if reverse:
                    self._selected_index = max(self._selected_index - 1, 0)
                else:
                    self._selected_index = min(self._selected_index + 1, len(self._results) - 1)
                self._update_results_display()
                self._ensure_visible()
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            now = time.time()
            # Guard 1: ignore Enter within 300ms of palette open (ghost events)
            if now - self._show_time < 0.3:
                logger.debug("Ignoring Enter: within 300ms of palette open")
                return
            # Guard 2: ignore Enter within 500ms of last action (feedback window)
            if now - self._action_cooldown < 0.5:
                logger.debug("Ignoring Enter: within 500ms of last action")
                return
            self._execute_selected()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.isAutoRepeat():
            return  # ignore auto-repeat from held keys
        key = event.key()
        if self._hold_active and key in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space,
        ):
            held_duration = time.time() - self._hold_press_time
            logger.info("Hold key released after %.2fs", held_duration)
            # Dispatch to the right handler
            if getattr(self, "_spring_hold_identifier", None):
                self._finish_spring_hold()
            else:
                self._finish_hold()
            return
        super().keyReleaseEvent(event)

    def _submenu_navigate(self, reverse: bool = False) -> None:
        """Cycle focus through submenu buttons with Tab/Shift+Tab."""
        buttons = self._submenu._buttons
        if not buttons:
            return
        focused = QApplication.focusWidget()
        try:
            idx = buttons.index(focused)  # type: ignore[arg-type]
        except ValueError:
            idx = -1
        if reverse:
            idx = (idx - 1) % len(buttons)
        else:
            idx = (idx + 1) % len(buttons)
        buttons[idx].setFocus()

    def _reset_search_style(self) -> None:
        """Reset search bar to normal style after error flash."""
        self._search.setStyleSheet(
            f"QLineEdit {{ color: {TEXT_COLOR}; "
            f"background-color: rgba({SEARCH_BG_COLOR[0]},{SEARCH_BG_COLOR[1]},{SEARCH_BG_COLOR[2]},{SEARCH_BG_COLOR[3]}); "
            f"border: none; border-bottom: 1px solid rgba(80,80,120,150); "
            f"border-top-left-radius: 10px; border-top-right-radius: 10px; "
            f"padding: 12px 16px; font-size: {cfg.SEARCH_FONT_SIZE}px; }}"
        )
        self._search.setReadOnly(False)
        self._search.clear()
        self._search.setFocus()

    def _ensure_visible(self) -> None:
        if self._selected_index < len(self._item_widgets):
            widget = self._item_widgets[self._selected_index]
            self._scroll.ensureWidgetVisible(widget, 0, 10)

    # ─── Navigation actions (public — driven by both keyboard events and
    #     optional user-configured hotkeys / joystick bindings) ────────
    def nav_select_up(self) -> None:
        """Move selection up one row. Respects submenu vs main list."""
        self._restart_inactivity_timer()
        if self._in_submenu:
            self._submenu_navigate(reverse=True)
            return
        if self._results:
            self._selected_index = max(self._selected_index - 1, 0)
            self._update_results_display()
            self._ensure_visible()

    def nav_select_down(self) -> None:
        """Move selection down one row. Respects submenu vs main list."""
        self._restart_inactivity_timer()
        if self._in_submenu:
            self._submenu_navigate(reverse=False)
            return
        if self._results:
            self._selected_index = min(
                self._selected_index + 1, len(self._results) - 1,
            )
            self._update_results_display()
            self._ensure_visible()

    def nav_activate(self) -> None:
        """Execute the currently selected item (press edge).

        Mirrors Enter press: in a submenu, clicks the focused button;
        in the main list, executes the highlighted command.  No-op during
        a hold (so we don't re-fire while a spring-loaded switch is held).
        """
        self._restart_inactivity_timer()
        if self._hold_active:
            return
        if self._in_submenu:
            focused = QApplication.focusWidget()
            if isinstance(focused, QPushButton):
                focused.click()
            return
        # Main list — share the same cooldown guard as Enter-handling in
        # keyPressEvent to avoid double-fires during the action animation.
        now = time.time()
        if now - self._action_cooldown < 0.5:
            return
        self._execute_selected()

    def nav_deactivate(self) -> None:
        """Complete any hold started via nav_activate (release edge).

        Mirrors Enter release: if a momentary hold or spring-loaded hold
        is active, run the appropriate finish handler (set_state(0) for
        momentary, recenter for spring-loaded).  Lets HOTAS users control
        the hold duration — press+hold the bound button = DCS button
        held; release = DCS button released.
        """
        self._restart_inactivity_timer()
        if not self._hold_active:
            return
        if getattr(self, "_spring_hold_identifier", None):
            self._finish_spring_hold()
        else:
            self._finish_hold()

    def apply_keyboard_nav_bindings(
        self, up_combo: str, down_combo: str, activate_combo: str = "",
    ) -> None:
        """Register user-configured keyboard shortcuts for up/down navigation.

        Joystick bindings (strings starting with 'Joy') are ignored here —
        those are polled by ``main.py`` instead.  Empty strings clear the
        binding.  Re-invoking replaces any previously registered shortcuts.
        """
        # Tear down previous shortcuts
        for sc in getattr(self, "_nav_shortcuts", []):
            try:
                sc.setParent(None)
                sc.deleteLater()
            except Exception:  # noqa: BLE001
                pass
        self._nav_shortcuts = []

        from PyQt6.QtGui import QKeySequence, QShortcut  # type: ignore[import-untyped]

        # Keys already handled natively by keyPressEvent / eventFilter; we
        # must not register a QShortcut for them because QShortcut grabs
        # the KeyPress in the event chain before our handlers can see it,
        # which breaks hold detection (no matching KeyRelease).
        _RESERVED = {"Return", "Enter", "Space", "Escape", "Tab", "Backtab",
                     "Up", "Down"}

        def _register(combo: str, action: object) -> None:
            if not combo or combo.startswith("Joy"):
                return
            if combo.strip() in _RESERVED:
                logger.info(
                    "Ignoring nav binding %r — that key is already handled "
                    "by the palette natively.", combo,
                )
                return
            seq = QKeySequence(combo)
            if seq.isEmpty():
                return
            sc = QShortcut(seq, self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(action)  # type: ignore[arg-type]
            self._nav_shortcuts.append(sc)
            logger.debug("Registered nav shortcut %r", combo)

        _register(up_combo, self.nav_select_up)
        _register(down_combo, self.nav_select_down)
        _register(activate_combo, self.nav_activate)

    def focusOutEvent(self, event: object) -> None:
        QTimer.singleShot(100, self._check_focus)
        super().focusOutEvent(event)  # type: ignore[arg-type]

    def _check_focus(self) -> None:
        if not self.isActiveWindow() and self.isVisible():
            self.hide_palette()
