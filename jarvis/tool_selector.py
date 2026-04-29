"""
JARVIS Tool Selector — dynamic tool filtering based on user input.

Selects a relevant subset of available tools based on keyword matching
against the user's input. This prevents overwhelming local LLMs (<30B params)
with 100+ tool definitions when only a few are relevant.
"""

from __future__ import annotations

import re
from typing import Any


def _build_tool_groups(available_tools: list) -> dict[str, list]:
    """Construye grupos de herramientas indexados por nombre de función."""
    by_name = {f.__name__: f for f in available_tools}

    def _pick(*names: str) -> list:
        return [by_name[n] for n in names if n in by_name]

    return {
        "files": _pick(
            "create_file", "edit_file", "read_file", "search_replace_in_file",
            "append_file", "insert_after", "delete_path", "copy_path", "move_path",
            "list_directory", "glob_find", "exists_path", "describe_path",
            "create_folder", "apply_template",
        ),
        "system": _pick(
            "run_command", "run_command_checked", "run_command_retry",
            "service_status", "service_restart", "service_health_report",
            "service_restart_with_deps", "service_wait_active",
            "list_processes", "disk_usage", "install_packages",
        ),
        "search": _pick(
            "fuzzy_search_paths", "build_text_index", "rag_query",
            "tail_file", "estimate_dir", "count_dir_children_matches",
        ),
        "project": _pick(
            "detect_project", "project_workflow_suggest",
            "apply_unified_patch", "ast_list_functions", "ast_read_function",
        ),
        "docker": _pick("docker_ps", "docker_logs", "docker_exec"),
        "data":   _pick("db_query_sqlite"),
        "admin":  _pick(
            "rollback", "rollback_tokens", "policy_show", "policy_set",
            "policy_reset", "resolve_path", "schedule_agent_task",
        ),
        "agents": _pick(
            "dev_agent_create", "dev_agent_status", "dev_agent_log",
            "dev_agent_result", "dev_agent_stop", "dev_agent_schedule",
            "dev_agent_list", "dev_agent_quick",
        ),
        "apis": _pick(
            "get_weather", "get_news", "web_search", "wikipedia_search",
            "translate_text", "get_ip_info", "get_crypto_price", "get_datetime_info",
        ),
        "automation": _pick(
            "open_application", "close_application", "get_volume", "set_volume",
            "toggle_mute", "take_screenshot", "set_wallpaper", "get_clipboard",
            "set_clipboard", "show_notification", "open_url", "lock_screen",
            "system_info", "get_battery", "set_brightness", "get_brightness",
            "empty_recycle_bin",
        ),
        "productivity": _pick(
            "set_reminder", "set_timer", "list_reminders", "cancel_reminder",
            "create_macro", "run_macro", "list_macros", "delete_macro",
            "generate_password", "save_password", "get_password",
            "list_passwords", "delete_password",
        ),
        "intelligence": _pick(
            "screen_ocr", "image_ocr", "extract_document_text",
            "summarize_document", "semantic_search", "index_directory",
        ),
        "hotkey": _pick(
            "start_voice_listener", "stop_voice_listener",
            "get_listener_status",
        ),
        "clipboard_intel": _pick(
            "analyze_clipboard", "smart_clipboard_action",
        ),
        "briefing": _pick(
            "daily_briefing", "quick_status",
        ),
        "network": _pick(
            "scan_network", "ping_host", "scan_ports", "check_internet",
        ),
        "media": _pick(
            "media_play_pause", "media_next", "media_previous",
            "media_stop", "now_playing",
        ),
        "organizer": _pick(
            "organize_folder", "find_duplicates", "clean_old_files",
            "folder_stats",
        ),
        "git": _pick(
            "git_status", "git_diff", "git_smart_commit",
            "git_log", "git_branch", "git_describe_pr",
        ),
        "guard": _pick(
            "start_guard", "stop_guard", "guard_status",
            "set_guard_threshold", "guard_alerts_history",
        ),
        "knowledge": _pick(
            "save_note", "save_bookmark", "save_snippet",
            "search_knowledge", "delete_knowledge", "list_knowledge_tags",
        ),
        "wm": _pick(
            "list_windows", "list_monitors", "move_to_monitor",
            "snap_window", "minimize_all",
            "close_window", "focus_window",
        ),
        "scraper": _pick(
            "scrape_text", "scrape_links", "scrape_images",
            "monitor_price",
        ),
        "obsidian": _pick(
            "obsidian_create_note", "obsidian_read_note", "obsidian_search",
            "obsidian_list_notes", "obsidian_daily_note", "obsidian_append_to_note",
            "obsidian_delete_note", "obsidian_list_tags", "obsidian_recent",
            "migrate_kb_to_obsidian",
        ),
    }


