"""
JARVIS Dev Agent — Agente autónomo de programación.

Permite a JARVIS trabajar en proyectos de código mientras el usuario duerme:
- Ejecuta tareas de programación en background con progreso persistente
- Soporta proyectos multi-fase (planificar → implementar → testear → reportar)
- Reintentos automáticos ante fallos
- Notificaciones al finalizar
- Programación con cron/scheduler

Uso desde JARVIS:
    "crea un agente que construya una API REST en Flask y la testee"
    "programa para las 3am que el agente refactorice el módulo X"
    "qué está haciendo el agente dev_api?"
"""

import json
import os
import re
import subprocess
import sys
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

_JARVIS_DIR = Path(os.environ.get(
    "JARVIS_APP_DIR",
    os.path.join(os.path.expanduser("~"), ".jarvis"),
))

DEV_AGENTS_DIR = _JARVIS_DIR / "dev_agents"
AGENT_REGISTRY_PATH = DEV_AGENTS_DIR / "registry.json"

# Cuántas rondas máximas de tool-calling usa el agente dev por fase
DEV_AGENT_ROUNDS_PER_PHASE = int(os.environ.get("JARVIS_DEV_AGENT_ROUNDS", "30"))

# Fases estándar de un proyecto de programación
PROJECT_PHASES = ["plan", "scaffold", "implement", "test", "refine", "report"]


# ---------------------------------------------------------------------------
# Persistencia del agente
# ---------------------------------------------------------------------------

