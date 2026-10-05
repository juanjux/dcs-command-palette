"""Small, acknowledged loopback protocol to the DCS GUI hook (not DCS-BIOS)."""
import socket
import time
import uuid
from typing import Optional

HEAD_TRACKING_PORT = 7781
HEAD_TRACKING_COMMANDS = {
    "__HEAD_TRACKING_DISABLE__": "disable",
    "__HEAD_TRACKING_ENABLE__": "enable",
    "__HEAD_TRACKING_TOGGLE__": "toggle",
}


class HeadTrackingClient:
    """One non-blocking request at a time; never retry a toggle automatically."""

    def __init__(self, port: int = HEAD_TRACKING_PORT) -> None:
        self._port = port
        self._socket: Optional[socket.socket] = None
        self._request_id = ""
        self._deadline = 0.0

    @property
    def pending(self) -> bool:
        return self._socket is not None

    def start(self, action: str) -> None:
        if action not in HEAD_TRACKING_COMMANDS.values():
            raise ValueError("Unknown head tracking action")
        if self.pending:
            raise RuntimeError("A head tracking request is already pending")
        self._request_id = uuid.uuid4().hex
        self._deadline = time.monotonic() + 3.0
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._socket.connect(("127.0.0.1", self._port))
            self._socket.setblocking(False)
            message = f"HT1 {self._request_id} {time.time() + 2.5:.3f} {action}"
            self._socket.send(message.encode("ascii"))
        except OSError:
            self.close()
            raise

    def poll(self) -> Optional[str]:
        """Return a confirmed state, None while waiting, or raise on failure."""
        if self._socket is None:
            return None
        try:
            for _ in range(8):
                try:
                    reply = self._socket.recv(1024).decode("ascii")
                except (BlockingIOError, UnicodeError):
                    break
                parts = reply.split(" ", 3)
                if len(parts) != 4 or parts[:2] != ["HT1", self._request_id]:
                    continue
                if parts[2] == "OK" and parts[3] in ("enabled", "disabled"):
                    self.close()
                    return parts[3]
                if parts[2] == "ERR":
                    raise RuntimeError(parts[3])
            if time.monotonic() >= self._deadline:
                raise TimeoutError(
                    "DCS did not confirm the change. Update the Palette Lua hook, "
                    "restart DCS, and try in an unpaused mission. "
                    "Use Enable or Disable to retry, not Toggle."
                )
        except (OSError, RuntimeError):
            self.close()
            raise
        return None

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
