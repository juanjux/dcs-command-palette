"""Detect whether the user is playing DCS in VR and whether OpenKneeboard is installed.

VR state is read from ``%USERPROFILE%/Saved Games/DCS/Config/options.lua``
(``VR.enable`` entry).  We use a small regex rather than a real Lua parser —
the relevant block is always formatted the same way by DCS and the file is
small.

OpenKneeboard presence is detected by checking its standard install paths
and registry entry.  We never launch or modify OpenKneeboard; we only want
to tell the user whether to install it.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from typing import Callable, Optional

from src.config.settings import DCS_SAVED_GAMES

logger = logging.getLogger(__name__)


# Matches: ["VR"] = { ... ["enable"] = true/false, ... }
# The VR block has many keys so we use a non-greedy match up to the closing
# brace and look for "enable" anywhere inside.
_VR_ENABLE_RE = re.compile(
    r'\[\s*"VR"\s*\]\s*=\s*\{[^{}]*?\[\s*"enable"\s*\]\s*=\s*(true|false)',
    re.DOTALL,
)


def read_vr_enabled(options_path: Optional[str] = None) -> Optional[bool]:
    """Return True/False from DCS options.lua VR.enable, or None if unknown.

    Returns None when the file is missing or unparseable — the caller should
    treat this as "don't know" rather than "VR is off".
    """
    if options_path is None:
        options_path = os.path.join(DCS_SAVED_GAMES, "Config", "options.lua")
    if not os.path.isfile(options_path):
        return None
    try:
        with open(options_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        logger.debug("Cannot read %s: %s", options_path, e)
        return None
    m = _VR_ENABLE_RE.search(text)
    if not m:
        return None
    return m.group(1) == "true"


def detect_openkneeboard() -> Optional[str]:
    """Return the directory containing OpenKneeboardApp.exe, or None.

    Checks (in order):
    1. Common install path roots — both the root folder and the ``bin/``
       subfolder used by modern OpenKneeboard installers.
    2. Walking up from a running instance's executable path (most reliable
       if the app is actually running — uses tasklist to find the PID then
       WMI/PowerShell for the path).
    3. Windows Registry install locations.

    Returns the directory containing ``OpenKneeboardApp.exe`` (so callers can
    use ``os.path.join(dir, 'OpenKneeboardApp.exe')`` directly).
    """
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_appdata = os.environ.get("LOCALAPPDATA", "")

    # 1. Path candidates — try both plain install dir and bin/ subdir
    roots = [
        os.path.join(program_files, "OpenKneeboard"),
        os.path.join(program_files_x86, "OpenKneeboard"),
        os.path.join(local_appdata, "Programs", "OpenKneeboard"),
    ]
    for root in roots:
        for sub in ("bin", ""):
            candidate = os.path.join(root, sub, "OpenKneeboardApp.exe")
            if os.path.isfile(candidate):
                return os.path.dirname(candidate)

    # 2. Live-process lookup — cheapest way to find a non-standard install
    running_path = _running_openkneeboard_path()
    if running_path and os.path.isfile(running_path):
        return os.path.dirname(running_path)

    # 3. Registry fallbacks
    try:
        import winreg  # type: ignore[import-not-found]
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for subkey in (
                r"Software\Fred Emmott\OpenKneeboard",
                r"Software\OpenKneeboard\OpenKneeboard",
            ):
                try:
                    with winreg.OpenKey(hive, subkey) as k:
                        try:
                            value, _ = winreg.QueryValueEx(k, "InstallLocation")
                        except FileNotFoundError:
                            continue
                        if not isinstance(value, str):
                            continue
                        for sub in ("bin", ""):
                            candidate = os.path.join(
                                value, sub, "OpenKneeboardApp.exe",
                            )
                            if os.path.isfile(candidate):
                                return os.path.dirname(candidate)
                except OSError:
                    continue
    except ImportError:
        pass

    return None


def _running_openkneeboard_path() -> Optional[str]:
    """Return the full path of a running OpenKneeboardApp.exe, or None.

    Uses PowerShell's Get-Process which exposes ``.Path`` without needing
    psutil.  Short timeout so startup stays snappy.
    """
    try:
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-Command",
                "(Get-Process OpenKneeboardApp -ErrorAction SilentlyContinue"
                " | Select-Object -First 1 -ExpandProperty Path)",
            ],
            capture_output=True, text=True, timeout=3.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    path = out.stdout.strip() if out.returncode == 0 else ""
    return path or None


def is_openkneeboard_running() -> bool:
    """Return True if OpenKneeboardApp.exe appears in the running process list."""
    try:
        # tasklist is stock Windows, much lighter than pulling in psutil
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq OpenKneeboardApp.exe", "/NH"],
            capture_output=True, text=True, timeout=3.0,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "OpenKneeboardApp.exe" in out.stdout


def launch_openkneeboard() -> bool:
    """Launch OpenKneeboard if installed and not already running.

    Returns True if a launch was attempted (or the app was already running),
    False if OpenKneeboard is not installed or the launch failed.
    """
    install_dir = detect_openkneeboard()
    if install_dir is None:
        logger.debug("OpenKneeboard not installed — skipping launch")
        return False
    if is_openkneeboard_running():
        logger.debug("OpenKneeboard already running — skipping launch")
        return True
    exe = os.path.join(install_dir, "OpenKneeboardApp.exe")
    if not os.path.isfile(exe):
        logger.warning("OpenKneeboard exe missing: %s", exe)
        return False
    try:
        # Detach — OpenKneeboard outlives our process
        subprocess.Popen(
            [exe], cwd=install_dir,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
        logger.info("Launched OpenKneeboard: %s", exe)
        return True
    except OSError as e:
        logger.warning("Failed to launch OpenKneeboard: %s", e)
        return False


class VRStateWatcher:
    """Polls DCS options.lua for VR state and fires callbacks on transitions.

    Runs a daemon thread that reads options.lua every ``interval`` seconds.
    When ``VR.enable`` flips from false→true we call ``on_vr_on``; the reverse
    calls ``on_vr_off``.  Initial state is reported via a single on_vr_on
    callback when the watcher starts if VR is already active.

    Use ``stop()`` to cleanly terminate the thread.
    """

    def __init__(
        self,
        on_vr_on: Callable[[], None],
        on_vr_off: Callable[[], None],
        interval: float = 5.0,
        options_path: Optional[str] = None,
    ) -> None:
        self._on_vr_on = on_vr_on
        self._on_vr_off = on_vr_off
        self._interval = interval
        self._options_path = options_path
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._last_state: Optional[bool] = None

    @property
    def current_state(self) -> Optional[bool]:
        return self._last_state

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._run, name="VRStateWatcher", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def force_check(self) -> None:
        """Synchronously re-read options.lua and fire callbacks on change."""
        self._check_once()

    def _check_once(self) -> None:
        state = read_vr_enabled(self._options_path)
        if state is None:
            # Unknown state — don't flip anything
            return
        if state == self._last_state:
            return
        prev = self._last_state
        self._last_state = state
        logger.info("DCS VR state: %s → %s", prev, state)
        try:
            if state:
                self._on_vr_on()
            else:
                self._on_vr_off()
        except Exception:  # noqa: BLE001
            logger.exception("VR state callback raised")

    def _run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self._check_once()
            except Exception:  # noqa: BLE001
                logger.exception("VR state watcher tick failed")
            self._stop_evt.wait(self._interval)
