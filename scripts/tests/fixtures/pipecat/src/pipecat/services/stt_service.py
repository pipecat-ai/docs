from pipecat.services.ai_service import AIService


class STTService(AIService):
    def __init__(self, *, sample_rate: int | None = None, text_transforms: list | None = None, **kwargs):
        super().__init__(**kwargs)
        self._sample_rate = sample_rate
        self._text_transforms = text_transforms or []
