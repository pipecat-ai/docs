"""An example bot. Names defined here are real to the checker: pages describe them."""

import os

from pipecat.frames.frames import Frame
from pipecat.services.acme.tts import AcmeTTSService


class ExampleHoldFrame(Frame):
    pass


tts = AcmeTTSService(api_key=os.getenv("ACME_ALT_API_KEY"))
