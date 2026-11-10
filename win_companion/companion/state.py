"""Thread-safe state shared between the media worker and the web server."""

from __future__ import annotations

import copy
import threading
import time
from typing import Any

SCHEMA_VERSION = 1


def idle_media() -> dict[str, Any]:
    return {
        "active": False,
        "app_id": "",
        "title": "",
        "artist": "",
        "album": "",
        "playback_status": "closed",
        "position_ms": 0,
        "duration_ms": 0,
        "can_play_pause": False,
        "can_next": False,
        "can_previous": False,
        "art_id": None,
    }


def unavailable_volume() -> dict[str, Any]:
    return {"available": False, "level": None, "muted": None}


def build_state(
    *,
    media: dict[str, Any],
    volume: dict[str, Any],
    health_media: str,
    health_volume: str,
    server_version: str,
) -> dict[str, Any]:
    level = volume.get("level")
    if isinstance(level, (int, float)):
        level = max(0.0, min(1.0, float(level)))
    else:
        level = None
    muted = volume.get("muted")
    return {
        "schema_version": SCHEMA_VERSION,
        "server": {"version": server_version},
        "health": {"media": health_media, "volume": health_volume},
        "media": copy.deepcopy(media),
        "volume": {
            "available": bool(volume.get("available")),
            "level": level,
            "muted": bool(muted) if muted is not None else None,
        },
    }


class StateStore:
    """Latest snapshot, read by HTTP handlers and written by the worker."""

    def __init__(self, server_version: str) -> None:
        self._lock = threading.Lock()
        self._version = 0
        self._updated_at = time.time()
        self._state: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "seq": 0,
            "updated_at": self._updated_at,
            "server": {"version": server_version},
            "health": {"media": "no_session", "volume": "unavailable"},
            "media": idle_media(),
            "volume": unavailable_volume(),
        }

    def publish(self, state: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._version += 1
            now = time.time()
            snapshot = copy.deepcopy(state)
            snapshot["schema_version"] = SCHEMA_VERSION
            snapshot["seq"] = self._version
            snapshot["updated_at"] = now
            self._state = snapshot
            self._updated_at = now
            return copy.deepcopy(snapshot)

    def get(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def version(self) -> int:
        with self._lock:
            return self._version

    def last_updated(self) -> float:
        with self._lock:
            return self._updated_at

    def age_ms(self) -> int:
        return max(0, int((time.time() - self.last_updated()) * 1000))
