"""Filesystem locations used by the companion app.

The preferred location is ``%LOCALAPPDATA%\\EspMediaController``. Some
restricted/sandboxed sessions deny writes there even though the directory
looks writable, so the resolver probes the location and falls back to a
writable workspace ``.data`` directory and finally the temp directory.
``ESP_MEDIA_CONTROLLER_DATA`` forces a specific location.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import CONFIG_DIR_NAME

PLACEHOLDER_ASSET_NAME = "no_info.png"

_resolved_dir: Path | None = None
_used_fallback = False


def _preferred_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / CONFIG_DIR_NAME
    return Path.home() / ".esp_media_controller"


def _candidate_dirs() -> list[Path]:
    override = os.environ.get("ESP_MEDIA_CONTROLLER_DATA")
    if override:
        return [Path(override).expanduser().resolve()]
    return [
        _preferred_dir(),
        package_dir().parent / ".data",
        Path(tempfile.gettempdir()) / CONFIG_DIR_NAME,
    ]


def _probe_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".write-test-{os.getpid()}"
        with open(probe, "wb") as handle:
            handle.write(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def _resolve_dir() -> Path:
    global _resolved_dir, _used_fallback
    if _resolved_dir is not None:
        return _resolved_dir

    override = bool(os.environ.get("ESP_MEDIA_CONTROLLER_DATA"))
    candidates = _candidate_dirs()
    for index, candidate in enumerate(candidates):
        if _probe_writable(candidate):
            _resolved_dir = candidate
            _used_fallback = index > 0 and not override
            return candidate

    if override:
        raise OSError(
            "ESP_MEDIA_CONTROLLER_DATA is not writable: "
            f"{candidates[0]}"
        )
    raise OSError(
        "no writable data directory; tried "
        + ", ".join(str(candidate) for candidate in candidates)
    )


def data_dir() -> Path:
    return _resolve_dir()


def using_fallback() -> bool:
    data_dir()
    return _used_fallback


def config_path() -> Path:
    return data_dir() / "config.json"


def log_dir() -> Path:
    return data_dir() / "logs"


def log_path() -> Path:
    return log_dir() / "app.log"


def web_dir() -> Path:
    return package_dir() / "web"


def assets_dir() -> Path:
    return package_dir() / "assets"


def placeholder_asset_path() -> Path:
    return assets_dir() / PLACEHOLDER_ASSET_NAME


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def app_script() -> Path:
    """Absolute path to the entry point script (used by the startup entry)."""
    return package_dir().parent / "app.py"


def ensure_dirs() -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)


def reset_for_tests() -> None:
    """Clear the cached location (tests only)."""

    global _resolved_dir, _used_fallback
    _resolved_dir = None
    _used_fallback = False
