"""Acme connection: registers events without the `on_` prefix, like
pipecat.transports.sip.connection.SIPConnection. A page names them in an
events table, which the prose scan's `on_...` pattern never matches."""

from pipecat.utils.base_object import BaseObject


class AcmeConnection(BaseObject):
    def __init__(self, *, user: str, domain: str, password: str = ""):
        super().__init__()
        self._user = user
        self._domain = domain
        self._password = password
        self._register_event_handler("connected")
        self._register_event_handler("dropped")
        self._register_event_handler("idle")

    async def start(self):
        await self._call_event_handler("connected")
        await self._call_event_handler("dropped")
