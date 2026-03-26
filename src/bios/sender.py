import socket
from typing import Tuple

from src.config.settings import DCS_BIOS_HOST, DCS_BIOS_PORT


class DCSBiosSender:
    def __init__(self, host: str = DCS_BIOS_HOST, port: int = DCS_BIOS_PORT) -> None:
        self.sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addr: Tuple[str, int] = (host, port)

    def send(self, identifier: str, argument: str) -> None:
        message = f"{identifier} {argument}\n"
        self.sock.sendto(message.encode("ascii"), self.addr)

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
        self.sock.close()
