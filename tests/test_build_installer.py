"""Installer builds must use the same DLL-safe builder as portable builds."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import build_installer


def test_installer_uses_shared_builder():
    with patch("build_installer.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
        assert build_installer.build_pyinstaller()
    run.assert_called_once_with(
        [sys.executable, os.path.join(build_installer.PROJECT_DIR, "build_exe.py")],
        cwd=build_installer.PROJECT_DIR,
    )


def test_installer_rejects_failed_application_build():
    with patch("build_installer.subprocess.run", return_value=SimpleNamespace(returncode=1)):
        assert not build_installer.build_pyinstaller()
