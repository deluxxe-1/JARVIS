import json
import os
import re
import time
import difflib
from typing import Any
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from ollama import chat

from tools import (
    append_file,
    create_file,
    create_folder,
    copy_path,
    detect_project,
    build_text_index,
    rag_query,
    project_workflow_suggest,
    delete_path,
    describe_path,
    count_dir_children_matches,
    service_status,
    service_restart,
    service_health_report,
    service_restart_with_deps,
    service_wait_active,
    apply_unified_patch,
    install_packages,
    disk_usage,
    edit_file,
    fuzzy_search_paths,
    glob_find,
    estimate_dir,
    apply_template,
    exists_path,
    list_directory,
    list_processes,
    insert_after,
    read_file,
    move_path,
    resolve_path,
    rollback,
    rollback_tokens,
    run_command,
    run_command_checked,
    run_command_retry,
    search_replace_in_file,
    tail_file,
    ast_list_functions,
    ast_read_function,
    docker_ps,
    docker_logs,
    docker_exec,
    db_query_sqlite,
    delegate_task,
    schedule_agent_task,
    policy_show,
    policy_set,
    policy_reset,
)

from apis import (
    get_weather, get_news, web_search, wikipedia_search, translate_text, get_ip_info, get_crypto_price, get_datetime_info,
)
from automation import (
    open_application, close_application, get_volume, set_volume, toggle_mute, take_screenshot, set_wallpaper, get_clipboard, set_clipboard, show_notification, open_url, lock_screen, system_info, get_battery, set_brightness, get_brightness, empty_recycle_bin,
)
from productivity import (
    set_reminder, set_timer, list_reminders, cancel_reminder, create_macro, run_macro, list_macros, delete_macro, generate_password, save_password, get_password, list_passwords, delete_password,
)
from intelligence import (
    screen_ocr, image_ocr, extract_document_text, summarize_document, semantic_search, index_directory,
)

from hotkey import (
    start_voice_listener, stop_voice_listener, get_listener_status,
)
from clipboard_intel import (
    analyze_clipboard, smart_clipboard_action,
)
from briefing import (
    daily_briefing, quick_status,
)
from network import (
    scan_network, ping_host, scan_ports, check_internet,
)
from media import (
    media_play_pause, media_next, media_previous, media_stop, now_playing,
)
from organizer import (
    organize_folder, find_duplicates, clean_old_files, folder_stats,
)
from git_tools import (
    git_status, git_diff, git_smart_commit, git_log, git_branch, git_describe_pr,
)
from guard import (
    start_guard, stop_guard, guard_status, set_guard_threshold, guard_alerts_history,
)
from knowledge import (
    save_note, save_bookmark, save_snippet, search_knowledge, delete_knowledge, list_knowledge_tags,
)
from windows import (
    list_windows, list_monitors, move_to_monitor, snap_window, minimize_all, close_window, focus_window,
)
from scraper import (
    scrape_text, scrape_links, scrape_images, monitor_price,
)
from obsidian import (
    obsidian_create_note, obsidian_read_note, obsidian_search, obsidian_list_notes, obsidian_daily_note, obsidian_append_to_note, obsidian_delete_note, obsidian_list_tags, obsidian_recent, migrate_kb_to_obsidian,
)
from dev_agent import (
    dev_agent_create, dev_agent_status, dev_agent_log, dev_agent_result,
    dev_agent_stop, dev_agent_schedule, dev_agent_list, dev_agent_quick,
)
from brain import JarvisBrain
from jarvis.tools_registry import get_all_tools
from jarvis.tool_selector import _build_tool_groups, _select_tools

console = Console()

MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
MAX_TOOL_ROUNDS = int(os.environ.get("JARVIS_MAX_TOOL_ROUNDS", "12"))
MAX_CONTEXT_MESSAGES = int(os.environ.get("JARVIS_MAX_CONTEXT_MESSAGES", "20"))
MEMORY_UPDATE_EVERY = int(os.environ.get("JARVIS_MEMORY_UPDATE_EVERY", "5"))
PLAN_MODE = os.environ.get("JARVIS_PLAN_MODE", "off")  # off | auto | confirm
DRY_RUN = os.environ.get("JARVIS_DRY_RUN", "false").strip().lower() in ("1", "true", "yes", "si", "sí", "on")
PREVIEW_MUTATIONS = os.environ.get("JARVIS_PREVIEW_MUTATIONS", "true").strip().lower() in ("1", "true", "yes", "si", "sí", "on")
PREVIEW_CONFIRM_ALWAYS = os.environ.get("JARVIS_PREVIEW_CONFIRM_ALWAYS", "false").strip().lower() in (
    "1", "true", "yes", "si", "sí", "on",
)
DIFF_MAX_LINES = int(os.environ.get("JARVIS_DIFF_MAX_LINES", "300"))
BACKUP_MAX_AGE_DAYS = int(os.environ.get("JARVIS_BACKUP_MAX_AGE_DAYS", "7"))

DEFAULT_MEMORY_PATH = os.environ.get(
    "JARVIS_MEMORY_PATH",
    os.path.join(os.path.expanduser("~"), ".jarvis", "memory.json"),
)

DEFAULT_LOG_PATH = os.environ.get(
    "JARVIS_LOG_PATH",
    os.path.join(os.path.expanduser("~"), ".jarvis", "agent_log.jsonl"),
)

DEFAULT_APP_DIR = os.environ.get("JARVIS_APP_DIR", os.path.join(os.getcwd(), ".jarvis"))
UNDO_REDO_PATH = os.environ.get("JARVIS_UNDO_REDO_PATH", os.path.join(DEFAULT_APP_DIR, "undo_redo.json"))





# ---------------------------------------------------------------------------
# Limpieza de backups antiguos
# ---------------------------------------------------------------------------

