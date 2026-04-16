"""
JARVIS Smart File Organizer Module.

Organiza automáticamente carpetas (como Descargas), detecta duplicados,
y limpia archivos antiguos.
"""

import hashlib
import json
import os
import shutil
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Mapeo de extensiones a categorías
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, list[str]] = {
    "Documentos": [
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".odt", ".ods", ".odp", ".rtf", ".tex", ".csv",
    ],
    "Imagenes": [
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp",
        ".ico", ".tiff", ".tif", ".raw", ".heic", ".heif",
    ],
    "Videos": [
        ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm",
        ".m4v", ".mpg", ".mpeg", ".3gp",
    ],
    "Musica": [
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a",
        ".opus", ".mid", ".midi",
    ],
    "Codigo": [
        ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs",
        ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
        ".html", ".css", ".scss", ".less", ".vue", ".jsx", ".tsx",
        ".sql", ".sh", ".bat", ".ps1", ".r", ".lua", ".dart",
    ],
    "Comprimidos": [
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
        ".tar.gz", ".tgz", ".cab",
    ],
    "Instaladores": [
        ".exe", ".msi", ".dmg", ".deb", ".rpm", ".appimage",
        ".apk", ".app",
    ],
    "Texto": [
        ".txt", ".md", ".rst", ".log", ".ini", ".cfg", ".conf",
        ".yaml", ".yml", ".toml", ".json", ".xml",
    ],
    "Fuentes": [
        ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ],
    "Datos": [
        ".db", ".sqlite", ".sqlite3", ".sql", ".bak",
    ],
}

# Invertir mapa: extensión → categoría
_EXT_TO_CATEGORY: dict[str, str] = {}
for category, extensions in _CATEGORY_MAP.items():
    for ext in extensions:
        _EXT_TO_CATEGORY[ext] = category


def _get_category(filename: str) -> str:
    """Obtiene la categoría de un archivo según su extensión."""
    ext = os.path.splitext(filename)[1].lower()
    return _EXT_TO_CATEGORY.get(ext, "Otros")


def _file_hash(filepath: str, chunk_size: int = 8192) -> str:
    """Calcula el hash MD5 de un archivo."""
    hasher = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Herramientas públicas
# ---------------------------------------------------------------------------

