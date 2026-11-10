from __future__ import annotations

from concurrent.futures import Future
from typing import Any

from companion.state import StateStore


class FakeWorker:
    """Synchronous stand-in for MediaWorker used by the API tests."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.actions: list[dict[str, Any]] = []
        self.errors: dict[str, str] = {}
        self.alive = True

    def submit(self, action) -> Future:
        payload = action.model_dump()
        self.actions.append(payload)
        future: Future = Future()
        error = self.errors.get(payload["action"])
        result: dict[str, Any] = {"ok": error is None, "state": self.store.get()}
        if error:
            result["error"] = error
        future.set_result(result)
        return future

    def is_alive(self) -> bool:
        return self.alive