def _cleanup_old_backups(max_age_days: int = 7) -> None:
    """Elimina backups con más de max_age_days días para no llenar el disco."""
    try:
        from tools import _backup_base_dir
        base = _backup_base_dir()
        cutoff = time.time() - max_age_days * 86400
        files_cleaned = 0
        for f in (base / "files").glob("*.bak"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    files_cleaned += 1
            except Exception:
                pass
        for f in (base / "meta").glob("*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass
        if files_cleaned:
            console.print(f"[dim]🧹 Backups antiguos eliminados: {files_cleaned}[/dim]")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Resto de funciones sin cambios
# ---------------------------------------------------------------------------

def _chat_options() -> dict[str, Any]:
    opts: dict[str, Any] = {}
    if ctx := os.environ.get("OLLAMA_NUM_CTX"):
        try:
            opts["num_ctx"] = int(ctx)
        except ValueError:
            pass
    if t := os.environ.get("OLLAMA_TEMPERATURE"):
        try:
            opts["temperature"] = float(t)
        except ValueError:
            pass
    return opts


def _load_undo_redo_state() -> dict[str, Any]:
    try:
        p = Path(UNDO_REDO_PATH).expanduser()
        if not p.is_file():
            return {"undo": [], "redo": []}
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"undo": [], "redo": []}
        data.setdefault("undo", [])
        data.setdefault("redo", [])
        return data
    except Exception:
        return {"undo": [], "redo": []}


def _save_undo_redo_state(state: dict[str, Any]) -> None:
    try:
        p = Path(UNDO_REDO_PATH).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass


SYSTEM_PROMPT = """Eres J.A.R.V.I.S. (Just A Rather Very Intelligent System), el asistente de IA de este sistema. Siempre respondes en español. Eres preciso, eficiente y profesional.

## ⚡ REGLA ABSOLUTA — HERRAMIENTAS
Cuando el usuario pida CUALQUIER acción sobre el sistema, DEBES llamar a la herramienta correspondiente INMEDIATAMENTE. NUNCA expliques cómo se haría — HAZLO.

Acciones que SIEMPRE requieren tool call (ejemplos no exhaustivos):
- "crea una carpeta X" → create_folder(path="X")
- "crea un archivo Y con contenido Z" → create_file(path="Y", content="Z")
- "lista esta carpeta" → list_directory(path=".")
- "lee el archivo Z" → read_file(path="Z")
- "ejecuta este comando" → run_command(command="...")
- "mueve / copia / borra X" → move_path / copy_path / delete_path
- "edita el archivo X" → edit_file o search_replace_in_file
- "busca archivos" → glob_find o fuzzy_search_paths
- "qué hay en esta carpeta" → list_directory

Si el usuario pide algo que involucra el sistema de archivos, comandos, APIs, aplicaciones o cualquier tarea sobre el equipo: USA LA HERRAMIENTA. No describas. No expliques. Actúa.

## Reglas adicionales
- Para rutas como Documents, Descargas, Desktop → usa resolve_path primero.
- Para borrar carpetas → delete_path con recursive=true y confirm=true.
- Para cambios pequeños en archivos → prefiere search_replace_in_file sobre edit_file completo.
- Si una herramienta falla, reintenta con argumentos corregidos.
- Solo responde en texto plano cuando el usuario hace una pregunta conversacional sin acción sobre el sistema.

## Personalidad
Tono formal y conciso. Llamas al usuario "señor". Frases como: "A sus órdenes.", "Ejecutado.", "Completado, señor.", "¿Desea algo más?"."""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_memory(memory_path: str) -> dict[str, Any]:
    try:
        p = Path(memory_path).expanduser()
        if not p.is_file():
            return {
                "memory_summary": "",
                "stable_facts": [],
                "preferences": {},
                "last_updated": "",
                "last_turns": [],
            }
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("memory.json no es un objeto JSON")
        data.setdefault("memory_summary", "")
        data.setdefault("stable_facts", [])
        data.setdefault("preferences", {})
        data.setdefault("last_updated", "")
        data.setdefault("last_turns", [])
        return data
    except Exception:
        return {
            "memory_summary": "",
            "stable_facts": [],
            "preferences": {},
            "last_updated": "",
            "last_turns": [],
        }


def _save_memory(memory_path: str, memory: dict[str, Any]) -> None:
    p = Path(memory_path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _build_prefix_messages(memory: dict[str, Any]) -> list[dict[str, Any]]:
    prefix: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if memory.get("memory_summary"):
        prefix.append({
            "role": "system",
            "content": "Memoria persistente del usuario (resumen estable):\n" + str(memory.get("memory_summary")),
        })
    if memory.get("stable_facts"):
        prefix.append({
            "role": "system",
            "content": "Hechos estables del usuario:\n"
            + "\n".join(str(x) for x in (memory.get("stable_facts") or [])[:50]),
        })
    if memory.get("preferences"):
        prefix.append({
            "role": "system",
            "content": "Preferencias detectadas del usuario (para decidir rutas y estilo):\n"
            + json.dumps(memory.get("preferences") or {}, ensure_ascii=False),
        })
    return prefix


def _prune_messages(messages: list[dict[str, Any]], keep_last: int) -> list[dict[str, Any]]:
    if len(messages) <= keep_last:
        return messages
    prefix = messages[:2] if len(messages) >= 2 and messages[0].get("role") == "system" else messages[:1]
    tail = messages[-(keep_last - len(prefix)):]
    return prefix + tail


def _extract_recent_for_memory(messages: list[dict[str, Any]], max_items: int = 10) -> list[dict[str, Any]]:
    reduced: list[dict[str, Any]] = []
    for m in messages:
        if m.get("role") in ("user", "assistant", "system"):
            reduced.append({"role": m.get("role"), "content": m.get("content", "")})
    reduced = [m for m in reduced if m["role"] in ("user", "assistant")]
    return reduced[-max_items:]


def _heuristic_requires_tools(user_input: str) -> bool:
    s = user_input.lower()
    keywords = [
        "crear", "editar", "actualizar", "borrar", "eliminar", "borra",
        "carpeta", "directorio", "archivo", "comando", "ejecuta", "instalar",
        "rm ", "cp ", "mv ", "sudo ",
    ]
    return any(k in s for k in keywords)


def _plan_turn(user_input: str, messages: list[dict[str, Any]], opts: dict[str, Any]) -> dict[str, Any]:
    planning_user = {
        "role": "user",
        "content": (
            "Necesito un PLAN ANTES de ejecutar acciones con herramientas.\n"
            "Devuelve SOLO JSON válido con estas claves:\n"
            "- requires_tools (boolean)\n"
            "- summary (string)\n"
            "- steps (lista de strings, máximo 8)\n"
            "- safety_notes (lista de strings, máximo 5)\n\n"
            f"Tarea del usuario: {user_input}"
        ),
    }
    planning_messages = messages[:] + [planning_user]
    plan_opts = dict(opts)
    plan_opts["temperature"] = 0.1
    try:
        response = chat(model=MODEL, messages=planning_messages, options=plan_opts or None)
        content = response["message"].get("content") or ""
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            if "requires_tools" not in parsed:
                parsed["requires_tools"] = _heuristic_requires_tools(user_input)
            return parsed
    except Exception:
        pass
    return {
        "requires_tools": _heuristic_requires_tools(user_input),
        "summary": "Plan aproximado (sin respuesta JSON válida).",
        "steps": [],
        "safety_notes": [],
    }


def _update_memory(
    messages: list[dict[str, Any]],
    memory: dict[str, Any],
    opts: dict[str, Any],
) -> dict[str, Any]:
    recent = _extract_recent_for_memory(messages, max_items=10)
    if not recent:
        return memory
    mem_prompt = {
        "role": "system",
        "content": (
            "Actualiza la memoria persistente. Devuelve SOLO JSON válido con las claves: "
            "`memory_summary` (string), `stable_facts` (lista de strings), `preferences` (objeto). "
            "No incluyas markdown ni explicaciones fuera del JSON. "
            "Regla: solo agrega información que sea estable (preferencias) y un resumen corto de lo ocurrido."
        ),
    }
    user_payload = {
        "current_memory_summary": memory.get("memory_summary", ""),
        "recent_turns": recent,
    }
    mem_options = dict(opts)
    mem_options["temperature"] = 0.1
    response = chat(
        model=MODEL,
        messages=[mem_prompt, {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
        options=mem_options or None,
    )
    content = response["message"].get("content") or ""
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("JSON no es objeto")
        memory["memory_summary"] = str(parsed.get("memory_summary") or "").strip()
        memory["stable_facts"] = list(parsed.get("stable_facts") or [])
        new_prefs = parsed.get("preferences") or {}
        if isinstance(new_prefs, dict):
            memory["preferences"] = {**(memory.get("preferences") or {}), **new_prefs}
        else:
            memory["preferences"] = memory.get("preferences") or {}
        memory["last_updated"] = _now_iso()
        return memory
    except Exception:
        return memory


def _normalize_tool_arguments(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _run_tool_loop(
    messages: list,
    available_tools: list,
    tool_map: dict,
    options: dict[str, Any],
) -> str:
    rounds = 0
    reply_content = ""
    hit_round_limit = False
    rollback_tokens_accum: list[str] = []

    # Inyectar refuerzo de tool-use antes del primer round.
    # Los modelos locales necesitan recordatorio explícito en cada llamada.
    _tool_reinforcement = {
        "role": "system",
        "content": (
            "INSTRUCCIÓN CRÍTICA: El usuario ha pedido una acción. "
            "DEBES llamar a la herramienta apropiada AHORA MISMO. "
            "NO expliques cómo se haría. NO escribas texto antes de llamar la tool. "
            "USA la función disponible directamente."
        ),
    }
    # Solo inyectar si el último mensaje es del usuario (no repetir en rounds sucesivos)
    _reinforcement_injected = False

    # Temperatura baja para tool calling — los modelos locales son más precisos con <0.3
    _tool_options = dict(options or {})
    if "temperature" not in _tool_options:
        _tool_options["temperature"] = 0.1

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1
        _msgs_for_call = list(messages)
        if not _reinforcement_injected and _msgs_for_call and _msgs_for_call[-1].get("role") == "user":
            _msgs_for_call = _msgs_for_call[:-1] + [_tool_reinforcement, _msgs_for_call[-1]]
            _reinforcement_injected = True
        with console.status("[bold cyan]Pensando…[/bold cyan]", spinner="dots"):
            response = chat(
                model=MODEL,
                messages=_msgs_for_call,
                tools=available_tools,
                options=_tool_options or None,
            )
        response_message = response["message"]
        messages.append(response_message)

        tool_calls = response_message.get("tool_calls") or []
        if not tool_calls:
            reply_content = response_message.get("content") or ""
            # Si es el primer round y el modelo no llamó ninguna tool pero había tools disponibles,
            # inyectar un retry más directo (solo una vez para no entrar en loop infinito).
            if rounds == 1 and available_tools and reply_content.strip():
                # Detectar si la respuesta es una explicación en lugar de una acción
                _explaining_indicators = [
                    "puedes usar", "podrías usar", "para crear", "para hacer",
                    "el comando", "deberías", "necesitas", "tienes que",
                    "para ello", "primero", "simplemente",
                    "you can", "you could", "to create", "to make",
                ]
                _is_explaining = any(ind in reply_content.lower() for ind in _explaining_indicators)
                if _is_explaining:
                    console.print("[dim yellow]⚠ El modelo explicó en lugar de actuar. Forzando retry con tool...[/dim yellow]")
                    messages.append({
                        "role": "system",
                        "content": (
                            "No expliques cómo hacer la tarea. EJECUTA la acción directamente "
                            "llamando a la herramienta adecuada AHORA. El usuario espera que actúes, no que expliques."
                        ),
                    })
                    # Quitar la respuesta explicativa del historial para no confundir
                    messages.pop(-2)  # quitar response_message
                    continue  # reintentar sin contar este round
            break

        for tool_call in tool_calls:
            fn = tool_call.get("function") or {}
            function_name = fn.get("name") or ""
            arguments = _normalize_tool_arguments(fn.get("arguments"))
            args_preview = json.dumps(arguments, ensure_ascii=False)
            if len(args_preview) > 500:
                args_preview = args_preview[:500] + "…"

            console.print(f"[dim italic]⚙ {function_name}({args_preview})[/dim italic]")

            mutation_tools = {
                "create_file", "edit_file", "search_replace_in_file",
                "create_folder", "append_file", "insert_after",
                "delete_path", "run_command", "copy_path", "move_path",
            }

            tool_risk = {
                "run_command": "high", "delete_path": "high",
                "service_restart": "high", "service_restart_with_deps": "high",
                "service_health_report": "low", "service_wait_active": "medium",
                "move_path": "medium", "copy_path": "medium",
                "edit_file": "medium", "search_replace_in_file": "medium",
                "apply_unified_patch": "high", "install_packages": "high",
                "append_file": "medium", "insert_after": "medium",
                "create_file": "medium", "create_folder": "low",
            }
            need_human_confirm = (
                PREVIEW_CONFIRM_ALWAYS
                or PLAN_MODE == "confirm"
                or tool_risk.get(function_name) == "high"
            )

            try:
                sensitive_prefixes = ["/etc/", "/usr/", "/var/"]
                sensitive_substrings = ["/.ssh", "/.gnupg", "/.kube", "/.local/share", "/.config"]
                path_guess = None
                if function_name == "delete_path":
                    path_guess = arguments.get("path")
                elif function_name in ("edit_file", "search_replace_in_file", "read_file", "append_file", "insert_after", "apply_unified_patch"):
                    path_guess = arguments.get("path") or arguments.get("destination") or arguments.get("workdir")
                elif function_name in ("copy_path", "move_path"):
                    path_guess = arguments.get("to_path") or arguments.get("from_path")
                if path_guess:
                    resolved = resolve_path(str(path_guess), must_exist=True)
                    if not str(resolved).startswith("Error:"):
                        r = str(resolved)
                        if any(r.startswith(p) for p in sensitive_prefixes) or any(s in r for s in sensitive_substrings):
                            need_human_confirm = True
            except Exception:
                pass

            if function_name in ("copy_path", "move_path") and bool(arguments.get("overwrite")):
                need_human_confirm = True
            if function_name in ("apply_unified_patch", "install_packages", "service_restart"):
                if not bool(arguments.get("confirm")) and not bool(arguments.get("allow_dangerous")):
                    need_human_confirm = True
            result = ""

            if PREVIEW_MUTATIONS and function_name in mutation_tools:
                preview = ""
                try:
                    if function_name == "delete_path":
                        p = arguments.get("path") or ""
                        rec = bool(arguments.get("recursive"))
                        preview = f"Destino: {describe_path(p)}"
                        if rec:
                            preview += "\nAlcance (estimado): " + estimate_dir(p, max_entries=1000)
                            if arguments.get("glob_filter"):
                                preview += f"\nFiltro: glob_filter={arguments.get('glob_filter')!r}"
                                try:
                                    m = count_dir_children_matches(p, arguments.get("glob_filter") or "", show_hidden=False)
                                    preview += f"\nCoincidencias inmediatas: {m}"
                                except Exception:
                                    pass
                    elif function_name in ("create_file", "edit_file", "read_file"):
                        preview = "Destino: " + describe_path(arguments.get("path") or "")
                    elif function_name == "create_folder":
                        preview = "Carpeta: " + describe_path(arguments.get("path") or "")
                    elif function_name in ("append_file", "insert_after"):
                        preview = "Destino: " + describe_path(arguments.get("path") or "")
                    elif function_name in ("copy_path", "move_path"):
                        preview = (
                            f"Origen: {describe_path(arguments.get('from_path') or '')}\n"
                            f"Destino: {describe_path(arguments.get('to_path') or '')}"
                        )
                    elif function_name == "run_command":
                        preview = f"Comando: {arguments.get('command') or ''}"
                    elif function_name == "search_replace_in_file":
                        preview = "Archivo: " + describe_path(arguments.get("path") or "")
                except Exception:
                    preview = "(sin previsualización)"

                if preview:
                    console.print(f"[dim]Preflight:[/dim]\n{preview}")

                try:
                    if function_name == "edit_file":
                        p = arguments.get("path") or ""
                        old = read_file(p, max_chars=80000)
                        if isinstance(old, str) and not old.startswith("Error:") and old.strip():
                            new_content = arguments.get("new_content") or ""
                            if str(p).lower().endswith(".json"):
                                try:
                                    old_obj = json.loads(old)
                                    new_obj = json.loads(new_content)
                                    if isinstance(old_obj, dict) and isinstance(new_obj, dict):
                                        old_keys = set(old_obj.keys())
                                        new_keys = set(new_obj.keys())
                                        added = sorted(list(new_keys - old_keys))[:20]
                                        removed = sorted(list(old_keys - new_keys))[:20]
                                        changed = [k for k in list(old_keys & new_keys)[:50] if old_obj.get(k) != new_obj.get(k)]
                                        if added or removed or changed:
                                            console.print(f"[dim]JSON keys diff:[/dim] added={added} removed={removed} changed_head={changed[:20]}")
                                except Exception:
                                    pass
                            diff_lines_iter = difflib.unified_diff(
                                old.splitlines(True), new_content.splitlines(True),
                                fromfile="before", tofile="after", n=3,
                            )
                            diff_lines_list = list(diff_lines_iter)
                            diff_text = "".join(diff_lines_list[:DIFF_MAX_LINES])
                            if diff_text.strip():
                                console.print(f"[dim]Diff (preview):[/dim]\n{diff_text}")
                            changed_lines = [
                                l for l in diff_lines_list
                                if (l.startswith("+") or l.startswith("-"))
                                and not l.startswith("+++") and not l.startswith("---")
                            ]
                            if len(changed_lines) > 60 or len(diff_lines_list) > 200:
                                if need_human_confirm and not DRY_RUN and not result:
                                    ans = Prompt.ask("Este `edit_file` parece un cambio grande. ¿Confirmas? (s/N)", default="N").strip().lower()
                                    if ans not in ("s", "si", "sí", "y", "yes"):
                                        result = "Acción cancelada por el usuario."
                            elif len(changed_lines) <= 10 and not DRY_RUN:
                                console.print("[dim]Sugerencia: para cambios pequeños, intenta `search_replace_in_file`/`insert_after` en vez de `edit_file` completo.[/dim]")

                    elif function_name == "search_replace_in_file":
                        p = arguments.get("path") or ""
                        old = read_file(p, max_chars=80000)
                        if isinstance(old, str) and not old.startswith("Error:"):
                            old_text = arguments.get("old_text") or ""
                            new_text = arguments.get("new_text") or ""
                            replace_all = bool(arguments.get("replace_all"))
                            if old_text in old:
                                predicted = old.replace(old_text, new_text) if replace_all else old.replace(old_text, new_text, 1)
                                diff_lines = difflib.unified_diff(
                                    old.splitlines(True), predicted.splitlines(True),
                                    fromfile="before", tofile="after", n=3,
                                )
                                diff_text = "".join(list(diff_lines)[:DIFF_MAX_LINES])
                                if diff_text.strip():
                                    console.print(f"[dim]Diff (preview):[/dim]\n{diff_text}")
                except Exception:
                    pass

            if function_name == "delete_path" and bool(arguments.get("recursive")) and not arguments.get("confirm"):
                if need_human_confirm and not DRY_RUN:
                    p = arguments.get("path") or ""
                    console.print(f"[bold yellow]Confirmación requerida:[/bold yellow] borrado recursivo de {p}")
                    console.print("Alcance (estimado): " + estimate_dir(p, max_entries=1000))
                    ans = Prompt.ask("¿Confirmas? (s/N)", default="N").strip().lower()
                    if ans in ("s", "si", "sí", "y", "yes"):
                        arguments["confirm"] = True
                    else:
                        result = "Acción cancelada por el usuario."
                if DRY_RUN:
                    result = "DRY_RUN: cancelado por preflight (confirm=false)."

            if function_name == "run_command" and bool(arguments.get("allow_dangerous")) and not result:
                if need_human_confirm and not DRY_RUN:
                    cmd = arguments.get("command") or ""
                    ans = Prompt.ask(f"Ejecutar comando peligroso?\n{cmd}\n(s/N)", default="N").strip().lower()
                    if ans not in ("s", "si", "sí", "y", "yes"):
                        result = "Acción cancelada por el usuario."

            if not result and DRY_RUN and function_name in mutation_tools:
                result = "DRY_RUN: acción no ejecutada (previsualización mostrada)."

            if not result:
                if function_name in tool_map:
                    func = tool_map[function_name]
                    try:
                        result = func(**arguments)
                    except TypeError as e:
                        result = f"Error de argumentos para {function_name}: {e}"
                    except Exception as e:
                        result = f"Error: {e}"
                else:
                    result = f"Herramienta desconocida: {function_name}"

            if (
                function_name == "resolve_path"
                and isinstance(result, str)
                and "CANDIDATES_JSON=" in result
                and not DRY_RUN
            ):
                try:
                    m = re.search(r"CANDIDATES_JSON=([\s\S]*?)\.\s*Repite", result)
                    if not m:
                        m = re.search(r"CANDIDATES_JSON=([\s\S]*)", result)
                    if m:
                        candidates = json.loads(m.group(1).strip())
                        if isinstance(candidates, list) and candidates:
                            console.print("[bold yellow]Resolución de ruta ambigua:[/bold yellow]")
                            for i, c in enumerate(candidates[:10]):
                                console.print(f"{i+1}. {c.get('name')} (score={c.get('score')}) -> {c.get('path')}")
                            auto_pref = os.environ.get("JARVIS_AUTO_RESOLVE_AMBIGUOUS", "").strip().lower()
                            chosen_path = None
                            if auto_pref in ("", "none", "off"):
                                ans = Prompt.ask("Elige número", default="1").strip()
                                idx = int(ans) - 1
                                if 0 <= idx < len(candidates):
                                    chosen_path = candidates[idx].get("path")
                            elif auto_pref in ("first", "0"):
                                chosen_path = candidates[0].get("path")
                            elif auto_pref in ("best", "best_score", "mejor", "mejor_score"):
                                chosen_path = candidates[0].get("path")
                            elif auto_pref in ("mtime_recent", "mtime_newest", "reciente", "nuevo"):
                                best_ts = -1.0
                                for c in candidates:
                                    cp = c.get("path")
                                    if not cp:
                                        continue
                                    try:
                                        ts = os.path.getmtime(str(cp))
                                    except Exception:
                                        ts = -1.0
                                    if ts > best_ts:
                                        best_ts = ts
                                        chosen_path = cp
                            else:
                                ans = Prompt.ask("Elige número", default="1").strip()
                                idx = int(ans) - 1
                                if 0 <= idx < len(candidates):
                                    chosen_path = candidates[idx].get("path")
                            if chosen_path:
                                result = str(chosen_path)
                except Exception:
                    pass

            if result and not str(result).startswith("Error"):
                m = re.search(r"ROLLBACK_TOKEN=([a-fA-F0-9]+)", str(result))
                if m:
                    rollback_tokens_accum.append(m.group(1))
                m2 = re.search(r"ROLLBACK_TOKENS=([a-zA-Z0-9,-]+)", str(result))
                if m2:
                    toks = [x.strip() for x in m2.group(1).split(",") if x.strip()]
                    rollback_tokens_accum.extend(toks)

            if result and str(result).startswith("Error") and rollback_tokens_accum and not DRY_RUN:
                try:
                    rb_func = tool_map.get("rollback_tokens")
                    if rb_func:
                        tokens_str = ",".join(reversed(rollback_tokens_accum))
                        rb_res = rb_func(tokens=tokens_str, overwrite=True)
                        messages.append({"role": "tool", "name": "rollback_tokens", "content": str(rb_res)})
                    return "Ocurrió un error durante la ejecución de herramientas. Se intentó un rollback automático del último estado."
                except Exception:
                    return "Ocurrió un error durante la ejecución de herramientas (rollback automático falló)."

            rpreview = str(result)
            if len(rpreview) > 1200:
                rpreview = rpreview[:1200] + "…"
            console.print(f"[dim green]→ {rpreview}[/dim green]")

            tool_content = str(result)
            if len(tool_content) > 16000:
                tool_content = tool_content[:16000] + "\n[...Truncado por seguridad de memoria...]"

            tool_msg: dict[str, Any] = {"role": "tool", "content": tool_content}
            if function_name:
                tool_msg["name"] = function_name
            messages.append(tool_msg)

            if (
                str(result).startswith("Error")
                and os.environ.get("JARVIS_TOOL_ERROR_HINT", "true").strip().lower()
                in ("1", "true", "yes", "si", "sí", "on")
            ):
                messages.append({
                    "role": "system",
                    "content": (
                        f"La tool `{function_name}` falló con este error: {str(result)[:800]}. "
                        "Analiza el error, corrige los argumentos y vuelve a llamar la tool "
                        "con los parámetros correctos. No expliques el error al usuario todavía."
                    ),
                })

        if rounds >= MAX_TOOL_ROUNDS:
            hit_round_limit = True
            break

    if hit_round_limit and not reply_content.strip():
        messages.append({
            "role": "user",
            "content": "Resume en español qué hiciste y qué falta; no llames más herramientas en esta respuesta.",
        })
        with console.status("[bold cyan]Síntesis…[/bold cyan]", spinner="dots"):
            final = chat(model=MODEL, messages=messages, options=options or None)
        final_msg = final["message"]
        messages.append(final_msg)
        reply_content = final_msg.get("content") or ""

    if hit_round_limit and not reply_content.strip():
        reply_content = (
            "Se alcanzó el límite de rondas de herramientas (JARVIS_MAX_TOOL_ROUNDS). "
            "Repite la petición o aumenta el límite."
        )

    return reply_content


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
        r"^hola",
        r"^(qu[eé] eres|qui[eé]n eres)",
        r"^(qu[eé] puedes hacer|qu[eé] sabes hacer)",
        r"^(buenos? d[ií]as?|buenas? tardes?|buenas? noches?)",
        r"^(c[oó]mo est[aá]s|qu[eé] tal)\??$",
        r"^(gracias|de nada|ok|vale|perfecto|entendido)[\.\!]?$",
        r"^(ayuda|help)$",
    ]
    return any(re.search(p, s) for p in simple_patterns)


def _run_simple_chat_streaming(messages: list, options: dict) -> str:
    """Versión con streaming para respuestas visibles inmediatamente."""
    full_response = ""
    console.print("\n[bold purple]Asistente:[/bold purple] ", end="")
    try:
        stream = chat(model=MODEL, messages=messages, options=options or None, stream=True)
        for chunk in stream:
            token = chunk.get("message", {}).get("content") or ""
            console.print(token, end="")
            full_response += token
        console.print()
    except Exception as e:
        console.print(f"\n[red]Error de stream: {e}[/red]")
    return full_response


def main():
    opts = _chat_options()
    log_path = os.path.abspath(DEFAULT_LOG_PATH)

    # --- Brain (Obsidian vault) ---
    brain = JarvisBrain()
    brain.initialize()

    # Mensajes base: solo system prompt
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Usar registry centralizado para todas las tools (Bug 7 fix)
    available_tools = get_all_tools()
    tool_map = {f.__name__: f for f in available_tools}
    tool_groups = _build_tool_groups(available_tools)
    _turn_counter = 0

    # Limpieza de backups antiguos al arrancar
    _cleanup_old_backups(max_age_days=BACKUP_MAX_AGE_DAYS)

    console.print(
        Panel.fit(
            f"[bold blue]J.A.R.V.I.S.[/bold blue] — asistente local (modelo [cyan]{MODEL}[/cyan])\n"
            "Escribe salir / exit / quit para terminar.\n"
            "Comandos: `ver memoria`, `reset memoria`, `workspace show`, `set workspace <ruta>`.\n"
            f"[dim]Opciones: OLLAMA_MODEL, OLLAMA_NUM_CTX, OLLAMA_TEMPERATURE, JARVIS_MAX_TOOL_ROUNDS, "
            f"JARVIS_MAX_CONTEXT_MESSAGES, JARVIS_BACKUP_MAX_AGE_DAYS[/dim]",
            border_style="blue",
        )
    )

    import sys
    if "--server" in sys.argv:
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class JarvisAPI(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path == '/api/chat':
                    length = int(self.headers.get('Content-Length', '0'))
                    post_data = self.rfile.read(length)
                    data = json.loads(post_data.decode('utf-8'))
                    prompt = data.get('prompt', '')
                    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + [{"role": "user", "content": prompt}]
                    active = _select_tools(prompt, available_tools, tool_groups)
                    reply = _run_tool_loop(msgs, active, tool_map, opts)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(json.dumps({"response": reply}, ensure_ascii=False).encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()
        server_address = ('', 8080)
        httpd = HTTPServer(server_address, JarvisAPI)
        console.print("[bold green]Starting daemon server on port 8080...[/bold green]")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        return


    if "--run-prompt" in sys.argv:
        idx = sys.argv.index("--run-prompt")
        if idx + 1 < len(sys.argv):
            prompt = sys.argv[idx + 1]
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + [{"role": "user", "content": prompt}]
            active = _select_tools(prompt, available_tools, tool_groups)
            reply = _run_tool_loop(msgs, active, tool_map, opts)
            console.print(Markdown(reply))
        return

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]Tú[/bold green]")
            if user_input.lower() in ("salir", "exit", "quit"):
                console.print("[bold yellow]¡Hasta luego![/bold yellow]")
                break

            if not user_input.strip():
                continue

            low = user_input.lower().strip()

            if low in ("reset memoria", "olvidar memoria", "borrar memoria"):
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                console.print("[dim]Memoria de contexto reiniciada.[/dim]")
                continue

            if low == "ver memoria":
                console.print("\n[bold purple]Estado del vault:[/bold purple]")
                console.print(brain.vault_status())
                continue

            if low in ("undo last", "undo último", "undo ultimo"):
                try:
                    state = _load_undo_redo_state()
                    if not state.get("undo"):
                        console.print("[dim]Nada para deshacer.[/dim]")
                        continue
                    entry = state["undo"].pop()
                    state.setdefault("redo", []).append(entry)
                    _save_undo_redo_state(state)
                    tokens = entry.get("rollback_tokens") or []
                    tokens_str = ",".join(tokens)
                    if not tokens_str:
                        console.print("[dim]El último undo no tiene tokens de rollback guardados.[/dim]")
                        continue
                    if DRY_RUN:
                        console.print("[dim]DRY_RUN activo; no ejecuto undo.[/dim]")
                        continue
                    rb_res = rollback_tokens(tokens_str, overwrite=True)
                    console.print(f"\n[bold purple]Undo:[/bold purple] {rb_res}")
                except Exception as e:
                    console.print(f"[bold red]Error en undo:[/bold red] {e}")
                continue

            if low in ("redo last", "redo último", "redo ultimo"):
                try:
                    state = _load_undo_redo_state()
                    if not state.get("redo"):
                        console.print("[dim]Nada para rehacer.[/dim]")
                        continue
                    # El redo es complejo porque el rollback es destructivo si no se tiene backup del rollback.
                    # Por ahora lo dejamos como placeholder informativo.
                    console.print("[dim]Redo no implementado completamente (requiere backup de rollbacks).[/dim]")
                except Exception:
                    pass
                continue

            if low in ("history", "historial"):
                try:
                    if not os.path.isfile(log_path):
                        console.print("[dim]No hay logs.[/dim]")
                        continue
                    lines = []
                    with open(log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            lines.append(line)
                    for line in lines[-10:]:
                        obj = json.loads(line)
                        ts = obj.get("ts")
                        user = obj.get("user")
                        tool_names = [tc.get("name") for tc in (obj.get("tool_calls") or [])]
                        active_count = obj.get("active_tools_count", "?")
                        console.print(f"- {ts} | {user} | tools={tool_names} | activas={active_count}")
                except Exception as e:
                    console.print(f"[bold red]Error en history:[/bold red] {e}")
                continue

            if low.startswith("history search "):
                term = user_input[len("history search "):].strip()
                if not term:
                    console.print("[dim]Uso: history search <texto>[/dim]")
                    continue
                try:
                    if not os.path.isfile(log_path):
                        console.print("[dim]No hay logs.[/dim]")
                        continue
                    matches = 0
                    with open(log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if term.lower() in line.lower():
                                matches += 1
                                if matches <= 10:
                                    obj = json.loads(line)
                                    console.print(f"- {obj.get('ts')} | {obj.get('user')} | tools={[tc.get('name') for tc in (obj.get('tool_calls') or [])]}")
                    if matches == 0:
                        console.print("[dim]Sin coincidencias.[/dim]")
                except Exception as e:
                    console.print(f"[bold red]Error en history search:[/bold red] {e}")
                continue

            if low in ("capabilities", "cap", "capacidades"):
                console.print("[bold purple]Capabilities:[/bold purple]")
                console.print(f"- JARVIS_DRY_RUN={DRY_RUN}")
                console.print(f"- JARVIS_PLAN_MODE={PLAN_MODE}")
                console.print(f"- JARVIS_READ_ONLY={os.environ.get('JARVIS_READ_ONLY', 'false')}")
                console.print(f"- JARVIS_USE_TRASH={os.environ.get('JARVIS_USE_TRASH', 'true')}")
                console.print(f"- Tools disponibles={len(available_tools)}")
                continue

            if low in ("workspace show", "workspace", "ver workspace"):
                console.print(f"[bold purple]Workspace:[/bold purple] cwd={os.getcwd()}")
                continue

            if low.startswith("set workspace "):
                raw = user_input[len("set workspace "):].strip()
                resolved_ws = resolve_path(raw, must_exist=True)
                if str(resolved_ws).startswith("Error:"):
                    console.print(f"[bold red]Error:[/bold red] {resolved_ws}")
                    continue
                os.chdir(resolved_ws)
                console.print(f"[dim]Workspace fijado: {resolved_ws}[/dim]")
                continue

            if low in ("reset workspace", "clear workspace", "unset workspace"):
                os.chdir(str(Path.home()))
                console.print("[dim]Workspace eliminado. Vuelves a tu home.[/dim]")
                continue

            if low in ("rollback last", "undo last", "deshacer last", "rollback último", "undo último"):
                try:
                    if not os.path.isfile(log_path):
                        console.print("[dim]No hay logs para rollback todavía.[/dim]")
                        continue
                    last_token = None
                    with open(log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue
                            for tc in (obj.get("tool_calls") or []):
                                rp = tc.get("result_preview") or ""
                                if "ROLLBACK_TOKEN=" in rp:
                                    m = re.search(r"ROLLBACK_TOKEN=([a-fA-F0-9]+)", rp)
                                    if m:
                                        last_token = m.group(1)
                                if "ROLLBACK_TOKENS=" in rp:
                                    m2 = re.search(r"ROLLBACK_TOKENS=([a-zA-Z0-9,-]+)", rp)
                                    if m2:
                                        parts = [x for x in m2.group(1).split(",") if x.strip()]
                                        if parts:
                                            last_token = parts[-1]
                    if not last_token:
                        console.print("[dim]No encontré tokens de rollback en el último log.[/dim]")
                        continue
                    ans_overwrite = Prompt.ask("Si el destino existe, ¿lo sobreescribo? (s/N)", default="N").strip().lower()
                    overwrite = ans_overwrite in ("s", "si", "sí", "y", "yes")
                    res = rollback(last_token, overwrite=overwrite)
                    console.print(f"\n[bold purple]Rollback:[/bold purple] {res}")
                    continue
                except Exception as e:
                    console.print(f"[bold red]Error en rollback:[/bold red] {e}")
                    continue

            if low.startswith("rollback "):
                token = low.split(" ", 1)[1].strip()
                if token:
                    ans_overwrite = Prompt.ask("¿Sobreescribir si existe? (s/N)", default="N").strip().lower()
                    overwrite = ans_overwrite in ("s", "si", "sí", "y", "yes")
                    res = rollback(token, overwrite=overwrite)
                    console.print(f"\n[bold purple]Rollback:[/bold purple] {res}")
                continue

            if low in ("replay ultimo", "replay last", "replay último", "replay"):
                last_line = None
                try:
                    if os.path.isfile(log_path):
                        with open(log_path, "r", encoding="utf-8") as f:
                            for line in f:
                                last_line = line
                    if not last_line:
                        console.print("[dim]No hay logs para reproducir todavía.[/dim]")
                        continue
                    last_log = json.loads(last_line)
                    tool_calls = last_log.get("tool_calls") or []
                    if not tool_calls:
                        console.print("[dim]El último log no tiene tool_calls.[/dim]")
                        continue
                    console.print(f"\n[bold]Replaying último (tool_calls={len(tool_calls)})[/bold]")
                    if DRY_RUN:
                        console.print("[dim]DRY_RUN está activo; no ejecuto durante replay.[/dim]")
                        for tc in tool_calls:
                            console.print(f"- {tc.get('name')}: {tc.get('arguments')}")
                        continue
                    ans = Prompt.ask("¿Ejecutar exactamente esas herramientas? (s/N)", default="N").strip().lower()
                    if ans not in ("s", "si", "sí", "y", "yes"):
                        console.print("[dim]Replay cancelado.[/dim]")
                        continue
                    for tc in tool_calls:
                        name = tc.get("name") or ""
                        args = tc.get("arguments") or {}
                        if name and name in tool_map:
                            if name == "delete_path" and bool(args.get("recursive")) and not args.get("confirm"):
                                args["confirm"] = True
                            func = tool_map[name]
                            res = func(**args)
                            console.print(f"[dim green]✓ {name}[/dim green] {res[:300]}")
                        else:
                            console.print(f"[dim red]Herramienta desconocida en log:[/dim red] {name}")
                    continue
                except Exception as e:
                    console.print(f"[bold red]Error en replay:[/bold red] {e}")
                    continue

            # ----------------------------------------------------------------
            # Turno principal
            # ----------------------------------------------------------------
            plan_info: dict[str, Any] | None = None
            if PLAN_MODE in ("auto", "confirm"):
                plan_info = _plan_turn(user_input, messages, opts)
                if plan_info.get("requires_tools"):
                    console.print("\n[bold]Plan:[/bold]")
                    if plan_info.get("summary"):
                        console.print(Markdown(str(plan_info.get("summary"))))
                    for step in plan_info.get("steps") or []:
                        console.print(f"- {step}")
                    for note in plan_info.get("safety_notes") or []:
                        console.print(f"[dim]Seguridad: {note}[/dim]")
                    if PLAN_MODE == "confirm":
                        ans = Prompt.ask("¿Ejecutar ahora? (s/N)", default="N").strip().lower()
                        if ans not in ("s", "si", "sí", "y", "yes"):
                            console.print("[dim]Ejecución cancelada. Te dejo el plan listo.[/dim]")
                            continue

            if plan_info and plan_info.get("requires_tools"):
                steps = plan_info.get("steps") or []
                summary = plan_info.get("summary") or ""
                steps_text = "\n".join([f"{i+1}. {s}" for i, s in enumerate(steps[:8])]) if steps else "(sin pasos explícitos)"
                messages.append({
                    "role": "system",
                    "content": "Eres el worker. Sigue el plan descrito para cumplir la tarea. "
                    f"Resumen del plan: {summary}\nPasos:\n{steps_text}\n"
                    "Usa herramientas solo para ejecutar acciones del plan y detente cuando el plan esté completo; "
                    "si falta algo del plan, pide aclaración.",
                })

            turn_start_idx = len(messages)

            # Inyectar contexto del vault de JARVIS (brain)
            vault_context = brain.before_turn(user_input)
            if vault_context:
                messages.append({"role": "system", "content": vault_context})

            messages.append({"role": "user", "content": user_input})

            # Selección dinámica de herramientas
            active_tools = _select_tools(user_input, available_tools, tool_groups)
            console.print(f"[dim]Tools activas: {len(active_tools)}/{len(available_tools)}[/dim]")

            if _is_simple_conversational(user_input) and PLAN_MODE == "off":
                reply_content = _run_simple_chat_streaming(messages, opts)
                messages.append({"role": "assistant", "content": reply_content})
                turn_tool_ms = 0
            else:
                turn_tool_start = datetime.now().timestamp()
                reply_content = _run_tool_loop(messages, active_tools, tool_map, opts)
                turn_tool_ms = int((datetime.now().timestamp() - turn_tool_start) * 1000)
                if reply_content.strip():
                    console.print("\n[bold purple]Asistente:[/bold purple]")
                    console.print(Markdown(reply_content))

            # Log
            tool_calls_log: list = []
            try:
                tool_calls_extracted: list[dict[str, Any]] = []
                tool_results: list[str] = []
                for m in messages[turn_start_idx:]:
                    if m.get("role") == "assistant" and m.get("tool_calls"):
                        for tc in m.get("tool_calls") or []:
                            fn = (tc.get("function") or {})
                            name = fn.get("name") or ""
                            args = _normalize_tool_arguments(fn.get("arguments"))
                            if name:
                                tool_calls_extracted.append({"name": name, "arguments": args})
                    if m.get("role") == "tool":
                        tool_results.append(m.get("content") or "")

                tool_calls_log = []
                for i, tc in enumerate(tool_calls_extracted):
                    res_preview = tool_results[i][:800] if i < len(tool_results) else ""
                    tool_calls_log.append({"name": tc["name"], "arguments": tc["arguments"], "result_preview": res_preview})

                log_obj = {
                    "ts": _now_iso(),
                    "user": user_input,
                    "plan_mode": PLAN_MODE,
                    "plan": plan_info,
                    "tool_calls": tool_calls_log,
                    "tool_call_count": len(tool_calls_log),
                    "active_tools_count": len(active_tools),
                    "tool_loop_ms": turn_tool_ms,
                    "assistant_preview": reply_content[:1200],
                }
                os.makedirs(os.path.dirname(DEFAULT_LOG_PATH), exist_ok=True)
                with open(DEFAULT_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_obj, ensure_ascii=False) + "\n")

                try:
                    tokens_found: list[str] = []
                    for tr in tool_results:
                        if not isinstance(tr, str):
                            continue
                        mt = re.findall(r"ROLLBACK_TOKEN=([a-fA-F0-9]+)", tr)
                        tokens_found.extend(mt)
                        mt2 = re.findall(r"ROLLBACK_TOKENS=([a-zA-Z0-9,-]+)", tr)
                        for group in mt2:
                            tokens_found.extend([x for x in group.split(",") if x.strip()])
                    tokens_found = [t for t in tokens_found if t]
                    if tokens_found and tool_calls_log:
                        state = _load_undo_redo_state()
                        state.setdefault("undo", []).append({
                            "ts": log_obj.get("ts"),
                            "tool_calls": tool_calls_log,
                            "rollback_tokens": list(dict.fromkeys(tokens_found))[-50:],
                        })
                        state["redo"] = []
                        _save_undo_redo_state(state)
                except Exception:
                    pass
            except Exception:
                pass

            messages = _prune_messages(messages, keep_last=MAX_CONTEXT_MESSAGES)

            # Brain: registrar turno y aprender
            _turn_counter += 1
            brain.after_turn(user_input, reply_content, tool_calls_log)

        except KeyboardInterrupt:
            console.print("\n[bold yellow]Cancelado. Saliendo…[/bold yellow]")
            brain.shutdown("Sesión terminada por el usuario (Ctrl+C)")
            break
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}")
            messages.append({"role": "system", "content": f"Error previo (no repetir): {e}"})

    # Shutdown limpio del brain
    try:
        brain.shutdown("Sesión finalizada normalmente")
    except Exception:
        pass


if __name__ == "__main__":
    main()
