import glob as glob_module
import json
import os
import subprocess
from pathlib import Path
import re
import difflib
import shutil
import unicodedata
from typing import Optional, Any
import fnmatch
import uuid
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import time
from contextlib import contextmanager

from jarvis.tools.core import *
from jarvis.tools.filesystem import resolve_path

def detect_project(root: str = ".") -> str:
    """
    Detecta el tipo de proyecto por marcadores en el filesystem.
    """
    try:
        resolved_root = resolve_path(root, must_exist=True)
        if resolved_root.startswith("Error:"):
            return resolved_root
        r = Path(resolved_root).resolve()
        markers = []

        def _has(name: str) -> bool:
            return (r / name).exists()

        project_type = "unknown"
        if _has("package.json"):
            project_type = "node"
            markers.append("package.json")
        if _has("pyproject.toml") or _has("requirements.txt"):
            project_type = "python"
            markers.extend([m for m in ["pyproject.toml", "requirements.txt"] if _has(m)])
        if _has("Cargo.toml"):
            project_type = "rust"
            markers.append("Cargo.toml")
        if _has("go.mod"):
            project_type = "go"
            markers.append("go.mod")
        if _has("docker-compose.yml") or _has("Dockerfile"):
            markers.extend([m for m in ["docker-compose.yml", "Dockerfile"] if _has(m)])

        info = {"root": str(r), "type": project_type, "markers": sorted(set(markers))}
        return json.dumps(info, ensure_ascii=False)
    except Exception as e:
        return f"Error en detect_project: {e}"

def project_workflow_suggest(root: str = ".", include_commands: bool = True) -> str:
    """
    Sugiere un pipeline típico según el tipo de proyecto.
    No ejecuta nada: solo devuelve pasos recomendados para que el agente los orqueste.
    """
    try:
        info_raw = detect_project(root)
        if not info_raw.startswith("{"):
            return info_raw
        info = json.loads(info_raw)
        ptype = info.get("type") or "unknown"
        root_resolved = info.get("root") or root

        steps: list[str] = []
        cmds: list[str] = []

        if ptype == "python":
            steps = [
                "Instalar dependencias con el gestor indicado por el repo (requirements.txt/pyproject).",
                "Ejecutar tests (pytest/unittest) y capturar resultados.",
                "Validar sintaxis Python (compileall/py_compile).",
                "Revisar linting si existe (ruff/flake8).",
                "Aplicar cambios y verificar de nuevo.",
            ]
            cmds = [
                "python -m compileall .",
                "python -m pytest -q",
            ]
        elif ptype == "node":
            steps = [
                "Instalar dependencias (npm/pnpm/yarn según existan).",
                "Ejecutar tests/lint (si existen scripts).",
                "Validar build (si existe).",
                "Aplicar cambios y verificar nuevamente.",
            ]
            cmds = [
                "npm test",
                "npm run lint",
            ]
        elif ptype == "rust":
            steps = [
                "Compilar (cargo build) y ejecutar tests (cargo test).",
                "Revisar clippy si existe.",
                "Aplicar cambios y volver a compilar.",
            ]
            cmds = [
                "cargo test",
                "cargo clippy",
            ]
        else:
            steps = [
                "Determinar dependencias y comandos disponibles en el repo.",
                "Ejecutar tests/validaciones si existen.",
                "Aplicar cambios y re-verificar.",
            ]
            cmds = []

        payload = {
            "root": root_resolved,
            "project_type": ptype,
            "steps": steps,
            "commands": cmds if include_commands else [],
        }
        return json.dumps(payload, ensure_ascii=False)
    except Exception as e:
        return f"Error en project_workflow_suggest: {e}"

