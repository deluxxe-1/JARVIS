"""
JARVIS Autonomous Agents Module

Gestiona subprocesos independientes ("Agentes" de JARVIS) que operan en background sin UI.
"""

import os
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# ============================================================================
# Configuración
# ============================================================================

_JARVIS_DIR = Path(os.environ.get(
    "JARVIS_APP_DIR",
    os.path.join(os.path.expanduser("~"), ".jarvis"),
))

AGENTS_TRACKER_PATH = _JARVIS_DIR / "agents.json"
AGENTS_LOGS_DIR = _JARVIS_DIR / "agents"


def _ensure_dirs():
    """Asegura que los directorios necesarios existen."""
    _JARVIS_DIR.mkdir(parents=True, exist_ok=True)
    AGENTS_LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _load_tracker() -> dict[str, Any]:
    """Carga la lista de agentes rastreados."""
    try:
        if AGENTS_TRACKER_PATH.is_file():
            data = json.loads(AGENTS_TRACKER_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_tracker(data: dict[str, Any]) -> None:
    """Guarda la lista de agentes."""
    _ensure_dirs()
    tmp = AGENTS_TRACKER_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(AGENTS_TRACKER_PATH)


# ============================================================================
# Herramientas de Agentes
# ============================================================================

def spawn_agent(name: str, task: str) -> str:
    """
    Lanza un agente autónomo de JARVIS en segundo plano para realizar una tarea pesada o larga.
    El agente no interactuará con el usuario y trabajará invisiblemente.

    Args:
        name: Nombre único sin espacios para el agente (ej: "buscador_web", "analista").
        task: La instrucción exhaustiva y clara de lo que debe hacer el agente.
              Sugiérele que guarde el resultado usando create_file o que intente auto-completar 
              la investigación en menos de 10 iteraciones.
    """
    try:
        if not name or not name.strip():
            return "Error: el agente debe tener un nombre."
        if not task or not task.strip():
            return "Error: el agente necesita una tarea asignada."

        name = name.strip().lower().replace(" ", "_")
        _ensure_dirs()

        main_py = str(Path(__file__).resolve().parent / "main.py")
        if not os.path.isfile(main_py):
            return f"Error: no se encontró {main_py}"

        # Usar CREATE_NO_WINDOW o start_new_session según el OS
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(
            [sys.executable, main_py, "--run-agent", name, task],
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            cwd=os.getcwd(),
            **kwargs,
        )

        tracker = _load_tracker()
        from datetime import datetime
        tracker[name] = {
            "pid": proc.pid,
            "task": task,
            "started_at": datetime.now().isoformat(timespec="seconds")
        }
        _save_tracker(tracker)

        return json.dumps({
            "status": "ok",
            "message": f"Agente '{name}' despachado exitosamente.",
            "pid": proc.pid,
            "log_path": str(AGENTS_LOGS_DIR / f"{name}_result.md")
        }, ensure_ascii=False)

    except Exception as e:
        return f"Error en spawn_agent: {e}"


def list_running_agents() -> str:
    """
    Lista todos los agentes autónomos de JARVIS y comprueba si siguen activos o terminaron.
    """
    try:
        import psutil
    except ImportError:
        return "Error: psutil no instalado. Ejecuta 'pip install psutil'."

    try:
        tracker = _load_tracker()
        alive_agents = []
        dead_agents = []

        for name, info in tracker.items():
            pid = info.get("pid")
            is_alive = False
            if pid:
                try:
                    p = psutil.Process(pid)
                    # Verifica que el proceso es python (o similar) y no otro que reusó PID
                    if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                        cmdline = p.cmdline()
                        if any("--run-agent" in arg for arg in cmdline):
                            is_alive = True
                except psutil.NoSuchProcess:
                    pass

            if is_alive:
                alive_agents.append({"name": name, "pid": pid, "task": info.get("task", "")[:50]})
            else:
                dead_agents.append(name)

        if dead_agents:
            for name in dead_agents:
                del tracker[name]
            _save_tracker(tracker)

        return json.dumps({
            "active_count": len(alive_agents),
            "agents": alive_agents,
            "cleaned_up": len(dead_agents),
        }, ensure_ascii=False)

    except Exception as e:
        return f"Error en list_running_agents: {e}"


def kill_agent(name: str) -> str:
    """
    Termina forzosamente un agente autónomo que esté bloqueado.

    Args:
        name: Nombre del agente a destruir (ej: "buscador_web").
    """
    try:
        tracker = _load_tracker()
        name = name.strip().lower().replace(" ", "_")

        if name not in tracker:
            return f"Error: no hay registro del agente '{name}'."

        pid = tracker[name].get("pid")
        if not pid:
            return "Error: el agente no tiene PID asociado."

        import psutil
        try:
            p = psutil.Process(pid)
            if any("--run-agent" in arg for arg in p.cmdline()):
                p.kill()
                msg = f"Agente '{name}' (PID {pid}) asesinado exitosamente."
            else:
                msg = f"El proceso con PID {pid} no parece ser un agente. Limpiando registro."
        except psutil.NoSuchProcess:
            msg = f"El agente '{name}' ya no estaba ejecutándose. Registro limpiado."

        del tracker[name]
        _save_tracker(tracker)
        return msg

    except Exception as e:
        return f"Error kill_agent: {e}"


def read_agent_result(name: str) -> str:
    """
    Lee el archivo de resultados o reporte final generado por un agente.
    Usar después de que un agente haya notificado su finalización.

    Args:
        name: Nombre del agente.
    """
    try:
        name = name.strip().lower().replace(" ", "_")
        result_path = AGENTS_LOGS_DIR / f"{name}_result.md"

        if not result_path.is_file():
            return f"Error: el agente '{name}' no ha generado su reporte final en {result_path} todavía, o falló sin generarlo."

        content = result_path.read_text(encoding="utf-8")
        if not content.strip():
            return f"El reporte del agente '{name}' existe pero está vacío."

        return f"--- REPORTE FINAL DEL AGENTE '{name}' ---\n{content}\n--- FIN REPORTE ---"

    except Exception as e:
        return f"Error leyendo resultado del agente: {e}"
