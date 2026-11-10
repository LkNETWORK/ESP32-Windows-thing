"""HTTP server for the phone controller.

Phase 1 deliberately has no authentication: the UI is meant for a trusted
home LAN. The API surface is intentionally small and read/control-only.
"""

from __future__ import annotations

import asyncio
import logging
import string
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, paths
from .art import ArtCache
from .commands import CommandAction, ERROR_STATUS, WorkerBusy
from .config import Config
from .state import StateStore

log = logging.getLogger(__name__)

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


class WorkerLike(Protocol):
    def submit(self, action: Any): ...

    def is_alive(self) -> bool: ...


def _state_response(state_store: StateStore) -> JSONResponse:
    return JSONResponse(
        state_store.get(),
        headers={"Cache-Control": "no-store"},
    )


def create_app(
    config: Config,
    state_store: StateStore,
    worker: WorkerLike,
    art_cache: ArtCache,
) -> FastAPI:
    app = FastAPI(
        title="ESP32 Media Controller",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    web_dir = paths.web_dir()
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")
    app.mount("/assets", StaticFiles(directory=str(paths.assets_dir())), name="assets")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Frame-Options", "DENY")
        if (
            request.url.path == "/"
            or request.url.path.startswith("/static/")
            or request.url.path.startswith("/assets/")
        ):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(
            web_dir / "index.html",
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/state")
    def get_state() -> JSONResponse:
        return _state_response(state_store)

    @app.post("/api/action")
    async def post_action(command: CommandAction) -> JSONResponse:
        try:
            future = worker.submit(command)
        except RuntimeError as exc:
            log.warning("media worker unavailable: %s", exc)
            return JSONResponse(
                {
                    "ok": False,
                    "error": "unavailable",
                    "state": state_store.get(),
                },
                status_code=503,
            )

        try:
            result = await asyncio.wait_for(asyncio.wrap_future(future), timeout=12.0)
        except asyncio.TimeoutError:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "timeout",
                    "state": state_store.get(),
                },
                status_code=504,
            )
        except WorkerBusy:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "busy",
                    "state": state_store.get(),
                },
                status_code=429,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("action request failed")
            return JSONResponse(
                {
                    "ok": False,
                    "error": "internal",
                    "state": state_store.get(),
                },
                status_code=500,
            )

        if not isinstance(result, dict):
            result = {"ok": False, "error": "internal"}
        result.setdefault("state", state_store.get())
        status = 200 if result.get("ok") else ERROR_STATUS.get(result.get("error"), 500)
        return JSONResponse(result, status_code=status)

    @app.get("/api/art/{art_id}")
    def get_art(
        art_id: str,
        request: Request,
        w: int | None = Query(default=None, ge=32, le=2048),
    ) -> Response:
        if (
            not art_id
            or len(art_id) != 16
            or any(char not in string.hexdigits for char in art_id)
        ):
            raise HTTPException(status_code=404, detail="art not found")

        rendered = art_cache.render(art_id, w)
        if rendered is None:
            raise HTTPException(status_code=404, detail="art not found")
        data, media_type = rendered
        width = w or 0
        etag = f'"{art_id}-{width}"'

        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})

        return Response(
            content=data,
            media_type=media_type,
            headers={
                "ETag": etag,
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "worker_alive": bool(worker.is_alive()),
            "age_ms": state_store.age_ms(),
            "version": __version__,
        }

    return app
