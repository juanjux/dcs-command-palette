"""DCS-BIOS installer: download, backup, and install DCS-BIOS."""
import io
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime
from typing import Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com/repos/DCS-Skunkworks/dcs-bios/releases/latest"
EXPORT_LUA_LINE = 'dofile(lfs.writedir() .. [[Scripts\\DCS-BIOS\\BIOS.lua]])'


def get_latest_release_url() -> Tuple[Optional[str], Optional[str]]:
    """Query GitHub API for the latest DCS-BIOS release.

    Returns (download_url, version_tag) or (None, None) on failure.
    Looks for an asset named DCS-BIOS_v*.zip.
    """
    try:
        req = Request(GITHUB_API_URL, headers={"User-Agent": "DCS-Command-Palette"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        tag = data.get("tag_name", "unknown")
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.startswith("DCS-BIOS") and name.endswith(".zip"):
                return asset["browser_download_url"], tag

        logger.warning("No DCS-BIOS zip asset found in release %s", tag)
        return None, tag
    except (URLError, json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to fetch latest release info: %s", e)
        return None, None


def download_zip(url: str) -> Optional[bytes]:
    """Download a zip file from URL. Returns bytes or None on failure."""
    try:
        req = Request(url, headers={"User-Agent": "DCS-Command-Palette"})
        with urlopen(req, timeout=120) as resp:
            return resp.read()
    except URLError as e:
        logger.error("Failed to download %s: %s", url, e)
        return None


def backup_scripts(dcs_saved_games: str) -> Optional[str]:
    """Create a backup of the Scripts folder and Export.lua.

    Returns the backup directory path, or None on failure.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(dcs_saved_games, f"Scripts_backup_{timestamp}")

    scripts_dir = os.path.join(dcs_saved_games, "Scripts")
    export_lua = os.path.join(scripts_dir, "Export.lua")

    try:
        os.makedirs(backup_dir, exist_ok=True)

        # Backup Export.lua if it exists
        if os.path.isfile(export_lua):
            shutil.copy2(export_lua, os.path.join(backup_dir, "Export.lua"))
            logger.info("Backed up Export.lua to %s", backup_dir)

        # Backup existing DCS-BIOS folder if it exists
        bios_dir = os.path.join(scripts_dir, "DCS-BIOS")
        if os.path.isdir(bios_dir):
            shutil.copytree(bios_dir, os.path.join(backup_dir, "DCS-BIOS"))
            logger.info("Backed up DCS-BIOS folder to %s", backup_dir)

        return backup_dir
    except OSError as e:
        logger.error("Failed to create backup: %s", e)
        return None


def install_bios(dcs_saved_games: str, zip_data: bytes) -> bool:
    """Extract DCS-BIOS zip to the Scripts directory.

    The zip typically contains a top-level folder like "DCS-BIOS" or similar.
    We extract to Scripts/.
    """
    scripts_dir = os.path.join(dcs_saved_games, "Scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            # Check if the zip has a top-level DCS-BIOS directory
            names = zf.namelist()
            has_prefix = all(
                n.startswith("DCS-BIOS/") or n.startswith("DCS-BIOS\\")
                for n in names
                if n
            )

            if has_prefix:
                # Extract directly to Scripts/ (the DCS-BIOS/ folder is in the zip)
                zf.extractall(scripts_dir)
            else:
                # Extract into Scripts/DCS-BIOS/
                target = os.path.join(scripts_dir, "DCS-BIOS")
                os.makedirs(target, exist_ok=True)
                zf.extractall(target)

        logger.info("DCS-BIOS extracted to %s", scripts_dir)
        return True
    except (zipfile.BadZipFile, OSError) as e:
        logger.error("Failed to extract DCS-BIOS: %s", e)
        return False


def ensure_export_lua(dcs_saved_games: str) -> bool:
    """Ensure Export.lua contains the DCS-BIOS dofile line.

    Creates Export.lua if it doesn't exist. Adds the line if not already present.
    """
    scripts_dir = os.path.join(dcs_saved_games, "Scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    export_path = os.path.join(scripts_dir, "Export.lua")

    # Check if the line already exists
    if os.path.isfile(export_path):
        try:
            with open(export_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
            if EXPORT_LUA_LINE in content:
                logger.info("Export.lua already contains DCS-BIOS dofile line")
                return True
            # Append the line
            with open(export_path, "a", encoding="utf-8") as f:
                f.write(f"\n{EXPORT_LUA_LINE}\n")
            logger.info("Added DCS-BIOS dofile line to existing Export.lua")
            return True
        except OSError as e:
            logger.error("Failed to update Export.lua: %s", e)
            return False
    else:
        # Create new Export.lua
        try:
            with open(export_path, "w", encoding="utf-8") as f:
                f.write(f"{EXPORT_LUA_LINE}\n")
            logger.info("Created Export.lua with DCS-BIOS dofile line")
            return True
        except OSError as e:
            logger.error("Failed to create Export.lua: %s", e)
            return False


def is_bios_installed(dcs_saved_games: str) -> bool:
    """Check if DCS-BIOS appears to be installed."""
    bios_lua = os.path.join(dcs_saved_games, "Scripts", "DCS-BIOS", "BIOS.lua")
    return os.path.isfile(bios_lua)
