import socket
from unittest.mock import MagicMock, patch

from dcs_bios import DCSBiosSender


def test_send_format() -> None:
    sender = DCSBiosSender()
    sender.sock = MagicMock()
    sender.send("MASTER_ARM_SW", "TOGGLE")
    sender.sock.sendto.assert_called_once_with(
        b"MASTER_ARM_SW TOGGLE\n", ("127.0.0.1", 7778)
    )


def test_toggle() -> None:
    sender = DCSBiosSender()
    sender.sock = MagicMock()
    sender.toggle("GEAR_LEVER")
    sender.sock.sendto.assert_called_once_with(
        b"GEAR_LEVER TOGGLE\n", ("127.0.0.1", 7778)
    )


def test_set_state() -> None:
    sender = DCSBiosSender()
    sender.sock = MagicMock()
    sender.set_state("MC_SW", 1)
    sender.sock.sendto.assert_called_once_with(
        b"MC_SW 1\n", ("127.0.0.1", 7778)
    )


def test_inc_dec() -> None:
    sender = DCSBiosSender()
    sender.sock = MagicMock()
    sender.inc("UFC_COMM1_CHANNEL_SELECT")
    sender.sock.sendto.assert_called_once_with(
        b"UFC_COMM1_CHANNEL_SELECT INC\n", ("127.0.0.1", 7778)
    )


def test_variable_step_positive() -> None:
    sender = DCSBiosSender()
    sender.sock = MagicMock()
    sender.variable_step("AMPCD_BRT_CTL", 3200)
    sender.sock.sendto.assert_called_once_with(
        b"AMPCD_BRT_CTL +3200\n", ("127.0.0.1", 7778)
    )


def test_variable_step_negative() -> None:
    sender = DCSBiosSender()
    sender.sock = MagicMock()
    sender.variable_step("AMPCD_BRT_CTL", -3200)
    sender.sock.sendto.assert_called_once_with(
        b"AMPCD_BRT_CTL -3200\n", ("127.0.0.1", 7778)
    )