def _select_tools(user_input: str, available_tools: list, tool_groups: dict[str, list]) -> list:
    """Selecciona el subconjunto de herramientas relevantes para la petición."""
    s = user_input.lower()
    selected: list = []
    added_names: set[str] = set()

    def _add_group(group_name: str) -> None:
        for t in tool_groups.get(group_name, []):
            if t.__name__ not in added_names:
                selected.append(t)
                added_names.add(t.__name__)

    def _add_by_names(names: list[str]) -> None:
        by_name = {f.__name__: f for f in available_tools}
        for n in names:
            t = by_name.get(n)
            if t is None:
                continue
            if t.__name__ in added_names:
                continue
            selected.append(t)
            added_names.add(t.__name__)

    # Archivos/sistema siempre disponibles — son el core
    _add_group("files")

    # Palabras de acción sobre el sistema de archivos y comandos
    if any(k in s for k in [
        "crea", "crear", "créa", "haz", "hace", "pon", "ponme", "ponle",
        "new ", "nueva", "nuevo", "añade", "agrega", "genera", "genera",
        "carpeta", "directorio", "folder", "archivo", "fichero",
        "edita", "modifica", "cambia", "actualiza", "escribe",
        "borra", "elimina", "quita", "mueve", "copia", "renombra",
        "lista", "muéstrame", "show", "qué hay", "contenido de",
    ]):
        _add_group("files")
        _add_group("system")

    if any(k in s for k in ["ejecuta", "comando", "instala", "sudo", "script", "terminal", "servicio", "service", "systemctl", "puerto", "proceso", "ps ", "reinicia", "restart", "activo", "activa"]):
        _add_group("system")
    if any(k in s for k in ["busca", "encuentra", "search", "índice", "indice", "rag", "fuzzy", "grep", "contiene", "ocurrencia"]):
        _add_group("search")
    if any(k in s for k in ["proyecto", "project", "test", "pytest", "función", "funcion", "clase", "parche", "patch", "diff", "ast", "método", "metodo", "compilar", "lint", "importa"]):
        _add_group("project")
    if any(k in s for k in ["docker", "contenedor", "container", "imagen", "compose"]):
        _add_group("docker")
    if any(k in s for k in ["sqlite", "base de datos", "sql", "db", "tabla", "query", "select"]):
        _add_group("data")
    if any(k in s for k in ["rollback", "deshacer", "política", "politica", "policy", "delega", "agenda", "cron", "programa"]):
        _add_group("admin")
    if any(k in s for k in [
        "agente", "agent", "dev_agent", "mientras duermo", "en background",
        "autónomo", "autonomo", "programa para", "programa a las",
        "proyecto completo", "implementa", "construye", "desarrolla",
        "haz un proyecto", "crea un proyecto", "api rest", "web app",
        "scraper", "bot", "backend", "frontend", "fullstack",
    ]):
        _add_group("agents")
    if any(k in s for k in ["clima", "tiempo", "weather", "noticias", "news", "busca en", "web search", "wikipedia", "wiki", "traduce", "translate", "mi ip", "ip", "bitcoin", "crypto", "hora en", "fecha"]):
        _add_group("apis")
    if any(k in s for k in ["abre", "cierra", "abrir", "cerrar", "chrome", "firefox", "notepad", "spotify", "discord", "volumen", "volume", "silencia", "mute", "captura", "screenshot", "wallpaper", "portapapeles", "clipboard", "notificación", "url", "bloquear", "sistema", "batería", "brillo", "papelera"]):
        _add_group("automation")
    if any(k in s for k in ["recordatorio", "reminder", "timer", "temporizador", "alarma", "macro", "contraseña", "password", "clave"]):
        _add_group("productivity")
    if any(k in s for k in ["ocr", "leer pantalla", "texto en pantalla", "resume", "resumir", "documento", "semantic search", "indexar"]):
        _add_group("intelligence")
    if any(k in s for k in ["voz", "escuchar", "micrófono", "wake word", "listener"]):
        _add_group("hotkey")
    if any(k in s for k in ["analiza lo copiado", "qué tengo copiado"]):
        _add_group("clipboard_intel")
    if any(k in s for k in ["buenos días", "briefing", "resumen del día", "estado rápido"]):
        _add_group("briefing")
    if any(k in s for k in ["red", "network", "wifi", "escanear red", "ping", "puertos", "internet"]):
        _add_group("network")
    if any(k in s for k in ["música", "play", "pause", "reproduce", "siguiente", "anterior", "qué suena", "canción"]):
        _add_group("media")
    if any(k in s for k in ["organiza", "ordenar", "descargas", "duplicados", "limpiar archivos", "estadísticas carpeta"]):
        _add_group("organizer")
    if any(k in s for k in ["git", "commit", "push", "pull", "rama", "repo"]):
        _add_group("git")
    if any(k in s for k in ["guard", "vigía", "vigilar", "umbral", "alertas del sistema"]):
        _add_group("guard")
    if any(k in s for k in ["nota", "apunte", "guarda esto", "bookmark", "base de conocimiento"]):
        _add_group("knowledge")
    if any(k in s for k in ["ventana", "window", "snap", "minimiza todo", "monitor", "pantalla 2", "display"]):
        _add_group("wm")
    if any(k in s for k in ["scrape", "extraer de web", "enlaces de", "precio"]):
        _add_group("scraper")
    if any(k in s for k in ["obsidian", "vault", "nota diaria", "daily note"]):
        _add_group("obsidian")

    # -----------------------------------------------------------------------
    # Capabilities/tags (fallback): añade tools puntuales por intención.
    # Esto reduce falsos negativos sin abrir "todas las tools".
    # -----------------------------------------------------------------------
    intent_ocr = any(k in s for k in ["ocr", "leer pantalla", "texto en pantalla", "tesseract"])
    intent_docs = any(k in s for k in ["pdf", "docx", "documento", "resume archivo", "resumir archivo", "extrae texto"])
    intent_web = any(k in s for k in ["requests", "http", "scrape", "scraping", "extraer de web", "enlaces", "links"])
    intent_git = any(k in s for k in ["git", "commit", "push", "pull", "merge", "branch", "rama", "repo"])
    intent_voice = any(k in s for k in ["voz", "escuchar", "micrófono", "wake word", "listener"])
    intent_monitor = any(k in s for k in ["psutil", "cpu", "ram", "memoria", "batería", "procesos"])

    if intent_ocr:
        _add_by_names(["screen_ocr", "image_ocr"])
    if intent_docs:
        _add_by_names(["extract_document_text", "summarize_document"])
    if intent_web:
        _add_by_names(["web_search", "scrape_text", "scrape_links", "scrape_images", "monitor_price"])
    if intent_git:
        _add_by_names(["git_status", "git_diff", "git_smart_commit", "git_log", "git_branch", "git_describe_pr"])
    if intent_voice:
        _add_by_names(["start_voice_listener", "stop_voice_listener", "get_listener_status"])
    if intent_monitor:
        _add_by_names(["quick_status", "guard_status", "guard_alerts_history"])

    # NO dumpeamos todas las tools aunque solo estén las de files.
    # Los modelos locales se abruman con >50 tools y prefieren explicar antes que actuar.
    # Devolver solo las relevantes mejora la tasa de tool-calling.
    return selected


