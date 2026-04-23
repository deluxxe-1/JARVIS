from __future__ import annotations

"""
Engine entrypoints.

For now this module delegates to `_legacy_main` to preserve behavior while we
incrementally refactor the original monolithic `main.py`.
"""

from typing import Any

from jarvis.logging import configure_logging

# Re-export selected legacy surface that other entrypoints rely on
from _legacy_main import (  # noqa: F401
    _load_memory,
    _save_memory,
    _build_prefix_messages,
    _build_tool_groups,
    _prune_messages,
    _select_tools,
    _run_tool_loop,
    _run_simple_chat_streaming,
    DEFAULT_MEMORY_PATH,
    MAX_CONTEXT_MESSAGES,
    MEMORY_UPDATE_EVERY,
    MODEL,
    console,
    SYSTEM_PROMPT,
)


def main() -> None:
    configure_logging()
    from _legacy_main import main as legacy_main

    legacy_main()


# Backwards-compatible surface for code that expects these symbols.
def run_tool_loop(*args: Any, **kwargs: Any) -> Any:
    return _run_tool_loop(*args, **kwargs)


def run_simple_chat_streaming(*args: Any, **kwargs: Any) -> Any:
    return _run_simple_chat_streaming(*args, **kwargs)


def select_tools(*args: Any, **kwargs: Any) -> Any:
    return _select_tools(*args, **kwargs)