def apply_template(template_name: str, destination: str, context_json: str = "{}") -> str:
    """
    Crea un archivo desde una plantilla embebida.
    """
    try:
        if _read_only_mode():
            return "Error: JARVIS_READ_ONLY=true. apply_template deshabilitado."
        ctx = json.loads(context_json or "{}")
        if not isinstance(ctx, dict):
            ctx = {}

        template_dir = os.environ.get(
            "JARVIS_TEMPLATE_DIR",
            os.path.join(os.path.expanduser("~"), ".jarvis", "templates"),
        )
        template_dir = os.path.abspath(os.path.expanduser(template_dir))

        templates: dict[str, str] = {
            "python_script": (
                "#!/usr/bin/env python3\n"
                "\"\"\"{{title}}\"\"\"\n\n"
                "def main():\n"
                "    print(\"{{message}}\")\n\n"
                "if __name__ == \"__main__\":\n"
                "    main()\n"
            ),
            "systemd_service": (
                "[Unit]\n"
                "Description={{description}}\n"
                "After=network.target\n\n"
                "[Service]\n"
                "Type=simple\n"
                "User={{user}}\n"
                "WorkingDirectory={{workdir}}\n"
                "ExecStart={{execstart}}\n"
                "Restart=always\n\n"
                "[Install]\n"
                "WantedBy=multi-user.target\n"
            ),
            "systemd_timer": (
                "[Unit]\n"
                "Description={{description}}\n\n"
                "[Timer]\n"
                "OnCalendar={{oncalendar}}\n"
                "Persistent=true\n\n"
                "[Install]\n"
                "WantedBy=timers.target\n"
            ),
            "bash_script": (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n\n"
                "{{body}}\n"
            ),
            "cron_entry": (
                "{{minute}} {{hour}} {{day_of_month}} {{month}} {{day_of_week}} {{command}}\n"
            ),
            "readme": (
                "# {{title}}\n\n"
                "{{summary}}\n"
            ),
        }

        # Si existe plantilla externa, la usamos primero.
        external_content: Optional[str] = None
        for candidate in [template_name, f"{template_name}.tpl", f"{template_name}.txt"]:
            p = Path(template_dir) / candidate
            if p.is_file():
                try:
                    external_content = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    external_content = None
                break

        if external_content is not None:
            content = external_content
        else:
            if template_name not in templates:
                return f"Error: plantilla desconocida: {template_name}"
            content = templates[template_name]

        resolved_dest = resolve_path(destination, must_exist=False)
        if resolved_dest.startswith("Error:"):
            return resolved_dest
        for k, v in ctx.items():
            content = content.replace("{{" + str(k) + "}}", str(v))

        # Creamos directorios padre y escribimos.
        parent = os.path.dirname(resolved_dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(resolved_dest, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Plantilla aplicada en {resolved_dest} (template={template_name})."
    except Exception as e:
        return f"Error en apply_template: {e}"

def scaffold_project(
    project_type: str,
    destination: str,
    name: str = "app",
    confirm: bool = False,
    allow_dangerous: bool = False,
) -> str:
    """
    Crea (scaffold) un proyecto base para que el agente pueda implementarlo.

    Tipos soportados (iniciales):
    - web_static: HTML/CSS/JS sin dependencias
    - api_fastapi: API Python mínima (FastAPI)
    - web_vite_react: Vite + React (requiere Node/npm) (confirm=true)
    - mobile_expo: React Native con Expo (requiere Node/npm) (confirm=true)
    - mobile_flutter: Flutter (requiere flutter) (confirm=true)

    Nota: los tipos que ejecutan generadores externos requieren confirm=true.
    """
    try:
        if _read_only_mode():
            return "Error: JARVIS_READ_ONLY=true. scaffold_project deshabilitado."

        ptype = (project_type or "").strip().lower()
        if not ptype:
            return "Error: project_type vacío."

        resolved_dest = resolve_path(destination, must_exist=False)
        if resolved_dest.startswith("Error:"):
            return resolved_dest
        dest = Path(resolved_dest).resolve()
        dest.mkdir(parents=True, exist_ok=True)

        safe_name = re.sub(r"[^\w\-]", "-", (name or "app").strip().lower())[:60] or "app"

        def _need_confirm(msg: str) -> str:
            if confirm:
                return ""
            return (
                "Confirmación requerida: "
                + msg
                + " Repite con confirm=true (y allow_dangerous=true si aplica)."
            )

        # -------------------------------------------------------------------
        # 1) Web estática (sin herramientas externas)
        # -------------------------------------------------------------------
        if ptype == "web_static":
            (dest / "index.html").write_text(
                "<!doctype html>\n"
                "<html lang=\"es\">\n"
                "<head>\n"
                "  <meta charset=\"utf-8\" />\n"
                "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
                f"  <title>{safe_name}</title>\n"
                "  <link rel=\"stylesheet\" href=\"style.css\" />\n"
                "</head>\n"
                "<body>\n"
                "  <main class=\"container\">\n"
                f"    <h1>{safe_name}</h1>\n"
                "    <p>Proyecto creado por JARVIS.</p>\n"
                "    <button id=\"btn\">Probar</button>\n"
                "    <pre id=\"out\"></pre>\n"
                "  </main>\n"
                "  <script src=\"app.js\"></script>\n"
                "</body>\n"
                "</html>\n",
                encoding="utf-8",
            )
            (dest / "style.css").write_text(
                "html, body { height: 100%; }\n"
                "body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; }\n"
                ".container { max-width: 900px; margin: 40px auto; padding: 0 16px; }\n"
                "button { padding: 10px 14px; border-radius: 10px; border: 1px solid #ccc; cursor: pointer; }\n"
                "pre { margin-top: 14px; background: #111; color: #eee; padding: 12px; border-radius: 12px; overflow:auto; }\n",
                encoding="utf-8",
            )
            (dest / "app.js").write_text(
                "const btn = document.querySelector('#btn');\n"
                "const out = document.querySelector('#out');\n"
                "btn.addEventListener('click', () => {\n"
                "  const now = new Date().toISOString();\n"
                "  out.textContent = `OK: ${now}`;\n"
                "});\n",
                encoding="utf-8",
            )
            (dest / "README.md").write_text(
                f"# {safe_name}\n\n"
                "## Ejecutar\n\n"
                "- Abre `index.html` en tu navegador.\n",
                encoding="utf-8",
            )
            return json.dumps(
                {
                    "status": "ok",
                    "project_type": ptype,
                    "destination": str(dest),
                    "run": ["Abrir index.html en el navegador"],
                },
                ensure_ascii=False,
                indent=2,
            )

        # -------------------------------------------------------------------
        # 2) API FastAPI mínima (sin generadores externos)
        # -------------------------------------------------------------------
        if ptype == "api_fastapi":
            app_dir = dest / safe_name
            app_dir.mkdir(parents=True, exist_ok=True)
            (app_dir / "__init__.py").write_text("", encoding="utf-8")
            (app_dir / "main.py").write_text(
                "from fastapi import FastAPI\n\n"
                "app = FastAPI(title=\"jarvis-api\")\n\n"
                "@app.get(\"/health\")\n"
                "def health():\n"
                "    return {\"status\": \"ok\"}\n",
                encoding="utf-8",
            )
            (dest / "requirements.txt").write_text("fastapi>=0.110.0\nuvicorn>=0.27.0\n", encoding="utf-8")
            (dest / "README.md").write_text(
                f"# {safe_name} (FastAPI)\n\n"
                "## Setup\n\n"
                "```bash\n"
                "python -m venv .venv\n"
                ".venv\\Scripts\\activate\n"
                "pip install -r requirements.txt\n"
                "```\n\n"
                "## Run\n\n"
                "```bash\n"
                f"uvicorn {safe_name}.main:app --reload\n"
                "```\n",
                encoding="utf-8",
            )
            return json.dumps(
                {
                    "status": "ok",
                    "project_type": ptype,
                    "destination": str(dest),
                    "run": [f"pip install -r requirements.txt", f"uvicorn {safe_name}.main:app --reload"],
                },
                ensure_ascii=False,
                indent=2,
            )

        # -------------------------------------------------------------------
        # 3) Generadores externos (requieren confirm)
        # -------------------------------------------------------------------
        if ptype in ("web_vite_react", "mobile_expo", "mobile_flutter"):
            msg = _need_confirm(f"Esto ejecuta herramientas externas para crear '{ptype}'.")
            if msg:
                return msg
            if not allow_dangerous:
                return "Error: scaffold_project requiere allow_dangerous=true para ejecutar generadores."

            # Elegimos comandos con paths entre comillas (Windows friendly).
            if ptype == "web_vite_react":
                cmd = f"npm create vite@latest \"{safe_name}\" -- --template react"
                res = run_command_checked(cmd, cwd=str(dest), timeout_seconds=900, allow_dangerous=True)
                return res

            if ptype == "mobile_expo":
                # create-expo-app (Expo) scaffold
                cmd = f"npx create-expo-app@latest \"{safe_name}\""
                res = run_command_checked(cmd, cwd=str(dest), timeout_seconds=1200, allow_dangerous=True)
                return res

            if ptype == "mobile_flutter":
                cmd = f"flutter create \"{safe_name}\""
                res = run_command_checked(cmd, cwd=str(dest), timeout_seconds=1200, allow_dangerous=True)
                return res

        return (
            "Error: project_type no soportado. "
            "Usa: web_static | api_fastapi | web_vite_react | mobile_expo | mobile_flutter"
        )
    except Exception as e:
        return f"Error en scaffold_project: {e}"

