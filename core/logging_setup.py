"""Logging configuration for Aureus AI."""

import logging
import json
from pathlib import Path
from datetime import datetime


def setup_logging(level="INFO", format_type="json"):
    """Configure logging for the system."""
    log_dir = Path("./logs")
    log_dir.mkdir(exist_ok=True)

    # Root logger
    root = logging.getLogger()
    root.setLevel(getattr(logging, level))

    # Remove existing handlers
    for h in root.handlers[:]:
        root.removeHandler(h)

    # File handler (JSON format)
    if format_type == "json":
        fh = logging.FileHandler(log_dir / "aureus.log")
        formatter = logging.Formatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
        )
    else:
        fh = logging.FileHandler(log_dir / "aureus.log")
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
        )

    fh.setFormatter(formatter)
    root.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, level))
    ch.setFormatter(formatter)
    root.addHandler(ch)

    return root
