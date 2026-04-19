"""Local HTTP server that exposes the palette to OpenKneeboard's web-tab view.

Runs on ``127.0.0.1:<port>`` (default 7788).  Only bound to localhost — never
accepts connections from outside the machine.

Endpoints:
  GET  /                  → index.html
  GET  /static/<file>     → CSS/JS assets
  GET  /api/search?q=...  → JSON list of search results (shared with overlay)
  POST /api/execute       → body {identifier, value?} executes a command
  POST /api/favorite      → body {identifier} toggles favorite, returns new state
  GET  /api/status        → {bios_connected, vr_active}
  POST /api/submenu       → body {identifier} returns submenu info for a command

All responses are JSON except static files.  The handler holds references
to the same ``UsageTracker`` / ``DCSBiosSender`` / commands list used by the
desktop overlay, so favorites and usage are shared.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from src.bios.sender import DCSBiosSender
from src.bios.state import BiosStateReader
from src.palette.commands import Command, CommandSource
from src.palette.usage import UsageTracker
from src.lib.search import search

logger = logging.getLogger(__name__)


def _resolve_static_dir() -> str:
    """Locate the bundled static assets for both source and frozen builds.

    In a PyInstaller --onedir build, data files land under ``sys._MEIPASS`` or
    next to the extracted ``src`` tree.  ``__file__`` will be inside
    ``_internal/src/vr/`` at runtime, so the sibling ``static`` folder just
    works — but we check a couple of fallback locations for safety.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    primary = os.path.join(here, "static")
    if os.path.isdir(primary):
        return primary
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        alt = os.path.join(meipass, "src", "vr", "static")
        if os.path.isdir(alt):
            return alt
    # Last resort — return primary even if missing so errors are loud
    return primary


