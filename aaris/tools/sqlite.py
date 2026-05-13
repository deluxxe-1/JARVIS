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

def db_query_sqlite(db_path: str, query: str) -> str:
    """Ejecuta una consulta SQL en una base de datos SQLite (.db, .sqlite)."""
    try:
        import sqlite3
        resolved = resolve_path(db_path, must_exist=True)
        if resolved.startswith("Error:"): return resolved
        if _read_only_mode() and not query.strip().upper().startswith("SELECT"):
            return "Error: AARIS_READ_ONLY=true, solo SELECT está permitido."
            
        with sqlite3.connect(resolved) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query)
            if query.strip().upper().startswith("SELECT"):
                rows = cursor.fetchall()
                if not rows: return "0 results."
                res = [dict(r) for r in rows]
                return json.dumps(res, ensure_ascii=False)[:24000]
            else:
                conn.commit()
                return f"Affected rows: {cursor.rowcount}"
    except Exception as e:
        return f"Error en db_query_sqlite: {e}"

