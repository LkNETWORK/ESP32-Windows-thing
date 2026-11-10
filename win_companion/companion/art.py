"""In-memory album-art cache.

Art is content-addressed: the first 16 hex characters of the SHA-256 digest
become the art id. The HTTP layer serves it immutably, and an optional width
query produces a downscaled JPEG for small screens / the future ESP32.
"""

from __future__ import annotations

import hashlib
import io
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)

_MAX_ART_ENTRIES = 8
_MAX_VARIANT_ENTRIES = 16


@dataclass(frozen=True)
class ArtRecord:
    art_id: str
    data: bytes
    content_type: str


def _normalize_content_type(data: bytes, content_type: str | None) -> str:
    if content_type and content_type.lower().startswith("image/"):
        return content_type
    try:
        with Image.open(io.BytesIO(data)) as image:
            return Image.MIME.get(image.format or "", "application/octet-stream")
    except (UnidentifiedImageError, OSError, ValueError):
        return "application/octet-stream"


class ArtCache:
    def __init__(
        self,
        max_entries: int = _MAX_ART_ENTRIES,
        max_variants: int = _MAX_VARIANT_ENTRIES,
    ) -> None:
        self._lock = threading.Lock()
        self._arts: OrderedDict[str, ArtRecord] = OrderedDict()
        self._variants: OrderedDict[tuple[str, int], tuple[bytes, str]] = OrderedDict()
        self._max_entries = max(1, max_entries)
        self._max_variants = max(1, max_variants)

    def put(self, data: bytes, content_type: str | None) -> str:
        art_id = hashlib.sha256(data).hexdigest()[:16]
        record = ArtRecord(
            art_id=art_id,
            data=bytes(data),
            content_type=_normalize_content_type(data, content_type),
        )
        with self._lock:
            existing = self._arts.get(art_id)
            if existing is not None:
                self._arts.move_to_end(art_id)
                return art_id
            self._arts[art_id] = record
            while len(self._arts) > self._max_entries:
                self._arts.popitem(last=False)
        log.debug("cached art %s (%d bytes, %s)", art_id, len(data), record.content_type)
        return art_id

    def get(self, art_id: str) -> ArtRecord | None:
        with self._lock:
            record = self._arts.get(art_id)
            if record is not None:
                self._arts.move_to_end(art_id)
            return record

    def info(self, art_id: str | None) -> tuple[int, str] | None:
        if not art_id:
            return None
        record = self.get(art_id)
        if record is None:
            return None
        return len(record.data), record.content_type

    def render(self, art_id: str, width: int | None) -> Optional[tuple[bytes, str]]:
        """Return art bytes, optionally downscaled to ``width`` pixels.

        Images narrower than ``width`` are left alone. Undecodable art is
        served as-is so unusual formats can still reach the browser.
        """

        record = self.get(art_id)
        if record is None:
            return None
        if width is None or width <= 0:
            return record.data, record.content_type

        key = (art_id, width)
        with self._lock:
            cached = self._variants.get(key)
            if cached is not None:
                self._variants.move_to_end(key)
                return cached

        try:
            with Image.open(io.BytesIO(record.data)) as image:
                if image.width <= width:
                    return record.data, record.content_type
                rgb = image.convert("RGB")
                ratio = width / float(rgb.width)
                height = max(1, round(rgb.height * ratio))
                resized = rgb.resize((width, height), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                resized.save(buffer, format="JPEG", quality=85, optimize=True)
                result = (buffer.getvalue(), "image/jpeg")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            log.debug("could not resize art %s: %s", art_id, exc)
            return record.data, record.content_type

        with self._lock:
            self._variants[key] = result
            while len(self._variants) > self._max_variants:
                self._variants.popitem(last=False)
        return result