STATIC_DIR = _resolve_static_dir()

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class VRServerContext:
    """Shared state injected into each request handler.

    We can't use __init__ args on BaseHTTPRequestHandler directly; instead the
    server instance carries a ``context`` attribute that handlers read.
    """

    def __init__(
        self,
        commands: List[Command],
        usage: UsageTracker,
        sender: DCSBiosSender,
        state_reader: Optional[BiosStateReader] = None,
        vr_active_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.commands = commands
        self.usage = usage
        self.sender = sender
        self.state_reader = state_reader
        self._vr_active_fn = vr_active_fn

    def vr_active(self) -> bool:
        if self._vr_active_fn is None:
            return False
        try:
            return bool(self._vr_active_fn())
        except Exception:  # noqa: BLE001
            return False

    def update_commands(self, commands: List[Command]) -> None:
        """Swap the command set (called on aircraft change)."""
        self.commands = commands


class VRRequestHandler(BaseHTTPRequestHandler):
    # Silence stdlib's per-request logging — we have our own
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug("%s - %s", self.address_string(), format % args)

    # Short timeout so slow clients don't hold a thread
    timeout = 10

    @property
    def ctx(self) -> VRServerContext:
        return self.server.context  # type: ignore[attr-defined]

    # ── Helpers ────────────────────────────────────────────────
    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _send_static(self, relpath: str) -> None:
        # Block path traversal — static files only
        safe = os.path.normpath(relpath).replace("\\", "/").lstrip("/")
        if safe.startswith("..") or os.path.isabs(safe):
            self._send_error_json(400, "bad path")
            return
        full = os.path.join(STATIC_DIR, safe)
        if not os.path.isfile(full):
            self._send_error_json(404, "not found")
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = _MIME.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError as e:
            logger.warning("Static read failed %s: %s", full, e)
            self._send_error_json(500, "read error")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> Optional[Dict[str, Any]]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > 1_000_000:
            return None
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return None

    # ── Serialization ──────────────────────────────────────────
    def _cmd_to_dict(self, cmd: Command) -> Dict[str, Any]:
        return {
            "identifier": cmd.identifier,
            "description": cmd.description,
            "category": cmd.category,
            "source": cmd.source.value,
            "key_combo": cmd.key_combo,
            "favorite": self.ctx.usage.is_favorite(cmd.identifier),
            "is_momentary": bool(cmd.is_momentary),
            "is_spring_loaded": bool(cmd.is_spring_loaded),
            "max_value": cmd.max_value,
            "position_labels": (
                {str(k): v for k, v in cmd.position_labels.items()}
                if cmd.position_labels else None
            ),
            "has_fixed_step": cmd.has_fixed_step,
            "has_variable_step": cmd.has_variable_step,
            "has_set_string": cmd.has_set_string,
            "has_toggle": cmd.has_toggle,
        }

    # ── GET dispatch ──────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802 — stdlib API
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/" or path == "/index.html":
                self._send_static("index.html")
                return
            if path.startswith("/static/"):
                self._send_static(path[len("/static/"):])
                return
            if path == "/api/search":
                q = parse_qs(parsed.query).get("q", [""])[0]
                results = search(q, self.ctx.commands, self.ctx.usage)
                self._send_json({"results": [self._cmd_to_dict(c) for c in results]})
                return
            if path == "/api/status":
                bios_connected = (
                    self.ctx.state_reader is not None
                    and self.ctx.state_reader.connected
                )
                self._send_json({
                    "bios_connected": bool(bios_connected),
                    "vr_active": self.ctx.vr_active(),
                })
                return
            self._send_error_json(404, "not found")
        except Exception:  # noqa: BLE001
            logger.exception("GET handler failed for %s", self.path)
            try:
                self._send_error_json(500, "server error")
            except Exception:  # noqa: BLE001
                pass

    # ── POST dispatch ─────────────────────────────────────────
    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            body = self._read_json_body()
            if body is None:
                self._send_error_json(400, "invalid json")
                return

            if path == "/api/execute":
                self._handle_execute(body)
                return
            if path == "/api/favorite":
                self._handle_favorite(body)
                return
            self._send_error_json(404, "not found")
        except Exception:  # noqa: BLE001
            logger.exception("POST handler failed for %s", self.path)
            try:
                self._send_error_json(500, "server error")
            except Exception:  # noqa: BLE001
                pass

    def _find_cmd(self, identifier: str) -> Optional[Command]:
        for c in self.ctx.commands:
            if c.identifier == identifier:
                return c
        return None

    def _handle_favorite(self, body: Dict[str, Any]) -> None:
        ident = str(body.get("identifier", "")).strip()
        if not ident:
            self._send_error_json(400, "missing identifier")
            return
        new_state = self.ctx.usage.toggle_favorite(ident)
        self._send_json({"identifier": ident, "favorite": new_state})

    def _handle_execute(self, body: Dict[str, Any]) -> None:
        ident = str(body.get("identifier", "")).strip()
        if not ident:
            self._send_error_json(400, "missing identifier")
            return
        cmd = self._find_cmd(ident)
        if cmd is None:
            self._send_error_json(404, "unknown identifier")
            return

        action = str(body.get("action", "execute"))
        raw_value = body.get("value")

        # Record usage — mirrors what _execute_selected does on the desktop side
        self.ctx.usage.record_use(ident)

        # Keyboard shortcut → simulate key combo via the existing helper
        if cmd.source == CommandSource.KEYBOARD:
            if cmd.key_combo:
                from src.lib.key_sender import send_key_combo
                send_key_combo(cmd.key_combo)
                self._send_json({"ok": True, "mode": "key_combo"})
            else:
                self._send_json({"ok": False, "error": "no key binding"})
            return

        # DCS-BIOS
        if cmd.source == CommandSource.DCS_BIOS:
            if action == "set_state":
                try:
                    value = int(raw_value) if raw_value is not None else 0
                except (TypeError, ValueError):
                    self._send_error_json(400, "invalid value")
                    return
                self.ctx.sender.set_state(ident, value)
                self._send_json({"ok": True, "mode": "set_state", "value": value})
                return
            if action == "toggle":
                # Read current state to pick the opposite (matches overlay.py logic)
                current = None
                if (
                    self.ctx.state_reader is not None
                    and self.ctx.state_reader.connected
                    and cmd.output_address is not None
                    and cmd.output_mask is not None
                    and cmd.output_shift is not None
                ):
                    current = self.ctx.state_reader.get_value(
                        cmd.output_address, cmd.output_mask, cmd.output_shift,
                    )
                new_val = 0 if current else 1
                self.ctx.sender.set_state(ident, new_val)
                self._send_json({
                    "ok": True, "mode": "toggle",
                    "prev": current, "new": new_val,
                })
                return
            if action == "momentary_press":
                self.ctx.sender.set_state(ident, 1)
                self._send_json({"ok": True, "mode": "momentary_press"})
                return
            if action == "momentary_release":
                self.ctx.sender.set_state(ident, 0)
                self._send_json({"ok": True, "mode": "momentary_release"})
                return
            if action == "inc":
                self.ctx.sender.inc(ident)
                self._send_json({"ok": True, "mode": "inc"})
                return
            if action == "dec":
                self.ctx.sender.dec(ident)
                self._send_json({"ok": True, "mode": "dec"})
                return
            if action == "variable_step":
                # Signed delta for continuous controls (dimmers, volume knobs)
                try:
                    delta = int(raw_value) if raw_value is not None else 0
                except (TypeError, ValueError):
                    self._send_error_json(400, "invalid variable_step value")
                    return
                self.ctx.sender.variable_step(ident, delta)
                self._send_json({"ok": True, "mode": "variable_step", "delta": delta})
                return
            if action == "set_string":
                if not isinstance(raw_value, str):
                    self._send_error_json(400, "value must be string")
                    return
                self.ctx.sender.send(ident, raw_value)
                self._send_json({"ok": True, "mode": "set_string"})
                return
            # Default: treat as simple toggle for max_value == 1, else set_state 0
            if cmd.max_value is not None and cmd.max_value <= 1:
                # Treat as momentary press — client sends release separately
                self.ctx.sender.set_state(ident, 1)
                self._send_json({"ok": True, "mode": "press"})
            else:
                self._send_error_json(400, "no action for multi-position command")
            return

        self._send_error_json(400, "unsupported command source")


class _Server(ThreadingHTTPServer):
    """Tiny wrapper so we can stash a context attribute on the server."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: tuple, handler: type, context: VRServerContext) -> None:
        super().__init__(addr, handler)
        self.context = context


class VRServer:
    """Start/stop wrapper around a threaded HTTP server.

    Lifecycle:
        srv = VRServer(commands, usage, sender, state_reader, vr_active_fn)
        srv.start(port=7788)
        ...
        srv.stop()

    Safe to call ``start`` and ``stop`` repeatedly; extra calls are no-ops.
    """

    def __init__(
        self,
        commands: List[Command],
        usage: UsageTracker,
        sender: DCSBiosSender,
        state_reader: Optional[BiosStateReader] = None,
        vr_active_fn: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._context = VRServerContext(
            commands=commands, usage=usage, sender=sender,
            state_reader=state_reader, vr_active_fn=vr_active_fn,
        )
        self._server: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None
        self._port: Optional[int] = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def port(self) -> Optional[int]:
        return self._port

    @property
    def url(self) -> Optional[str]:
        if self._port is None:
            return None
        return f"http://127.0.0.1:{self._port}/"

    def update_commands(self, commands: List[Command]) -> None:
        self._context.update_commands(commands)

    def update_sender(self, sender: DCSBiosSender) -> None:
        self._context.sender = sender

    def start(self, port: int = 7788) -> bool:
        if self._server is not None:
            return True
        try:
            srv = _Server(("127.0.0.1", port), VRRequestHandler, self._context)
        except OSError as e:
            logger.warning("VR server failed to bind 127.0.0.1:%d — %s", port, e)
            return False
        self._server = srv
        self._port = port
        self._thread = threading.Thread(
            target=srv.serve_forever, name=f"VRServer:{port}",
            daemon=True,
        )
        self._thread.start()
        logger.info("VR server listening on http://127.0.0.1:%d/", port)
        return True

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:  # noqa: BLE001
            logger.exception("VR server shutdown failed")
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None
        logger.info("VR server stopped (was port %s)", self._port)
        self._port = None
