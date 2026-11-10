"""Validated web actions."""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class WorkerBusy(RuntimeError):
    """Raised when the media worker's command queue is full."""


class PlayPauseAction(BaseModel):
    action: Literal["play_pause"]


class NextAction(BaseModel):
    action: Literal["next"]


class PreviousAction(BaseModel):
    action: Literal["previous"]


class VolumeStepAction(BaseModel):
    action: Literal["volume_step"]
    delta: float = Field(ge=-0.5, le=0.5)


CommandAction = Annotated[
    Union[PlayPauseAction, NextAction, PreviousAction, VolumeStepAction],
    Field(discriminator="action"),
]

ERROR_STATUS: dict[str, int] = {
    "no_session": 409,
    "not_supported": 409,
    "volume_unavailable": 503,
    "timeout": 504,
    "busy": 429,
}
