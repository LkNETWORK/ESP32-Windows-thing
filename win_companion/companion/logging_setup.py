"""Application logging."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3
FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging(log_file: Path, level: str = "INFO", console: bool = False) -> None:
    """Configure the root logger with a rotating file and optional console."""

    log_file.parent.mkdir(parents=True, exist_ok=True)
    numeric = getattr(logging, str(level).upper(), logging.INFO)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    root.setLevel(numeric)

    formatter = logging.Formatter(FORMAT)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    # Uvicorn configures its loggers only when log_config is provided. We pass
    # log_config=None, so keep them propagating to the root logger and avoid
    # duplicate access log noise.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").setLevel(numeric)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("pystray").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