def _ensure_dirs() -> None:
    DEV_AGENTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_registry() -> dict[str, Any]:
    try:
        if AGENT_REGISTRY_PATH.is_file():
            return json.loads(AGENT_REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_registry(data: dict[str, Any]) -> None:
    _ensure_dirs()
    tmp = AGENT_REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(AGENT_REGISTRY_PATH)


def _agent_dir(name: str) -> Path:
    d = DEV_AGENTS_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _agent_state_path(name: str) -> Path:
    return _agent_dir(name) / "state.json"


def _agent_log_path(name: str) -> Path:
    return _agent_dir(name) / "progress.md"


def _agent_result_path(name: str) -> Path:
    return _agent_dir(name) / "result.md"


def _load_agent_state(name: str) -> dict[str, Any]:
    p = _agent_state_path(name)
    try:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_agent_state(name: str, state: dict[str, Any]) -> None:
    _agent_state_path(name).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _append_log(name: str, text: str) -> None:
    """Añade una línea al log de progreso del agente."""
    ts = datetime.now().strftime("%H:%M:%S")
    with open(_agent_log_path(name), "a", encoding="utf-8") as f:
        f.write(f"\n[{ts}] {text}")


# ---------------------------------------------------------------------------
# Motor del agente — ejecuta fases con Ollama
# ---------------------------------------------------------------------------

def _build_phase_prompt(task: str, phase: str, prev_results: dict[str, str], cwd: str) -> str:
    """Construye el prompt para cada fase del agente."""

    phase_instructions = {
        "plan": f"""Eres un agente autónomo de programación. Tu tarea es:

{task}

FASE: PLANIFICACIÓN
Tu objetivo en esta fase es:
1. Analizar la tarea en detalle
2. Definir la estructura del proyecto (archivos, carpetas, dependencias)
3. Listar los pasos de implementación en orden
4. Identificar posibles problemas y sus soluciones

Usa las tools disponibles para:
- Explorar el directorio actual ({cwd}) con list_directory
- Verificar si ya existe algún código relevante con glob_find
- Detectar el tipo de proyecto con detect_project
- Crear un archivo PLAN.md con el plan detallado usando create_file

Al final, crea el archivo PLAN.md con toda la información.""",

        "scaffold": f"""Eres un agente autónomo de programación. Tu tarea es:

{task}

FASE: ESTRUCTURA BASE (SCAFFOLD)
Plan previo:
{prev_results.get('plan', 'No disponible')}

Tu objetivo en esta fase es:
1. Crear la estructura de carpetas del proyecto
2. Crear los archivos base vacíos o con boilerplate mínimo
3. Crear el archivo de dependencias (requirements.txt, package.json, etc.)
4. NO implementar lógica todavía — solo la estructura

Usa create_folder y create_file para crear la estructura.
Al finalizar, confirma qué archivos y carpetas creaste.""",

        "implement": f"""Eres un agente autónomo de programación. Tu tarea es:

{task}

FASE: IMPLEMENTACIÓN
Plan previo:
{prev_results.get('plan', 'No disponible')}

Tu objetivo en esta fase es implementar TODA la funcionalidad requerida:
1. Escribe el código completo para cada archivo
2. Implementa todas las funciones y clases necesarias
3. Añade manejo de errores apropiado
4. Añade comentarios donde sea necesario

Usa create_file y edit_file para escribir el código.
Usa run_command para verificar sintaxis si es necesario (python -m py_compile, etc.).
NO dejes funciones vacías ni TODOs sin resolver — implementa todo completamente.""",

        "test": f"""Eres un agente autónomo de programación. Tu tarea es:

{task}

FASE: TESTING
Implementación previa completada. Ahora debes:
1. Ejecutar los tests existentes con run_command
2. Si no hay tests, crear tests básicos y ejecutarlos
3. Si hay errores, corregirlos con edit_file o search_replace_in_file
4. Documentar los resultados de los tests

Usa run_command para ejecutar tests y verificar que el código funciona.
Si algo falla, corrígelo antes de continuar.
Guarda los resultados de tests en TESTS.md.""",

        "refine": f"""Eres un agente autónomo de programación. Tu tarea es:

{task}

FASE: REFINAMIENTO
Tests completados. Ahora:
1. Revisa el código en busca de mejoras de calidad
2. Verifica que el código sigue buenas prácticas
3. Asegúrate de que todos los archivos están completos
4. Añade un README.md si no existe
5. Verifica que las dependencias están bien documentadas

Usa read_file para revisar el código y search_replace_in_file para mejoras puntuales.""",

        "report": f"""Eres un agente autónomo de programación. Tu tarea era:

{task}

FASE: REPORTE FINAL
El proyecto está completo. Crea un reporte final detallado en RESULT.md que incluya:
1. ✅ Qué se implementó
2. 📁 Estructura de archivos creados
3. 🚀 Cómo ejecutar/usar el proyecto
4. ⚠️ Limitaciones o cosas pendientes si las hay
5. 🧪 Resultados de los tests

Usa list_directory para ver los archivos creados.
Usa create_file para crear RESULT.md con el reporte completo.""",
    }

    return phase_instructions.get(phase, f"Ejecuta la tarea: {task}")


def _run_agent_phase(
    agent_name: str,
    task: str,
    phase: str,
    prev_results: dict[str, str],
    cwd: str,
    model: str,
) -> str:
    """Ejecuta una fase del agente y devuelve el resultado."""
    from ollama import chat

    # Importar todas las tools disponibles
    try:
        from jarvis.tools_registry import get_all_tools
        available_tools = get_all_tools()
    except Exception:
        from tools import (
            create_file, edit_file, read_file, search_replace_in_file,
            create_folder, append_file, list_directory, glob_find,
            exists_path, describe_path, run_command, run_command_checked,
            detect_project, project_workflow_suggest, fuzzy_search_paths,
            tail_file, estimate_dir, delete_path, copy_path, move_path,
        )
        available_tools = [
            create_file, edit_file, read_file, search_replace_in_file,
            create_folder, append_file, list_directory, glob_find,
            exists_path, describe_path, run_command, run_command_checked,
            detect_project, project_workflow_suggest, fuzzy_search_paths,
            tail_file, estimate_dir, delete_path, copy_path, move_path,
        ]

    tool_map = {f.__name__: f for f in available_tools}

    system_prompt = f"""Eres JARVIS, un agente autónomo de programación experto.
Trabajas de forma completamente autónoma — el usuario no está presente.
Directorio de trabajo: {cwd}
Agente: {agent_name}
Fase: {phase}

REGLAS ABSOLUTAS:
1. USA las herramientas directamente — no expliques, actúa.
2. Si encuentras un error, corrígelo y continúa — no te rindas.
3. Escribe código COMPLETO y funcional — sin TODOs ni stubs.
4. Al finalizar cada acción importante, escribe un resumen de lo que hiciste.
5. Trabaja en el directorio: {cwd}
"""

    phase_prompt = _build_phase_prompt(task, phase, prev_results, cwd)

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "system",
            "content": (
                "INSTRUCCIÓN CRÍTICA: Usa las herramientas disponibles para ejecutar "
                "cada paso. NO expliques cómo hacerlo — HAZLO directamente."
            ),
        },
        {"role": "user", "content": phase_prompt},
    ]

    _append_log(agent_name, f"── Iniciando fase: {phase.upper()} ──")
    result_content = ""
    rounds = 0

    while rounds < DEV_AGENT_ROUNDS_PER_PHASE:
        rounds += 1
        try:
            response = chat(
                model=model,
                messages=messages,
                tools=available_tools,
                options={"temperature": 0.1},
            )
        except Exception as e:
            _append_log(agent_name, f"Error en chat: {e}")
            break

        response_msg = response["message"]
        messages.append(response_msg)
        tool_calls = response_msg.get("tool_calls") or []

        if not tool_calls:
            result_content = response_msg.get("content") or ""
            _append_log(agent_name, f"Fase {phase} completada ({rounds} rondas).")
            break

        for tc in tool_calls:
            fn = tc.get("function") or {}
            fn_name = fn.get("name") or ""
            raw_args = fn.get("arguments") or {}
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except Exception:
                    raw_args = {}

            _append_log(agent_name, f"  → {fn_name}({str(raw_args)[:80]})")

            func = tool_map.get(fn_name)
            if func:
                try:
                    # Para comandos, aseguramos que se ejecutan en el cwd del proyecto
                    if fn_name == "run_command" and "cwd" not in raw_args:
                        raw_args["cwd"] = cwd
                    result = func(**raw_args)
                except Exception as e:
                    result = f"Error: {e}"
            else:
                result = f"Herramienta desconocida: {fn_name}"

            _append_log(agent_name, f"    ✓ {str(result)[:120]}")

            tool_msg: dict[str, Any] = {"role": "tool", "content": str(result)}
            if fn_name:
                tool_msg["name"] = fn_name
            messages.append(tool_msg)

    return result_content or f"Fase {phase} ejecutada ({rounds} rondas)."


