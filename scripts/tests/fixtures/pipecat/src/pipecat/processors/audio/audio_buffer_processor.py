"""The registry has `class` entries for AudioBufferProcessor that record
deprecated events, not a deprecated class: their messages don't name it."""

from pipecat.processors.frame_processor import FrameProcessor


class AudioBufferProcessor(FrameProcessor):
    def __init__(self, *, sample_rate: int | None = None, num_channels: int = 1, **kwargs):
        super().__init__(**kwargs)
        self._num_channels = num_channels
        self._register_event_handler("on_audio_data")

    async def start_recording(self):
        await self._call_event_handler("on_audio_data", b"")