def organize_folder(
    folder_path: str = "",
    dry_run: bool = True,
) -> str:
    """
    Organiza los archivos de una carpeta clasificándolos en subcarpetas por tipo.
    Las subcarpetas creadas: Documentos, Imagenes, Videos, Musica, Codigo, 
    Comprimidos, Instaladores, Texto, Fuentes, Datos, Otros.

    Args:
        folder_path: Ruta de la carpeta a organizar. Si vacía, usa la carpeta de Descargas.
        dry_run: Si True, solo muestra qué haría sin mover archivos. Si False, mueve los archivos.
    """
    try:
        if not folder_path:
            # Auto-detectar Descargas
            downloads = os.path.join(os.path.expanduser("~"), "Downloads")
            if not os.path.isdir(downloads):
                downloads = os.path.join(os.path.expanduser("~"), "Descargas")
            folder_path = downloads

        abs_path = os.path.abspath(os.path.expanduser(folder_path))
        if not os.path.isdir(abs_path):
            return f"Error: carpeta no existe: {abs_path}"

        # Recoger archivos (solo nivel raíz, no subdirectorios)
        files = [
            f for f in os.listdir(abs_path)
            if os.path.isfile(os.path.join(abs_path, f))
            and not f.startswith(".")
        ]

        if not files:
            return json.dumps({
                "status": "ok",
                "message": "No hay archivos para organizar.",
                "folder": abs_path,
            }, ensure_ascii=False)

        # Clasificar
        movements: dict[str, list[str]] = defaultdict(list)
        for f in files:
            category = _get_category(f)
            movements[category].append(f)

        if dry_run:
            # Solo mostrar plan
            plan = {}
            for category, file_list in sorted(movements.items()):
                plan[category] = {
                    "count": len(file_list),
                    "files": file_list[:10],
                    "destination": os.path.join(abs_path, category),
                }

            return json.dumps({
                "status": "ok",
                "mode": "dry_run",
                "folder": abs_path,
                "total_files": len(files),
                "categories": plan,
                "message": "Vista previa. Usa dry_run=False para mover los archivos.",
            }, ensure_ascii=False)

        # Mover archivos
        moved = 0
        errors = []
        for category, file_list in movements.items():
            dest_dir = os.path.join(abs_path, category)
            os.makedirs(dest_dir, exist_ok=True)

            for f in file_list:
                src = os.path.join(abs_path, f)
                dst = os.path.join(dest_dir, f)

                # Evitar sobreescritura
                if os.path.exists(dst):
                    name, ext = os.path.splitext(f)
                    counter = 1
                    while os.path.exists(dst):
                        dst = os.path.join(dest_dir, f"{name}_{counter}{ext}")
                        counter += 1

                try:
                    shutil.move(src, dst)
                    moved += 1
                except Exception as e:
                    errors.append(f"{f}: {e}")

        return json.dumps({
            "status": "ok",
            "mode": "executed",
            "folder": abs_path,
            "files_moved": moved,
            "errors": errors[:10],
            "categories_created": list(movements.keys()),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en organize_folder: {e}"


def find_duplicates(
    folder_path: str,
    recursive: bool = True,
    min_size_kb: int = 1,
) -> str:
    """
    Busca archivos duplicados en una carpeta usando hash MD5.

    Args:
        folder_path: Ruta de la carpeta a analizar.
        recursive: Si buscar en subcarpetas.
        min_size_kb: Tamaño mínimo de archivo en KB para considerar (ignora archivos pequeños).
    """
    try:
        abs_path = os.path.abspath(os.path.expanduser(folder_path))
        if not os.path.isdir(abs_path):
            return f"Error: carpeta no existe: {abs_path}"

        min_size = min_size_kb * 1024
        size_groups: dict[int, list[str]] = defaultdict(list)

        # Fase 1: Agrupar por tamaño
        if recursive:
            for root, dirs, files in os.walk(abs_path):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in files:
                    fpath = os.path.join(root, f)
                    try:
                        size = os.path.getsize(fpath)
                        if size >= min_size:
                            size_groups[size].append(fpath)
                    except Exception:
                        continue
        else:
            for f in os.listdir(abs_path):
                fpath = os.path.join(abs_path, f)
                if os.path.isfile(fpath):
                    try:
                        size = os.path.getsize(fpath)
                        if size >= min_size:
                            size_groups[size].append(fpath)
                    except Exception:
                        continue

        # Fase 2: Solo hashear archivos con tamaño duplicado
        duplicates: list[dict] = []
        hash_groups: dict[str, list[str]] = defaultdict(list)

        for size, paths in size_groups.items():
            if len(paths) < 2:
                continue
            for fpath in paths:
                h = _file_hash(fpath)
                if h:
                    hash_groups[h].append(fpath)

        for h, paths in hash_groups.items():
            if len(paths) >= 2:
                size = os.path.getsize(paths[0])
                duplicates.append({
                    "hash": h,
                    "size_bytes": size,
                    "size_human": _human_size(size),
                    "count": len(paths),
                    "files": paths,
                })

        # Calcular espacio recuperable
        total_wasted = sum(
            d["size_bytes"] * (d["count"] - 1)
            for d in duplicates
        )

        return json.dumps({
            "status": "ok",
            "folder": abs_path,
            "duplicate_groups": len(duplicates),
            "total_duplicate_files": sum(d["count"] - 1 for d in duplicates),
            "wasted_space": _human_size(total_wasted),
            "duplicates": duplicates[:20],  # Límite para no saturar
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en find_duplicates: {e}"


def clean_old_files(
    folder_path: str,
    days: int = 30,
    dry_run: bool = True,
    extensions: str = "",
) -> str:
    """
    Limpia archivos más antiguos que X días. Por seguridad, por defecto es dry_run.

    Args:
        folder_path: Carpeta a limpiar.
        days: Eliminar archivos más antiguos que este número de días.
        dry_run: Si True, solo muestra qué eliminaría. Si False, elimina.
        extensions: Si especificado, solo elimina estas extensiones (ej: '.tmp,.log,.bak').
    """
    try:
        abs_path = os.path.abspath(os.path.expanduser(folder_path))
        if not os.path.isdir(abs_path):
            return f"Error: carpeta no existe: {abs_path}"

        if days < 1:
            return "Error: days debe ser al menos 1."

        cutoff = datetime.now() - timedelta(days=days)
        ext_filter = set()
        if extensions:
            ext_filter = set(
                e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
                for e in extensions.split(",") if e.strip()
            )

        old_files = []
        total_size = 0

        for f in os.listdir(abs_path):
            fpath = os.path.join(abs_path, f)
            if not os.path.isfile(fpath):
                continue
            if f.startswith("."):
                continue
            if ext_filter:
                ext = os.path.splitext(f)[1].lower()
                if ext not in ext_filter:
                    continue

            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if mtime < cutoff:
                    size = os.path.getsize(fpath)
                    old_files.append({
                        "file": f,
                        "size": _human_size(size),
                        "size_bytes": size,
                        "modified": mtime.strftime("%Y-%m-%d"),
                    })
                    total_size += size
            except Exception:
                continue

        if not old_files:
            return json.dumps({
                "status": "ok",
                "message": f"No hay archivos más antiguos de {days} días.",
                "folder": abs_path,
            }, ensure_ascii=False)

        if dry_run:
            return json.dumps({
                "status": "ok",
                "mode": "dry_run",
                "folder": abs_path,
                "files_to_delete": len(old_files),
                "space_to_free": _human_size(total_size),
                "files": old_files[:30],
                "message": "Vista previa. Usa dry_run=False para eliminar.",
            }, ensure_ascii=False)

        # Eliminar
        deleted = 0
        errors = []
        for f_info in old_files:
            try:
                fpath = os.path.join(abs_path, f_info["file"])
                os.remove(fpath)
                deleted += 1
            except Exception as e:
                errors.append(f"{f_info['file']}: {e}")

        return json.dumps({
            "status": "ok",
            "mode": "executed",
            "files_deleted": deleted,
            "space_freed": _human_size(total_size),
            "errors": errors[:10],
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en clean_old_files: {e}"


def folder_stats(folder_path: str = "") -> str:
    """
    Muestra estadísticas de una carpeta: distribución de archivos por tipo, tamaño total, etc.

    Args:
        folder_path: Ruta de la carpeta. Si vacía, usa la carpeta de Descargas.
    """
    try:
        if not folder_path:
            folder_path = os.path.join(os.path.expanduser("~"), "Downloads")
            if not os.path.isdir(folder_path):
                folder_path = os.path.join(os.path.expanduser("~"), "Descargas")

        abs_path = os.path.abspath(os.path.expanduser(folder_path))
        if not os.path.isdir(abs_path):
            return f"Error: carpeta no existe: {abs_path}"

        categories: dict[str, dict] = defaultdict(lambda: {"count": 0, "size": 0})
        total_files = 0
        total_size = 0

        for f in os.listdir(abs_path):
            fpath = os.path.join(abs_path, f)
            if not os.path.isfile(fpath):
                continue

            category = _get_category(f)
            try:
                size = os.path.getsize(fpath)
            except Exception:
                size = 0

            categories[category]["count"] += 1
            categories[category]["size"] += size
            total_files += 1
            total_size += size

        stats = {}
        for cat, data in sorted(categories.items(), key=lambda x: x[1]["size"], reverse=True):
            stats[cat] = {
                "count": data["count"],
                "size": _human_size(data["size"]),
                "percentage": round(data["size"] / total_size * 100, 1) if total_size else 0,
            }

        return json.dumps({
            "status": "ok",
            "folder": abs_path,
            "total_files": total_files,
            "total_size": _human_size(total_size),
            "categories": stats,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en folder_stats: {e}"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _human_size(size_bytes: int) -> str:
    """Convierte bytes a formato legible."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"
