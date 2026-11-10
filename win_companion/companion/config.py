r"""Configuration loading and validation.

The config file lives outside the repository so that autostart can find it
regardless of the working directory:

    %LOCALAPPDATA%\EspMediaController\config.json
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from . import CONFIG_DIR_NAME, paths

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8722
DEFAULT_POLL_MS = 500
DEFAULT_LOG_LEVEL = "INFO"
_MIN_PORT = 1024
_MAX_PORT = 65535
_MIN_POLL_MS = 200
_MAX_POLL_MS = 5000
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class ConfigError(ValueError):
    """Raised when the config file cannot be used."""


@dataclass(frozen=True)
class ArtConfig:
    max_bytes: int = 8_388_608
    default_width: int = 640
    max_width: int = 2048

    def validate(self) -> None:
        if not 1 <= self.max_bytes <= 64 * 1024 * 1024:
            raise ConfigError("art.max_bytes must be between 1 and 67108864")
        if not 32 <= self.default_width <= self.max_width:
            raise ConfigError("art.default_width must be between 32 and art.max_width")
        if not 32 <= self.max_width <= 4096:
            raise ConfigError("art.max_width must be between 32 and 4096")


@dataclass(frozen=True)
class Config:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    poll_interval_ms: int = DEFAULT_POLL_MS
    log_level: str = DEFAULT_LOG_LEVEL
    art: ArtConfig = field(default_factory=ArtConfig)

    def validate(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ConfigError("host must be a non-empty string")
        if not _MIN_PORT <= self.port <= _MAX_PORT:
            raise ConfigError(f"port must be between {_MIN_PORT} and {_MAX_PORT}")
        if not _MIN_POLL_MS <= self.poll_interval_ms <= _MAX_POLL_MS:
            raise ConfigError(
                f"poll_interval_ms must be between {_MIN_POLL_MS} and {_MAX_POLL_MS}"
            )
        level = str(self.log_level).upper()
        if level not in _LOG_LEVELS:
            raise ConfigError(f"log_level must be one of {sorted(_LOG_LEVELS)}")
        self.art.validate()

    def with_overrides(self, host: str | None = None, port: int | None = None) -> "Config":
        updates: dict[str, Any] = {}
        if host:
            updates["host"] = host
        if port is not None:
            updates["port"] = port
        if not updates:
            return self
        updated = replace(self, **updates)
        updated.validate()
        return updated


def config_to_dict(config: Config) -> dict[str, Any]:
    return asdict(config)


def _parse(data: Any) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("config root must be a JSON object")

    art_raw = data.get("art", {})
    if art_raw is None:
        art_raw = {}
    if not isinstance(art_raw, dict):
        raise ConfigError("art must be a JSON object")
    art = ArtConfig(
        max_bytes=int(art_raw.get("max_bytes", ArtConfig.max_bytes)),
        default_width=int(art_raw.get("default_width", ArtConfig.default_width)),
        max_width=int(art_raw.get("max_width", ArtConfig.max_width)),
    )
    config = Config(
        host=str(data.get("host", DEFAULT_HOST)),
        port=int(data.get("port", DEFAULT_PORT)),
        poll_interval_ms=int(data.get("poll_interval_ms", DEFAULT_POLL_MS)),
        log_level=str(data.get("log_level", DEFAULT_LOG_LEVEL)).upper(),
        art=art,
    )
    config.validate()
    return config


def load_config(path: Path | None = None, *, create: bool = True) -> Config:
    """Load config, creating a default file on first run.

    Raises ConfigError on malformed content. A malformed file is never
    silently overwritten.
    """

    target = Path(path) if path is not None else paths.config_path()
    if not target.exists():
        config = Config()
        if create:
            save_config(config, target)
        return config

    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {target}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{target} is not valid JSON: {exc}") from exc

    try:
        return _parse(data)
    except ConfigError:
        raise
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid config in {target}: {exc}") from exc


def save_config(config: Config, path: Path | None = None) -> Path:
    """Atomically write config so a crash cannot leave a truncated file."""

    target = Path(path) if path is not None else paths.config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config_to_dict(config), indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


__all__ = [
    "ArtConfig",
    "Config",
    "ConfigError",
    "CONFIG_DIR_NAME",
    "config_to_dict",
    "load_config",
    "save_config",
]
