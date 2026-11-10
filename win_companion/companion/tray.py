"""System tray icon and menu."""

from __future__ import annotations

import logging
import threading
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageOps

from . import APP_NAME, clipboard, net, paths, startup
from .config import Config
from .state import StateStore

log = logging.getLogger(__name__)


def _allow_tray_message_filter_failure() -> None:
    """Let the tray start when Windows refuses the optional taskbar filter.

    pystray opts in to WM_TASKBARCREATED so the icon survives an Explorer
    restart. That call is denied in restricted/sandboxed sessions, but the
    icon itself is still usable, so treat it as best-effort.
    """

    try:
        from pystray._util import win32 as pystray_win32
    except Exception:
        return

    original = getattr(pystray_win32, "ChangeWindowMessageFilterEx", None)
    if original is None:
        return

    def safe_change_window_message_filter(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except OSError as exc:
            log.debug("optional tray message filter unavailable: %s", exc)
            return False

    pystray_win32.ChangeWindowMessageFilterEx = safe_change_window_message_filter


def _fit_square(image: Image.Image, size: int = 64) -> Image.Image:
    # Center-crop to a square so the tray image fills its box with no
    # transparent margins.
    return ImageOps.fit(
        image.convert("RGBA"),
        (size, size),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def _make_icon() -> Image.Image:
    # Custom tray artwork, converted from the supplied no_info.jfif.
    asset = paths.placeholder_asset_path()
    try:
        with Image.open(asset) as source:
            source.load()
            return _fit_square(source.copy(), 64)
    except (OSError, ValueError):
        log.warning("tray icon asset unavailable; using built-in icon", exc_info=True)

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(22, 24, 34, 255))
    # A simple music note.
    draw.ellipse((16, 38, 34, 54), fill=(116, 203, 255, 255))
    draw.rectangle((31, 16, 36, 48), fill=(116, 203, 255, 255))
    draw.polygon(
        [(36, 16), (52, 11), (52, 22), (36, 27)],
        fill=(116, 203, 255, 255),
    )
    return image


class TrayApp:
    def __init__(
        self,
        config: Config,
        state_store: StateStore,
        config_path: Path,
        on_quit,
    ) -> None:
        self._config = config
        self._store = state_store
        self._config_path = config_path
        self._on_quit = on_quit
        self._startup_command = startup.command_for_current_install(config_path)
        _allow_tray_message_filter_failure()
        self._icon = pystray.Icon(
            "esp32-media-controller",
            _make_icon(),
            APP_NAME,
            menu=self._create_menu(),
        )
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._icon.run(setup=self._on_setup)
            log.info("tray icon stopped")
        except Exception:
            log.exception("tray icon stopped unexpectedly")

    def _on_setup(self, icon: pystray.Icon) -> None:
        # A custom setup callback replaces pystray's default one, which is
        # what makes the icon visible. Without this line the icon exists but
        # is never added to the notification area.
        try:
            icon.visible = True
            log.info("tray icon visible")
        except Exception:
            log.exception("could not make the tray icon visible")
            return

        local = f"http://127.0.0.1:{self._config.port}/"
        phone = net.primary_url(self._config.port)
        log.info("tray icon ready; local=%s phone=%s", local, phone)
        try:
            icon.notify(
                f"Controller running.\nOpen on your phone: {phone}",
                APP_NAME,
            )
        except Exception:
            log.debug("tray notification failed", exc_info=True)

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    # -- menu --------------------------------------------------------------

    def _create_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(self._status_text, self._open_ui),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open controller", self._open_ui, default=True),
            pystray.MenuItem("Copy phone URL", self._copy_phone_url),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start with Windows",
                self._toggle_startup,
                checked=self._startup_checked,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open logs folder", self._open_logs),
            pystray.MenuItem("Open config folder", self._open_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _status_text(self, item: pystray.MenuItem) -> str:
        if self._store.age_ms() > 5000:
            return "Media unavailable"
        state = self._store.get()
        health = state.get("health", {}).get("media")
        media = state.get("media", {})
        if media.get("active"):
            title = media.get("title") or "Unknown title"
            artist = media.get("artist") or ""
            line = f"Now: {title}"
            if artist:
                line += f" — {artist}"
            if media.get("playback_status") == "paused":
                line += " (paused)"
            return line[:90]
        if health == "error":
            return "Media unavailable"
        return "Nothing playing"

    def _startup_checked(self, item: pystray.MenuItem) -> bool:
        return startup.is_enabled()

    # -- actions -----------------------------------------------------------

    def _open_ui(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        webbrowser.open(f"http://127.0.0.1:{self._config.port}/")

    def _copy_phone_url(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        url = net.primary_url(self._config.port)
        if clipboard.copy_text(url):
            self._notify(icon, "Phone URL copied", url)
        else:
            log.warning("could not copy phone URL to the clipboard")
            self._notify(icon, "Could not copy URL", url)

    def _toggle_startup(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        try:
            if startup.is_enabled():
                startup.disable()
                self._notify(icon, APP_NAME, "Autostart disabled")
            else:
                startup.enable(self._startup_command)
                self._notify(icon, APP_NAME, "Autostart enabled")
        except OSError as exc:
            log.warning("could not update autostart: %s", exc)
            self._notify(icon, "Autostart failed", str(exc))
        finally:
            try:
                icon.update_menu()
            except Exception:
                pass

    def _open_logs(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        paths.log_dir().mkdir(parents=True, exist_ok=True)
        self._open_folder(paths.log_dir())

    def _open_config(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        self._open_folder(paths.data_dir())

    def _open_folder(self, path: Path) -> None:
        try:
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            log.warning("could not open %s", path, exc_info=True)

    def _quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        log.info("quit requested from tray")
        try:
            self._on_quit()
        finally:
            try:
                icon.stop()
            except Exception:
                pass

    def _notify(self, icon: pystray.Icon, title: str, message: str) -> None:
        try:
            icon.notify(message, title)
        except Exception:
            pass
