"""
AARIS Tool Selector — dynamic tool filtering based on user input.

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
            "scaffold_project",
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
            "get_weather", "get_news", "web_search", "web_search_full",
            "web_read_page", "extract_info_from_url", "wikipedia_search",
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
            "screen_ocr", "image_ocr", "vision_analyze_image",
            "extract_document_text",
            "summarize_document", "document_ask", "semantic_search", "index_directory",
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


def _informacion_sobre_typo(s: str) -> bool:
    """Detecta 'información sobre' / typos tipo 'informacion ssobre' (sin depender del string exacto)."""
    return bool(re.search(r"informaci[oó]n\s+\w*obre", s, re.IGNORECASE))


def _compound_disk_and_web_research(s: str) -> bool:
    """Varias acciones en un mensaje (carpeta/archivo/html + investigar en la web)."""
    disk = bool(re.search(r"\b(crea|crear|carpeta|archivo|html|\.html|directorio)\b", s, re.I))
    webish = bool(
        re.search(r"\b(busca|investiga|wikipedia|internet|en la web)\b", s, re.I)
        or _informacion_sobre_typo(s)
        or "informacion" in s
        or "información" in s
    )
    glue = bool(
        re.search(r"\b(luego|despu[eé]s|despues|adem[aá]s|tambi[eé]n)\b", s, re.I)
    ) or (" y " in s)
    return disk and webish and glue


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

    if "[adjuntos aaris]" in s:
        _add_group("intelligence")
        _add_by_names([
            "vision_analyze_image", "document_ask", "extract_document_text",
            "summarize_document", "image_ocr",
        ])

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
        # "busca X" → internet salvo intención clara de buscar EN código/archivo concreto.
        # NO usar solo "carpeta"/"directorio": en frases compuestas ("crea carpeta… busca info…")
        # eso bloqueaba web_search_full por error.
        _local_fs_or_code_search = any(
            k in s
            for k in (
                "rag_query", "build_text_index", "glob_find", "fuzzy_search",
                "en este archivo", "en mi código", "en mi codigo",
                "en el código", "en el codigo", "ocurrencia en el",
                "grep ", "índice local", "indice local",
            )
        )
        _local_fs_or_code_search = _local_fs_or_code_search or any(
            ext in s for ext in (
                ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".cs", ".json",
            )
        )
        _local_fs_or_code_search = _local_fs_or_code_search or bool(
            re.search(r"[cde]:\\", s, re.I),
        )
        _local_fs_or_code_search = _local_fs_or_code_search or (
            "busca" in s
            and any(
                p in s
                for p in (
                    "en la carpeta",
                    "dentro de la carpeta",
                    "archivo llamado",
                    "nombre del archivo",
                    "glob_find",
                )
            )
        )
        # "busca el archivo X" / "busca archivos" → disco, no DuckDuckGo
        _local_fs_or_code_search = _local_fs_or_code_search or (
            ("busca" in s or "encuentra" in s) and "archivo" in s
        )
        _force_web = _informacion_sobre_typo(s) or _compound_disk_and_web_research(s)
        if _force_web or not _local_fs_or_code_search:
            _add_by_names(["web_search_full", "web_read_page", "wikipedia_search", "extract_info_from_url"])
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
    # Programación directa (sin dev_agent) — cuando pide código, scripts, programas
    if any(k in s for k in [
        "programa", "programar", "programame", "código", "codigo",
        "script", "función", "funcion", "clase ", "algoritmo",
        "python", "javascript", "java ", "html", "css", "react",
        "flask", "fastapi", "django", "node", "express",
        "hazme un", "escríbeme", "escribeme", "codea",
        "app ", "aplicación", "aplicacion", "página web", "pagina web",
        "crear web", "desarrolla una web", "web app", "sitio web", "web"
    ]):
        _add_group("files")
        _add_group("system")
        _add_group("project")

    # Investigación web / información de internet
    if any(k in s for k in [
        "busca en internet", "busca en la web", "busca online",
        "investiga", "información sobre", "informacion sobre",
        "qué dice internet", "que dice internet",
        "lee esta página", "lee esta pagina", "lee esta url",
        "abre esta web", "abre esta url", "contenido de la web",
        "averigua", "indaga", "consulta en internet",
        "resume esta web", "extrae información de", "resume este artículo",
    ]) or _informacion_sobre_typo(s) or _compound_disk_and_web_research(s):
        _add_group("apis")
        _add_group("scraper")

    if any(k in s for k in [
        "clima", "tiempo", "weather", "noticias", "news", "busca en", "web search",
        "wikipedia", "wiki", "traduce", "translate", "mi ip", "ip", "bitcoin", "crypto",
        "hora en", "fecha", "google", "duckduckgo", "reddit", "stackoverflow",
        "stack overflow", "documentación", "documentacion", "en línea", "en linea",
        "página web", "pagina web", "url http", "https://", "http://",
    ]):
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
    intent_ocr = any(k in s for k in [
        "ocr", "leer pantalla", "texto en pantalla", "tesseract",
        "screenshot", "captura de pantalla", "analiza la imagen", "analiza esta imagen",
        "imagen adjunta", "foto adjunta", "qué hay en la imagen", "que hay en la imagen",
    ])
    intent_docs = any(k in s for k in [
        "pdf", "docx", "documento", "resume archivo", "resumir archivo", "extrae texto",
        "pregunta sobre el pdf", "analiza el pdf", "analiza el documento",
    ])
    intent_web = any(k in s for k in [
        "requests", "http", "https", "scrape", "scraping", "extraer de web", "enlaces", "links",
    ])
    intent_git = any(k in s for k in ["git", "commit", "push", "pull", "merge", "branch", "rama", "repo"])
    intent_voice = any(k in s for k in ["voz", "escuchar", "micrófono", "wake word", "listener"])
    intent_monitor = any(k in s for k in ["psutil", "cpu", "ram", "memoria", "batería", "procesos"])
    intent_programming = any(k in s for k in [
        "script", "código", "codigo", "programa", "programar", "función", "funcion",
        "python", "javascript", "typescript", "rust", "golang", "kotlin", "swift",
        "depura", "depurar", "debug", "stack trace", "traceback", "syntax error",
    ])
    intent_web_research = any(k in s for k in [
        "investiga", "averigua", "busca en internet", "información sobre", "informacion sobre",
        "actualidad", "últimas noticias", "ultimas noticias", "hoy en día", "hoy en dia",
    ]) or _informacion_sobre_typo(s) or _compound_disk_and_web_research(s)

    if intent_ocr:
        _add_by_names(["screen_ocr", "image_ocr", "vision_analyze_image"])
    if intent_docs:
        _add_by_names(["extract_document_text", "summarize_document", "document_ask"])
    if intent_web:
        _add_by_names([
            "web_search_full", "web_search", "web_read_page", "extract_info_from_url",
            "scrape_text", "scrape_links", "scrape_images", "monitor_price",
        ])
    if intent_git:
        _add_by_names(["git_status", "git_diff", "git_smart_commit", "git_log", "git_branch", "git_describe_pr"])
    if intent_voice:
        _add_by_names(["start_voice_listener", "stop_voice_listener", "get_listener_status"])
    if intent_monitor:
        _add_by_names(["quick_status", "guard_status", "guard_alerts_history"])
    if intent_programming:
        _add_by_names([
            "create_file", "edit_file", "read_file", "search_replace_in_file",
            "create_folder", "run_command", "run_command_checked", "list_directory",
            "validate_python_syntax", "ast_list_functions", "ast_read_function",
            "detect_project", "project_workflow_suggest",
        ])
    if intent_web_research:
        _add_by_names([
            "web_search_full", "web_read_page", "web_search", "wikipedia_search",
            "extract_info_from_url", "scrape_text", "scrape_links",
        ])

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
        "programa", "programar", "código", "codigo", "script",
        "python", "javascript", "html", "css",
        "investiga", "averigua",
        "qué es", "que es", "quién es", "quien es", "qué son", "que son",
        "información sobre", "informacion sobre", "dime sobre",
        "cuéntame sobre", "cuentame sobre", "haz una búsqueda",
        "what is", "who is", "who are", "tell me about", "look up", "search for",
        "define ", "definición", "definicion", "wikipedia", "en internet",
        "[adjuntos aaris]",
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
