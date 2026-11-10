from __future__ import annotations

import io

from PIL import Image

from companion.art import ArtCache


def make_jpeg(width: int = 200, height: int = 100) -> bytes:
    image = Image.new("RGB", (width, height), (40, 120, 220))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_put_is_content_addressed() -> None:
    cache = ArtCache()
    data = make_jpeg()
    first = cache.put(data, "image/jpeg")
    second = cache.put(data, "image/jpeg")
    assert first == second
    record = cache.get(first)
    assert record is not None
    assert record.content_type == "image/jpeg"
    assert record.data == data


def test_render_downscales_and_keeps_aspect_ratio() -> None:
    cache = ArtCache()
    art_id = cache.put(make_jpeg(200, 100), "image/jpeg")
    result = cache.render(art_id, 64)
    assert result is not None
    data, content_type = result
    assert content_type == "image/jpeg"
    with Image.open(io.BytesIO(data)) as image:
        assert image.width == 64
        assert image.height == 32


def test_render_does_not_upscale() -> None:
    cache = ArtCache()
    source = make_jpeg(120, 80)
    art_id = cache.put(source, "image/jpeg")
    result = cache.render(art_id, 400)
    assert result == (source, "image/jpeg")


def test_undecodable_art_is_still_served() -> None:
    cache = ArtCache()
    raw = b"not-an-image"
    art_id = cache.put(raw, "")
    record = cache.get(art_id)
    assert record is not None
    assert record.content_type == "application/octet-stream"
    assert cache.render(art_id, 64) == (raw, "application/octet-stream")


def test_unknown_art_is_none() -> None:
    assert ArtCache().get("0000000000000000") is None
