"""Dedicated Windows/COM worker thread.

The web server and tray never touch COM directly. This thread owns the SMTC
session and the audio endpoint, serializes all WinRT calls, and publishes
immutable snapshots to the shared StateStore.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import ctypes
import logging
import threading
from typing import Any

from . import __version__
from .art import ArtCache
from .audio import AudioController
from .commands import WorkerBusy
from .config import Config
from .player import PollResult, SmtcPlayer
from .state import StateStore, build_state

log = logging.getLogger(__name__)

MAX_QUEUE = 64


class MediaWorker:
    def __init__(
        self,
        config: Config,
        state_store: StateStore,
        art_cache: ArtCache,
    ) -> None:
        self._config = config
        self._store = state_store
        self._art_cache = art_cache
        self._player = SmtcPlayer(art_max_bytes=config.art.max_bytes)
        self._audio = AudioController()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="media-worker",
            daemon=True,
        )
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[tuple[dict[str, Any], concurrent.futures.Future]] | None = None
        self._lock: asyncio.Lock | None = None
        self._stop_event: asyncio.Event | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self, timeout: float = 10.0) -> None:
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("media worker did not become ready")
        if not self._thread.is_alive():
            raise RuntimeError("media worker thread exited during startup")

    def stop(self, timeout: float = 8.0) -> None:
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(self._request_stop)
            except RuntimeError:
                pass
        self._thread.join(timeout)
        if self._thread.is_alive():
            log.warning("media worker did not stop within %.1fs", timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive() and self._ready.is_set()

    # -- commands ----------------------------------------------------------

    def submit(self, action) -> concurrent.futures.Future:
        loop = self._loop
        if loop is None or loop.is_closed():
            raise RuntimeError("media worker is not running")
        future: concurrent.futures.Future = concurrent.futures.Future()
        payload = action.model_dump() if hasattr(action, "model_dump") else dict(action)
        try:
            loop.call_soon_threadsafe(self._enqueue, payload, future)
        except RuntimeError as exc:
            raise RuntimeError("media worker is stopping") from exc
        return future

    def _enqueue(
        self,
        payload: dict[str, Any],
        future: concurrent.futures.Future,
    ) -> None:
        if self._queue is None:
            if not future.done():
                future.set_exception(RuntimeError("media worker is stopping"))
            return
        if self._queue.qsize() >= MAX_QUEUE:
            if not future.done():
                future.set_exception(WorkerBusy("media command queue is full"))
            return
        self._queue.put_nowait((payload, future))

    # -- thread internals --------------------------------------------------

    def _request_stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    def _thread_main(self) -> None:
        # MTA is required for both WinRT async operations and pycaw.
        ctypes.windll.ole32.CoInitializeEx(None, 0)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        # Create primitives before advertising readiness so submit() can never
        # race an uninitialized queue.
        self._queue = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._ready.set()
        try:
            loop.run_until_complete(self._main())
        except BaseException:
            log.exception("media worker stopped unexpectedly")
        finally:
            self._ready.clear()
            self._fail_pending()
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
            asyncio.set_event_loop(None)
            self._loop = None
            ctypes.windll.ole32.CoUninitialize()

    def _fail_pending(self) -> None:
        if self._queue is None:
            return
        while not self._queue.empty():
            try:
                _, future = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not future.done():
                future.set_exception(RuntimeError("media worker stopped"))

    async def _main(self) -> None:
        assert self._stop_event is not None
        poll_task = asyncio.create_task(self._poll_loop(), name="media-poll")
        command_task = asyncio.create_task(self._command_loop(), name="media-commands")
        try:
            await self._stop_event.wait()
        finally:
            for task in (poll_task, command_task):
                task.cancel()
            await asyncio.gather(poll_task, command_task, return_exceptions=True)

    async def _poll_loop(self) -> None:
        interval = max(0.2, self._config.poll_interval_ms / 1000.0)
        while True:
            try:
                async with self._winrt_lock():
                    await self._collect()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("media poll failed")
            await asyncio.sleep(interval)

    async def _command_loop(self) -> None:
        assert self._queue is not None
        while True:
            payload, future = await self._queue.get()
            try:
                async with self._winrt_lock():
                    error = await self._dispatch(payload)
                    state = await self._collect()
                result = {"ok": error is None, "state": state}
                if error is not None:
                    result["error"] = error
                if not future.done():
                    future.set_result(result)
            except asyncio.CancelledError:
                if not future.done():
                    future.cancel()
                raise
            except Exception as exc:
                log.exception("media action failed")
                if not future.done():
                    future.set_exception(exc)

    def _winrt_lock(self) -> asyncio.Lock:
        assert self._lock is not None
        return self._lock

    async def _collect(self) -> dict[str, Any]:
        """Read Windows state and publish a snapshot. Caller holds the lock."""
        try:
            result = await self._player.poll(self._art_cache)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("SMTC poll failed")
            result = PollResult(self._player.last_media, "error")

        volume = self._audio.read()
        health_volume = "ok" if volume.get("available") else "unavailable"
        state = build_state(
            media=result.media,
            volume=volume,
            health_media=result.health,
            health_volume=health_volume,
            server_version=__version__,
        )
        return self._store.publish(state)

    async def _dispatch(self, payload: dict[str, Any]) -> str | None:
        action = payload.get("action")
        if action == "volume_step":
            volume = self._audio.step(float(payload.get("delta", 0.0)))
            return None if volume.get("available") else "volume_unavailable"
        if action == "play_pause":
            error = await self._player.toggle_play_pause()
            await asyncio.sleep(0.12)
            return error
        if action == "next":
            error = await self._player.skip_next()
            await asyncio.sleep(0.12)
            return error
        if action == "previous":
            error = await self._player.skip_previous()
            await asyncio.sleep(0.12)
            return error
        return "not_supported"
