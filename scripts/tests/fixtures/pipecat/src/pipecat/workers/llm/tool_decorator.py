"""Decorator for marking methods as LLM tools, shaped like pipecat's.

`timeout` is deprecated: deprecations.json records it as `tool.timeout`, a
parameter of a function rather than of a class.
"""


def tool(fn=None, *, cancel_on_interruption=True, timeout_secs=None, timeout=None):
    """Mark a method as a tool."""
    if timeout is not None and timeout_secs is None:
        timeout_secs = timeout

    def decorator(fn):
        fn._pipecat_is_llm_tool = True
        fn._timeout_secs = timeout_secs
        return fn

    if fn is not None:
        return decorator(fn)
    return decorator
