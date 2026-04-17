"""
JARVIS Obsidian Module — Integración con vault de Obsidian.

Permite a JARVIS crear, leer, buscar y gestionar notas en formato Markdown
con frontmatter YAML. Compatible al 100% con Obsidian, Logseq y cualquier
editor Markdown.

Estructura del vault:
    vault/
    ├── Daily/          ← Notas diarias
    ├── Notes/          ← Notas generales
    ├── Bookmarks/      ← URLs guardadas
    ├── Snippets/       ← Fragmentos de código
    ├── Projects/       ← Notas de proyectos
    └── _index.json     ← Cache de índice para búsquedas rápidas
"""

import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional, Any


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

_JARVIS_DIR = Path(os.environ.get(
    "JARVIS_APP_DIR",
    os.path.join(os.path.expanduser("~"), ".jarvis"),
))

VAULT_PATH = Path(os.environ.get(
    "JARVIS_OBSIDIAN_VAULT",
    str(_JARVIS_DIR / "vault"),
))

_INDEX_PATH = VAULT_PATH / "_index.json"

# Carpetas del vault
_FOLDERS = {
    "note": "Notes",
    "bookmark": "Bookmarks",
    "snippet": "Snippets",
    "project": "Projects",
    "daily": "Daily",
}


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _ensure_vault() -> None:
    """Crea la estructura del vault si no existe."""
    VAULT_PATH.mkdir(parents=True, exist_ok=True)
    for folder in _FOLDERS.values():
        (VAULT_PATH / folder).mkdir(exist_ok=True)
    # Crear config mínima de Obsidian si no existe
    obsidian_dir = VAULT_PATH / ".obsidian"
    if not obsidian_dir.exists():
        obsidian_dir.mkdir(exist_ok=True)
        app_config = {
            "alwaysUpdateLinks": True,
            "newFileLocation": "folder",
            "newFileFolderPath": "Notes",
            "showUnsupportedFiles": False,
            "defaultViewMode": "preview",
        }
        (obsidian_dir / "app.json").write_text(
            json.dumps(app_config, indent=2), encoding="utf-8"
        )


def _sanitize_filename(title: str) -> str:
    """Convierte un título en un nombre de archivo seguro."""
    # Eliminar caracteres no válidos para nombres de archivo
    safe = re.sub(r'[<>:"/\\|?*]', '', title)
    safe = safe.strip('. ')
    if not safe:
        safe = f"nota_{secrets.token_hex(3)}"
    # Limitar longitud
    if len(safe) > 100:
        safe = safe[:100].rstrip()
    return safe


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extrae el frontmatter YAML y el cuerpo de un archivo Markdown."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter_raw = parts[1].strip()
    body = parts[2].strip()

    # Parser YAML básico (sin dependencia externa)
    meta: dict[str, Any] = {}
    for line in frontmatter_raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ": " in line:
            key, value = line.split(": ", 1)
            key = key.strip()
            value = value.strip()
            # Parsear listas YAML simples [a, b, c]
            if value.startswith("[") and value.endswith("]"):
                items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
                meta[key] = items
            elif value.lower() in ("true", "false"):
                meta[key] = value.lower() == "true"
            elif value.isdigit():
                meta[key] = int(value)
            else:
                meta[key] = value.strip("'\"")

    return meta, body


def _build_frontmatter(meta: dict[str, Any]) -> str:
    """Construye el bloque frontmatter YAML."""
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, list):
            formatted = ", ".join(str(v) for v in value)
            lines.append(f"{key}: [{formatted}]")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def _build_note_content(meta: dict[str, Any], title: str, body: str) -> str:
    """Construye el contenido completo de una nota (.md)."""
    frontmatter = _build_frontmatter(meta)
    return f"{frontmatter}\n\n# {title}\n\n{body}\n"


def _load_index() -> list[dict[str, Any]]:
    """Carga el índice del vault."""
    try:
        if _INDEX_PATH.is_file():
            data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_index(entries: list[dict[str, Any]]) -> None:
    """Guarda el índice del vault."""
    _ensure_vault()
    tmp = _INDEX_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_INDEX_PATH)


