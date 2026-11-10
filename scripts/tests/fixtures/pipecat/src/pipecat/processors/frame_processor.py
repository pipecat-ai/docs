from pipecat.frames.frames import Frame
from pipecat.utils.base_object import BaseObject


class FrameProcessor(BaseObject):
    def __init__(self, *, name: str | None = None, enable_direct_mode: bool = False, **kwargs):
        super().__init__(name=name, **kwargs)
        self._enable_direct_mode = enable_direct_mode

    async def push_frame(self, frame: Frame):
        pass

    async def queue_frame(self, frame: Frame):
        pass
