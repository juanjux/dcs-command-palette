"""Test the real Lua hook with a fake DCS host, and the UDP client separately."""
import socket
from pathlib import Path
from unittest.mock import patch

import pytest
from lupa import LuaRuntime

from src.lib.head_tracking import HeadTrackingClient


@pytest.fixture
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.execute('''
        now = 1000
        queue, replies, changes = {}, {}, {}
        configured, native = false, false
        devices = {'TrackIR', 'Mouse', 'Joystick'}
        lfs = {writedir = function() return 'missing/' end}
        log = {INFO=1, ERROR=2, WARNING=3, write=function() end}
        DCS = {getPlayerUnitType=function() return nil end,
               setUserCallbacks=function(c) callbacks=c end}
        udp = {
          settimeout=function() end, setsockname=function() return true end,
          close=function() end,
          receivefrom=function()
            local r=table.remove(queue, 1)
            if r then return r[1], r[2], r[3] end
          end,
          sendto=function(_, msg) replies[#replies+1]=msg end
        }
        package.preload['socket']=function()
          return {udp=function() return udp end, gettime=function() return now end}
        end
        package.preload['Input']=function() return {
          getDevices=function() return devices end,
          getDeviceTypeName=function(n) return n end,
          getTrackirDeviceTypeName=function() return 'TrackIR' end,
          setDeviceDisabled=function(name, disabled)
            assert(name=='TrackIR')
            if failSetter then error('setter unavailable') end
            native=disabled; changes[#changes+1]=disabled
          end
        } end
        package.preload['Input.Data']=function() return {
          getDeviceDisabled=function() return configured end
        } end
        function request(action, id, expiry, host)
          queue[#queue+1]={'HT1 '..(id or string.rep('a',32))..' '..
            tostring(expiry or 1002)..' '..action, host or '127.0.0.1', 12345}
          callbacks.onSimulationFrame()
        end
    ''')
    hook = Path(__file__).parents[1] / "src/lua/dcs_command_palette_hook.lua"
    runtime.execute(hook.read_text(encoding="utf-8"))
    runtime.execute("callbacks.onSimulationStart()")
    return runtime


def test_lua_toggle_dedup_and_restore(lua):
    lua.execute("request('toggle')")
    assert lua.globals().native is True
    assert lua.globals().configured is False  # no persistence
    lua.execute("request('toggle')")  # duplicate datagram: do not toggle twice
    assert lua.globals().native is True
    assert len(lua.globals().changes) == 1
    lua.execute("request('toggle', string.rep('b',32))")
    assert lua.globals().native is False
    lua.execute("request('disable', string.rep('c',32)); callbacks.onSimulationStop()")
    assert lua.globals().native is False


def test_lua_enable_preserves_original_disabled_setting(lua):
    lua.execute("configured=true; native=true; request('enable')")
    assert lua.globals().native is False
    lua.execute("callbacks.onSimulationStop()")
    assert lua.globals().native is True


def test_lua_pause_restores_and_allows_new_request(lua):
    lua.execute("request('disable'); callbacks.onSimulationPause()")
    assert lua.globals().native is False
    lua.execute("request('disable', string.rep('b',32))")
    assert lua.globals().native is True


def test_lua_rejects_expired_unknown_and_remote_requests(lua):
    lua.execute("request('toggle', nil, 999)")
    assert "ERR" in lua.globals().replies[1]
    lua.execute("request('execute'); request('disable', nil, nil, '10.0.0.1')")
    assert len(lua.globals().changes) == 0
    assert len(lua.globals().replies) == 1


def test_lua_no_tracker_and_api_failure(lua):
    lua.execute("devices={'Mouse'}; request('disable')")
    assert "ERR" in lua.globals().replies[1]
    assert len(lua.globals().changes) == 0
    lua.execute("devices={'TrackIR'}; failSetter=true; request('disable', string.rep('b',32))")
    assert "ERR" in lua.globals().replies[2]


@pytest.fixture
def connection():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind(("127.0.0.1", 0))
        server.settimeout(1)
        client = HeadTrackingClient(server.getsockname()[1])
        try:
            yield client, server
        finally:
            client.close()


def test_client_ack_and_busy(connection):
    client, server = connection
    client.start("disable")
    with pytest.raises(RuntimeError):
        client.start("toggle")
    data, address = server.recvfrom(1024)
    version, request_id, expiry, action = data.decode().split()
    assert (version, action) == ("HT1", "disable")
    assert float(expiry) > 0
    server.sendto(b"HT1 wrong-id OK disabled", address)
    assert client.poll() is None
    server.sendto(f"HT1 {request_id} OK disabled".encode(), address)
    assert client.poll() == "disabled"
    assert not client.pending


def test_client_error_and_timeout(connection):
    client, server = connection
    client.start("enable")
    data, address = server.recvfrom(1024)
    request_id = data.decode().split()[1]
    server.sendto(f"HT1 {request_id} ERR No device".encode(), address)
    with pytest.raises(RuntimeError, match="No device"):
        client.poll()
    assert not client.pending
    client.start("toggle")
    with patch("src.lib.head_tracking.time.monotonic", return_value=float("inf")):
        with pytest.raises(TimeoutError):
            client.poll()
    assert not client.pending


def test_client_rejects_unknown_action():
    with pytest.raises(ValueError):
        HeadTrackingClient().start("arbitrary Lua")


def test_commands_available_for_all_aircraft_without_bios():
    from src.main import _add_palette_commands
    from src.lib.head_tracking import HEAD_TRACKING_COMMANDS
    from src.palette.commands import CommandSource

    commands = _add_palette_commands([])
    tracking = [c for c in commands if c.identifier in HEAD_TRACKING_COMMANDS]
    assert len(tracking) == 3
    assert all(c.source == CommandSource.KEYBOARD and not c.key_combo for c in tracking)


def test_app_dispatches_and_polls_confirmation():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from src.main import App

    app = SimpleNamespace(
        _head_tracking=Mock(), _head_tracking_timer=Mock(),
        _head_tracking_feedback=Mock(),
    )
    App._on_palette_command(app, "__HEAD_TRACKING_DISABLE__")
    app._head_tracking.start.assert_called_once_with("disable")
    app._head_tracking_timer.start.assert_called_once()
    app._head_tracking_feedback.assert_not_called()
    app._head_tracking.poll.return_value = "disabled"
    App._poll_head_tracking(app)
    app._head_tracking_timer.stop.assert_called_once()
    assert "disabled" in app._head_tracking_feedback.call_args.args[0]
