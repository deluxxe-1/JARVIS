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

def delegate_task(prompt: str) -> str:
    """Delega una tarea a una nueva instancia del agente ejecutando main.py --run-prompt."""
    try:
        agent_script = str(Path(__file__).resolve().parent / "main.py")
        import sys
        proc = subprocess.run(
            [sys.executable, agent_script, "--run-prompt", prompt],
            capture_output=True, text=True, timeout=300, env={**os.environ}
        )
        out = proc.stdout + proc.stderr
        return f"Delegado ejecutado (código {proc.returncode}). Salida:\n{out[-12000:]}"
    except Exception as e:
        return f"Error en delegate_task: {e}"

def schedule_agent_task(cron_expr: str, prompt: str, task_name: str) -> str:
    """Crea una tarea programada usando crontab del usuario para lanzar el agente."""
    try:
        agent_script = str(Path(__file__).resolve().parent / "main.py")
        import shlex, sys
        prompt_q = shlex.quote(prompt)
        command = f"{sys.executable} {agent_script} --run-prompt {prompt_q} >> ~/.aaris/cron.log 2>&1"
        cron_line = f"{cron_expr} {command}\n"
        
        cron_file = Path.home() / ".aaris" / "crontab.txt"
        cron_file.parent.mkdir(parents=True, exist_ok=True)
        
        proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        current_cron = proc.stdout if proc.returncode == 0 else ""
        
        if cron_line in current_cron:
            return f"Tarea '{task_name}' ya estaba programada."
            
        new_cron = current_cron.strip() + "\n" + f"# AARIS_TASK: {task_name}\n{cron_line}"
        cron_file.write_text(new_cron, encoding="utf-8")
        
        apply_proc = subprocess.run(["crontab", str(cron_file)], capture_output=True, text=True)
        if apply_proc.returncode != 0:
            return f"Error aplicando crontab (fallback cron no disponible): {apply_proc.stderr}"
        return f"Tarea '{task_name}' programada exitosamente con cron '{cron_expr}'."
    except Exception as e:
        return f"Error en schedule_agent_task: {e}"

