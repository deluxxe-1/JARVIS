from __future__ import annotations
import json
import os
import re
import time
from typing import Any
from rich.console import Console
from ollama import chat

from jarvis.logging import configure_logging
from jarvis.tool_selector import _build_tool_groups, _select_tools
from jarvis.prompts import SYSTEM_PROMPT

console = Console()
MAX_CONTEXT_MESSAGES = 10
MODEL = os.environ.get("JARVIS_MODEL", "qwen2.5:14b")

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
    from jarvis.cli import main as cli_main
    cli_main()
