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

from jarvis.tools.core import _read_only_mode, tool_result
from jarvis.tools.filesystem import resolve_path

def list_processes(limit: int = 30) -> str:
    """
    Lista procesos visibles desde /proc con pid y cmdline (limitado).
    """
    try:
        procs = []
        proc_dir = Path("/proc")
        for pid_dir in proc_dir.iterdir():
            if not pid_dir.name.isdigit():
                continue
            pid = int(pid_dir.name)
            cmdline_file = pid_dir / "cmdline"
            try:
                raw = cmdline_file.read_bytes()
                cmd = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
            except Exception:
                cmd = ""
            if not cmd:
                # fallback: comm
                try:
                    cmd = (pid_dir / "comm").read_text(encoding="utf-8", errors="replace").strip()
                except Exception:
                    cmd = ""
            procs.append({"pid": pid, "cmd": cmd[:300]})
            if len(procs) >= limit:
                break
        procs.sort(key=lambda x: x["pid"])
        return json.dumps({"count": len(procs), "processes": procs}, ensure_ascii=False)
    except Exception as e:
        return f"Error en list_processes: {e}"

def validate_python_syntax(path: str) -> str:
    """
    Valida sintaxis Python ejecutando `python -m py_compile`.
    """
    try:
        resolved = resolve_path(path, must_exist=True)
        if resolved.startswith("Error:"):
            return resolved
        p = Path(resolved)
        if not p.is_file():
            return f"Error: {p} no es un archivo."
        import sys
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", str(p)],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ},
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            return f"Error: validación py_compile falló: {msg[:12000]}"
        return f"OK validate_python_syntax: {p}"
    except Exception as e:
        return f"Error en validate_python_syntax: {e}"

def service_status(service_name: str, allow_dangerous: bool = False) -> str:
    """
    Consulta estado de un servicio con systemctl.
    """
    try:
        if not shutil.which("systemctl"):
            return "Error: no existe `systemctl`."
        if not service_name or "/" in service_name:
            return "Error: service_name inválido."
        proc = subprocess.run(
            ["systemctl", "status", service_name, "--no-pager"],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ},
        )
        out = (proc.stdout or "") + (("\n--- stderr ---\n" + proc.stderr) if proc.stderr else "")
        if len(out) > 12000:
            out = out[:12000] + "\n[…truncado…]"
        return out if out.strip() else "(sin salida)"
    except Exception as e:
        return f"Error en service_status: {e}"

def service_restart(
    service_name: str,
    reload: bool = False,
    confirm: bool = False,
    allow_dangerous: bool = False,
) -> str:
    """
    Reinicia un servicio. Requiere confirm=true.
    """
    try:
        if _read_only_mode():
            return "Error: JARVIS_READ_ONLY=true. service_restart deshabilitado."
        if not shutil.which("systemctl"):
            return "Error: no existe `systemctl`."
        if not service_name or "/" in service_name:
            return "Error: service_name inválido."
        if not confirm and not allow_dangerous:
            return "Error: confirm=true requerido para service_restart."
        cmd = ["systemctl", "reload" if reload else "restart", service_name]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ},
        )
        out = (proc.stdout or "") + (("\n--- stderr ---\n" + proc.stderr) if proc.stderr else "")
        exit_note = f"\n[código de salida: {proc.returncode}]"
        return (out if out.strip() else "(sin salida)") + exit_note
    except Exception as e:
        return f"Error en service_restart: {e}"

def service_wait_active(
    service_name: str,
    timeout_seconds: int = 60,
    poll_interval_seconds: float = 1.0,
) -> str:
    """
    Espera a que el servicio esté activo (systemctl is-active).
    """
    try:
        if not shutil.which("systemctl"):
            return "Error: no existe `systemctl`."
        if not service_name or "/" in service_name:
            return "Error: service_name inválido."
        start = time.time()
        while True:
            proc = subprocess.run(
                ["systemctl", "is-active", service_name],
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ},
            )
            out = (proc.stdout or "").strip()
            if out == "active":
                health = service_health_report(service_name)
                return f"OK service_wait_active: {service_name} está activo.\nHealth: {health}"
            if time.time() - start >= timeout_seconds:
                return f"Error: timeout esperando active. Estado actual: {out or '(desconocido)'}"
            time.sleep(poll_interval_seconds)
    except Exception as e:
        return f"Error en service_wait_active: {e}"

