"""Frames: dataclasses, so their constructors are their fields."""

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class Frame:
    id: int = field(init=False)
    name: str = field(init=False)


@dataclass
class TextFrame(Frame):
    text: str


@dataclass
class TTSSpeakFrame(Frame):
    text: str
    append_to_context: bool | None = None


@dataclass
class STTUpdateSettingsFrame(Frame):
    """Shaped like pipecat's: a deprecated `settings` dict beside `delta`."""

    settings: Mapping[str, Any] = field(default_factory=dict)
    delta: Any = None
