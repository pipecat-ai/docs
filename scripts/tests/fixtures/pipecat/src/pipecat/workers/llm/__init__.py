"""LLM worker package: re-exports the `@tool` decorator, as pipecat's does."""

from pipecat.workers.llm.tool_decorator import tool

__all__ = ["tool"]
