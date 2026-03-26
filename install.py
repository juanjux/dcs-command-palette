"""First-run installer for DCS Command Palette.

This script is run after extracting the distribution to set up:
1. Detect DCS Saved Games directory
2. Install the Lua hook to Scripts/Hooks/
3. Optionally install DCS-BIOS if not present
4. Create a desktop shortcut (optional)

Can be run standalone or called from the main app on first launch.
"""
from __future__ import annotations

import os
import shutil
import sys


def find_dcs_saved_games() -> str | None:
    """Find the DCS Saved Games directory."""
    userprofile = os.environ.get("USERPROFILE", "")
    candidates = [
        os.path.join(userprofile, "Saved Games", "DCS"),
        os.path.join(userprofile, "Saved Games", "DCS.openbeta"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return None


def install_hook(palette_dir: str, dcs_saved_games: str) -> bool:
    """Install the Lua hook to Scripts/Hooks/."""
    hook_src = os.path.join(palette_dir, "dcs_command_palette_hook.lua")
    if not os.path.isfile(hook_src):
        # In .exe distribution, the hook is bundled alongside the exe
        hook_src = os.path.join(os.path.dirname(sys.executable), "dcs_command_palette_hook.lua")

    if not os.path.isfile(hook_src):
        print(f"ERROR: Hook file not found at {hook_src}")
        return False

    hooks_dir = os.path.join(dcs_saved_games, "Scripts", "Hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    dest = os.path.join(hooks_dir, "dcs_command_palette_hook.lua")
    shutil.copy2(hook_src, dest)
    print(f"Lua hook installed to: {dest}")
    return True


def check_dcs_bios(dcs_saved_games: str) -> bool:
    """Check if DCS-BIOS is installed."""
    bios_lua = os.path.join(dcs_saved_games, "Scripts", "DCS-BIOS", "BIOS.lua")
    return os.path.isfile(bios_lua)


def run_interactive() -> None:
    """Run the interactive installer."""
    print("=" * 60)
    print("  DCS Command Palette - Installer")
    print("=" * 60)
    print()

    # Find DCS Saved Games
    dcs_dir = find_dcs_saved_games()
    if dcs_dir:
        print(f"Found DCS Saved Games: {dcs_dir}")
    else:
        print("Could not auto-detect DCS Saved Games directory.")
        dcs_dir = input("Enter path to DCS Saved Games: ").strip()
        if not os.path.isdir(dcs_dir):
            print(f"ERROR: Directory not found: {dcs_dir}")
            sys.exit(1)

    palette_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Palette directory: {palette_dir}")
    print()

    # Install Lua hook
    print("[1/3] Installing Lua hook...")
    if install_hook(palette_dir, dcs_dir):
        print("  OK - Hook installed. The palette will auto-start with DCS missions.")
    else:
        print("  FAILED - You can install the hook later from Settings.")
    print()

    # Check DCS-BIOS
    print("[2/3] Checking DCS-BIOS...")
    if check_dcs_bios(dcs_dir):
        print("  OK - DCS-BIOS is installed.")
    else:
        print("  DCS-BIOS is NOT installed.")
        print("  DCS-BIOS provides cockpit control integration (switches, dials, etc.)")
        print("  Without it, only keyboard shortcuts will be available.")
        print()
        answer = input("  Install DCS-BIOS now? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            print("  Downloading DCS-BIOS from GitHub...")
            try:
                # Import here to avoid issues if running without full deps
                from bios_installer import (
                    get_latest_release_url,
                    download_zip,
                    backup_scripts,
                    install_bios,
                    ensure_export_lua,
                )

                url, tag = get_latest_release_url()
                if not url:
                    print(f"  ERROR: Could not find DCS-BIOS release download URL")
                else:
                    print(f"  Found release: {tag}")
                    zip_data = download_zip(url)
                    if not zip_data:
                        print("  ERROR: Download failed")
                    else:
                        print(f"  Downloaded {len(zip_data) / 1024 / 1024:.1f} MB")
                        backup_dir = backup_scripts(dcs_dir)
                        if backup_dir:
                            print(f"  Backup created: {backup_dir}")
                        if install_bios(dcs_dir, zip_data):
                            print("  DCS-BIOS extracted successfully")
                            if ensure_export_lua(dcs_dir):
                                print("  Export.lua configured")
                            print("  DCS-BIOS installation complete!")
                        else:
                            print("  ERROR: Failed to extract DCS-BIOS")
            except Exception as e:
                print(f"  ERROR: {e}")
                print("  You can install DCS-BIOS later from the Settings window.")
        else:
            print("  Skipped. You can install DCS-BIOS later from Settings.")
    print()

    # Done
    print("[3/3] Setup complete!")
    print()
    print("To start the palette:")
    print(f"  - Manually: Run dcs-command-palette.exe")
    print(f"  - Automatically: Start a DCS mission (Lua hook will launch it)")
    print()
    print("Default hotkey: Ctrl+Space")
    print("Configure in: Settings (search 'settings' in the palette or use tray icon)")
    print()
    input("Press Enter to exit...")


if __name__ == "__main__":
    run_interactive()
