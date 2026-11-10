"""Base TTS service. Its events are documented once, on its own page, so a
provider's page isn't expected to list them."""

from pipecat.services.ai_service import AIService


class TTSService(AIService):
    def __init__(self, *, sample_rate: int | None = None, push_stop_frames: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._sample_rate = sample_rate
        self._register_event_handler("on_connected")
        self._register_event_handler("on_connection_error")

    async def start(self, frame):
        await self._call_event_handler("on_connected")

    async def say(self, text: str):
        try:
            pass
        except Exception as e:
            await self._report_error(e)

    async def _report_error(self, error):
        await self._call_event_handler("on_connection_error", error)
