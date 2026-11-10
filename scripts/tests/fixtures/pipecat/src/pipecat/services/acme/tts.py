"""Acme text-to-speech: a provider service shaped like pipecat's real ones.

Each name here exists to trigger or to dodge one of the checker's rules; the
tests in scripts/tests/test_check_reference.py say which.
"""

from dataclasses import dataclass, field
from typing import Optional

from acme_sdk import SdkClientBase
from pydantic import BaseModel

from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.types import NOT_GIVEN, NotGiven

DEFAULT_SAMPLE_RATE = 24000


@dataclass
class AcmeTTSSettings(TTSSettings):
    """Settings for AcmeTTSService."""

    speed: float | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)
    emotion: str | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)
    style: str | None | NotGiven = field(default_factory=lambda: NOT_GIVEN)


class AcmeTTSService(TTSService):
    Settings = AcmeTTSSettings
    _settings: Settings

    class InputParams(BaseModel):
        language: Language | None = Language.EN
        speed: float | None = 1.0

    def __init__(
        self,
        *,
        api_key: str,
        encoding: str = "pcm",
        container: str = "raw",
        region: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        timeout_secs: float = 5.0,
        voice_id: str | None = None,
        params: InputParams | None = None,
        model_name: str | None = None,
        settings: Settings | None = None,
        _test_delay: float = 0.0,
        **kwargs,
    ):
        default_settings = self.Settings(
            model="acme-2",
            voice="ava",
            language="en",
            speed=1.0,
            emotion=None,
        )
        if settings is not None:
            default_settings.apply_update(settings)
        super().__init__(sample_rate=sample_rate, settings=default_settings, **kwargs)
        self._api_key = api_key
        self._register_event_handler("on_acme_ready")
        self._register_event_handler("on_acme_connected")
        self._register_event_handler("on_acme_never")
        self._register_event_handler("on_acme_unused")
        self._register_event_handler("on_acme_shared")

    @property
    def voice_count(self) -> int:
        return 3

    async def start(self, frame):
        await self._call_event_handler("on_acme_ready")
        await self._call_event_handler("on_acme_shared")
        await self._handle_connect()

    async def _handle_connect(self):
        await self._call_event_handler("on_acme_connected")

    async def _dead_code(self):
        await self._call_event_handler("on_acme_never")

    def set_voice(self, voice: str, encoding: str = "pcm", container: str = "raw", legacy: bool = False):
        pass

    def old_flush(self):
        pass


class AcmeHttpTTSService(TTSService):
    Settings = AcmeTTSSettings

    def __init__(self, *, api_key: str, settings: Settings | None = None, **kwargs):
        super().__init__(settings=settings, **kwargs)
        self._register_event_handler("on_acme_shared")
        self._register_event_handler("on_acme_http_only")


class OldAcmeTTSService(AcmeTTSService):
    pass


class AcmeSdkWrapper(SdkClientBase):
    """Passes unknown keywords to a base outside pipecat."""

    def __init__(self, *, api_key: str, **kwargs):
        super().__init__(**kwargs)
