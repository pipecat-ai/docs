"""Acme speech-to-text: a setting that `__init__` fills in when left unset."""

from dataclasses import dataclass, field

from pipecat.services.settings import STTSettings
from pipecat.services.stt_service import STTService
from pipecat.utils.types import NOT_GIVEN, NotGiven, is_given


@dataclass
class AcmeSTTSettings(STTSettings):
    punctuate: bool | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)


class AcmeSTTService(STTService):
    Settings = AcmeSTTSettings

    def __init__(self, *, api_key: str, settings: Settings | None = None, **kwargs):
        default_settings = self.Settings(model="acme-stt-1", punctuate=True)
        if settings is not None:
            default_settings.apply_update(settings)
        super().__init__(settings=default_settings, **kwargs)
        if not is_given(self._settings.language):
            self._settings.language = "en"
