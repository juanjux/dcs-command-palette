"""Interactive installer/wizard for DCS Command Palette.

Provides a menu-driven setup experience:
1. Fresh install (hook + DCS-BIOS)
2. Repair installation (reinstall hook)
3. Update DCS-BIOS
4. Uninstall (remove hook and palette files)

Can be run standalone or called from the main app on first launch.
"""
from __future__ import annotations

import os
import shutil
import sys


def _get_palette_dir() -> str:
    """Get the palette directory, handling both source and frozen (.exe) cases."""
    if getattr(sys, "frozen", False):
        # Running as .exe — files are next to the executable
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_dcs_saved_games() -> str | None:
    """Find the DCS Saved Games directory.

    Tries:
    1. If the palette is inside a DCS saved games dir, use it
    2. Standard Windows paths
    """
    palette_dir = _get_palette_dir()
    parent = os.path.dirname(palette_dir)
    if os.path.isdir(os.path.join(parent, "Config")) or os.path.isdir(
        os.path.join(parent, "Scripts")
    ):
        return parent

    userprofile = os.environ.get("USERPROFILE", "")
    for name in ["DCS", "DCS.openbeta"]:
        candidate = os.path.join(userprofile, "Saved Games", name)
        if os.path.isdir(candidate):
            return candidate
    return None


