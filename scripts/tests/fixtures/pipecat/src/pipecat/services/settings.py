"""Settings dataclasses shared by every service."""

from dataclasses import dataclass, field
from typing import Any, ClassVar

from pipecat.transcriptions.language import Language
from pipecat.utils.types import NOT_GIVEN, NotGiven


@dataclass
class ServiceSettings:
    model: str | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)
    extra: dict[str, Any] = field(default_factory=dict)
    _aliases: ClassVar[dict[str, str]] = {}

    def apply_update(self, delta: "ServiceSettings"):
        pass


@dataclass
class TTSSettings(ServiceSettings):
    voice: str | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)
    language: Language | str | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)


@dataclass
class STTSettings(ServiceSettings):
    language: Language | str | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)
