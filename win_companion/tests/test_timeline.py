from __future__ import annotations

from datetime import datetime, timedelta, timezone

from companion.timeline import live_position_ms

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_playing_advances_with_last_updated_time() -> None:
    position = live_position_ms(
        1000,
        100_000,
        "playing",
        NOW - timedelta(seconds=10),
        now=NOW,
    )
    assert position == 11_000


def test_paused_does_not_advance() -> None:
    position = live_position_ms(
        42_000,
        100_000,
        "paused",
        NOW - timedelta(seconds=30),
        now=NOW,
    )
    assert position == 42_000


def test_future_timestamp_does_not_rewind() -> None:
    position = live_position_ms(
        5000,
        100_000,
        "playing",
        NOW + timedelta(seconds=5),
        now=NOW,
    )
    assert position == 5000


def test_position_is_clamped_to_duration() -> None:
    position = live_position_ms(
        95_000,
        100_000,
        "playing",
        NOW - timedelta(seconds=10),
        now=NOW,
    )
    assert position == 100_000


def test_naive_last_updated_is_treated_as_utc() -> None:
    naive_now = NOW.replace(tzinfo=None)
    position = live_position_ms(
        1000,
        100_000,
        "playing",
        naive_now - timedelta(seconds=5),
        now=naive_now,
    )
    assert position == 6000


def test_playback_rate_is_applied() -> None:
    position = live_position_ms(
        1000,
        100_000,
        "playing",
        NOW - timedelta(seconds=10),
        now=NOW,
        rate=2.0,
    )
    assert position == 21_000
