"""Small heuristics for distinguishing real album art from app logos.

Chrome exposes its own logo as the SMTC thumbnail when a page does not supply
Media Session artwork. That is not album art, so the controller substitutes
the project's placeholder image. Detection is a perceptual-hash comparison
against the standard Chrome logo, with references for both a transparent
(white-composited) and black-composited rendering.
"""

from __future__ import annotations

import functools
import io
import logging
from pathlib import Path

from PIL import Image

from . import paths

log = logging.getLogger(__name__)

# dHash/aHash of the standard Chrome logo, 8x8, generated from the logo on a
# white and a black background respectively.
_CHROME_WHITE_DHASH = 0x060741494921170E
_CHROME_WHITE_AHASH = 0xF7E1E1E0E08181E7
_CHROME_BLACK_DHASH = 0x61C4828888A2D471
_CHROME_BLACK_AHASH = 0x107C7EFEFE7E3C00
_HASH_TOLERANCE = 6
_WHITE = (255, 255, 255, 255)
_BLACK = (0, 0, 0, 255)


def placeholder_path() -> Path:
    return paths.placeholder_asset_path()


@functools.lru_cache(maxsize=1)
def placeholder_bytes() -> bytes:
    return placeholder_path().read_bytes()


def _flattened_gray(image: Image.Image, background: tuple[int, int, int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    canvas = Image.new("RGBA", rgba.size, background)
    return Image.alpha_composite(canvas, rgba).convert("L")


def _pixels(image: Image.Image) -> list[int]:
    # Pillow 13 deprecates getdata(); prefer the new accessor when available.
    if hasattr(image, "get_flattened_data"):
        return list(image.get_flattened_data())
    return list(image.getdata())


def _dhash(gray: Image.Image, size: int = 8) -> int:
    resized = gray.resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = _pixels(resized)
    bits = 0
    index = 0
    for row in range(size):
        offset = row * (size + 1)
        for column in range(size):
            if pixels[offset + column] > pixels[offset + column + 1]:
                bits |= 1 << index
            index += 1
    return bits


def _ahash(gray: Image.Image, size: int = 8) -> int:
    resized = gray.resize((size, size), Image.Resampling.LANCZOS)
    pixels = _pixels(resized)
    average = sum(pixels) / len(pixels)
    bits = 0
    for index, value in enumerate(pixels):
        if value > average:
            bits |= 1 << index
    return bits


def _hamming(first: int, second: int) -> int:
    return (first ^ second).bit_count()


def is_chrome_logo(data: bytes) -> bool:
    """Return True when the image looks like Chrome's default app logo."""

    if not data:
        return False
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            if source.width < 8 or source.height < 8:
                return False
            white = _flattened_gray(source, _WHITE)
            black = _flattened_gray(source, _BLACK)
            white_match = (
                _hamming(_dhash(white), _CHROME_WHITE_DHASH) <= _HASH_TOLERANCE
                and _hamming(_ahash(white), _CHROME_WHITE_AHASH) <= _HASH_TOLERANCE
            )
            black_match = (
                _hamming(_dhash(black), _CHROME_BLACK_DHASH) <= _HASH_TOLERANCE
                and _hamming(_ahash(black), _CHROME_BLACK_AHASH) <= _HASH_TOLERANCE
            )
            return white_match or black_match
    except (OSError, ValueError):
        return False
