from __future__ import annotations

import logging
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
    DESCRIPTION_FONT_SIZE,
    HIGHLIGHT_COLOR,
    IDENTIFIER_COLOR,
    IDENTIFIER_FONT_SIZE,
    OVERLAY_MAX_HEIGHT,
    OVERLAY_WIDTH,
    SEARCH_BG_COLOR,
    SEARCH_FONT_SIZE,
    TEXT_COLOR,
    TEXT_MUTED_COLOR,
)
from src.bios.state import BiosStateReader
from src.bios.sender import DCSBiosSender
from src.lib.key_sender import send_key_combo
from src.lib.search import search
from src.palette.usage import UsageTracker


class ResultItem(QWidget):  # type: ignore[misc]
    _state_reader: Optional[BiosStateReader] = None

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.command: Optional[Command] = None
        self._selected: bool = False
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(0)

        left = QVBoxLayout()
        left.setSpacing(1)
        left.setContentsMargins(0, 0, 0, 0)

        self.id_label = QLabel()
        self.id_label.setStyleSheet(
            f"color: {IDENTIFIER_COLOR}; font-size: {IDENTIFIER_FONT_SIZE}px; "
            f"font-family: 'Consolas', 'Courier New', monospace; font-weight: bold;"
        )
        left.addWidget(self.id_label)

        self.desc_label = QLabel()
        self.desc_label.setStyleSheet(
            f"color: {TEXT_MUTED_COLOR}; font-size: {DESCRIPTION_FONT_SIZE}px;"
        )
        left.addWidget(self.desc_label)

        layout.addLayout(left, stretch=1)

        # Right side: category tag + key combo
        right = QVBoxLayout()
        right.setSpacing(1)
        right.setContentsMargins(0, 0, 0, 0)

        self.cat_label = QLabel()
        self.cat_label.setStyleSheet(
            f"color: {CATEGORY_COLOR}; font-size: 11px; "
            f"padding: 2px 8px; border: 1px solid {CATEGORY_COLOR}; border-radius: 3px;"
        )
        self.cat_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(self.cat_label)

        self.combo_label = QLabel()
        self.combo_label.setStyleSheet(
            f"color: {TEXT_MUTED_COLOR}; font-size: 10px;"
        )
        self.combo_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(self.combo_label)

        layout.addLayout(right)

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
            f"color: {dim}; font-size: {IDENTIFIER_FONT_SIZE}px; "
            f"font-family: 'Consolas', 'Courier New', monospace; font-weight: bold;"
        )
        if cfg.SHOW_IDENTIFIERS:
            self.desc_label.setText(cmd.identifier)
            self.desc_label.setStyleSheet(f"color: {dim_desc}; font-size: {DESCRIPTION_FONT_SIZE}px;")
            self.desc_label.show()
        else:
            self.desc_label.setText("")
            self.desc_label.hide()
        cat = cmd.category if len(cmd.category) <= 30 else cmd.category[:27] + "..."
        self.cat_label.setText(cat)
        if bios_offline:
            self.combo_label.setText("BIOS offline")
            self.combo_label.setStyleSheet(
                f"color: #cc3333; font-size: 10px; font-style: italic;"
            )
        elif unbound:
            self.combo_label.setText("no key")
            self.combo_label.setStyleSheet(
                f"color: #cc3333; font-size: 10px; font-style: italic;"
            )
        else:
            self.combo_label.setText(cmd.key_combo if cmd.key_combo else "")
            self.combo_label.setStyleSheet(f"color: {TEXT_MUTED_COLOR}; font-size: 10px;")

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

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.command: Optional[Command] = None
        self._sender: Optional[DCSBiosSender] = None
        self._state_reader: Optional[BiosStateReader] = None
        self._slider: Optional[QSlider] = None
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
                f"color: {ACCENT_COLOR}; font-size: 12px;"
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
                f"padding: 8px 16px; text-align: left; font-size: 13px; font-weight: bold; }}"
                f"QPushButton:hover, QPushButton:focus {{ background: rgba(60,120,220,220); }}"
            )
        return (
            f"QPushButton {{ color: {TEXT_COLOR}; background: rgba(50,50,70,200); "
            f"border: 1px solid rgba(100,100,140,150); border-radius: 4px; "
            f"padding: 8px 16px; text-align: left; font-size: 13px; }}"
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
        # Visually update: highlight the selected button, dim the old one
        for i, btn in enumerate(self._buttons):
            is_new = (i == pos)
            btn.setStyleSheet(self._make_btn_style(is_new))
            if is_new and self._current_value != pos:
                # Flash with a brief marker update
                old_text = btn.text()
                btn.setText(old_text.rstrip(" ◄") + " ◄")
        self._current_value = pos
        self.action_requested.emit(self.command.identifier, str(pos))
        # Delay close so the user sees the selection
        QTimer.singleShot(300, self.close_requested.emit)

    def _add_inc_dec(self, cmd: Command) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)

        dec_btn = QPushButton("  DEC")
        inc_btn = QPushButton("INC  ")
        for btn in (dec_btn, inc_btn):
            btn.setStyleSheet(
                f"QPushButton {{ color: {TEXT_COLOR}; background: rgba(50,50,70,200); "
                f"border: 1px solid rgba(100,100,140,150); border-radius: 4px; "
                f"padding: 8px 24px; font-size: 13px; font-weight: bold; }}"
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
        value_label.setStyleSheet(f"color: {TEXT_COLOR}; font-size: 12px; min-width: 50px;")
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
            f"padding: 8px; font-size: 14px;"
        )
        send_btn = QPushButton("Send")
        send_btn.setStyleSheet(
            f"QPushButton {{ color: {TEXT_COLOR}; background: rgba(60,120,220,180); "
            f"border-radius: 4px; padding: 8px 16px; font-size: 13px; font-weight: bold; }}"
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
        self._sender = sender
        self._results: List[Command] = []
        self._selected_index: int = 0
        self._in_submenu: bool = False

        # Callback for built-in palette commands (set by main.py)
        self.palette_command_triggered: Optional[object] = None

        self._setup_window()
        self._build_ui()

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Auto-hide timer
        self._inactivity_timer = QTimer()
        self._inactivity_timer.setSingleShot(True)
        self._inactivity_timer.timeout.connect(self.hide_palette)

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
            f"padding: 12px 16px; font-size: {SEARCH_FONT_SIZE}px; }}"
        )
        self._search.textChanged.connect(self._on_search_changed)
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
        self._submenu.hide()
        self._container_layout.addWidget(self._submenu)

        self._main_layout.addWidget(self._container)

        self._item_widgets: List[ResultItem] = []

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

        # Vertical — estimate overlay height (~60px search + results)
        overlay_h = min(OVERLAY_MAX_HEIGHT, 60 + len(self._results) * 50)
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

    def show_palette(self) -> None:
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

    def _on_search_changed(self, text: str) -> None:
        self._results = search(text, self._commands, self._usage)
        self._selected_index = 0
        self._update_results_display()
        self._restart_inactivity_timer()

    def _update_results_display(self) -> None:
        while self._results_layout.count() > 0:
            item = self._results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()

        while len(self._item_widgets) < len(self._results):
            item_widget = ResultItem(self._results_widget)
            idx = len(self._item_widgets)
            item_widget.mousePressEvent = lambda e, i=idx: self._on_item_clicked(i)  # type: ignore[assignment]
            self._item_widgets.append(item_widget)

        for i, cmd in enumerate(self._results):
            widget = self._item_widgets[i]
            widget.set_command(cmd)
            widget.set_selected(i == self._selected_index)
            widget.show()
            self._results_layout.addWidget(widget)

        self._results_layout.addStretch()

        item_count = len(self._results)
        results_height = min(item_count * 52, OVERLAY_MAX_HEIGHT - 60)
        self._scroll.setFixedHeight(results_height + 10)
        self.adjustSize()

    def _on_item_clicked(self, index: int) -> None:
        self._selected_index = index
        self._update_results_display()
        self._execute_selected()

    def _execute_selected(self) -> None:
        if not self._results or self._selected_index >= len(self._results):
            return

        cmd = self._results[self._selected_index]
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
                f"padding: 12px 16px; font-size: {SEARCH_FONT_SIZE}px; }}"
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
                    f"padding: 12px 16px; font-size: {SEARCH_FONT_SIZE}px; }}"
                )
                self._search.setText("No keybinding assigned for this command")
                self._search.setReadOnly(True)
                QTimer.singleShot(1500, self._reset_search_style)
            return

        # DCS-BIOS: simple toggle (max_value <= 1)
        if cmd.max_value is not None and cmd.max_value <= 1:
            if cmd.has_toggle:
                self._sender.toggle(cmd.identifier)
            elif cmd.has_fixed_step:
                self._sender.inc(cmd.identifier)
            else:
                self._sender.set_state(cmd.identifier, 1)
            self.hide_palette()
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
                f"padding: 12px 16px; font-size: {SEARCH_FONT_SIZE}px; }}"
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
        """Intercept Tab/Shift+Tab before Qt's default focus chain."""
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
        logger.debug("keyPressEvent: key=%s (0x%x), in_submenu=%s", event.text(), key, self._in_submenu)
        self._restart_inactivity_timer()

        if key == Qt.Key.Key_Escape:
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
            if self._results:
                self._selected_index = min(self._selected_index + 1, len(self._results) - 1)
                self._update_results_display()
                self._ensure_visible()
            return

        if key == Qt.Key.Key_Up:
            if self._results:
                self._selected_index = max(self._selected_index - 1, 0)
                self._update_results_display()
                self._ensure_visible()
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
            self._execute_selected()
            return

        super().keyPressEvent(event)

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
            f"padding: 12px 16px; font-size: {SEARCH_FONT_SIZE}px; }}"
        )
        self._search.setReadOnly(False)
        self._search.clear()
        self._search.setFocus()

    def _ensure_visible(self) -> None:
        if self._selected_index < len(self._item_widgets):
            widget = self._item_widgets[self._selected_index]
            self._scroll.ensureWidgetVisible(widget, 0, 10)

    def focusOutEvent(self, event: object) -> None:
        QTimer.singleShot(100, self._check_focus)
        super().focusOutEvent(event)  # type: ignore[arg-type]

    def _check_focus(self) -> None:
        if not self.isActiveWindow() and self.isVisible():
            self.hide_palette()
