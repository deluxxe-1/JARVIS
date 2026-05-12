import json
import os
import re
import time
import difflib
from typing import Any
from datetime import datetime
from pathlib import Path

from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from jarvis.engine import MODEL, console, prune_messages, run_simple_chat, run_tool_loop
from jarvis.tools.core import rollback, rollback_tokens
from jarvis.tools.filesystem import resolve_path
from brain import JarvisBrain
from jarvis.tools_registry import get_all_tools
from jarvis.tool_selector import _build_tool_groups, _select_tools


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
        from jarvis.tools.core import _backup_base_dir
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


from jarvis.prompts import SYSTEM_PROMPT


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
        from jarvis.http_server import start_server

        api_token = os.environ.get("JARVIS_API_TOKEN", "").strip() or None
        max_body = os.environ.get("JARVIS_HTTP_MAX_BODY_BYTES", "").strip()
        try:
            max_body_bytes = int(max_body) if max_body else 1024 * 1024
        except Exception:
            max_body_bytes = 1024 * 1024

        def _reply(prompt: str) -> str:
            msgs = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
            active = _select_tools(prompt, available_tools, tool_groups)
            return run_tool_loop(msgs, active, tool_map, opts)

        console.print("[bold green]Servidor HTTP activo (POST /api/chat, GET /health).[/bold green]")
        start_server(_reply, api_token=api_token, max_body_bytes=max_body_bytes)
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
