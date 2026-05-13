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

from aaris.tools.core import *

def docker_ps() -> str:
    """Ejecuta docker ps y devuelve el listado de contenedores corriendo."""
    try:
        proc = subprocess.run(["docker", "ps", "--format", "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"], capture_output=True, text=True, timeout=10)
        if proc.returncode != 0: return f"Error: {proc.stderr}"
        return proc.stdout or "No containers running."
    except Exception as e:
        return f"Error en docker_ps (¿Docker está instalado y activo?): {e}"

def docker_logs(container: str, tail: int = 50) -> str:
    """Obtiene las últimas líneas de logs de un contenedor docker."""
    try:
        proc = subprocess.run(["docker", "logs", "--tail", str(tail), container], capture_output=True, text=True, timeout=15)
        return (proc.stdout + proc.stderr) or "(sin logs)"
    except Exception as e:
        return f"Error en docker_logs: {e}"

def docker_exec(container: str, command: str, allow_dangerous: bool = False) -> str:
    """Ejecuta un comando en un contenedor docker en ejecución."""
    try:
        if _policy_require_confirm("docker_exec") and not allow_dangerous:
            return "Error: confirmación o allow_dangerous=true requerido."
        proc = subprocess.run(["docker", "exec", container, "sh", "-c", command], capture_output=True, text=True, timeout=60)
        return (proc.stdout + proc.stderr) or f"Comando ejecutado con código {proc.returncode}."
    except Exception as e:
        return f"Error en docker_exec: {e}"

