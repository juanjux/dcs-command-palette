import logging
import socket
import threading
from typing import Optional, Tuple

from src.config.settings import DCS_BIOS_HOST, DCS_BIOS_PORT

logger = logging.getLogger(__name__)


class DCSBiosSender:
    def __init__(self, host: str = DCS_BIOS_HOST, port: int = DCS_BIOS_PORT) -> None:
        self.addr: Tuple[str, int] = (host, port)
        self._tcp_sock: Optional[socket.socket] = None
        self._use_tcp: Optional[bool] = None  # None = probe in progress
        self._probe_done = threading.Event()
        # Always create UDP socket (cheap fallback)
        self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Probe TCP in background to avoid blocking startup
        threading.Thread(target=self._run_probe, daemon=True).start()

    def _run_probe(self) -> None:
        """Probe DCS-BIOS protocol in a background thread."""
        result = self._probe_tcp()
        self._use_tcp = result
        self._probe_done.set()
        if result:
            logger.info("DCS-BIOS sender using TCP to %s:%d", *self.addr)
        else:
            logger.info("DCS-BIOS sender using UDP to %s:%d", *self.addr)

    def _probe_tcp(self) -> bool:
        """Check if DCS-BIOS is listening on TCP."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(self.addr)
            s.close()
            return True
        except (ConnectionRefusedError, OSError, TimeoutError):
            return False

    def _get_tcp_sock(self) -> Optional[socket.socket]:
        """Get or create a TCP connection."""
        if self._tcp_sock is not None:
            return self._tcp_sock
        try:
            self._tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._tcp_sock.settimeout(2.0)
            self._tcp_sock.connect(self.addr)
            logger.debug("TCP connection established to %s", self.addr)
            return self._tcp_sock
        except (ConnectionRefusedError, OSError, TimeoutError) as e:
            logger.warning("TCP connect to %s failed: %s", self.addr, e)
            self._tcp_sock = None
            return None

    def send(self, identifier: str, argument: str) -> None:
        message = f"{identifier} {argument}\n"
        # Wait for probe if it hasn't finished yet (should be instant by first use)
        if self._use_tcp is None:
            self._probe_done.wait(timeout=1.0)
            if self._use_tcp is None:
                self._use_tcp = False  # default to UDP on timeout
        if self._use_tcp:
            sock = self._get_tcp_sock()
            if sock:
                try:
                    sock.sendall(message.encode("ascii"))
                    logger.debug("TCP send to %s: %r", self.addr, message)
                    return
                except (BrokenPipeError, ConnectionResetError, OSError) as e:
                    logger.warning("TCP send failed: %s, reconnecting...", e)
                    self._tcp_sock = None
                    # Retry once with a fresh connection
                    sock = self._get_tcp_sock()
                    if sock:
                        try:
                            sock.sendall(message.encode("ascii"))
                            logger.debug("TCP send (retry) to %s: %r", self.addr, message)
                            return
                        except OSError as e2:
                            logger.error("TCP send retry failed: %s", e2)
            else:
                logger.warning("No TCP connection, cannot send: %r", message)
        else:
            logger.debug("UDP send to %s: %r", self.addr, message)
            self._udp_sock.sendto(message.encode("ascii"), self.addr)

    def toggle(self, identifier: str) -> None:
        self.send(identifier, "TOGGLE")

    def set_state(self, identifier: str, value: int) -> None:
        self.send(identifier, str(value))

    def inc(self, identifier: str) -> None:
        self.send(identifier, "INC")

    def dec(self, identifier: str) -> None:
        self.send(identifier, "DEC")

    def variable_step(self, identifier: str, delta: int) -> None:
        sign = "+" if delta >= 0 else ""
        self.send(identifier, f"{sign}{delta}")

    def close(self) -> None:
        if self._tcp_sock:
            try:
                self._tcp_sock.close()
            except OSError:
                pass
        self._udp_sock.close()
