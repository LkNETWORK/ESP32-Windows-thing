from __future__ import annotations

from companion import paths
from companion.tray import _make_icon


def test_custom_tray_icon_asset_exists() -> None:
    assert paths.placeholder_asset_path().is_file()


def test_tray_icon_is_square_rgba() -> None:
    image = _make_icon()
    assert image.size == (64, 64)
    assert image.mode == "RGBA"
    assert image.getbbox() is not None
