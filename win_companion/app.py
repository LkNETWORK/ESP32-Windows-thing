"""Entry point for the ESP32 Windows media companion."""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import socket
import sys
import threading
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path

import uvicorn

from companion import APP_NAME, __version__, net, paths, startup
from companion.art import ArtCache
from companion.config import Config, ConfigError, load_config
from companion.logging_setup import setup_logging
from companion.server import create_app
from companion.state import StateStore
from companion.tray import TrayApp
from companion.worker import MediaWorker

log = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    """Named mutex so autostart and a manual start cannot both serve."""

    def __init__(self, name: str = r"Local\EspMediaController") -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32 = kernel32
        self._handle = kernel32.CreateMutexW(None, False, name)
        self.acquired = bool(self._handle) and ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        if not self.acquired:
            log.warning("another instance is already running")
            if self._handle:
                kernel32.CloseHandle(self._handle)
                self._handle = None

    def release(self) -> None:
        if self._handle:
            try:
                self._kernel32.CloseHandle(self._handle)
            finally:
                self._handle = None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ESP32 Media Controller",
        description="Tray-resident Windows media controller with a LAN web UI.",
    )
    parser.add_argument("--console", action="store_true", help="run in the foreground with console logs")
    parser.add_argument(
        "--no-dialog",
        action="store_true",
        help="do not show the startup OK confirmation in tray mode",
    )
    parser.add_argument("--probe", action="store_true", help="print one live state snapshot and exit")
    parser.add_argument("--host", help="override config host")
    parser.add_argument("--port", type=int, help="override config port")
    parser.add_argument("--config", type=Path, help="config file path")
    parser.add_argument("--install-startup", action="store_true", help="enable autostart and exit")
    parser.add_argument("--uninstall-startup", action="store_true", help="disable autostart and exit")
    return parser.parse_args(argv)


def _fatal(message: str, *, console: bool) -> None:
    text = f"{APP_NAME} error.\n\n{message}\n\nLog: {paths.log_path()}"
    try:
        if console or sys.stderr is not None:
            print(text, file=sys.stderr)
        else:
            ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10)
    except Exception:
        try:
            print(text, file=sys.stderr)
        except Exception:
            pass


def _show_startup_dialog(config: Config) -> None:
    """Show a non-blocking confirmation dialog for a manual tray launch."""

    def show() -> None:
        # Give uvicorn and the tray a moment to come up before the user is
        # asked to acknowledge the window.
        time.sleep(0.8)
        local = f"http://127.0.0.1:{config.port}/"
        phone = net.primary_url(config.port)
        text = (
            f"{APP_NAME} is running.\n\n"
            f"Local:  {local}\n"
            f"Phone:  {phone}\n\n"
            "Click OK to dismiss this window.\n"
            "The controller keeps running in the system tray."
        )
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                text,
                APP_NAME,
                0x00000040 | 0x00010000 | 0x00040000,  # info | foreground | topmost
            )
        except Exception:
            log.debug("startup dialog could not be shown", exc_info=True)

    log.info("showing startup confirmation dialog")
    threading.Thread(target=show, name="startup-dialog", daemon=True).start()


