from __future__ import annotations

import io

from PIL import Image

from companion.art_detect import is_chrome_logo, placeholder_bytes


def test_placeholder_is_a_png() -> None:
    data = placeholder_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "PNG"
        assert image.width > 0 and image.height > 0


def test_placeholder_is_not_detected_as_chrome_logo() -> None:
    assert is_chrome_logo(placeholder_bytes()) is False


def test_ordinary_image_is_not_detected_as_chrome_logo() -> None:
    image = Image.new("RGB", (128, 128), (20, 100, 180))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    assert is_chrome_logo(buffer.getvalue()) is False
