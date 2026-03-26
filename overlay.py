from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer  # type: ignore[import-untyped]
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

from commands import Command, CommandSource
import config as cfg
from config import (
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
from dcs_bios import DCSBiosSender
from key_sender import send_key_combo
from search import search
from usage_tracker import UsageTracker


class ResultItem(QWidget):  # type: ignore[misc]
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
        dim = "#555555" if unbound else IDENTIFIER_COLOR
        dim_desc = "#444444" if unbound else TEXT_MUTED_COLOR

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
        if unbound:
            self.combo_label.setText("no key")
            self.combo_label.setStyleSheet(
                f"color: #664444; font-size: 10px; font-style: italic;"
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
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 8, 12, 8)
        self._layout.setSpacing(6)

    def set_command(self, cmd: Command, sender: DCSBiosSender) -> None:
        self.command = cmd
        self._sender = sender
        self._buttons: List[QPushButton] = []
        self._clear()

        header = QLabel(f"  {cmd.identifier} - {cmd.description}")
        header.setStyleSheet(
            f"color: {ACCENT_COLOR}; font-size: 14px; font-weight: bold;"
        )
        self._layout.addWidget(header)

        if cmd.has_set_string:
            self._add_string_input(cmd)
            return

        if cmd.position_labels and cmd.max_value is not None and cmd.max_value <= 10:
            self._add_position_buttons(cmd)

        if cmd.has_fixed_step or cmd.has_variable_step:
            self._add_inc_dec(cmd)

        if cmd.control_type in ("limited_dial", "analog_dial") and cmd.max_value is not None:
            self._add_slider(cmd)

        # Focus the first button so Enter/arrows work immediately
        if self._buttons:
            self._buttons[0].setFocus()

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

    def _add_position_buttons(self, cmd: Command) -> None:
        if not cmd.position_labels:
            return
        for pos, label in sorted(cmd.position_labels.items()):
            btn = QPushButton(f"  {pos} - {label}")
            btn.setStyleSheet(
                f"QPushButton {{ color: {TEXT_COLOR}; background: rgba(50,50,70,200); "
                f"border: 1px solid rgba(100,100,140,150); border-radius: 4px; "
                f"padding: 8px 16px; text-align: left; font-size: 13px; }}"
                f"QPushButton:hover, QPushButton:focus {{ background: rgba(60,120,220,120); }}"
            )
            btn.clicked.connect(lambda checked, p=pos: self._on_position(p))
            self._buttons.append(btn)
            self._layout.addWidget(btn)

    def _on_position(self, pos: int) -> None:
        if self.command:
            self.action_requested.emit(self.command.identifier, str(pos))
            self.close_requested.emit()

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
            dec_btn.clicked.connect(
                lambda: self.action_requested.emit(cmd.identifier, f"-{step}")
            )
            inc_btn.clicked.connect(
                lambda: self.action_requested.emit(cmd.identifier, f"+{step}")
            )
        else:
            dec_btn.clicked.connect(
                lambda: self.action_requested.emit(cmd.identifier, "DEC")
            )
            inc_btn.clicked.connect(
                lambda: self.action_requested.emit(cmd.identifier, "INC")
            )

        self._buttons.append(dec_btn)
        self._buttons.append(inc_btn)
        row.addWidget(dec_btn)
        row.addWidget(inc_btn)
        self._layout.addLayout(row)

    def _add_slider(self, cmd: Command) -> None:
        slider_row = QHBoxLayout()
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, cmd.max_value or 65535)
        slider.setStyleSheet(
            "QSlider::groove:horizontal { background: rgba(50,50,70,200); height: 8px; border-radius: 4px; }"
            "QSlider::handle:horizontal { background: #4a9eff; width: 16px; margin: -4px 0; border-radius: 8px; }"
        )
        value_label = QLabel("0")
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
    ) -> None:
        super().__init__()
        self._commands = commands
        self._usage = usage
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

    def _restart_inactivity_timer(self) -> None:
        timeout = cfg.AUTO_HIDE_SECONDS
        if timeout > 0:
            self._inactivity_timer.start(timeout * 1000)
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
            x = (geo.width() - self.width()) // 2
            y = int(geo.height() * 0.2)
            self.move(x, y)

        self.setWindowOpacity(0.0)
        self.show()
        self.activateWindow()
        self.raise_()
        self._search.setFocus()

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

    def _show_submenu(self, cmd: Command) -> None:
        self._in_submenu = True
        self._scroll.hide()
        self._search.setReadOnly(True)
        self._search.setText(f"{cmd.identifier} - {cmd.description}")
        self._submenu.set_command(cmd, self._sender)
        self._submenu.show()
        self.adjustSize()

    def _on_submenu_action(self, identifier: str, argument: str) -> None:
        self._sender.send(identifier, argument)

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

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        key = event.key()
        self._restart_inactivity_timer()

        if key == Qt.Key.Key_Escape:
            if self._in_submenu:
                self._back_from_submenu()
            else:
                self.hide_palette()
            return

        if self._in_submenu:
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

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._execute_selected()
            return

        super().keyPressEvent(event)

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