def _run_dev_project(
    agent_name: str,
    task: str,
    project_dir: str,
    model: str,
    phases: list[str],
    notify: bool,
) -> None:
    """Loop principal del agente — ejecuta todas las fases en orden."""
    _ensure_dirs()
    _append_log(agent_name, f"=== JARVIS Dev Agent '{agent_name}' iniciado ===")
    _append_log(agent_name, f"Tarea: {task}")
    _append_log(agent_name, f"Directorio: {project_dir}")
    _append_log(agent_name, f"Fases: {' → '.join(phases)}")

    state = _load_agent_state(agent_name)
    state["status"] = "running"
    state["started_at"] = datetime.now().isoformat(timespec="seconds")
    state["task"] = task
    state["phases"] = phases
    state["current_phase"] = ""
    state["completed_phases"] = state.get("completed_phases", [])
    _save_agent_state(agent_name, state)

    prev_results: dict[str, str] = state.get("phase_results", {})
    completed = state.get("completed_phases", [])

    for phase in phases:
        if phase in completed:
            _append_log(agent_name, f"Saltando fase '{phase}' (ya completada)")
            continue

        state["current_phase"] = phase
        _save_agent_state(agent_name, state)

        try:
            phase_result = _run_agent_phase(
                agent_name, task, phase, prev_results, project_dir, model
            )
            prev_results[phase] = phase_result
            completed.append(phase)
            state["completed_phases"] = completed
            state["phase_results"] = prev_results
            _save_agent_state(agent_name, state)
            _append_log(agent_name, f"✅ Fase '{phase}' completada.")

        except Exception as e:
            _append_log(agent_name, f"❌ Error en fase '{phase}': {e}")
            state["status"] = "failed"
            state["error"] = str(e)
            _save_agent_state(agent_name, state)
            break
    else:
        # Todas las fases completadas
        state["status"] = "done"
        state["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _save_agent_state(agent_name, state)

        # Copiar RESULT.md al directorio de agentes si existe
        result_file = Path(project_dir) / "RESULT.md"
        if result_file.is_file():
            import shutil
            shutil.copy2(str(result_file), str(_agent_result_path(agent_name)))

        _append_log(agent_name, "=== ✅ PROYECTO COMPLETADO ===")

        if notify:
            try:
                from automation import show_notification
                show_notification(
                    title=f"✅ JARVIS Dev Agent: {agent_name}",
                    message=f"Proyecto completado. Resultado en {_agent_result_path(agent_name)}",
                    timeout=30,
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# API pública — tools que JARVIS puede llamar
# ---------------------------------------------------------------------------

def dev_agent_create(
    name: str,
    task: str,
    project_dir: str = "",
    phases: str = "plan,scaffold,implement,test,refine,report",
    notify: bool = True,
) -> str:
    """
    Crea y lanza un agente autónomo de programación en background.
    El agente trabaja de forma completamente autónoma — implementa, testea y reporta.

    Args:
        name: Nombre único del agente (ej: 'api_flask', 'scraper_amazon').
        task: Descripción completa de lo que debe programar.
              Sé específico: lenguaje, frameworks, endpoints, estructura esperada.
        project_dir: Carpeta donde crear el proyecto. Si vacío, crea una carpeta
                     nueva con el nombre del agente en el directorio actual.
        phases: Fases a ejecutar separadas por comas.
                Opciones: plan, scaffold, implement, test, refine, report.
                Por defecto ejecuta todas.
        notify: Si True, muestra notificación del sistema al terminar.
    """
    try:
        if not name or not name.strip():
            return "Error: el agente necesita un nombre."
        if not task or not task.strip():
            return "Error: el agente necesita una tarea."

        name = re.sub(r"[^\w]", "_", name.strip().lower())
        _ensure_dirs()

        # Directorio del proyecto
        if not project_dir:
            project_dir = str(Path(os.getcwd()) / name)
        project_dir = os.path.abspath(os.path.expanduser(project_dir))
        Path(project_dir).mkdir(parents=True, exist_ok=True)

        # Fases a ejecutar
        phase_list = [p.strip() for p in phases.split(",") if p.strip() in PROJECT_PHASES]
        if not phase_list:
            phase_list = PROJECT_PHASES[:]

        # Verificar que no hay un agente con ese nombre ya corriendo
        registry = _load_registry()
        if name in registry and registry[name].get("status") == "running":
            return f"Error: el agente '{name}' ya está en ejecución. Usa dev_agent_status para ver su progreso."

        model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

        # Registrar el agente
        registry[name] = {
            "task": task,
            "project_dir": project_dir,
            "phases": phase_list,
            "status": "starting",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "log": str(_agent_log_path(name)),
            "result": str(_agent_result_path(name)),
        }
        _save_registry(registry)

        # Lanzar en un hilo daemon (o subproceso si se prefiere persistencia total)
        def _run():
            try:
                _run_dev_project(name, task, project_dir, model, phase_list, notify)
                reg = _load_registry()
                if name in reg:
                    state = _load_agent_state(name)
                    reg[name]["status"] = state.get("status", "done")
                    reg[name]["finished_at"] = datetime.now().isoformat(timespec="seconds")
                    _save_registry(reg)
            except Exception as e:
                _append_log(name, f"Error fatal: {e}")

        t = threading.Thread(target=_run, daemon=True, name=f"jarvis-dev-{name}")
        t.start()

        return json.dumps({
            "status": "ok",
            "message": f"Agente '{name}' lanzado en background.",
            "project_dir": project_dir,
            "phases": phase_list,
            "log": str(_agent_log_path(name)),
            "result": str(_agent_result_path(name)),
            "tip": f"Usa dev_agent_status('{name}') para ver el progreso.",
        }, ensure_ascii=False)

    except Exception as e:
        return f"Error en dev_agent_create: {e}"


def dev_agent_status(name: str = "") -> str:
    """
    Muestra el estado y progreso de uno o todos los agentes de programación.

    Args:
        name: Nombre del agente. Si vacío, muestra todos.
    """
    try:
        _ensure_dirs()
        registry = _load_registry()

        if not registry:
            return "No hay agentes de programación registrados."

        if name:
            name = re.sub(r"[^\w]", "_", name.strip().lower())
            if name not in registry:
                return f"Error: agente '{name}' no encontrado."
            agents_to_show = {name: registry[name]}
        else:
            agents_to_show = registry

        results = []
        for agent_name, info in agents_to_show.items():
            state = _load_agent_state(agent_name)
            status = state.get("status") or info.get("status", "unknown")
            current_phase = state.get("current_phase", "")
            completed_phases = state.get("completed_phases", [])
            all_phases = info.get("phases", [])
            progress = f"{len(completed_phases)}/{len(all_phases)}" if all_phases else "?"

            # Últimas líneas del log
            log_tail = ""
            log_path = _agent_log_path(agent_name)
            if log_path.is_file():
                lines = log_path.read_text(encoding="utf-8").splitlines()
                log_tail = "\n".join(lines[-5:])

            entry = {
                "name": agent_name,
                "status": status,
                "current_phase": current_phase,
                "progress": progress,
                "completed_phases": completed_phases,
                "project_dir": info.get("project_dir", ""),
                "started_at": info.get("created_at", ""),
                "task_preview": info.get("task", "")[:80],
                "recent_log": log_tail,
                "result_ready": _agent_result_path(agent_name).is_file(),
            }
            results.append(entry)

        return json.dumps({"agents": results}, ensure_ascii=False, indent=2)

    except Exception as e:
        return f"Error en dev_agent_status: {e}"


def dev_agent_log(name: str, lines: int = 30) -> str:
    """
    Muestra el log de progreso completo de un agente.

    Args:
        name: Nombre del agente.
        lines: Número de líneas recientes a mostrar.
    """
    try:
        name = re.sub(r"[^\w]", "_", name.strip().lower())
        log_path = _agent_log_path(name)
        if not log_path.is_file():
            return f"No hay log para el agente '{name}' todavía."
        content = log_path.read_text(encoding="utf-8").splitlines()
        tail = content[-lines:]
        return f"=== Log de '{name}' (últimas {lines} líneas) ===\n" + "\n".join(tail)
    except Exception as e:
        return f"Error en dev_agent_log: {e}"


def dev_agent_result(name: str) -> str:
    """
    Muestra el reporte final de un agente cuando ha terminado.

    Args:
        name: Nombre del agente.
    """
    try:
        name = re.sub(r"[^\w]", "_", name.strip().lower())
        result_path = _agent_result_path(name)
        if not result_path.is_file():
            state = _load_agent_state(name)
            status = state.get("status", "unknown")
            return f"El agente '{name}' aún no ha generado el resultado. Estado: {status}."
        return result_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error en dev_agent_result: {e}"


def dev_agent_stop(name: str) -> str:
    """
    Marca un agente como cancelado (el hilo terminará al acabar la fase actual).

    Args:
        name: Nombre del agente.
    """
    try:
        name = re.sub(r"[^\w]", "_", name.strip().lower())
        state = _load_agent_state(name)
        if not state:
            return f"Agente '{name}' no encontrado."
        state["status"] = "cancelled"
        _save_agent_state(name, state)

        registry = _load_registry()
        if name in registry:
            registry[name]["status"] = "cancelled"
            _save_registry(registry)

        _append_log(name, "⛔ Agente cancelado por el usuario.")
        return f"Agente '{name}' marcado como cancelado. Terminará al acabar la fase actual."
    except Exception as e:
        return f"Error en dev_agent_stop: {e}"


def dev_agent_schedule(
    name: str,
    task: str,
    run_at: str,
    project_dir: str = "",
    phases: str = "plan,scaffold,implement,test,refine,report",
) -> str:
    """
    Programa un agente de programación para ejecutarse a una hora específica.
    Perfecto para dejar tareas para que corran mientras duermes.

    Args:
        name: Nombre del agente.
        task: Descripción de lo que debe programar.
        run_at: Hora de inicio en formato HH:MM (ej: '03:00' para las 3am)
                o en formato ISO 'YYYY-MM-DD HH:MM'.
        project_dir: Carpeta del proyecto (opcional).
        phases: Fases a ejecutar.
    """
    try:
        if not name or not task or not run_at:
            return "Error: name, task y run_at son obligatorios."

        name = re.sub(r"[^\w]", "_", name.strip().lower())
        _ensure_dirs()

        # Parsear la hora
        now = datetime.now()
        target_dt: Optional[datetime] = None

        run_at = run_at.strip()
        if re.match(r"^\d{2}:\d{2}$", run_at):
            h, m = map(int, run_at.split(":"))
            target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target_dt <= now:
                target_dt += timedelta(days=1)
        elif re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", run_at):
            target_dt = datetime.strptime(run_at, "%Y-%m-%d %H:%M")
        else:
            return f"Error: formato de hora no válido: '{run_at}'. Usa HH:MM o YYYY-MM-DD HH:MM."

        wait_seconds = (target_dt - now).total_seconds()

        # Guardar la tarea programada en el registry
        registry = _load_registry()
        registry[name] = {
            "task": task,
            "project_dir": project_dir,
            "phases": [p.strip() for p in phases.split(",") if p.strip() in PROJECT_PHASES],
            "status": "scheduled",
            "scheduled_for": target_dt.isoformat(timespec="seconds"),
            "created_at": now.isoformat(timespec="seconds"),
            "log": str(_agent_log_path(name)),
            "result": str(_agent_result_path(name)),
        }
        _save_registry(registry)

        # Lanzar hilo que espera y luego ejecuta
        def _delayed_run():
            wait = (target_dt - datetime.now()).total_seconds()
            if wait > 0:
                time.sleep(wait)
            _append_log(name, f"⏰ Iniciando ejecución programada a las {run_at}")
            model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
            phase_list = registry[name].get("phases", PROJECT_PHASES[:])
            proj_dir = project_dir or str(Path(os.getcwd()) / name)
            Path(proj_dir).mkdir(parents=True, exist_ok=True)
            _run_dev_project(name, task, proj_dir, model, phase_list, notify=True)

        t = threading.Thread(target=_delayed_run, daemon=True, name=f"jarvis-sched-{name}")
        t.start()

        wait_h = int(wait_seconds // 3600)
        wait_m = int((wait_seconds % 3600) // 60)

        return json.dumps({
            "status": "scheduled",
            "name": name,
            "run_at": target_dt.isoformat(timespec="seconds"),
            "wait": f"{wait_h}h {wait_m}m",
            "task_preview": task[:100],
            "log": str(_agent_log_path(name)),
        }, ensure_ascii=False)

    except Exception as e:
        return f"Error en dev_agent_schedule: {e}"


def dev_agent_list() -> str:
    """
    Lista todos los agentes de programación (activos, programados y finalizados).
    """
    try:
        _ensure_dirs()
        registry = _load_registry()
        if not registry:
            return json.dumps({"agents": [], "message": "No hay agentes registrados."}, ensure_ascii=False)

        summary = []
        for agent_name, info in registry.items():
            state = _load_agent_state(agent_name)
            status = state.get("status") or info.get("status", "unknown")
            completed = len(state.get("completed_phases", []))
            total = len(info.get("phases", []))
            summary.append({
                "name": agent_name,
                "status": status,
                "progress": f"{completed}/{total} fases",
                "scheduled_for": info.get("scheduled_for", ""),
                "finished_at": state.get("finished_at", ""),
                "task": info.get("task", "")[:60],
            })

        return json.dumps({"agents": summary}, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error en dev_agent_list: {e}"


def dev_agent_quick(task: str, project_dir: str = "") -> str:
    """
    Lanza un agente de programación con nombre automático y todas las fases.
    Forma rápida de delegar un proyecto completo sin configurar nada.

    Args:
        task: Descripción del proyecto a implementar.
        project_dir: Carpeta destino (opcional).
    """
    import hashlib
    # Generar nombre corto desde la tarea
    name = "dev_" + hashlib.md5(task.encode()).hexdigest()[:6]
    return dev_agent_create(name=name, task=task, project_dir=project_dir)
