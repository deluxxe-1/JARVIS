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

def build_text_index(
    root: str = ".",
    exts: Optional[str] = None,
    max_files: int = 400,
    max_chars_per_file: int = 20000,
    index_path: Optional[str] = None,
) -> str:
    """
    Construye un índice local de texto (RAG sin embeddings) con caché.
    """
    try:
        if _read_only_mode():
            return "Error: JARVIS_READ_ONLY=true. build_text_index deshabilitado."

        resolved_root = resolve_path(root, must_exist=True)
        if resolved_root.startswith("Error:"):
            return resolved_root
        base = Path(resolved_root).resolve()

        if index_path is None:
            index_path = os.path.join(os.getcwd(), ".jarvis", "rag_text_index.json")
        index_path = os.path.abspath(os.path.expanduser(index_path))
        Path(os.path.dirname(index_path)).mkdir(parents=True, exist_ok=True)

        allowed_exts: Optional[set[str]] = None
        if exts:
            allowed_exts = {e.strip().lower() for e in exts.split(",") if e.strip()}

        entries: list[dict[str, Any]] = []
        count = 0
        for p in base.rglob("*"):
            if count >= max_files:
                break
            if p.is_dir():
                continue
            if allowed_exts is not None and p.suffix.lower() not in allowed_exts:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if len(text) > max_chars_per_file:
                text = text[:max_chars_per_file] + "\n[…truncado…]"
            try:
                st = p.stat()
                mtime = st.st_mtime
                size = st.st_size
            except Exception:
                mtime = 0.0
                size = 0

            entries.append(
                {
                    "path": str(p),
                    "size": size,
                    "mtime": mtime,
                    "text_excerpt": text,
                }
            )
            count += 1

        payload = {
            "root": str(base),
            "created_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "exts": exts,
            "max_files": max_files,
            "max_chars_per_file": max_chars_per_file,
            "entries": entries,
        }
        Path(index_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return f"OK build_text_index. entries={len(entries)} index={index_path}"
    except Exception as e:
        return f"Error en build_text_index: {e}"

def rag_query(
    query: str,
    index_path: Optional[str] = None,
    top_k: int = 6,
    max_excerpt_chars: int = 4000,
) -> str:
    """
    Consulta RAG local contra un índice de texto cacheado.
    """
    try:
        if not query or not query.strip():
            return "Error: query vacía."
        if index_path is None:
            index_path = os.path.join(os.getcwd(), ".jarvis", "rag_text_index.json")
        index_path = os.path.abspath(os.path.expanduser(index_path))
        if not os.path.isfile(index_path):
            return "Error: no existe el índice. Ejecuta build_text_index primero."
        payload = json.loads(Path(index_path).read_text(encoding="utf-8"))
        entries = payload.get("entries") or []
        qn = _norm_text(query)

        scored: list[tuple[float, dict[str, Any]]] = []
        for ent in entries:
            text_excerpt = ent.get("text_excerpt") or ""
            name_score = difflib.SequenceMatcher(None, qn, _norm_text(Path(ent.get("path") or "").name)).ratio()
            text_score = difflib.SequenceMatcher(None, qn, _norm_text(text_excerpt[:20000])).ratio()
            score = max(name_score, text_score)
            if score >= 0.15:
                scored.append((score, ent))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]
        if not top:
            return "Sin coincidencias en índice."
        out = []
        for score, ent in top:
            excerpt = ent.get("text_excerpt") or ""
            if len(excerpt) > max_excerpt_chars:
                excerpt = excerpt[:max_excerpt_chars] + "\n[…truncado…]"
            out.append({"score": score, "path": ent.get("path"), "excerpt": excerpt})
        return json.dumps({"top_k": top_k, "results": out}, ensure_ascii=False)
    except Exception as e:
        return f"Error en rag_query: {e}"

