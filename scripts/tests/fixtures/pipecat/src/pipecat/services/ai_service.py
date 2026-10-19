from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.settings import ServiceSettings


class AIService(FrameProcessor):
    def __init__(self, *, settings: ServiceSettings | None = None, **kwargs):
        super().__init__(**kwargs)
        self._settings = settings
