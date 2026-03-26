"""Read live DCS-BIOS export data to get current cockpit state.

DCS-BIOS exports cockpit state as a 65536-byte frame via UDP.
Each control's output specifies an address (byte offset), mask, and shift
to extract its current value from the frame.

Protocol (port 5010):
- Sync bytes: 0x55 0x55 0x55 0x55
- Then pairs of: [address (uint16)] [count (uint16)] [data (count bytes)]
- Frame end: address=0x5555, count=0x5555
"""
from __future__ import annotations

import logging
import socket
import struct
import threading
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

BIOS_MULTICAST_ADDR = "239.255.50.10"
BIOS_EXPORT_PORT = 5010
FRAME_SIZE = 65536

# Sync sequence that marks end of an update frame
SYNC_ADDR = 0x5555


class BiosStateReader:
    """Reads DCS-BIOS export stream and maintains current cockpit state."""

    def __init__(
        self,
        multicast_addr: str = BIOS_MULTICAST_ADDR,
        port: int = BIOS_EXPORT_PORT,
    ) -> None:
        self._multicast_addr = multicast_addr
        self._port = port
        self._frame = bytearray(FRAME_SIZE)
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        self._on_frame_update: Optional[Callable[[], None]] = None

    def start(self, on_frame_update: Optional[Callable[[], None]] = None) -> bool:
        """Start listening for DCS-BIOS export data.

        DCS-BIOS sends state updates via UDP multicast to 239.255.50.10:5010.
        We join the multicast group to receive the data.

        Args:
            on_frame_update: Optional callback invoked after each complete frame update.
        """
        self._on_frame_update = on_frame_update
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.settimeout(2.0)
            self._sock.bind(("", self._port))

            # Join the multicast group
            mreq = struct.pack(
                "4s4s",
                socket.inet_aton(self._multicast_addr),
                socket.inet_aton("0.0.0.0"),
            )
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError as e:
            logger.warning("Could not bind DCS-BIOS multicast listener (%s:%d): %s",
                           self._multicast_addr, self._port, e)
            return False

        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
        logger.info("DCS-BIOS state reader listening on %s:%d", self._multicast_addr, self._port)
        return True

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()

    def get_value(self, address: int, mask: int, shift_by: int) -> int:
        """Read a control's current value from the frame buffer."""
        with self._lock:
            if address + 1 >= FRAME_SIZE:
                return 0
            # DCS-BIOS uses little-endian uint16 at each address
            raw = self._frame[address] | (self._frame[address + 1] << 8)
        return (raw & mask) >> shift_by

    def _listen(self) -> None:
        while self._running:
            try:
                data, _addr = self._sock.recvfrom(4096)  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.debug("DCS-BIOS export socket closed")
                break

            self._process_packet(data)

    def _process_packet(self, data: bytes) -> None:
        """Process a DCS-BIOS export UDP packet.

        Each packet contains one or more update chunks:
        [address: uint16_le] [count: uint16_le] [data: count bytes]
        """
        offset = 0
        frame_complete = False

        while offset + 4 <= len(data):
            addr = struct.unpack_from("<H", data, offset)[0]
            count = struct.unpack_from("<H", data, offset + 2)[0]
            offset += 4

            if addr == SYNC_ADDR and count == SYNC_ADDR:
                frame_complete = True
                continue

            if offset + count > len(data):
                break

            with self._lock:
                end = min(addr + count, FRAME_SIZE)
                copy_len = end - addr
                if copy_len > 0:
                    self._frame[addr:end] = data[offset:offset + copy_len]

            offset += count

        if frame_complete and self._on_frame_update:
            try:
                self._on_frame_update()
            except Exception:
                logger.exception("Error in frame update callback")