def _rebuild_index() -> list[dict[str, Any]]:
    """Reconstruye el índice escaneando todos los .md del vault."""
    _ensure_vault()
    entries = []
    for md_file in VAULT_PATH.rglob("*.md"):
        # Saltar archivos en .obsidian
        if ".obsidian" in md_file.parts:
            continue
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
            meta, body = _parse_frontmatter(content)
            rel_path = str(md_file.relative_to(VAULT_PATH)).replace("\\", "/")
            entries.append({
                "id": meta.get("id", secrets.token_hex(4)),
                "title": meta.get("title", md_file.stem),
                "type": meta.get("type", "note"),
                "tags": meta.get("tags", []),
                "created": meta.get("created", ""),
                "modified": meta.get("modified", ""),
                "path": rel_path,
            })
        except Exception:
            continue

    _save_index(entries)
    return entries


def _add_to_index(entry: dict[str, Any]) -> None:
    """Añade una entrada al índice."""
    index = _load_index()
    # Eliminar entrada antigua con el mismo path si existe
    index = [e for e in index if e.get("path") != entry.get("path")]
    index.append(entry)
    _save_index(index)


def _remove_from_index(path: str) -> None:
    """Elimina una entrada del índice por path."""
    index = _load_index()
    index = [e for e in index if e.get("path") != path]
    _save_index(index)


# ---------------------------------------------------------------------------
# Funciones públicas (herramientas de JARVIS)
# ---------------------------------------------------------------------------

