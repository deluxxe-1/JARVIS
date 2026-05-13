from __future__ import annotations
import difflib
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from rich.console import Console
from rich.prompt import Prompt
from ollama import chat

from aaris.logging import configure_logging
from aaris.tool_selector import _build_tool_groups, _select_tools
from aaris.prompts import get_system_prompt


def refresh_system_prompt() -> str:
    """Recalcula el system prompt (rutas por defecto, etc.). Útil al arrancar la GUI tras cambiar env."""
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = get_system_prompt()
    return SYSTEM_PROMPT


SYSTEM_PROMPT = refresh_system_prompt()


def _redact_tool_arguments_for_log(arguments: dict[str, Any]) -> dict[str, Any]:
    """Acorta contenidos largos y oculta claves que suelen llevar secretos (solo para consola)."""
    sens = ("token", "password", "secret", "apikey", "api_key", "authorization", "credential", "bearer")
    out: dict[str, Any] = {}
    for k, v in arguments.items():
        lk = str(k).lower()
        if any(s in lk for s in sens):
            out[k] = "***"
        elif lk == "content" and isinstance(v, str) and len(v) > 200:
            out[k] = v[:120] + f"… ({len(v)} caracteres)"
        elif isinstance(v, dict):
            inner: dict[str, Any] = {}
            for k2, v2 in v.items():
                lk2 = str(k2).lower()
                if any(s in lk2 for s in sens):
                    inner[k2] = "***"
                else:
                    inner[k2] = v2
            out[k] = inner
        else:
            out[k] = v
    return out


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _get_tool_helpers():
    """Importa funciones de herramientas de filesystem usadas para previews."""
    try:
        from aaris.tools.filesystem import (
            resolve_path, describe_path, read_file,
            estimate_dir, count_dir_children_matches,
        )
        return resolve_path, describe_path, read_file, estimate_dir, count_dir_children_matches
    except ImportError:
        return None, None, None, None, None


# Importar helpers — disponibles como funciones de módulo
resolve_path, describe_path, read_file, estimate_dir, count_dir_children_matches = _get_tool_helpers()


console = Console()
MAX_CONTEXT_MESSAGES = 10
MODEL = os.environ.get("AARIS_MODEL", "qwen2.5:14b")
MAX_TOOL_ROUNDS = int(os.environ.get("AARIS_MAX_TOOL_ROUNDS", "12"))
PLAN_MODE = os.environ.get("AARIS_PLAN_MODE", "off")  # off | auto | confirm
DRY_RUN = os.environ.get("AARIS_DRY_RUN", "false").strip().lower() in ("1", "true", "yes", "si", "sí", "on")
PREVIEW_MUTATIONS = os.environ.get("AARIS_PREVIEW_MUTATIONS", "true").strip().lower() in ("1", "true", "yes", "si", "sí", "on")
PREVIEW_CONFIRM_ALWAYS = os.environ.get("AARIS_PREVIEW_CONFIRM_ALWAYS", "false").strip().lower() in (
    "1", "true", "yes", "si", "sí", "on",
)
DIFF_MAX_LINES = int(os.environ.get("AARIS_DIFF_MAX_LINES", "300"))


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


