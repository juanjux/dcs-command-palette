"""Build script for creating the DCS Command Palette .exe distribution.

Usage:
    python build_exe.py

Produces: dist/dcs-command-palette/ (directory with .exe and dependencies)

The resulting folder can be copied to Saved Games\DCS\dcs-command-palette\
for distribution.
"""
import os
import shutil
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist", "dcs-command-palette")


def build() -> None:
    print("Building DCS Command Palette .exe...")

    # PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "dcs-command-palette",
        "--noconsole",  # No console window (GUI app)
        "--noconfirm",  # Overwrite without asking
        # Include the Lua hook file as data
        "--add-data", f"dcs_command_palette_hook.lua{os.pathsep}.",
        # Hidden imports that PyInstaller might miss
        "--hidden-import", "pynput.keyboard._win32",
        "--hidden-import", "pynput.mouse._win32",
        # Collect pygame fully (it has SDL2 DLLs)
        "--collect-all", "pygame",
        # Main entry point
        "main.py",
    ]

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_DIR)

    if result.returncode != 0:
        print("ERROR: PyInstaller build failed!")
        sys.exit(1)

    print(f"\nBuild successful! Output: {DIST_DIR}")
    print("\nTo distribute:")
    print(f"  1. Copy the '{DIST_DIR}' folder to the target machine")
    print("  2. Place it in: Saved Games\\DCS\\dcs-command-palette\\")
    print("  3. Run dcs-command-palette.exe once to configure")
    print("  4. Open Settings -> Install Lua Hook")


if __name__ == "__main__":
    build()