def install_hook(palette_dir: str, dcs_saved_games: str) -> bool:
    """Install the Lua hook to Scripts/Hooks/."""
    hook_src = os.path.join(palette_dir, "dcs_command_palette_hook.lua")
    if not os.path.isfile(hook_src):
        # In .exe distribution, the hook is bundled alongside the exe
        if getattr(sys, "frozen", False):
            hook_src = os.path.join(
                os.path.dirname(sys.executable),
                "dcs_command_palette_hook.lua",
            )
        else:
            hook_src = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "dcs_command_palette_hook.lua",
            )

    if not os.path.isfile(hook_src):
        print(f"ERROR: Hook file not found at {hook_src}")
        return False

    hooks_dir = os.path.join(dcs_saved_games, "Scripts", "Hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    dest = os.path.join(hooks_dir, "dcs_command_palette_hook.lua")
    shutil.copy2(hook_src, dest)
    print(f"  Lua hook installed to: {dest}")
    return True


def uninstall_hook(dcs_saved_games: str) -> bool:
    """Remove the Lua hook from Scripts/Hooks/."""
    hook_path = os.path.join(
        dcs_saved_games, "Scripts", "Hooks", "dcs_command_palette_hook.lua"
    )
    if os.path.isfile(hook_path):
        os.remove(hook_path)
        print(f"  Removed hook: {hook_path}")
        return True
    else:
        print("  Hook not found (already removed).")
        return False


def check_dcs_bios(dcs_saved_games: str) -> bool:
    """Check if DCS-BIOS is installed."""
    bios_lua = os.path.join(dcs_saved_games, "Scripts", "DCS-BIOS", "BIOS.lua")
    return os.path.isfile(bios_lua)


def is_hook_installed(dcs_saved_games: str) -> bool:
    """Check if the Lua hook is installed."""
    hook_path = os.path.join(
        dcs_saved_games, "Scripts", "Hooks", "dcs_command_palette_hook.lua"
    )
    return os.path.isfile(hook_path)


def _install_dcs_bios(dcs_dir: str) -> bool:
    """Download and install DCS-BIOS. Returns True on success."""
    try:
        from src.bios.installer import (
            backup_scripts,
            download_zip,
            ensure_export_lua,
            get_latest_release_url,
            install_bios,
        )

        url, tag = get_latest_release_url()
        if not url:
            print("  ERROR: Could not find DCS-BIOS release download URL")
            return False

        print(f"  Found release: {tag}")
        zip_data = download_zip(url)
        if not zip_data:
            print("  ERROR: Download failed")
            return False

        print(f"  Downloaded {len(zip_data) / 1024 / 1024:.1f} MB")
        backup_dir = backup_scripts(dcs_dir)
        if backup_dir:
            print(f"  Backup created: {backup_dir}")
        if install_bios(dcs_dir, zip_data):
            print("  DCS-BIOS extracted successfully")
            if ensure_export_lua(dcs_dir):
                print("  Export.lua configured")
            print("  DCS-BIOS installation complete!")
            return True
        else:
            print("  ERROR: Failed to extract DCS-BIOS")
            return False
    except Exception as e:
        print(f"  ERROR: {e}")
        print("  You can install DCS-BIOS later from the Settings window.")
        return False


def _show_status(dcs_dir: str) -> None:
    """Print current installation status."""
    hook_ok = is_hook_installed(dcs_dir)
    bios_ok = check_dcs_bios(dcs_dir)
    print(f"  Lua hook:  {'installed' if hook_ok else 'NOT installed'}")
    print(f"  DCS-BIOS:  {'installed' if bios_ok else 'NOT installed'}")


def run_interactive() -> None:
    """Run the interactive installer wizard."""
    palette_dir = _get_palette_dir()

    print()
    print("DCS Command Palette - Setup")
    print("=" * 40)
    print()

    # Find DCS Saved Games
    dcs_dir = find_dcs_saved_games()
    if dcs_dir:
        print(f"DCS Saved Games: {dcs_dir}")
    else:
        print("Could not auto-detect DCS Saved Games directory.")
        dcs_dir = input("Enter path to DCS Saved Games: ").strip()
        if not os.path.isdir(dcs_dir):
            print(f"ERROR: Directory not found: {dcs_dir}")
            sys.exit(1)

    print()
    _show_status(dcs_dir)
    print()

    while True:
        print("Choose an option:")
        print("  1. Fresh install (hook + DCS-BIOS)")
        print("  2. Repair installation (reinstall hook)")
        print("  3. Update DCS-BIOS")
        print("  4. Uninstall (remove hook and palette files)")
        print("  5. Exit")
        print()

        choice = input("Enter choice [1-5]: ").strip()
        print()

        if choice == "1":
            # Fresh install
            print("[1/2] Installing Lua hook...")
            if install_hook(palette_dir, dcs_dir):
                print("  OK - Hook installed.")
            else:
                print("  FAILED - Could not install hook.")
            print()

            print("[2/2] Checking DCS-BIOS...")
            if check_dcs_bios(dcs_dir):
                print("  OK - DCS-BIOS is already installed.")
            else:
                print("  DCS-BIOS is NOT installed.")
                print(
                    "  DCS-BIOS provides cockpit control integration"
                    " (switches, dials, etc.)"
                )
                print(
                    "  Without it, only keyboard shortcuts will be available."
                )
                print()
                answer = (
                    input("  Install DCS-BIOS now? [Y/n]: ").strip().lower()
                )
                if answer in ("", "y", "yes"):
                    print("  Downloading DCS-BIOS from GitHub...")
                    _install_dcs_bios(dcs_dir)
                else:
                    print("  Skipped.")
            print()
            print("Setup complete!")
            print()
            print("To start the palette:")
            print("  - Run dcs-command-palette.exe")
            print("  - Or start a DCS mission (Lua hook auto-launches it)")
            print()
            print("Default hotkey: Ctrl+Space")
            print()

        elif choice == "2":
            # Repair
            print("Reinstalling Lua hook...")
            if install_hook(palette_dir, dcs_dir):
                print("  OK - Hook reinstalled.")
            else:
                print("  FAILED.")
            print()

        elif choice == "3":
            # Update DCS-BIOS
            print("Updating DCS-BIOS...")
            _install_dcs_bios(dcs_dir)
            print()

        elif choice == "4":
            # Uninstall
            confirm = (
                input(
                    "Are you sure you want to uninstall? [y/N]: "
                )
                .strip()
                .lower()
            )
            if confirm in ("y", "yes"):
                print()
                print("Removing Lua hook...")
                uninstall_hook(dcs_dir)
                print()
                remove_palette = (
                    input(
                        "Also remove the palette directory "
                        f"({palette_dir})? [y/N]: "
                    )
                    .strip()
                    .lower()
                )
                if remove_palette in ("y", "yes"):
                    try:
                        shutil.rmtree(palette_dir)
                        print(f"  Removed: {palette_dir}")
                    except OSError as e:
                        print(f"  ERROR removing directory: {e}")
                else:
                    print("  Palette directory kept.")
                print()
                print("Uninstall complete.")
            else:
                print("Cancelled.")
            print()

        elif choice == "5":
            print("Bye!")
            break

        else:
            print("Invalid choice. Enter 1-5.")
            print()
            continue

        # Show updated status after any action (except exit)
        if choice in ("1", "2", "3", "4"):
            _show_status(dcs_dir)
            print()


if __name__ == "__main__":
    run_interactive()
