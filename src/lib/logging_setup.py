"""Logging configuration for DCS Command Palette."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from src.config.settings import PROJECT_DIR

LOG_FILE = os.path.join(PROJECT_DIR, "dcs_command_palette.log")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_LOG_SIZE = 2 * 1024 * 1024  # 2 MB
BACKUP_COUNT = 3


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging to both file and stderr.

    Log file is stored in the project directory as dcs_command_palette.log.
    Rotates at 2 MB with 3 backups.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers on repeated calls
    if root.handlers:
        return

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Stderr handler (visible when running from terminal)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)
