from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from companion.art import ArtCache
from companion.config import Config
from companion.server import create_app
from companion.state import StateStore, build_state, idle_media
from tests.fakes import FakeWorker


def make_client() -> tuple[TestClient, StateStore, FakeWorker, ArtCache]:
    store = StateStore("test")
    worker = FakeWorker(store)
    art = ArtCache()
    app = create_app(Config(host="127.0.0.1", port=8722), store, worker, art)
    return TestClient(app), store, worker, art


def jpeg_bytes() -> bytes:
    image = Image.new("RGB", (200, 100), (30, 90, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_index_and_headers() -> None:
    client, _, _, _ = make_client()
    response = client.get("/")
    assert response.status_code == 200
    assert "ESP32 Media Controller" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-cache"
    assert "/assets/no_info.png" in response.text


def test_placeholder_asset_is_served() -> None:
    client, _, _, _ = make_client()
    response = client.get("/assets/no_info.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_state_has_no_auth_and_no_store() -> None:
    client, store, _, _ = make_client()
    media = {**idle_media(), "active": True, "title": "Test Song", "artist": "Artist"}
    store.publish(
        build_state(
            media=media,
            volume={"available": True, "level": 0.4, "muted": False},
            health_media="ok",
            health_volume="ok",
            server_version="test",
        )
    )
    response = client.get("/api/state")
    assert response.status_code == 200
    data = response.json()
    assert data["media"]["title"] == "Test Song"
    assert data["volume"]["level"] == 0.4
    assert response.headers["cache-control"] == "no-store"


def test_actions_are_dispatched() -> None:
    client, _, worker, _ = make_client()
    response = client.post("/api/action", json={"action": "play_pause"})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert worker.actions == [{"action": "play_pause"}]

    response = client.post("/api/action", json={"action": "volume_step", "delta": 0.1})
    assert response.status_code == 200
    assert worker.actions[-1] == {"action": "volume_step", "delta": 0.1}


def test_invalid_action_is_422() -> None:
    client, _, _, _ = make_client()
    assert client.post("/api/action", json={"action": "bogus"}).status_code == 422
    assert client.post("/api/action", json={"action": "volume_step"}).status_code == 422


def test_action_error_maps_to_status() -> None:
    client, _, worker, _ = make_client()
    worker.errors["play_pause"] = "no_session"
    assert client.post("/api/action", json={"action": "play_pause"}).status_code == 409

    worker.errors["volume_step"] = "volume_unavailable"
    assert (
        client.post("/api/action", json={"action": "volume_step", "delta": 0.1}).status_code
        == 503
    )


def test_art_is_served_with_etag_and_resize() -> None:
    client, _, _, art = make_client()
    art_id = art.put(jpeg_bytes(), "image/jpeg")

    first = client.get(f"/api/art/{art_id}?w=64")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    etag = first.headers["etag"]
    assert etag == f'"{art_id}-64"'
    with Image.open(io.BytesIO(first.content)) as image:
        assert image.width == 64

    second = client.get(f"/api/art/{art_id}?w=64", headers={"If-None-Match": etag})
    assert second.status_code == 304

    original = client.get(f"/api/art/{art_id}")
    assert original.status_code == 200
    assert original.headers["etag"] == f'"{art_id}-0"'


def test_unknown_art_is_404() -> None:
    client, _, _, _ = make_client()
    assert client.get("/api/art/0123456789abcdef").status_code == 404
    assert client.get("/api/art/not-an-id").status_code == 404


def test_healthz() -> None:
    client, _, worker, _ = make_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["worker_alive"] is True
    assert body["version"] == "0.1.0"
    worker.alive = False
    assert client.get("/healthz").json()["worker_alive"] is False