def obsidian_create_note(
    content: str,
    title: str = "",
    tags: str = "",
    note_type: str = "note",
    folder: str = "",
) -> str:
    """
    Crea una nota en el vault de Obsidian como archivo Markdown con frontmatter YAML.

    Args:
        content: Contenido de la nota (Markdown).
        title: Título de la nota. Si vacío, se genera automáticamente.
        tags: Tags separados por comas (ej: 'proyecto,idea,python').
        note_type: Tipo de nota: 'note', 'bookmark', 'snippet', 'project'.
        folder: Carpeta dentro del vault. Si vacío, se determina por note_type.
    """
    try:
        if not content or not content.strip():
            return "Error: contenido vacío."

        _ensure_vault()
        entry_id = secrets.token_hex(4)
        now = datetime.now().isoformat(timespec="seconds")

        # Auto-generar título
        if not title:
            words = content.strip().split()[:8]
            title = " ".join(words)
            if len(content.strip().split()) > 8:
                title += "..."

        # Tags
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []

        # Determinar carpeta
        if not folder:
            folder = _FOLDERS.get(note_type.strip().lower(), "Notes")

        target_dir = VAULT_PATH / folder
        target_dir.mkdir(parents=True, exist_ok=True)

        # Nombre del archivo
        filename = _sanitize_filename(title) + ".md"
        file_path = target_dir / filename

        # Si ya existe, añadir sufijo
        counter = 1
        while file_path.exists():
            filename = f"{_sanitize_filename(title)} ({counter}).md"
            file_path = target_dir / filename
            counter += 1

        # Frontmatter
        meta = {
            "id": entry_id,
            "title": title,
            "type": note_type.strip().lower(),
            "tags": tag_list,
            "created": now,
            "modified": now,
        }

        # Escribir archivo
        full_content = _build_note_content(meta, title, content.strip())
        file_path.write_text(full_content, encoding="utf-8")

        # Actualizar índice
        rel_path = str(file_path.relative_to(VAULT_PATH)).replace("\\", "/")
        _add_to_index({
            "id": entry_id,
            "title": title,
            "type": note_type.strip().lower(),
            "tags": tag_list,
            "created": now,
            "modified": now,
            "path": rel_path,
        })

        return json.dumps({
            "status": "ok",
            "id": entry_id,
            "title": title,
            "path": rel_path,
            "full_path": str(file_path),
            "tags": tag_list,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en obsidian_create_note: {e}"


def obsidian_read_note(
    title: str = "",
    path: str = "",
) -> str:
    """
    Lee una nota del vault por título o ruta relativa.

    Args:
        title: Parte del título de la nota a buscar.
        path: Ruta relativa dentro del vault (ej: 'Notes/Mi nota.md').
    """
    try:
        _ensure_vault()

        if path:
            file_path = VAULT_PATH / path.replace("/", os.sep)
            if not file_path.is_file():
                return f"Error: no existe la nota: {path}"
            content = file_path.read_text(encoding="utf-8", errors="replace")
            meta, body = _parse_frontmatter(content)
            return json.dumps({
                "status": "ok",
                "title": meta.get("title", file_path.stem),
                "path": path,
                "meta": meta,
                "content": body[:20000],
            }, ensure_ascii=False)

        if title:
            title_lower = title.strip().lower()
            for md_file in VAULT_PATH.rglob("*.md"):
                if ".obsidian" in md_file.parts:
                    continue
                if title_lower in md_file.stem.lower():
                    content = md_file.read_text(encoding="utf-8", errors="replace")
                    meta, body = _parse_frontmatter(content)
                    rel_path = str(md_file.relative_to(VAULT_PATH)).replace("\\", "/")
                    return json.dumps({
                        "status": "ok",
                        "title": meta.get("title", md_file.stem),
                        "path": rel_path,
                        "meta": meta,
                        "content": body[:20000],
                    }, ensure_ascii=False)
            return f"Error: no se encontró nota con título '{title}'."

        return "Error: especifica title o path."
    except Exception as e:
        return f"Error en obsidian_read_note: {e}"


def obsidian_search(
    query: str = "",
    tag: str = "",
    note_type: str = "",
    limit: int = 20,
) -> str:
    """
    Busca notas en el vault de Obsidian por texto, tags o tipo.

    Args:
        query: Texto a buscar en título y contenido.
        tag: Filtrar por tag específico.
        note_type: Filtrar por tipo ('note', 'bookmark', 'snippet', 'project').
        limit: Máximo de resultados.
    """
    try:
        _ensure_vault()

        query_lower = query.strip().lower() if query else ""
        tag_lower = tag.strip().lower() if tag else ""
        type_lower = note_type.strip().lower() if note_type else ""

        results = []

        for md_file in VAULT_PATH.rglob("*.md"):
            if ".obsidian" in md_file.parts:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                meta, body = _parse_frontmatter(content)

                # Filtro por tipo
                if type_lower and meta.get("type", "note") != type_lower:
                    continue

                # Filtro por tag
                if tag_lower:
                    note_tags = [t.lower() for t in meta.get("tags", [])]
                    if tag_lower not in note_tags:
                        continue

                # Filtro por query
                if query_lower:
                    searchable = " ".join([
                        meta.get("title", md_file.stem),
                        body,
                        " ".join(str(t) for t in meta.get("tags", [])),
                    ]).lower()
                    if query_lower not in searchable:
                        continue

                rel_path = str(md_file.relative_to(VAULT_PATH)).replace("\\", "/")
                results.append({
                    "title": meta.get("title", md_file.stem),
                    "type": meta.get("type", "note"),
                    "tags": meta.get("tags", []),
                    "created": meta.get("created", ""),
                    "path": rel_path,
                    "preview": body[:200] if body else "",
                })
            except Exception:
                continue

        # Ordenar por fecha (más reciente primero)
        results.sort(key=lambda x: x.get("created", ""), reverse=True)
        results = results[:limit]

        return json.dumps({
            "query": query,
            "tag": tag,
            "type": note_type,
            "results": results,
            "total": len(results),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en obsidian_search: {e}"


def obsidian_list_notes(
    folder: str = "",
    limit: int = 30,
) -> str:
    """
    Lista las notas del vault de Obsidian.

    Args:
        folder: Carpeta a listar (ej: 'Notes', 'Daily', 'Bookmarks'). Si vacío, lista todo.
        limit: Máximo de resultados.
    """
    try:
        _ensure_vault()
        base = VAULT_PATH / folder if folder else VAULT_PATH

        if not base.is_dir():
            return f"Error: carpeta '{folder}' no existe en el vault."

        notes = []
        for md_file in base.rglob("*.md"):
            if ".obsidian" in md_file.parts:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                meta, _ = _parse_frontmatter(content)
                rel_path = str(md_file.relative_to(VAULT_PATH)).replace("\\", "/")
                notes.append({
                    "title": meta.get("title", md_file.stem),
                    "type": meta.get("type", "note"),
                    "tags": meta.get("tags", []),
                    "created": meta.get("created", ""),
                    "path": rel_path,
                    "size_bytes": md_file.stat().st_size,
                })
            except Exception:
                continue

        notes.sort(key=lambda x: x.get("created", ""), reverse=True)
        notes = notes[:limit]

        folders_available = [
            d.name for d in VAULT_PATH.iterdir()
            if d.is_dir() and d.name != ".obsidian" and not d.name.startswith("_")
        ]

        return json.dumps({
            "status": "ok",
            "folder": folder or "(todo el vault)",
            "notes": notes,
            "total": len(notes),
            "vault_path": str(VAULT_PATH),
            "folders": folders_available,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en obsidian_list_notes: {e}"


def obsidian_daily_note(
    content: str = "",
    date: str = "",
) -> str:
    """
    Crea o actualiza la nota diaria en el vault. Si ya existe, añade contenido al final.

    Args:
        content: Contenido a añadir a la nota diaria. Si vacío, solo crea/devuelve la nota.
        date: Fecha en formato YYYY-MM-DD. Si vacío, usa la fecha de hoy.
    """
    try:
        _ensure_vault()

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        daily_dir = VAULT_PATH / "Daily"
        daily_dir.mkdir(exist_ok=True)
        file_path = daily_dir / f"{date}.md"

        weekdays_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            weekday = weekdays_es[dt.weekday()]
        except Exception:
            weekday = ""

        if file_path.exists():
            existing = file_path.read_text(encoding="utf-8", errors="replace")
            if content and content.strip():
                now = datetime.now().strftime("%H:%M")
                entry = f"\n\n## {now}\n\n{content.strip()}\n"
                updated = existing + entry
                file_path.write_text(updated, encoding="utf-8")
                action = "updated"
            else:
                action = "exists"
        else:
            # Crear nueva nota diaria
            now_iso = datetime.now().isoformat(timespec="seconds")
            meta = {
                "type": "daily",
                "date": date,
                "created": now_iso,
                "modified": now_iso,
                "tags": ["daily"],
            }
            title = f"📅 {weekday} {date}" if weekday else f"📅 {date}"
            body = ""
            if content and content.strip():
                now_time = datetime.now().strftime("%H:%M")
                body = f"## {now_time}\n\n{content.strip()}"

            full = _build_note_content(meta, title, body)
            file_path.write_text(full, encoding="utf-8")
            action = "created"

            # Añadir al índice
            _add_to_index({
                "id": secrets.token_hex(4),
                "title": title,
                "type": "daily",
                "tags": ["daily"],
                "created": now_iso,
                "modified": now_iso,
                "path": f"Daily/{date}.md",
            })

        rel_path = f"Daily/{date}.md"
        return json.dumps({
            "status": "ok",
            "action": action,
            "date": date,
            "weekday": weekday,
            "path": rel_path,
            "full_path": str(file_path),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en obsidian_daily_note: {e}"


def obsidian_append_to_note(
    title: str,
    content: str,
) -> str:
    """
    Añade contenido al final de una nota existente en el vault.

    Args:
        title: Parte del título de la nota.
        content: Contenido a añadir (Markdown).
    """
    try:
        if not content or not content.strip():
            return "Error: contenido vacío."

        _ensure_vault()
        title_lower = title.strip().lower()

        for md_file in VAULT_PATH.rglob("*.md"):
            if ".obsidian" in md_file.parts:
                continue
            if title_lower in md_file.stem.lower():
                existing = md_file.read_text(encoding="utf-8", errors="replace")
                updated = existing.rstrip() + "\n\n" + content.strip() + "\n"
                md_file.write_text(updated, encoding="utf-8")

                # Actualizar modified en frontmatter
                meta, body = _parse_frontmatter(updated)
                if meta:
                    meta["modified"] = datetime.now().isoformat(timespec="seconds")
                    full = _build_frontmatter(meta) + "\n\n" + body + "\n"
                    md_file.write_text(full, encoding="utf-8")

                rel_path = str(md_file.relative_to(VAULT_PATH)).replace("\\", "/")
                return json.dumps({
                    "status": "ok",
                    "title": md_file.stem,
                    "path": rel_path,
                    "appended_chars": len(content.strip()),
                }, ensure_ascii=False)

        return f"Error: no se encontró nota con título '{title}'."
    except Exception as e:
        return f"Error en obsidian_append_to_note: {e}"


def obsidian_delete_note(
    title: str = "",
    path: str = "",
    confirm: bool = False,
) -> str:
    """
    Elimina una nota del vault.

    Args:
        title: Parte del título de la nota a eliminar.
        path: Ruta relativa dentro del vault.
        confirm: Requerido para confirmar la eliminación.
    """
    try:
        if not confirm:
            return "Confirmación requerida. Repite con confirm=true."

        _ensure_vault()

        file_path = None

        if path:
            file_path = VAULT_PATH / path.replace("/", os.sep)
        elif title:
            title_lower = title.strip().lower()
            for md_file in VAULT_PATH.rglob("*.md"):
                if ".obsidian" in md_file.parts:
                    continue
                if title_lower in md_file.stem.lower():
                    file_path = md_file
                    break

        if not file_path or not file_path.is_file():
            return f"Error: no se encontró la nota."

        rel_path = str(file_path.relative_to(VAULT_PATH)).replace("\\", "/")
        file_path.unlink()
        _remove_from_index(rel_path)

        return json.dumps({
            "status": "ok",
            "deleted": rel_path,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en obsidian_delete_note: {e}"


def obsidian_list_tags() -> str:
    """
    Lista todos los tags usados en el vault con su frecuencia.
    """
    try:
        _ensure_vault()
        tag_count: dict[str, int] = {}
        total_notes = 0

        for md_file in VAULT_PATH.rglob("*.md"):
            if ".obsidian" in md_file.parts:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                meta, _ = _parse_frontmatter(content)
                for tag in meta.get("tags", []):
                    tag_str = str(tag).lower()
                    tag_count[tag_str] = tag_count.get(tag_str, 0) + 1
                total_notes += 1
            except Exception:
                continue

        sorted_tags = sorted(tag_count.items(), key=lambda x: x[1], reverse=True)

        return json.dumps({
            "tags": [{"tag": t, "count": c} for t, c in sorted_tags],
            "total_tags": len(sorted_tags),
            "total_notes": total_notes,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en obsidian_list_tags: {e}"


def obsidian_recent(limit: int = 10) -> str:
    """
    Muestra las notas más recientes del vault.

    Args:
        limit: Número máximo de notas a devolver.
    """
    try:
        _ensure_vault()
        notes = []

        for md_file in VAULT_PATH.rglob("*.md"):
            if ".obsidian" in md_file.parts:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
                meta, body = _parse_frontmatter(content)
                rel_path = str(md_file.relative_to(VAULT_PATH)).replace("\\", "/")
                notes.append({
                    "title": meta.get("title", md_file.stem),
                    "type": meta.get("type", "note"),
                    "tags": meta.get("tags", []),
                    "created": meta.get("created", ""),
                    "modified": meta.get("modified", meta.get("created", "")),
                    "path": rel_path,
                    "preview": body[:150] if body else "",
                })
            except Exception:
                continue

        notes.sort(key=lambda x: x.get("modified", x.get("created", "")), reverse=True)
        notes = notes[:limit]

        return json.dumps({
            "status": "ok",
            "notes": notes,
            "total": len(notes),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en obsidian_recent: {e}"


# ---------------------------------------------------------------------------
# Migración desde knowledge_base.json
# ---------------------------------------------------------------------------

def migrate_kb_to_obsidian() -> str:
    """
    Migra todas las entradas de knowledge_base.json al vault de Obsidian.
    Cada entrada se convierte en un archivo .md con frontmatter YAML.
    """
    try:
        kb_path = _JARVIS_DIR / "knowledge_base.json"
        if not kb_path.is_file():
            return "No hay knowledge_base.json para migrar."

        data = json.loads(kb_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return "Error: formato de knowledge_base.json no válido."

        _ensure_vault()
        migrated = 0
        errors = 0

        for entry in data:
            try:
                entry_type = entry.get("type", "note")
                title = entry.get("title", "Sin título")
                content = entry.get("content", entry.get("description", ""))
                tags = entry.get("tags", [])
                created = entry.get("created_at", datetime.now().isoformat(timespec="seconds"))

                # Para bookmarks, incluir la URL en el contenido
                if entry_type == "bookmark":
                    url = entry.get("url", "")
                    if url:
                        content = f"🔗 [{title}]({url})\n\n{content}" if content else f"🔗 [{title}]({url})"

                # Para snippets, incluir el lenguaje
                if entry_type == "snippet":
                    language = entry.get("language", "")
                    if language:
                        content = f"```{language}\n{content}\n```"

                folder = _FOLDERS.get(entry_type, "Notes")
                target_dir = VAULT_PATH / folder
                target_dir.mkdir(parents=True, exist_ok=True)

                filename = _sanitize_filename(title) + ".md"
                file_path = target_dir / filename

                counter = 1
                while file_path.exists():
                    filename = f"{_sanitize_filename(title)} ({counter}).md"
                    file_path = target_dir / filename
                    counter += 1

                meta = {
                    "id": entry.get("id", secrets.token_hex(4)),
                    "title": title,
                    "type": entry_type,
                    "tags": tags,
                    "created": created,
                    "modified": created,
                    "migrated_from": "knowledge_base.json",
                }

                full = _build_note_content(meta, title, content or "(sin contenido)")
                file_path.write_text(full, encoding="utf-8")
                migrated += 1
            except Exception:
                errors += 1
                continue

        # Reconstruir índice
        _rebuild_index()

        return json.dumps({
            "status": "ok",
            "migrated": migrated,
            "errors": errors,
            "vault_path": str(VAULT_PATH),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en migrate_kb_to_obsidian: {e}"
