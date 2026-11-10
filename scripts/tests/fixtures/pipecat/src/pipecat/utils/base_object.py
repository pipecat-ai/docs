"""Base class for pipecat objects: names and event handlers."""

from abc import ABC


class BaseObject(ABC):
    def __init__(self, *, name: str | None = None):
        self._name = name or self.__class__.__name__
        self._event_handlers = {}

    @property
    def name(self) -> str:
        return self._name

    def event_handler(self, event_name: str):
        def decorator(handler):
            self.add_event_handler(event_name, handler)
            return handler

        return decorator

    def add_event_handler(self, event_name: str, handler):
        self._event_handlers[event_name].append(handler)

    def _register_event_handler(self, event_name: str, sync: bool = False):
        self._event_handlers[event_name] = []

    async def _call_event_handler(self, event_name: str, *args, **kwargs):
        for handler in self._event_handlers[event_name]:
            await handler(self, *args, **kwargs)
