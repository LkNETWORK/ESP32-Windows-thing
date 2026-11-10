"""Async wrapper around the Windows System Media Transport Controls (SMTC).

Only the media worker thread calls this module. Every WinRT await is bounded
by a timeout so a hung media application cannot stall the whole service.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as MediaManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)
from winrt.windows.storage.streams import DataReader

from .art import ArtCache
from .art_detect import is_chrome_logo
from .state import idle_media
from .timeline import live_position_ms

log = logging.getLogger(__name__)

_STATUS_NAMES = {
    PlaybackStatus.CLOSED: "closed",
    PlaybackStatus.OPENED: "opened",
    PlaybackStatus.CHANGING: "changing",
    PlaybackStatus.STOPPED: "stopped",
    PlaybackStatus.PLAYING: "playing",
    PlaybackStatus.PAUSED: "paused",
}


def _status_name(value: Any) -> str:
    try:
        return _STATUS_NAMES.get(value, "unknown")
    except TypeError:
        return "unknown"


def _text(value: Any, limit: int = 512) -> str:
    if value is None:
        return ""
    return str(value)[:limit]


def _timedelta_ms(value: Any) -> int:
    try:
        return max(0, int(value.total_seconds() * 1000))
    except AttributeError:
        try:
            return max(0, int(float(value) * 1000))
        except (TypeError, ValueError):
            return 0


@dataclass(frozen=True)
class ArtPayload:
    data: bytes
    content_type: str


@dataclass(frozen=True)
class PollResult:
    media: dict[str, Any]
    health: str
    art: ArtPayload | None = None


class SmtcPlayer:
    def __init__(self, art_max_bytes: int = 8_388_608, op_timeout: float = 3.0) -> None:
        self._manager = None
        self._op_timeout = op_timeout
        self._art_max_bytes = art_max_bytes
        self._last_media = idle_media()
        self._metadata_key: tuple[str, str, str, str] | None = None
        self._art_key: tuple[str, str, str, str] | None = None
        self._last_art_id: str | None = None
        self._art_retry_at = 0.0

    @property
    def last_media(self) -> dict[str, Any]:
        return self._last_media

    async def poll(self, art_cache: ArtCache) -> PollResult:
        try:
            manager = await self._get_manager()
            session = manager.get_current_session()
        except asyncio.TimeoutError:
            log.warning("requesting the SMTC session manager timed out")
            self._manager = None
            return PollResult(self._last_media, "error")
        except Exception as exc:
            log.warning("SMTC session manager unavailable: %s", exc)
            self._manager = None
            return PollResult(self._last_media, "error")

        if session is None:
            self._reset_media()
            return PollResult(self._last_media, "no_session")

        try:
            props = await asyncio.wait_for(
                session.try_get_media_properties_async(), self._op_timeout
            )
            playback = session.get_playback_info()
            timeline = session.get_timeline_properties()
        except asyncio.TimeoutError:
            log.warning("reading SMTC media properties timed out")
            return PollResult(self._last_media, "error")
        except Exception:
            log.warning("reading SMTC media properties failed", exc_info=True)
            return PollResult(self._last_media, "error")

        if props is None:
            log.debug("SMTC returned no media properties")
            return PollResult(self._last_media, "error")

        app_id = _text(getattr(session, "source_app_user_model_id", ""), 256)
        title = _text(getattr(props, "title", ""))
        artist = _text(getattr(props, "artist", ""))
        album = _text(getattr(props, "album_title", ""))

        controls = getattr(playback, "controls", None)
        can_play_pause = bool(
            getattr(controls, "is_play_pause_toggle_enabled", False)
        )
        can_next = bool(getattr(controls, "is_next_enabled", False))
        can_previous = bool(getattr(controls, "is_previous_enabled", False))

        metadata_key = (app_id, title, artist, album)
        if metadata_key != self._metadata_key:
            self._metadata_key = metadata_key
            self._art_key = None
            self._last_art_id = None

        art_payload: ArtPayload | None = None
        thumbnail = getattr(props, "thumbnail", None)
        now = time.monotonic()
        if thumbnail is None:
            self._art_key = metadata_key
            self._last_art_id = None
        elif self._art_key != metadata_key and now >= self._art_retry_at:
            try:
                art_payload = await self._read_thumbnail(thumbnail)
            except asyncio.TimeoutError:
                log.warning("album art read timed out")
                self._art_retry_at = now + 30.0
            except Exception:
                log.debug("album art read failed", exc_info=True)
                self._art_retry_at = now + 30.0
            else:
                self._art_retry_at = 0.0
                if art_payload is not None:
                    self._last_art_id = art_cache.put(
                        art_payload.data, art_payload.content_type
                    )
                else:
                    self._last_art_id = None
                self._art_key = metadata_key

        status = _status_name(getattr(playback, "playback_status", None))
        position_ms = _timedelta_ms(getattr(timeline, "position", None))
        duration_ms = _timedelta_ms(getattr(timeline, "end_time", None))
        if duration_ms <= 0:
            duration_ms = 0
        position_ms = live_position_ms(
            position_ms,
            duration_ms,
            status,
            getattr(timeline, "last_updated_time", None),
            rate=getattr(playback, "playback_rate", None),
        )

        media = {
            "active": True,
            "app_id": app_id,
            "title": title,
            "artist": artist,
            "album": album,
            "playback_status": status,
            "position_ms": position_ms,
            "duration_ms": duration_ms,
            "can_play_pause": can_play_pause,
            "can_next": can_next,
            "can_previous": can_previous,
            "art_id": self._last_art_id,
        }
        self._last_media = media
        return PollResult(media, "ok", art_payload)

    async def toggle_play_pause(self) -> str | None:
        return await self._transport("try_toggle_play_pause_async")

    async def skip_next(self) -> str | None:
        return await self._transport("try_skip_next_async")

    async def skip_previous(self) -> str | None:
        return await self._transport("try_skip_previous_async")

    async def _transport(self, method_name: str) -> str | None:
        try:
            session = await self._current_session()
        except Exception:
            log.warning("could not get the current SMTC session", exc_info=True)
            self._manager = None
            return "error"
        if session is None:
            return "no_session"
        try:
            result = await asyncio.wait_for(
                getattr(session, method_name)(), self._op_timeout
            )
        except asyncio.TimeoutError:
            return "timeout"
        except Exception:
            log.warning("SMTC %s failed", method_name, exc_info=True)
            return "error"
        return None if bool(result) else "not_supported"

    async def _current_session(self):
        manager = await self._get_manager()
        return manager.get_current_session()

    async def _get_manager(self):
        if self._manager is None:
            self._manager = await asyncio.wait_for(
                MediaManager.request_async(), self._op_timeout
            )
        return self._manager

    async def _read_thumbnail(self, thumbnail) -> ArtPayload | None:
        stream = await asyncio.wait_for(
            thumbnail.open_read_async(), self._op_timeout
        )
        reader = None
        try:
            size = int(stream.size)
            if size <= 0 or size > self._art_max_bytes:
                log.debug("ignoring album art of %d bytes", size)
                return None
            reader = DataReader(stream)
            await asyncio.wait_for(reader.load_async(size), self._op_timeout)
            buffer = bytearray(size)
            reader.read_bytes(buffer)
            data = bytes(buffer)
            content_type = _text(getattr(stream, "content_type", ""), 128)
            if is_chrome_logo(data):
                # Treat the app logo as "no artwork". The web UI then uses the
                # same no_info placeholder as the idle/no-session state,
                # instead of rendering it as cropped album art.
                log.info(
                    "thumbnail is the Chrome app logo, not album art; "
                    "ignoring it and using the standard placeholder"
                )
                return None
            return ArtPayload(data, content_type)
        finally:
            if reader is not None:
                try:
                    reader.close()
                except Exception:
                    pass
            try:
                stream.close()
            except Exception:
                pass

    def _reset_media(self) -> None:
        self._last_media = idle_media()
        self._metadata_key = None
        self._art_key = None
        self._last_art_id = None
        self._art_retry_at = 0.0