def _port_available(host: str, port: int) -> bool:
    bind_host = "" if host in ("0.0.0.0", "::", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((bind_host, port))
        except OSError:
            return False
    return True


def _log_urls(config: Config, console: bool) -> None:
    local = f"http://127.0.0.1:{config.port}/"
    lines = [f"Local: {local}"]
    lan = net.all_urls(config.port)
    for interface, url in lan:
        lines.append(f"LAN:   {url}  [{interface}]")
    if not lan:
        lines.append("LAN:   no LAN IPv4 address found; use the local URL")
    if console:
        print(f"{APP_NAME} {__version__}", flush=True)
        print("\n".join(lines), flush=True)
    log.info("controller URLs:\n%s", "\n".join(lines))


def _install_startup(config_path: Path) -> int:
    command = startup.command_for_current_install(config_path)
    startup.enable(command)
    print("Autostart enabled:")
    print(command)
    return 0


def _uninstall_startup() -> int:
    startup.disable()
    print("Autostart disabled.")
    return 0


def _run_probe(config: Config) -> int:
    store = StateStore(__version__)
    art_cache = ArtCache()
    worker = MediaWorker(config, store, art_cache)
    try:
        worker.start()
        deadline = time.monotonic() + 10.0
        while store.version() == 0 and time.monotonic() < deadline:
            time.sleep(0.1)

        state = store.get()
        art_id = state.get("media", {}).get("art_id")
        art_info = art_cache.info(art_id)
        state["probe"] = {
            "worker_alive": worker.is_alive(),
            "art_bytes": art_info[0] if art_info else 0,
            "art_content_type": art_info[1] if art_info else None,
        }
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0 if store.version() > 0 else 1
    finally:
        worker.stop()


def _run_server(
    config: Config,
    config_path: Path,
    *,
    console: bool,
    show_dialog: bool,
) -> int:
    mutex = SingleInstance()
    if not mutex.acquired:
        webbrowser.open(f"http://127.0.0.1:{config.port}/")
        return 0

    if not _port_available(config.host, config.port):
        mutex.release()
        raise RuntimeError(
            f"port {config.port} is already in use on host {config.host}"
        )

    store = StateStore(__version__)
    art_cache = ArtCache()
    worker = MediaWorker(config, store, art_cache)
    try:
        worker.start()
    except Exception:
        worker.stop()
        mutex.release()
        raise

    app = create_app(config, store, worker, art_cache)
    uvicorn_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.port,
        log_config=None,
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(uvicorn_config)

    tray: TrayApp | None = None
    if not console:
        try:
            tray = TrayApp(
                config,
                store,
                config_path,
                on_quit=lambda: setattr(server, "should_exit", True),
            )
            tray.start()
        except Exception:
            log.exception("tray icon could not start; continuing without a tray")
            tray = None

    log.info(
        "%s %s starting on %s:%s (console=%s)",
        APP_NAME,
        __version__,
        config.host,
        config.port,
        console,
    )
    _log_urls(config, console)

    if show_dialog and not console:
        _show_startup_dialog(config)

    try:
        server.run()
    except SystemExit:
        log.error("web server exited")
        raise
    finally:
        if tray is not None:
            tray.stop()
        worker.stop()
        mutex.release()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config_path = (
        args.config.expanduser().resolve() if args.config else paths.config_path()
    )
    console = bool(args.console)

    try:
        config = load_config(config_path)
        config = config.with_overrides(args.host, args.port)
        paths.ensure_dirs()
        setup_logging(paths.log_path(), config.log_level, console=console)
        if paths.using_fallback():
            message = (
                f"using fallback data directory: {paths.data_dir()} "
                "(the normal AppData location is not writable)"
            )
            log.warning(message)
            if console:
                print(message, flush=True)
    except (ConfigError, OSError, ValueError) as exc:
        _fatal(str(exc), console=console)
        return 1

    if args.install_startup:
        try:
            return _install_startup(config_path)
        except OSError as exc:
            message = f"could not enable autostart: {exc}"
            if isinstance(exc, PermissionError):
                message += (
                    "\n\nWindows denied the registry write. If this terminal is "
                    "sandboxed or restricted, run --install-startup from a normal "
                    "PowerShell window, or use Start with Windows from the tray "
                    "menu after launching the app normally."
                )
            _fatal(message, console=console)
            return 1
    if args.uninstall_startup:
        try:
            return _uninstall_startup()
        except OSError as exc:
            message = f"could not disable autostart: {exc}"
            if isinstance(exc, PermissionError):
                message += (
                    "\n\nWindows denied the registry write. Run this command from "
                    "a normal PowerShell window."
                )
            _fatal(message, console=console)
            return 1

    try:
        if args.probe:
            return _run_probe(config)
        return _run_server(
            config,
            config_path,
            console=console,
            show_dialog=not args.no_dialog,
        )
    except KeyboardInterrupt:
        log.info("interrupted")
        return 0
    except Exception as exc:
        log.exception("fatal error")
        _fatal(str(exc), console=console)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
