"""
JARVIS Knowledge Base Module — Segundo cerebro persistente.

Almacena notas, snippets y bookmarks con tags para búsqueda rápida.
"""

import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional, Any


_JARVIS_DIR = Path(os.environ.get(
    "JARVIS_APP_DIR",
    os.path.join(os.path.expanduser("~"), ".jarvis"),
))

KB_PATH = _JARVIS_DIR / "knowledge_base.json"


def _load_kb() -> list[dict[str, Any]]:
    try:
        if KB_PATH.is_file():
            data = json.loads(KB_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_kb(entries: list[dict[str, Any]]) -> None:
    _JARVIS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = KB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(KB_PATH)


def _auto_tags(content: str) -> list[str]:
    """Genera tags automáticos básicos a partir del contenido."""
    tags = []
    low = content.lower()
    if re.search(r"https?://", low):
        tags.append("url")
    if re.search(r"def |class |function |import |const ", low):
        tags.append("code")
    if re.search(r"\b(server|servidor|ip|port|host)\b", low):
        tags.append("infra")
    if re.search(r"\b(password|contraseña|clave|key|token|secret)\b", low):
        tags.append("security")
    if re.search(r"\b(bug|error|fix|issue)\b", low):
        tags.append("debug")
    if re.search(r"\b(idea|todo|pendiente|tarea)\b", low):
        tags.append("todo")
    return tags


def save_note(
    content: str,
    title: str = "",
    tags: str = "",
) -> str:
    """
    Guarda una nota en la base de conocimiento de JARVIS.

    Args:
        content: Contenido de la nota.
        title: Título opcional. Si vacío, se genera automáticamente.
        tags: Tags separados por comas (ej: 'servidor,producción'). Se auto-detectan tags adicionales.
    """
    try:
        if not content or not content.strip():
            return "Error: contenido vacío."

        entry_id = secrets.token_hex(4)

        # Auto-generar título si no se da
        if not title:
            words = content.strip().split()[:8]
            title = " ".join(words)
            if len(content.strip().split()) > 8:
                title += "..."

        # Tags manuales + automáticos
        manual_tags = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
        auto = _auto_tags(content)
        all_tags = list(set(manual_tags + auto))

        entry = {
            "id": entry_id,
            "type": "note",
            "title": title,
            "content": content.strip(),
            "tags": all_tags,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

        kb = _load_kb()
        kb.append(entry)
        _save_kb(kb)

        return json.dumps({
            "status": "ok",
            "id": entry_id,
            "title": title,
            "tags": all_tags,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en save_note: {e}"


def save_bookmark(
    url: str,
    title: str = "",
    description: str = "",
    tags: str = "",
) -> str:
    """
    Guarda un bookmark (enlace web) en la base de conocimiento.

    Args:
        url: URL del bookmark.
        title: Título opcional.
        description: Descripción opcional.
        tags: Tags separados por comas.
    """
    try:
        if not url or not url.strip():
            return "Error: URL vacía."

        entry_id = secrets.token_hex(4)
        manual_tags = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
        all_tags = list(set(manual_tags + ["bookmark", "url"]))

        entry = {
            "id": entry_id,
            "type": "bookmark",
            "title": title or url,
            "url": url.strip(),
            "description": description,
            "tags": all_tags,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

        kb = _load_kb()
        kb.append(entry)
        _save_kb(kb)

        return json.dumps({
            "status": "ok",
            "id": entry_id,
            "title": entry["title"],
            "tags": all_tags,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en save_bookmark: {e}"


def save_snippet(
    code: str,
    language: str = "",
    title: str = "",
    tags: str = "",
) -> str:
    """
    Guarda un snippet de código en la base de conocimiento.

    Args:
        code: El código a guardar.
        language: Lenguaje de programación (ej: 'python', 'javascript').
        title: Título del snippet.
        tags: Tags separados por comas.
    """
    try:
        if not code or not code.strip():
            return "Error: código vacío."

        entry_id = secrets.token_hex(4)
        manual_tags = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
        all_tags = list(set(manual_tags + ["snippet", "code"] + ([language.lower()] if language else [])))

        entry = {
            "id": entry_id,
            "type": "snippet",
            "title": title or f"Snippet {language or 'code'}",
            "content": code.strip(),
            "language": language.lower() if language else "",
            "tags": all_tags,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

        kb = _load_kb()
        kb.append(entry)
        _save_kb(kb)

        return json.dumps({
            "status": "ok",
            "id": entry_id,
            "title": entry["title"],
            "language": entry["language"],
            "tags": all_tags,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en save_snippet: {e}"


def search_knowledge(
    query: str,
    tag: str = "",
    entry_type: str = "",
    limit: int = 20,
) -> str:
    """
    Busca en la base de conocimiento por texto, tags o tipo.

    Args:
        query: Texto a buscar en título y contenido.
        tag: Filtrar por tag específico.
        entry_type: Filtrar por tipo ('note', 'bookmark', 'snippet').
        limit: Máximo de resultados.
    """
    try:
        kb = _load_kb()
        if not kb:
            return json.dumps({"results": [], "total": 0, "message": "Base de conocimiento vacía."}, ensure_ascii=False)

        results = []
        query_lower = query.strip().lower() if query else ""
        tag_lower = tag.strip().lower() if tag else ""

        for entry in kb:
            # Filtro por tipo
            if entry_type and entry.get("type", "") != entry_type.strip().lower():
                continue

            # Filtro por tag
            if tag_lower and tag_lower not in [t.lower() for t in entry.get("tags", [])]:
                continue

            # Filtro por query
            if query_lower:
                searchable = " ".join([
                    entry.get("title", ""),
                    entry.get("content", ""),
                    entry.get("description", ""),
                    entry.get("url", ""),
                    " ".join(entry.get("tags", [])),
                ]).lower()
                if query_lower not in searchable:
                    continue

            results.append(entry)

        # Ordenar por fecha (más reciente primero)
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        results = results[:limit]

        return json.dumps({
            "results": results,
            "total": len(results),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en search_knowledge: {e}"


def delete_knowledge(entry_id: str, confirm: bool = False) -> str:
    """
    Elimina una entrada de la base de conocimiento.

    Args:
        entry_id: ID de la entrada a eliminar.
        confirm: Requerido para confirmar.
    """
    try:
        if not confirm:
            return f"Confirmación requerida para eliminar '{entry_id}'. Repite con confirm=true."

        kb = _load_kb()
        new_kb = [e for e in kb if e.get("id") != entry_id.strip()]

        if len(new_kb) == len(kb):
            return f"Error: entrada '{entry_id}' no encontrada."

        _save_kb(new_kb)
        return f"Entrada '{entry_id}' eliminada."
    except Exception as e:
        return f"Error en delete_knowledge: {e}"


def list_knowledge_tags() -> str:
    """
    Lista todos los tags usados en la base de conocimiento con su frecuencia.
    """
    try:
        kb = _load_kb()
        tag_count: dict[str, int] = {}
        for entry in kb:
            for tag in entry.get("tags", []):
                tag_count[tag] = tag_count.get(tag, 0) + 1

        sorted_tags = sorted(tag_count.items(), key=lambda x: x[1], reverse=True)

        return json.dumps({
            "tags": [{"tag": t, "count": c} for t, c in sorted_tags],
            "total_tags": len(sorted_tags),
            "total_entries": len(kb),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en list_knowledge_tags: {e}"
