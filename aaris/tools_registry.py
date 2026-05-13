from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


ToolFn = Callable[..., object]


@dataclass(frozen=True)
class ToolSpec:
    module: str
    names: tuple[str, ...]


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        module="aaris.tools.core",
        names=(
            "policy_show",
            "policy_set",
            "policy_reset",
            "rollback",
            "rollback_tokens",
        ),
    ),
    ToolSpec(
        module="aaris.tools.filesystem",
        names=(
            "create_file",
            "read_file",
            "edit_file",
            "search_replace_in_file",
            "create_folder",
            "list_directory",
            "glob_find",
            "resolve_path",
            "exists_path",
            "stat_path",
            "describe_path",
            "estimate_dir",
            "disk_usage",
            "tail_file",
            "count_dir_children_matches",
            "fuzzy_search_paths",
            "append_file",
            "insert_after",
            "copy_path",
            "move_path",
            "delete_path",
            "apply_unified_patch",
        ),
    ),
    ToolSpec(
        module="aaris.tools.system",
        names=(
            "list_processes",
            "validate_python_syntax",
            "service_status",
            "service_restart",
            "service_wait_active",
            "service_health_report",
            "service_restart_with_deps",
            "run_command",
            "run_command_checked",
            "run_command_retry",
            "install_packages",
        ),
    ),
    ToolSpec(
        module="aaris.tools.project",
        names=(
            "detect_project",
            "project_workflow_suggest",
            "apply_template",
            "scaffold_project",
        ),
    ),
    ToolSpec(
        module="aaris.tools.search",
        names=(
            "build_text_index",
            "rag_query",
        ),
    ),
    ToolSpec(
        module="aaris.tools.docker",
        names=(
            "docker_ps",
            "docker_logs",
            "docker_exec",
        ),
    ),
    ToolSpec(
        module="aaris.tools.sqlite",
        names=(
            "db_query_sqlite",
        ),
    ),
    ToolSpec(
        module="aaris.tools.ast_tools",
        names=(
            "ast_list_functions",
            "ast_read_function",
        ),
    ),
    ToolSpec(
        module="aaris.tools.agents",
        names=(
            "delegate_task",
            "schedule_agent_task",
        ),
    ),
    ToolSpec(
        module="apis",
        names=(
            "get_weather",
            "get_news",
            "web_search",
            "web_search_full",
            "web_read_page",
            "extract_info_from_url",
            "wikipedia_search",
            "translate_text",
            "get_ip_info",
            "get_crypto_price",
            "get_datetime_info",
        ),
    ),
    ToolSpec(
        module="automation",
        names=(
            "open_application",
            "close_application",
            "get_volume",
            "set_volume",
            "toggle_mute",
            "take_screenshot",
            "set_wallpaper",
            "get_clipboard",
            "set_clipboard",
            "show_notification",
            "open_url",
            "lock_screen",
            "system_info",
            "get_battery",
            "set_brightness",
            "get_brightness",
            "empty_recycle_bin",
        ),
    ),
    ToolSpec(
        module="productivity",
        names=(
            "set_reminder",
            "set_timer",
            "list_reminders",
            "cancel_reminder",
            "create_macro",
            "run_macro",
            "list_macros",
            "delete_macro",
            "generate_password",
            "save_password",
            "get_password",
            "list_passwords",
            "delete_password",
            "rotate_vault_key",
        ),
    ),
    ToolSpec(
        module="intelligence",
        names=(
            "screen_ocr",
            "image_ocr",
            "vision_analyze_image",
            "extract_document_text",
            "summarize_document",
            "document_ask",
            "semantic_search",
            "index_directory",
        ),
    ),
    ToolSpec(
        module="hotkey",
        names=("start_voice_listener", "stop_voice_listener", "get_listener_status"),
    ),
    ToolSpec(module="clipboard_intel", names=("analyze_clipboard", "smart_clipboard_action")),
    ToolSpec(module="briefing", names=("daily_briefing", "quick_status")),
    ToolSpec(module="network", names=("scan_network", "ping_host", "scan_ports", "check_internet")),
    ToolSpec(module="media", names=("media_play_pause", "media_next", "media_previous", "media_stop", "now_playing")),
    ToolSpec(module="organizer", names=("organize_folder", "find_duplicates", "clean_old_files", "folder_stats")),
    ToolSpec(module="git_tools", names=("git_status", "git_diff", "git_smart_commit", "git_log", "git_branch", "git_describe_pr")),
    ToolSpec(module="guard", names=("start_guard", "stop_guard", "guard_status", "set_guard_threshold", "guard_alerts_history")),
    ToolSpec(module="knowledge", names=("save_note", "save_bookmark", "save_snippet", "search_knowledge", "delete_knowledge", "list_knowledge_tags")),
    ToolSpec(module="windows", names=("list_windows", "list_monitors", "move_to_monitor", "snap_window", "minimize_all", "close_window", "focus_window")),
    ToolSpec(module="scraper", names=("scrape_text", "scrape_links", "scrape_images", "monitor_price")),
    ToolSpec(
        module="obsidian",
        names=(
            "obsidian_create_note",
            "obsidian_read_note",
            "obsidian_search",
            "obsidian_list_notes",
            "obsidian_daily_note",
            "obsidian_append_to_note",
            "obsidian_delete_note",
            "obsidian_list_tags",
            "obsidian_recent",
            "migrate_kb_to_obsidian",
        ),
    ),
    ToolSpec(
        module="dev_agent",
        names=(
            "dev_agent_create",
            "dev_agent_status",
            "dev_agent_log",
            "dev_agent_result",
            "dev_agent_stop",
            "dev_agent_schedule",
            "dev_agent_list",
            "dev_agent_quick",
        ),
    ),
)


def iter_tools(specs: Iterable[ToolSpec] = SPECS) -> list[ToolFn]:
    import importlib
    import logging

    out: list[ToolFn] = []
    seen: set[str] = set()
    for spec in specs:
        try:
            mod = importlib.import_module(spec.module)
        except Exception as e:
            logging.getLogger("aaris.tools_registry").warning(
                "No se pudo importar %s (%s). Se omite este paquete de tools.",
                spec.module,
                e,
            )
            continue
        for name in spec.names:
            fn = getattr(mod, name, None)
            if fn is None:
                continue
            fn_name = getattr(fn, "__name__", name)
            if fn_name in seen:
                continue
            out.append(fn)
            seen.add(fn_name)
    return out


def get_all_tools() -> list[ToolFn]:
    return iter_tools()
