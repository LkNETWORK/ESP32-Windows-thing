"""Timeline helpers.

Some media apps (notably Chrome) leave SMTC's ``position`` at the value from
the last state change instead of updating it continuously. The timeline does
carry ``last_updated_time``, so while playing the current position is
``position + (now - last_updated_time)``. This makes the web progress bar
advance even when the source never updates its position.
"""

from __future__ import annotations

from datetime import datetime, timezone

_MAX_EXTRAPOLATION_MS = 12 * 60 * 60 * 1000


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def live_position_ms(
    position_ms: int,
    duration_ms: int,
    playback_status: str,
    last_updated_time: datetime | None,
    *,
    now: datetime | None = None,
    rate: float | None = 1.0,
) -> int:
    """Return the playback position adjusted for elapsed playing time."""

    position = max(0, int(position_ms))
    duration = max(0, int(duration_ms))

    if (
        playback_status == "playing"
        and isinstance(last_updated_time, datetime)
        and last_updated_time is not None
    ):
        current = _as_utc(now) if now is not None else datetime.now(timezone.utc)
        elapsed_ms = (
            current - _as_utc(last_updated_time)
        ).total_seconds() * 1000.0
        if 0 < elapsed_ms <= _MAX_EXTRAPOLATION_MS:
            try:
                playback_rate = float(rate) if rate is not None else 1.0
            except (TypeError, ValueError):
                playback_rate = 1.0
            playback_rate = max(0.25, min(4.0, playback_rate))
            position += int(elapsed_ms * playback_rate)

    if duration > 0:
        position = min(position, duration)
    return position
