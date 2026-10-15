"""Frames: dataclasses, so their constructors are their fields."""

from dataclasses import dataclass, field


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