def service_health_report(service_name: str, allow_dangerous: bool = False) -> str:
    """
    Devuelve un resumen estructurado del estado del servicio.
    """
    try:
        if not shutil.which("systemctl"):
            return "Error: no existe `systemctl`."
        if not service_name or "/" in service_name:
            return "Error: service_name inválido."
        proc = subprocess.run(
            [
                "systemctl",
                "show",
                service_name,
                "--property=ActiveState,SubState,Result,ExecMainStatus,NRestarts,MainPID",
                "--no-page",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ},
        )
        out = (proc.stdout or "") + (("\n--- stderr ---\n" + proc.stderr) if proc.stderr else "")
        if proc.returncode != 0:
            return "Error en service_health_report:\n" + out[:12000]

        report: dict[str, Any] = {}
        for line in (proc.stdout or "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                report[k.strip()] = v.strip()
        if not report:
            return "Error: no pude leer propiedades de systemctl."
        return json.dumps({"service": service_name, "health": report, "raw": out[:2000]}, ensure_ascii=False)
    except Exception as e:
        return f"Error en service_health_report: {e}"

def service_restart_with_deps(
    service_name: str,
    confirm: bool = False,
    allow_dangerous: bool = False,
    depth: int = 1,
) -> str:
    """
    Reinicia un servicio y sus dependencias más cercanas (1 nivel por defecto).
    """
    try:
        if _read_only_mode():
            return "Error: JARVIS_READ_ONLY=true. service_restart_with_deps deshabilitado."
        if not shutil.which("systemctl"):
            return "Error: no existe `systemctl`."
        if not service_name or "/" in service_name:
            return "Error: service_name inválido."
        if not confirm and not allow_dangerous:
            return "Error: confirm=true requerido para service_restart_with_deps."

        # Solo consideramos units .service para evitar reinicios raros.
        def _get_requires(prop: str) -> list[str]:
            proc = subprocess.run(
                ["systemctl", "show", service_name, f"-p{prop}", "--value", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=20,
                env={**os.environ},
            )
            if proc.returncode != 0:
                return []
            raw = (proc.stdout or "").strip()
            if not raw:
                return []
            units = [u.strip() for u in raw.replace(",", " ").split() if u.strip()]
            return [u for u in units if u.endswith(".service")]

        requires = _get_requires("Requires")
        after = _get_requires("After")
        deps = []
        for u in requires + after:
            if u not in deps and u != service_name:
                deps.append(u)

        # 1 nivel: reiniciamos primero dependencias.
        actions = []
        for d in deps[:50]:
            r = service_restart(d, reload=False, confirm=True, allow_dangerous=allow_dangerous)
            actions.append(f"{d}: {r.splitlines()[0][:200]}")

        main_res = service_restart(service_name, reload=False, confirm=True, allow_dangerous=allow_dangerous)
        return "OK service_restart_with_deps.\nDeps:\n- " + "\n- ".join(actions) + f"\nMain:\n{main_res[:12000]}"
    except Exception as e:
        return f"Error en service_restart_with_deps: {e}"

def run_command(
    command: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 120,
    max_output_chars: int = 24000,
    allow_dangerous: bool = False,
) -> str:
    """
    Ejecuta un comando de shell. Usar con cuidado: el usuario es responsable de lo que ejecuta.
    Devuelve un JSON estructurado (tool_result) con el código de salida y output.
    Si el comando agota el tiempo (timeout), devuelve lo que haya impreso hasta ese momento.
    """
    try:
        if _read_only_mode():
            return tool_result("error", message="JARVIS_READ_ONLY=true. run_command deshabilitado.")

        if not allow_dangerous:
            dangerous_patterns = [
                r"\brm\s+-rf\b", r"\brm\s+-r[f]?\b", r"\bdd\s+if=", r"\bmkfs\w*\b",
                r"\bshutdown\b", r"\breboot\b", r"\bpoweroff\b", r"\bhalt\b",
                r"\bkillall\b.*\b-9\b", r"\bkill\s+-9\b.*\b-1\b", r"\b:(){\s*:|\s*&};\s*:", r"\bxargs\b.*\brm\b"
            ]
            for pat in dangerous_patterns:
                import re
                if re.search(pat, command):
                    return tool_result("error", message="Comando destructivo detectado. Usa allow_dangerous=true para forzar.")

        allowlist_only = os.environ.get("JARVIS_COMMAND_ALLOWLIST_ONLY", "false").strip().lower() in ("1", "true", "yes", "si", "sí", "on")
        if allowlist_only:
            allowlist_raw = os.environ.get("JARVIS_COMMAND_ALLOWLIST", "ls,cat,head,tail,stat,du,df,rg,systemctl,journalctl,ps,pwd,echo,whoami")
            allowed = {x.strip() for x in allowlist_raw.split(",") if x.strip()}
            cmd = (command or "").strip()
            if cmd.startswith("sudo "): cmd = cmd[len("sudo "):].lstrip()
            disallowed_chars = ["|", ";", "&&", "||", ">", "<", "\n", "\r", "`", "$(", "&"]
            for token in disallowed_chars:
                if token in cmd: return tool_result("error", message="JARVIS_COMMAND_ALLOWLIST_ONLY no permite operadores de shell.")
            parts = cmd.split()
            first = parts[0] if parts else ""
            if first and first not in allowed: return tool_result("error", message=f"Comando no permitido: {first}")

        if cwd:
            resolved_cwd = resolve_path(cwd, must_exist=True)
            if resolved_cwd.startswith("Error:"): return tool_result("error", message=resolved_cwd)
            work = os.path.abspath(resolved_cwd)
        else:
            work = None
        if work and not os.path.isdir(work): return tool_result("error", message=f"cwd no es un directorio: {work}")
        
        proc = subprocess.run(
            command,
            shell=True,
            cwd=work,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={**os.environ},
        )
        out = (proc.stdout or "") + (("\n--- stderr ---\n" + proc.stderr) if proc.stderr else "")
        if len(out) > max_output_chars:
            out = out[:max_output_chars] + f"\n[… salida truncada a {max_output_chars} caracteres]"
            
        return tool_result(
            "success" if proc.returncode == 0 else "error",
            data={"stdout": out, "exit_code": proc.returncode},
            message=f"Comando completado con exit code {proc.returncode}"
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "")
        if isinstance(out, bytes): out = out.decode('utf-8', errors='replace')
        err = (e.stderr or "")
        if isinstance(err, bytes): err = err.decode('utf-8', errors='replace')
        combined = out + ("\n--- stderr ---\n" + err if err else "")
        if len(combined) > max_output_chars: combined = combined[:max_output_chars] + "\n[… truncado]"
        
        return tool_result("timeout", data={"stdout": combined, "exit_code": None}, message=f"Comando superó {timeout_seconds}s y fue cancelado. Requiere interacción o está colgado.")
    except Exception as e:
        return tool_result("error", message=f"Error al ejecutar comando: {e}")


def run_command_checked(
    command: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 120,
    max_output_chars: int = 24000,
    allow_dangerous: bool = False,
) -> str:
    """
    Ejecuta comando y devuelve JSON con returncode/stdout/stderr (útil para loops/criterios).
    """
    try:
        if _read_only_mode():
            return tool_result("error", message="JARVIS_READ_ONLY=true. run_command_checked deshabilitado.")

        # run_command ya devuelve un JSON (tool_result), así que simplemente delegamos
        return run_command(
            command=command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
            allow_dangerous=allow_dangerous,
        )
    except Exception as e:
        return tool_result("error", message=f"Error en run_command_checked: {e}")

def run_command_retry(
    command: str,
    attempts: int = 3,
    delay_seconds: float = 1.0,
    cwd: Optional[str] = None,
    timeout_seconds: int = 120,
    max_output_chars: int = 12000,
    allow_dangerous: bool = False,
) -> str:
    """
    Ejecuta un comando varias veces hasta éxito (returncode==0) o agotar intentos.
    """
    try:
        if attempts < 1:
            return "Error: attempts debe ser >= 1."
        last = None
        for i in range(1, attempts + 1):
            res = run_command_checked(
                command=command,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                max_output_chars=max_output_chars,
                allow_dangerous=allow_dangerous,
            )
            last = res
            try:
                obj = json.loads(res)
                rc = obj.get("returncode")
                if rc == 0:
                    return json.dumps({"attempt": i, "result": obj}, ensure_ascii=False)
            except Exception:
                pass
            if i < attempts:
                import time

                time.sleep(delay_seconds)
        return json.dumps({"attempts": attempts, "last_result": json.loads(last) if last else None}, ensure_ascii=False)
    except Exception as e:
        return f"Error en run_command_retry: {e}"

def _sanitize_pkg_token(token: str) -> Optional[str]:
    t = (token or "").strip()
    if not t:
        return None
    # Paquetes típicamente usan [a-zA-Z0-9+._-]
    if not re.match(r"^[a-zA-Z0-9+._:-]+$", t):
        return None
    return t

def install_packages(
    packages: str,
    manager: str = "auto",
    update: bool = False,
    use_sudo: bool = False,
    assume_yes: bool = True,
    confirm: bool = False,
    allow_dangerous: bool = False,
) -> str:
    """
    Instala paquetes del sistema de forma segura (bloquea en modo read-only).

    - `packages`: lista separada por comas/espacios.
    - `confirm`: requerido cuando `update=true` o cuando el modo del sistema lo exija.
    - `allow_dangerous`: si true, permite operaciones más agresivas.
    """
    try:
        if _read_only_mode():
            return "Error: JARVIS_READ_ONLY=true. install_packages deshabilitado."

        tokens = [t.strip() for t in (packages or "").replace(";", ",").replace("|", ",").split(",")]
        tokens = [t for t in tokens if t]
        if len(tokens) == 1 and " " in tokens[0]:
            tokens = [x.strip() for x in tokens[0].split() if x.strip()]

        pkg_tokens: list[str] = []
        for tok in tokens:
            tok_s = _sanitize_pkg_token(tok)
            if tok_s:
                pkg_tokens.append(tok_s)
        if not pkg_tokens:
            return "Error: no pude parsear tokens de paquetes válidos."

        if not confirm and (update or not allow_dangerous):
            return "Error: confirm=true requerido para install_packages (especialmente si update=true)."

        m = (manager or "auto").strip().lower()
        if m == "auto":
            if shutil.which("pacman"):
                m = "pacman"
            elif shutil.which("apt-get"):
                m = "apt"
            elif shutil.which("dnf"):
                m = "dnf"
            elif shutil.which("yum"):
                m = "yum"
            else:
                return "Error: no detecté un gestor de paquetes soportado (pacman/apt/dnf/yum)."

        sudo_prefix: list[str] = ["sudo"] if use_sudo else []
        if m == "pacman":
            cmds: list[list[str]] = []
            if update:
                cmds.append(sudo_prefix + ["pacman", "-Sy", "--noconfirm"])
            cmd_install = sudo_prefix + ["pacman", "-S", "--noconfirm"] + pkg_tokens
            cmds.append(cmd_install)
            outputs = []
            for c in cmds:
                proc = subprocess.run(c, capture_output=True, text=True, timeout=900, env={**os.environ})
                outputs.append(proc.stdout + (("\n--- stderr ---\n" + proc.stderr) if proc.stderr else ""))
                if proc.returncode != 0:
                    return "Error install_packages pacman:\n" + "\n".join(outputs)
            return "OK install_packages pacman.\n" + "\n".join(outputs)[:24000]

        if m == "apt":
            cmds = []
            if update:
                cmds.append(sudo_prefix + ["apt-get", "update", "-y"])
            # apt-get install -y requiere -y
            install_cmd = sudo_prefix + ["apt-get", "install"]
            if assume_yes:
                install_cmd.append("-y")
            install_cmd += pkg_tokens
            cmds.append(install_cmd)

            outputs = []
            for c in cmds:
                proc = subprocess.run(c, capture_output=True, text=True, timeout=900, env={**os.environ})
                outputs.append(proc.stdout + (("\n--- stderr ---\n" + proc.stderr) if proc.stderr else ""))
                if proc.returncode != 0:
                    return "Error install_packages apt:\n" + "\n".join(outputs)
            return "OK install_packages apt.\n" + "\n".join(outputs)[:24000]

        return f"Error: gestor no soportado: {m}"
    except Exception as e:
        return f"Error en install_packages: {e}"

