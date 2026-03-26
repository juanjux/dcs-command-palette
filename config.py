import os
from typing import Set, Tuple

# Hotkey
HOTKEY_MODIFIERS: Set[str] = {"ctrl"}
HOTKEY_KEY: str = "space"

# DCS-BIOS UDP
DCS_BIOS_HOST: str = "127.0.0.1"
DCS_BIOS_PORT: int = 7778

# Palette toggle listener (receives TOGGLE_PALETTE from DCS Lua hook)
PALETTE_LISTEN_PORT: int = 7780

# Paths
PROJECT_DIR: str = os.path.dirname(os.path.abspath(__file__))
DCS_SAVED_GAMES: str = os.path.dirname(PROJECT_DIR)
USAGE_DATA_PATH: str = os.path.join(PROJECT_DIR, "usage_data.json")

# DCS installation directory (default, overridden by settings.json at runtime)
DCS_INSTALL_DIR: str = os.environ.get(
    "DCS_INSTALL_DIR",
    r"D:\SteamLibrary\steamapps\common\DCSWorld",
)
AIRCRAFT_MODULE: str = "FA-18C"
AIRCRAFT_INPUT_NAME: str = "FA-18C"

# UI
OVERLAY_WIDTH: int = 650
OVERLAY_MAX_HEIGHT: int = 550
MAX_RESULTS: int = 12

# Colors (RGBA)
BG_COLOR: Tuple[int, int, int, int] = (20, 20, 30, 220)
SEARCH_BG_COLOR: Tuple[int, int, int, int] = (40, 40, 55, 255)
HIGHLIGHT_COLOR: Tuple[int, int, int, int] = (60, 120, 220, 100)
TEXT_COLOR: str = "#e0e0e0"
TEXT_MUTED_COLOR: str = "#888888"
ACCENT_COLOR: str = "#4a9eff"
IDENTIFIER_COLOR: str = "#ffffff"
CATEGORY_COLOR: str = "#6a9fff"

# Fonts
SEARCH_FONT_SIZE: int = 18
IDENTIFIER_FONT_SIZE: int = 14
DESCRIPTION_FONT_SIZE: int = 12

# Display options
SHOW_IDENTIFIERS: bool = False  # Show DCS-BIOS identifiers below the description
AUTO_HIDE_SECONDS: int = 5  # Hide palette after N seconds of inactivity (0 = disabled)

# Search ranking weights
WEIGHT_FUZZY: float = 0.60
WEIGHT_FREQUENCY: float = 0.25
WEIGHT_RECENCY: float = 0.15
RECENCY_DECAY_HOURS: float = 24.0
PREFIX_MATCH_BONUS: int = 20
