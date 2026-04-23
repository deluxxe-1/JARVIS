from __future__ import annotations

"""
Engine entrypoints.

Provides the public API for GUI and other entrypoints to interact with the
JARVIS core without depending on internal implementation details.
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


# ---------------------------------------------------------------------------
# Public API (no underscore prefix)
# ---------------------------------------------------------------------------

def build_prefix_messages(memory: dict[str, Any]) -> list[dict[str, Any]]:
    return _build_prefix_messages(memory)


def build_tool_groups(available_tools: list) -> dict[str, list]:
    return _build_tool_groups(available_tools)


def prune_messages(messages: list[dict[str, Any]], keep_last: int) -> list[dict[str, Any]]:
    return _prune_messages(messages, keep_last=keep_last)


def select_tools(user_input: str, available_tools: list, tool_groups: dict[str, list]) -> list:
    return _select_tools(user_input, available_tools, tool_groups)


def run_tool_loop(messages: list, available_tools: list, tool_map: dict, options: dict[str, Any]) -> str:
    return _run_tool_loop(messages, available_tools, tool_map, options)


def run_simple_chat(messages: list, options: dict) -> str:
    return _run_simple_chat_streaming(messages, options)


def main() -> None:
    configure_logging()
    from _legacy_main import main as legacy_main

    legacy_main()
