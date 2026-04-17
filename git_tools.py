"""
JARVIS Git Assistant Module — Operaciones inteligentes de Git.

Analiza repos, genera commits con IA, gestiona ramas y describe PRs.
"""

import json
import os
import re
import subprocess
import sys
from typing import Optional


def _run_git(args: list[str], cwd: Optional[str] = None) -> tuple[int, str, str]:
    """Ejecuta un comando git y devuelve (returncode, stdout, stderr)."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, timeout=30,
            cwd=cwd or os.getcwd(),
            **kwargs,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", "Error: git no está instalado."
    except subprocess.TimeoutExpired:
        return -1, "", "Error: comando git excedió timeout."


def _is_git_repo(cwd: Optional[str] = None) -> bool:
    """Comprueba si estamos dentro de un repo git."""
    rc, _, _ = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    return rc == 0


def git_status(path: Optional[str] = None) -> str:
    """
    Muestra el estado del repositorio Git (archivos modificados, staged, untracked).

    Args:
        path: Ruta del repositorio. Si vacío, usa el directorio actual.
    """
    try:
        cwd = os.path.abspath(os.path.expanduser(path)) if path else None
        if not _is_git_repo(cwd):
            return "Error: no estás dentro de un repositorio Git."

        rc, out, err = _run_git(["status", "--porcelain=v1", "-b"], cwd)
        if rc != 0:
            return f"Error: {err}"

        lines = out.split("\n") if out else []
        branch = ""
        staged = []
        modified = []
        untracked = []

        for line in lines:
            if line.startswith("##"):
                branch = line[3:]
                continue
            if len(line) < 2:
                continue
            x, y = line[0], line[1]
            fname = line[3:]
            if x in ("A", "M", "D", "R"):
                staged.append({"file": fname, "action": x})
            if y == "M":
                modified.append(fname)
            elif y == "?":
                untracked.append(fname)

        return json.dumps({
            "status": "ok",
            "branch": branch,
            "staged": staged,
            "modified": modified,
            "untracked": untracked,
            "clean": len(staged) == 0 and len(modified) == 0 and len(untracked) == 0,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en git_status: {e}"


def git_diff(path: Optional[str] = None, staged: bool = False) -> str:
    """
    Muestra los cambios (diff) del repositorio.

    Args:
        path: Ruta del repositorio.
        staged: Si True, muestra solo cambios staged (listos para commit).
    """
    try:
        cwd = os.path.abspath(os.path.expanduser(path)) if path else None
        if not _is_git_repo(cwd):
            return "Error: no estás dentro de un repositorio Git."

        args = ["diff", "--stat"]
        if staged:
            args.append("--cached")

        rc, out, err = _run_git(args, cwd)
        if rc != 0:
            return f"Error: {err}"

        # También obtener diff completo pero truncado
        args2 = ["diff"]
        if staged:
            args2.append("--cached")
        rc2, full_diff, _ = _run_git(args2, cwd)

        return json.dumps({
            "status": "ok",
            "summary": out or "Sin cambios.",
            "diff": full_diff[:8000] if full_diff else "Sin cambios.",
            "truncated": len(full_diff) > 8000 if full_diff else False,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en git_diff: {e}"


def git_smart_commit(
    message: Optional[str] = None,
    add_all: bool = True,
    path: Optional[str] = None,
) -> str:
    """
    Hace commit inteligente. Si no se da mensaje, genera uno automático analizando los cambios.

    Args:
        message: Mensaje de commit. Si vacío, se auto-genera con el LLM.
        add_all: Si True, hace `git add .` antes del commit.
        path: Ruta del repositorio.
    """
    try:
        cwd = os.path.abspath(os.path.expanduser(path)) if path else None
        if not _is_git_repo(cwd):
            return "Error: no estás dentro de un repositorio Git."

        if add_all:
            _run_git(["add", "."], cwd)

        # Verificar que hay algo para commitear
        rc, status_out, _ = _run_git(["status", "--porcelain"], cwd)
        if not status_out.strip():
            return "No hay cambios para commitear."

        if not message:
            # Generar mensaje basado en diff
            _, diff_out, _ = _run_git(["diff", "--cached", "--stat"], cwd)
            _, diff_full, _ = _run_git(["diff", "--cached"], cwd)
            diff_text = diff_full[:4000] if diff_full else diff_out

            try:
                from ollama import chat
                response = chat(
                    model=os.environ.get("OLLAMA_MODEL", "qwen2.5:14b"),
                    messages=[{
                        "role": "user",
                        "content": (
                            "Genera un mensaje de commit conciso y descriptivo (máx 72 chars la primera línea) "
                            "para estos cambios. Solo devuelve el mensaje, nada más:\n\n"
                            f"{diff_text}"
                        ),
                    }],
                    options={"temperature": 0.3},
                )
                message = response["message"].get("content", "").strip()
                # Limpiar comillas si las añade
                message = message.strip('"').strip("'").strip("`")
            except Exception:
                message = f"Update: {len(status_out.splitlines())} files changed"

        rc, out, err = _run_git(["commit", "-m", message], cwd)
        if rc != 0:
            return f"Error en commit: {err}"

        return json.dumps({
            "status": "ok",
            "message": message,
            "output": out[:1000],
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en git_smart_commit: {e}"


def git_log(count: int = 10, path: Optional[str] = None) -> str:
    """
    Muestra el historial de commits reciente.

    Args:
        count: Número de commits a mostrar (máx 50).
        path: Ruta del repositorio.
    """
    try:
        cwd = os.path.abspath(os.path.expanduser(path)) if path else None
        if not _is_git_repo(cwd):
            return "Error: no estás dentro de un repositorio Git."

        count = min(max(1, count), 50)
        rc, out, err = _run_git(
            ["log", f"-{count}", "--pretty=format:%h|%an|%ar|%s"],
            cwd,
        )
        if rc != 0:
            return f"Error: {err}"

        commits = []
        for line in out.split("\n"):
            if "|" in line:
                parts = line.split("|", 3)
                if len(parts) == 4:
                    commits.append({
                        "hash": parts[0],
                        "author": parts[1],
                        "time": parts[2],
                        "message": parts[3],
                    })

        return json.dumps({
            "status": "ok",
            "commits": commits,
            "count": len(commits),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en git_log: {e}"


def git_branch(
    action: str = "list",
    name: str = "",
    path: Optional[str] = None,
) -> str:
    """
    Gestión de ramas Git.

    Args:
        action: 'list' | 'create' | 'switch' | 'delete'.
        name: Nombre de la rama (requerido para create/switch/delete).
        path: Ruta del repositorio.
    """
    try:
        cwd = os.path.abspath(os.path.expanduser(path)) if path else None
        if not _is_git_repo(cwd):
            return "Error: no estás dentro de un repositorio Git."

        action = action.strip().lower()

        if action == "list":
            rc, out, err = _run_git(["branch", "-a"], cwd)
            if rc != 0:
                return f"Error: {err}"
            branches = [b.strip() for b in out.split("\n") if b.strip()]
            current = next((b[2:] for b in branches if b.startswith("*")), "")
            return json.dumps({
                "status": "ok",
                "current": current,
                "branches": [b.lstrip("* ") for b in branches],
            }, ensure_ascii=False)

        if not name:
            return f"Error: se requiere nombre de rama para '{action}'."

        if action == "create":
            rc, out, err = _run_git(["checkout", "-b", name], cwd)
        elif action == "switch":
            rc, out, err = _run_git(["checkout", name], cwd)
        elif action == "delete":
            rc, out, err = _run_git(["branch", "-d", name], cwd)
        else:
            return f"Error: acción '{action}' no válida. Usa: list, create, switch, delete."

        if rc != 0:
            return f"Error: {err}"
        return json.dumps({"status": "ok", "action": action, "branch": name, "output": out}, ensure_ascii=False)
    except Exception as e:
        return f"Error en git_branch: {e}"


def git_describe_pr(path: Optional[str] = None, base: str = "main") -> str:
    """
    Genera automáticamente una descripción de Pull Request basada en los commits
    entre la rama actual y la rama base.

    Args:
        path: Ruta del repositorio.
        base: Rama base del PR (default: 'main').
    """
    try:
        cwd = os.path.abspath(os.path.expanduser(path)) if path else None
        if not _is_git_repo(cwd):
            return "Error: no estás dentro de un repositorio Git."

        # Obtener rama actual
        _, current_branch, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)

        # Obtener commits entre base y HEAD
        rc, log_out, _ = _run_git(
            ["log", f"{base}..HEAD", "--pretty=format:%s"],
            cwd,
        )
        commits_text = log_out if rc == 0 else "No se pudieron obtener commits."

        # Obtener diff stat
        rc2, diff_stat, _ = _run_git(["diff", f"{base}..HEAD", "--stat"], cwd)

        try:
            from ollama import chat
            response = chat(
                model=os.environ.get("OLLAMA_MODEL", "qwen2.5:14b"),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Genera una descripción de Pull Request para mergear '{current_branch}' en '{base}'.\n"
                        f"Commits:\n{commits_text}\n\nArchivos cambiados:\n{diff_stat}\n\n"
                        "Formato: título, descripción, lista de cambios, notas."
                    ),
                }],
                options={"temperature": 0.4},
            )
            description = response["message"].get("content", "").strip()
        except Exception:
            description = f"## {current_branch} → {base}\n\n### Commits\n{commits_text}\n\n### Archivos\n{diff_stat}"

        return json.dumps({
            "status": "ok",
            "branch": current_branch,
            "base": base,
            "description": description,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en git_describe_pr: {e}"
