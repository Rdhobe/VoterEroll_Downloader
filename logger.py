"""
ECI Electoral Roll Downloader — Logging setup (console + file)
"""

import logging
import sys
from pathlib import Path


def setup_logger(log_dir: str = ".") -> logging.Logger:
    """Configure and return the 'eroll' logger with console + file handlers."""
    logger = logging.getLogger("eroll")
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)

    # ── File handler (DEBUG+) ────────────────────────────────────────────
    log_path = Path(log_dir) / "download.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(str(log_path), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(file_fmt)
    logger.addHandler(fh)

    # ── Console handler (INFO+) ──────────────────────────────────────────
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)

    try:
        import colorlog

        color_fmt = colorlog.ColoredFormatter(
            "%(log_color)s[%(asctime)s] [%(levelname)-8s]%(reset)s %(message)s",
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
        ch.setFormatter(color_fmt)
    except ImportError:
        plain_fmt = logging.Formatter(
            "[%(asctime)s] [%(levelname)-8s] %(message)s",
            datefmt="%H:%M:%S",
        )
        ch.setFormatter(plain_fmt)

    logger.addHandler(ch)
    return logger
