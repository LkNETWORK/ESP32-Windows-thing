"""Default output device volume/mute control via pycaw."""

from __future__ import annotations

import logging
import time

from pycaw.pycaw import AudioUtilities

log = logging.getLogger(__name__)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class AudioController:
    """Thin wrapper around the default render endpoint.

    All methods must be called from the media worker thread (COM MTA).
    """

    def __init__(self, refresh_seconds: float = 5.0) -> None:
        self._refresh_seconds = refresh_seconds
        self._device = None
        self._checked_at = 0.0

    def _get_device(self):
        now = time.monotonic()
        if self._device is None or now - self._checked_at >= self._refresh_seconds:
            self._device = AudioUtilities.GetSpeakers()
            self._checked_at = now
        return self._device

    def _forget_device(self) -> None:
        self._device = None
        self._checked_at = 0.0

    def read(self) -> dict:
        try:
            device = self._get_device()
            if device is None:
                raise RuntimeError("no default output device")
            endpoint = device.EndpointVolume
            level = clamp01(endpoint.GetMasterVolumeLevelScalar())
            muted = bool(endpoint.GetMute())
            return {"available": True, "level": level, "muted": muted}
        except Exception as exc:  # COM failures are common on device changes
            log.debug("volume read failed: %s", exc)
            self._forget_device()
            return {"available": False, "level": None, "muted": None}

    def step(self, delta: float) -> dict:
        try:
            device = self._get_device()
            if device is None:
                raise RuntimeError("no default output device")
            endpoint = device.EndpointVolume
            level = clamp01(endpoint.GetMasterVolumeLevelScalar() + float(delta))
            endpoint.SetMasterVolumeLevelScalar(level, None)
            # A volume gesture should produce sound if the PC was muted.
            if level > 0.0 and bool(endpoint.GetMute()):
                endpoint.SetMute(False, None)
            return self.read()
        except Exception as exc:
            log.warning("volume change failed: %s", exc)
            self._forget_device()
            return {"available": False, "level": None, "muted": None}