def _is_simple_conversational(text: str) -> bool:
    """Detecta preguntas que claramente NO necesitan herramientas.
    Devuelve False en cuanto detecte cualquier intención de acción.
    """
    s = text.lower().strip()

    # Si hay cualquier palabra de acción → NUNCA es conversacional
    action_blocklist = [
        "crea", "crear", "créa", "haz", "hazme", "ponme", "pon ",
        "new ", "nueva", "nuevo", "añade", "agrega", "genera",
        "carpeta", "directorio", "folder", "archivo", "fichero",
        "edita", "modifica", "cambia", "actualiza", "escribe",
        "borra", "elimina", "quita", "mueve", "copia", "renombra",
        "lista", "muéstrame", "show me", "qué hay", "contenido de",
        "ejecuta", "corre", "lanza", "instala", "busca", "encuentra",
        "abre", "cierra", "descarga", "sube", "lee", "lee el",
        "escáner", "escanea", "verifica", "comprueba", "analiza",
        "traduce", "resume", "convierte", "extrae", "procesa",
        "git", "commit", "docker", "sqlite", "ping", "npm", "pip",
    ]
    if any(k in s for k in action_blocklist):
        return False

    simple_patterns = [
        r"^hola\b",
        r"^(qu[eé] eres|qui[eé]n eres)",
        r"^(qu[eé] puedes hacer|qu[eé] sabes hacer)",
        r"^(buenos? d[ií]as?|buenas? tardes?|buenas? noches?)",
        r"^(c[oó]mo est[aá]s|qu[eé] tal)\??$",
        r"^(gracias|de nada|ok|vale|perfecto|entendido)[\.\\!]?$",
        r"^(ayuda|help)$",
    ]
    return any(re.search(p, s) for p in simple_patterns)


def _heuristic_requires_tools(user_input: str) -> bool:
    s = user_input.lower()
    keywords = [
        "crear", "editar", "actualizar", "borrar", "eliminar", "borra",
        "carpeta", "directorio", "archivo", "comando", "ejecuta", "instalar",
        "rm ", "cp ", "mv ", "sudo ",
    ]
    return any(k in s for k in keywords)
