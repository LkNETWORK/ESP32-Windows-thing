from __future__ import annotations

from companion.state import (
    SCHEMA_VERSION,
    StateStore,
    build_state,
    idle_media,
    unavailable_volume,
)


def test_initial_state_is_idle() -> None:
    store = StateStore("test-version")
    state = store.get()
    assert state["schema_version"] == SCHEMA_VERSION
    assert state["seq"] == 0
    assert state["media"] == idle_media()
    assert state["volume"] == unavailable_volume()
    assert state["health"] == {"media": "no_session", "volume": "unavailable"}
    assert store.version() == 0


def test_publish_increments_seq_and_is_copied() -> None:
    store = StateStore("test-version")
    media = {
        **idle_media(),
        "active": True,
        "title": "Song",
    }
    state = build_state(
        media=media,
        volume={"available": True, "level": 0.5, "muted": False},
        health_media="ok",
        health_volume="ok",
        server_version="test-version",
    )
    published = store.publish(state)
    assert published["seq"] == 1
    assert published["updated_at"] > 0
    assert published["media"]["title"] == "Song"
    assert store.version() == 1

    published["media"]["title"] = "mutated"
    assert store.get()["media"]["title"] == "Song"

    store.publish(state)
    assert store.version() == 2
    assert store.get()["seq"] == 2


def test_volume_values_are_normalized() -> None:
    state = build_state(
        media=idle_media(),
        volume={"available": True, "level": 1.7, "muted": True},
        health_media="no_session",
        health_volume="ok",
        server_version="test",
    )
    assert state["volume"] == {"available": True, "level": 1.0, "muted": True}

    state = build_state(
        media=idle_media(),
        volume={"available": False},
        health_media="no_session",
        health_volume="unavailable",
        server_version="test",
    )
    assert state["volume"] == {"available": False, "level": None, "muted": None}