def _garbled_model_reply(text: str) -> bool:
    """Detecta salidas corruptas del modelo (p. ej. spam 'sourceMapping') sin tool calls."""
    t = (text or "").strip()
    if len(t) < 120:
        return False
    low = t.lower()
    if low.count("sourcemapping") >= 6:
        return True
    words = t.split()
    if len(words) > 60:
        uniq = len(set(w.strip() for w in words if w.strip()))
        if uniq <= 3:
            return True
    return False


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
            "INSTRUCCIÓN CRÍTICA (español): El usuario pidió acciones concretas. "
            "Invoca YA las herramientas nativas (tool calls): sin pedir JSON al usuario, sin preguntar qué función usar, sin texto en inglés. "
            "NO escribas explicaciones antes. Orden típico si aplica: resolve_path → create_folder; código sin ruta del usuario → subcarpeta bajo Documentos/Proyectos/<slug>; scripts triviales (p. ej. calculadora) → **solo** `create_file`, sin scaffold ni API; **en Windows no uses `nano`/`vim` en run_command** para editar — usa `create_file`/`edit_file`; web_search_full(query=...); create_file para HTML. "
            "Varias tareas en un mensaje = varias llamadas a tools en secuencia. Prohibido run_command de prueba salvo petición explícita."
        ),
    }
    # Solo inyectar si el último mensaje es del usuario (no repetir en rounds sucesivos)
    _reinforcement_injected = False
    # Reintentos si el modelo responde con meta-texto en vez de invocar tools
    _bogus_tool_reply_retries = 0
    _max_bogus_retries = 2

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
        content = response_message.get("content") or ""
        
        # --- Detectar si el contenido es basura (scripts, _icall, código) ---
        _is_garbage = False
        if content.strip():
            lc_content = content.lower()
            garbage_indicators = [
                "_icall", "eval \"$response\"", "#!/bin", "local response",
                "echo '{", "jq -r", "${AARIS_", "${JARVIS_",
                "function()", "if [", "fi\n", "esac",
            ]
            if any(g in lc_content for g in garbage_indicators):
                _is_garbage = True
            # Código con muchas llaves/corchetes = probablemente script, no respuesta
            if content.count("{") > 3 and content.count("}") > 3 and len(content) > 200:
                if "name" in lc_content and "arguments" in lc_content:
                    _is_garbage = True
        
        # Solo guardar contenido si NO es basura
        if content.strip() and not _is_garbage:
            reply_content = content
        
        # --- Fallback: Detectar herramientas que el modelo intenta llamar como texto ---
        if not tool_calls and content.strip():
            # Buscar CUALQUIER nombre de herramienta conocida en el texto
            _detected_tool = None
            _detected_args = {}
            
            # Mapa de patrones → herramienta real + argumentos por defecto
            _tool_patterns = {
                "get_news": "get_news",
                "web_search_full": "web_search_full",
                "web_search": "web_search",
                "semantic_search": "web_search_full",  # redirigir
                "get_latest_world_news": "get_news",   # no existe, redirigir
                "wikipedia_search": "wikipedia_search",
                "get_weather": "get_weather",
                "get_crypto_price": "get_crypto_price",
                "create_file": "create_file",
            }
            
            for pattern, real_tool in _tool_patterns.items():
                if pattern in content and real_tool in tool_map:
                    _detected_tool = real_tool
                    # Intentar extraer query/argumentos del texto
                    arg_match = re.search(r'["\'](.*?)["\']', content)
                    if arg_match:
                        _detected_args = {"query": arg_match.group(1)}
                    break
            
            # Si detectamos una herramienta, buscar la query original del usuario
            if _detected_tool and not _detected_args.get("query"):
                for m in reversed(messages):
                    if m.get("role") == "user":
                        user_q = m.get("content", "").strip()
                        if user_q and not user_q.startswith("INSTRUCCIÓN") and not user_q.startswith("PARA.") and not user_q.startswith("Has ejecutado"):
                            _detected_args = {"query": user_q}
                            break
            
            if _detected_tool:
                tool_calls = [{"function": {"name": _detected_tool, "arguments": _detected_args}}]
                reply_content = ""  # Limpiar la basura
                console.print(f"[dim yellow]⚠ Fallback: modelo escribió texto, ejecutando {_detected_tool}({_detected_args})[/dim yellow]")

        if not tool_calls:
            reply_content = response_message.get("content") or ""
            # Modelo respondió en texto en vez de invocar tools: reintentar con instrucción dura.
            if available_tools and reply_content.strip() and _bogus_tool_reply_retries < _max_bogus_retries:
                lc = reply_content.lower()
                _explaining_indicators = [
                    "puedes usar", "podrías usar", "para crear", "para hacer",
                    "el comando", "deberías", "necesitas", "tienes que",
                    "para ello", "primero", "simplemente",
                    "you can", "you could", "to create", "to make",
                ]
                _meta_tool_refusal = any(
                    p in lc
                    for p in (
                        "could you please",
                        "could you",
                        "which tool",
                        "what tool",
                        "specify which",
                        "function you would",
                        "function call",
                        "json object",
                        "json for",
                        "necessary parameters",
                        "let me know",
                        "provide you with",
                        "along with any",
                        "format it accordingly",
                        "tell me which",
                    )
                )
                _is_explaining = any(ind in lc for ind in _explaining_indicators)
                _garbled = _garbled_model_reply(reply_content)
                if _is_explaining or _meta_tool_refusal or _garbled:
                    _bogus_tool_reply_retries += 1
                    reason = "salida basura/repetitiva" if _garbled else "explicación o pedido de JSON/tools"
                    console.print(
                        f"[dim yellow]⚠ El modelo no invocó herramientas ({reason}). "
                        "Reintento forzado…[/dim yellow]"
                    )
                    extra = ""
                    if _garbled:
                        extra = (
                            " No escribas 'sourceMapping' ni basura repetida. "
                            "Si debes entregar una web, usa create_file con HTML válido (español), no pegues mapas de fuentes."
                        )
                    messages.append({
                        "role": "system",
                        "content": (
                            "PARA. No pidas al usuario que elija herramienta ni que escriba JSON. "
                            "No respondas en inglés. Usa SOLO las funciones disponibles (tool calls nativos): "
                            "por ejemplo resolve_path → create_folder, web_search_full(query=...), "
                            "create_file(path=..., content=...) para HTML. "
                            "Llama ya a la primera herramienta necesaria sin texto previo."
                            + extra
                        ),
                    })
                    messages.pop(-2)  # quitar response_message vacía de tool_calls
                    continue
            break

        for tool_call in tool_calls:
            fn = tool_call.get("function") or {}
            function_name = fn.get("name") or ""
            arguments = _normalize_tool_arguments(fn.get("arguments"))
            safe_args = _redact_tool_arguments_for_log(arguments)
            args_preview = json.dumps(safe_args, ensure_ascii=False)
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
                            auto_pref = os.environ.get("AARIS_AUTO_RESOLVE_AMBIGUOUS", "").strip().lower()
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
                and os.environ.get("AARIS_TOOL_ERROR_HINT", "true").strip().lower()
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

    # ── Síntesis final si no hay respuesta tras ejecutar herramientas ──
    # Recopilar nombres de tools ejecutadas y sus resultados para contexto
    executed_tools: list[str] = []
    last_tool_result = ""
    for m in messages:
        if m.get("role") == "tool":
            executed_tools.append(m.get("name", "tool"))
            last_tool_result = m.get("content", "")
    
    tools_were_used = len(executed_tools) > 0
    
    if tools_were_used and not reply_content.strip():
        # Intentar que el modelo genere un resumen
        tool_names_str = ", ".join(executed_tools[-5:])
        messages.append({
            "role": "user",
            "content": (
                f"Has ejecutado las herramientas: {tool_names_str}. "
                "Ahora responde al usuario en español explicando qué hiciste y el resultado. "
                "NO respondas con texto vacío. Sé conciso y directo."
            ),
        })
        with console.status("[bold cyan]Generando resumen final...[/bold cyan]", spinner="dots"):
            try:
                final = chat(model=MODEL, messages=messages, options=options or None)
                reply_content = final["message"].get("content") or ""
            except Exception as e:
                console.print(f"[red]Error en síntesis final: {e}[/red]")
        
        # SI SIGUE VACÍO: Fallback de emergencia — mostrar resultado crudo de la última tool
        if not reply_content.strip() and last_tool_result:
            console.print("[red]⚠ El modelo no generó resumen. Mostrando resultado directo.[/red]")
            try:
                data = json.loads(last_tool_result)
                if isinstance(data, dict):
                    if "results" in data:
                        # Resultados de búsqueda
                        lines = []
                        for r in data["results"][:5]:
                            lines.append(f"• **{r.get('title', '')}**: {r.get('snippet', '')}")
                        reply_content = f"Resultados encontrados:\n\n" + "\n".join(lines)
                    else:
                        # Otro tipo de resultado (create_file, etc.)
                        reply_content = f"Herramienta ejecutada correctamente:\n\n{json.dumps(data, indent=2, ensure_ascii=False)[:1500]}"
                else:
                    reply_content = f"Resultado:\n\n{last_tool_result[:1500]}"
            except (json.JSONDecodeError, ValueError):
                # No es JSON, mostrar como texto
                reply_content = f"Resultado de la herramienta:\n\n{last_tool_result[:1500]}"

    if not reply_content.strip():
        if hit_round_limit:
            reply_content = "Se alcanzó el límite de rondas de herramientas sin una respuesta clara. Intenta de nuevo."
        elif tools_were_used:
            reply_content = f"Las herramientas ({', '.join(executed_tools[-3:])}) se ejecutaron pero no se pudo generar un resumen. Último resultado:\n\n{last_tool_result[:800]}"
        else:
            reply_content = "No se ejecutaron herramientas ni se generó respuesta. Intenta ser más específico."

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
        # Preguntas factuales / investigación → no charla simple (usar tools, p. ej. web)
        "qué es", "que es", "quién es", "quien es", "qué son", "que son",
        "información sobre", "informacion sobre", "investiga", "averigua",
        "dime sobre", "cuéntame sobre", "cuentame sobre", "haz una búsqueda",
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
    from aaris.cli import main as cli_main
    cli_main()
