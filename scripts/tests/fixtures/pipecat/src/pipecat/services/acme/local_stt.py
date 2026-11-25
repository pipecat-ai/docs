"""Acme local STT: a service whose only own parameter is `settings`, like Moonshine's."""

from pipecat.services.acme.stt import AcmeSTTSettings
from pipecat.services.stt_service import STTService


class AcmeLocalSTTService(STTService):
    Settings = AcmeSTTSettings

    def __init__(self, *, settings: Settings | None = None, **kwargs):
        super().__init__(settings=settings, **kwargs)
