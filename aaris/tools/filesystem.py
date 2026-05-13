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

def create_file(path: str, content: str = "") -> str:
    """
    Crea un archivo en la ruta indicada. Crea directorios padre si no existen.

    Args:
        path: Ruta del archivo (absoluta o relativa al directorio de trabajo).
        content: Contenido inicial del archivo (texto UTF-8).
    """
    try:
        if _read_only_mode():
            return "Error: AARIS_READ_ONLY=true. create_file deshabilitado."
        resolved = resolve_path(path, must_exist=False)
        if resolved.startswith("Error:"):
            return resolved
        abs_path = resolved
        if os.path.exists(abs_path) and Path(abs_path).is_symlink():
            sym_err = _validate_symlink_for_path(abs_path, allow_escape=_allow_symlink_escape())
            if sym_err:
                return sym_err
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with _path_lock(abs_path):
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
        return f"Archivo creado correctamente en {abs_path}."
    except Exception as e:
        return f"Error al crear el archivo: {e}"

def read_file(path: str, max_chars: int = 80000) -> str:
    """
    Lee el contenido de un archivo de texto existente.

    Args:
        path: Ruta del archivo.
        max_chars: Máximo de caracteres a devolver (el resto se trunca).
    """
    try:
        if _read_only_mode():
            # lectura permitida aunque esté read-only; esta rama se usa solo para mutaciones,
            # pero mantenemos compatibilidad si el usuario lo activa.
            pass
        resolved = resolve_path(path, must_exist=True)
        if resolved.startswith("Error:"):
            return resolved
        abs_path = resolved
        if not os.path.isfile(abs_path):
            return f"Error: no existe el archivo {abs_path}."
        sym_err = _validate_symlink_for_path(abs_path, allow_escape=_allow_symlink_escape())
        if sym_err:
            return sym_err
        data = _read_file_cached(abs_path, max_chars)
        if len(data) > max_chars:
            return data[:max_chars] + f"\n\n[… truncado: más de {max_chars} caracteres; usa read_file con rango menor o edición parcial.]"
        return data if data else "(archivo vacío)"
    except Exception as e:
        return f"Error al leer: {e}"

@lru_cache(maxsize=512)
def _read_file_cached(abs_path: str, max_chars: int) -> str:
    with open(abs_path, encoding="utf-8", errors="replace") as f:
        data = f.read(max_chars + 1)
    # normalizamos para que el cache sea estable
    return data

def edit_file(path: str, new_content: str) -> str:
    """
    Sustituye por completo el contenido de un archivo existente.

    Args:
        path: Ruta del archivo.
        new_content: Nuevo contenido completo del archivo.
    """
    try:
        if _read_only_mode():
            return "Error: AARIS_READ_ONLY=true. edit_file deshabilitado."
        resolved = resolve_path(path, must_exist=True)
        if resolved.startswith("Error:"):
            return resolved
        abs_path = resolved
        if not os.path.exists(abs_path):
            return f"Error: el archivo {abs_path} no existe. Créalo antes con create_file."
        sym_err = _validate_symlink_for_path(abs_path, allow_escape=_allow_symlink_escape())
        if sym_err:
            return sym_err
        pol_reason = _policy_forbidden_reason(abs_path)
        if pol_reason:
            return pol_reason
        with _path_lock(abs_path):
            token = _create_file_backup(Path(abs_path))
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            if abs_path.lower().endswith(".py"):
                rb = validate_python_syntax(abs_path)
                if rb.startswith("Error"):
                    rollback_res = rollback(token, overwrite=True)
                    return f"Error: validación Python falló en {abs_path}. {rollback_res}"
        if abs_path.lower().endswith(".json"):
            try:
                json.loads(new_content)
            except Exception:
                rollback_res = rollback(token, overwrite=True)
                return f"Error: JSON inválido en {abs_path}. {rollback_res}"
        _read_file_cached.cache_clear()
        _exists_path_cached.cache_clear()
        return f"Archivo actualizado: {abs_path}. ROLLBACK_TOKEN={token}"
    except Exception as e:
        return f"Error al editar: {e}"

def search_replace_in_file(
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> str:
    """
    Reemplaza una porción de texto dentro de un archivo (útil para archivos grandes).

    Args:
        path: Ruta del archivo.
        old_text: Fragmento exacto a buscar.
        new_text: Texto de sustitución.
        replace_all: Si True, reemplaza todas las ocurrencias; si False, solo la primera.
    """
    try:
        if _read_only_mode():
            return "Error: AARIS_READ_ONLY=true. search_replace_in_file deshabilitado."
        resolved = resolve_path(path, must_exist=True)
        if resolved.startswith("Error:"):
            return resolved
        abs_path = resolved
        if not os.path.isfile(abs_path):
            return f"Error: no existe el archivo {abs_path}."
        sym_err = _validate_symlink_for_path(abs_path, allow_escape=_allow_symlink_escape())
        if sym_err:
            return sym_err
        pol_reason = _policy_forbidden_reason(abs_path)
        if pol_reason:
            return pol_reason
        with _path_lock(abs_path):
            token = _create_file_backup(Path(abs_path))
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                content = f.read()
            if old_text not in content:
                return "Error: old_text no aparece en el archivo (comprueba espacios y saltos de línea)."
            if replace_all:
                n = content.count(old_text)
                new_content = content.replace(old_text, new_text)
                msg = f"Reemplazadas {n} ocurrencias."
            else:
                new_content = content.replace(old_text, new_text, 1)
                msg = "Reemplazada la primera ocurrencia."
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            if abs_path.lower().endswith(".json"):
                try:
                    json.loads(new_content)
                except Exception:
                    rollback_res = rollback(token, overwrite=True)
                    return f"Error: JSON inválido en {abs_path}. {rollback_res}"
            if abs_path.lower().endswith(".py"):
                rb = validate_python_syntax(abs_path)
                if rb.startswith("Error"):
                    rollback_res = rollback(token, overwrite=True)
                    return f"Error: validación Python falló en {abs_path}. {rollback_res}"
            _read_file_cached.cache_clear()
            _exists_path_cached.cache_clear()
            return f"{msg} Archivo: {abs_path}. ROLLBACK_TOKEN={token}"
    except Exception as e:
        return f"Error en search_replace: {e}"

def create_folder(path: str) -> str:
    """
    Crea un directorio (y padres si hace falta).

    Args:
        path: Ruta del directorio a crear.
    """
    try:
        if _read_only_mode():
            return "Error: AARIS_READ_ONLY=true. create_folder deshabilitado."
        resolved = resolve_path(path, must_exist=False)
        if resolved.startswith("Error:"):
            return resolved
        abs_path = resolved
        if os.path.exists(abs_path) and Path(abs_path).is_symlink():
            sym_err = _validate_symlink_for_path(abs_path, allow_escape=_allow_symlink_escape())
            if sym_err:
                return sym_err
        os.makedirs(abs_path, exist_ok=True)
        return f"Carpeta lista: {abs_path}."
    except Exception as e:
        return f"Error al crear carpeta: {e}"

def list_directory(path: str = ".", show_hidden: bool = False) -> str:
    """
    Lista entradas en un directorio (nombre y tipo: archivo o directorio).

    Args:
        path: Ruta del directorio (por defecto el actual).
        show_hidden: Si True, incluye entradas cuyo nombre empieza por punto.
    """
    try:
        resolved = resolve_path(path, must_exist=True)
        if resolved.startswith("Error:"):
            return resolved
        root = Path(resolved).resolve()
        if not root.is_dir():
            return f"Error: {root} no es un directorio."
        lines = []
        for p in sorted(root.iterdir()):
            if not show_hidden and p.name.startswith("."):
                continue
            kind = "dir" if p.is_dir() else "file"
            lines.append(f"[{kind}] {p.name}")
        return "\n".join(lines) if lines else "(directorio vacío o sin entradas visibles)"
    except Exception as e:
        return f"Error al listar: {e}"

def glob_find(pattern: str, root: str = ".") -> str:
    """
    Busca rutas que coincidan con un patrón glob (ej: **/*.py, src/*.txt).

    Args:
        pattern: Patrón glob relativo a root.
        root: Directorio base para la búsqueda.
    """
    try:
        resolved_root = resolve_path(root, must_exist=True)
        if resolved_root.startswith("Error:"):
            return resolved_root
        base = Path(resolved_root).resolve()
        paths = sorted(
            Path(p).resolve()
            for p in glob_module.glob(str(base / pattern), recursive=True)
        )
        if not paths:
            return f"Sin coincidencias para {pattern!r} bajo {base}."
        text = "\n".join(str(p) for p in paths[:200])
        if len(paths) > 200:
            text += f"\n… y {len(paths) - 200} más."
        return text
    except Exception as e:
        return f"Error en glob: {e}"

def resolve_path(path: str, cwd: Optional[str] = None, must_exist: bool = False) -> str:
    """
    Resuelve rutas “humanas” (por ejemplo `Documents`/`Documentos`) a rutas absolutas reales.

    - Si el usuario pasa `Documents/...` se interpreta como `$HOME/Documents/...` (aunque el nombre real varíe).
    - Si el usuario pasa una ruta absoluta (`/etc/...`) se respeta tal cual.
    """
    try:
        if cwd is None:
            cwd = os.getcwd()

        raw = (path or "").strip()
        if not raw:
            return "Error: path vacío."

        expanded = os.path.expanduser(raw)
        if os.path.isabs(expanded):
            abs_path = os.path.abspath(expanded)
            if must_exist and not os.path.exists(abs_path):
                return f"Error: la ruta no existe: {abs_path}"
            return abs_path

        home = Path.home().resolve()
        tokens = [t for t in expanded.split("/") if t]
        if not tokens:
            return "Error: path inválido."

        # Mapeo de alias comunes al home del usuario.
        home_aliases: dict[str, list[str]] = {
            _norm_text("documents"): ["Documents"],
            _norm_text("documentos"): ["Documents"],
            _norm_text("docs"): ["Documents"],
            _norm_text("doc"): ["Documents"],
            _norm_text("downloads"): ["Downloads"],
            _norm_text("descargas"): ["Downloads"],
            _norm_text("download"): ["Downloads"],
            _norm_text("desktop"): ["Desktop"],
            _norm_text("escritorio"): ["Desktop"],
            _norm_text("music"): ["Music"],
            _norm_text("musica"): ["Music"],
            _norm_text("música"): ["Music"],
            _norm_text("pictures"): ["Pictures", "Photos", "Images"],
            _norm_text("photos"): ["Pictures", "Photos", "Images"],
            _norm_text("images"): ["Pictures", "Photos", "Images"],
            _norm_text("imagenes"): ["Pictures", "Photos", "Images"],
            _norm_text("imágenes"): ["Pictures", "Photos", "Images"],
            _norm_text("videos"): ["Videos"],
            _norm_text("video"): ["Videos"],
            _norm_text("public"): ["Public"],
            _norm_text("público"): ["Public"],
            _norm_text("publico"): ["Public"],
        }

        # Primero intentamos usar XDG user dirs (mapeo real del sistema).
        xdg = _load_xdg_user_dirs()
        alias_to_category: dict[str, str] = {
            _norm_text("documents"): "documents",
            _norm_text("documentos"): "documents",
            _norm_text("docs"): "documents",
            _norm_text("doc"): "documents",
            _norm_text("downloads"): "downloads",
            _norm_text("descargas"): "downloads",
            _norm_text("download"): "downloads",
            _norm_text("desktop"): "desktop",
            _norm_text("escritorio"): "desktop",
            _norm_text("music"): "music",
            _norm_text("musica"): "music",
            _norm_text("música"): "music",
            _norm_text("pictures"): "pictures",
            _norm_text("photos"): "pictures",
            _norm_text("images"): "pictures",
            _norm_text("imagenes"): "pictures",
            _norm_text("imágenes"): "pictures",
            _norm_text("videos"): "videos",
            _norm_text("video"): "videos",
            _norm_text("public"): "public",
            _norm_text("público"): "public",
            _norm_text("publico"): "public",
        }

        first_norm = _norm_text(tokens[0])
        if first_norm in alias_to_category:
            cat = alias_to_category[first_norm]
            base_xdg = xdg.get(cat)
            if base_xdg:
                rest = "/".join(tokens[1:])
                abs_path = os.path.abspath(os.path.join(base_xdg, rest)) if rest else os.path.abspath(base_xdg)
                if must_exist and not os.path.exists(abs_path):
                    return f"Error: la ruta no existe: {abs_path}"
                return abs_path

        if first_norm in home_aliases:
            expected = home_aliases[first_norm]
            entries = [p for p in home.iterdir() if p.is_dir()]

            # 1) Match exacto ignorando case/acento.
            for e in entries:
                for exp in expected:
                    if _norm_text(e.name) == _norm_text(exp):
                        base_dir = e
                        rest = "/".join(tokens[1:])
                        abs_path = str((base_dir / rest).resolve()) if rest else str(base_dir)
                        if must_exist and not os.path.exists(abs_path):
                            return f"Error: la ruta no existe: {abs_path}"
                        return abs_path

            # 2) Fuzzy match entre carpetas candidatas del home.
            expected_norm = [_norm_text(x) for x in expected]
            best_score = 0.0
            best_name: Optional[str] = None
            scored_entries: list[tuple[float, str]] = []
            for e in entries:
                name_norm = _norm_text(e.name)
                score = max(difflib.SequenceMatcher(None, name_norm, exp).ratio() for exp in expected_norm)
                if score > best_score:
                    best_score = score
                    best_name = e.name
                scored_entries.append((score, e.name))

            if best_name and best_score >= 0.67:
                base_dir = home / best_name
                rest = "/".join(tokens[1:])
                abs_path = str((base_dir / rest).resolve()) if rest else str(base_dir)
                if must_exist and not os.path.exists(abs_path):
                    return f"Error: la ruta no existe: {abs_path}"
                return abs_path

            if must_exist and scored_entries:
                scored_entries.sort(key=lambda x: x[0], reverse=True)
                top = scored_entries[:5]
                candidates_json = [
                    {
                        "name": name,
                        "score": score,
                        "path": str((home / name).resolve()),
                    }
                    for score, name in top
                ]
                candidates = ", ".join([f"{name}({score:.2f})" for score, name in top])
                return (
                    f"Error: mapeo ambiguo para `{tokens[0]}`. "
                    f"Candidatos en tu $HOME: {candidates}. "
                    f"CANDIDATES_JSON={json.dumps(candidates_json, ensure_ascii=False)}. "
                    "Repite usando el nombre exacto (o una ruta absoluta)."
                )

            # Si el usuario solo quiere crear, permitimos caer en el nombre canónico esperado.
            if not must_exist:
                base_dir = home / expected[0]
                rest = "/".join(tokens[1:])
                abs_path = os.path.abspath(str(base_dir / rest)) if rest else os.path.abspath(str(base_dir))
                return abs_path

            return (
                f"Error: no pude mapear `{tokens[0]}` a una carpeta real en tu `$HOME`. "
                "Usa una ruta con el nombre exacto o una ruta absoluta."
            )

        # Rutas relativas: se interpretan desde el cwd del proceso.
        abs_path = os.path.abspath(os.path.join(cwd, expanded))
        if must_exist and not os.path.exists(abs_path):
            return f"Error: la ruta no existe: {abs_path}"
        return abs_path
    except Exception as e:
        return f"Error en resolve_path: {e}"

def exists_path(path: str, cwd: Optional[str] = None) -> str:
    """
    Comprueba si existe una ruta (archivo o directorio) resolviendo alias tipo `Documents`.
    """
    try:
        resolved = resolve_path(path, cwd=cwd, must_exist=False)
        if resolved.startswith("Error:"):
            return resolved
        return "true" if _exists_path_cached(resolved) else "false"
    except Exception as e:
        return f"Error en exists_path: {e}"

@lru_cache(maxsize=4096)
def _exists_path_cached(resolved_abs_path: str) -> bool:
    return Path(resolved_abs_path).exists()

def stat_path(path: str, cwd: Optional[str] = None) -> str:
    """
    Devuelve un resumen JSON con tipo/tamaño/tiempos de una ruta.
    """
    try:
        resolved = resolve_path(path, cwd=cwd, must_exist=False)
        if resolved.startswith("Error:"):
            return resolved
        return _stat_path_cached(resolved)
    except Exception as e:
        return f"Error en stat_path: {e}"

def _stat_path_cached(resolved_abs_path: str) -> str:
    p = Path(resolved_abs_path)
    if not p.exists() and not p.is_symlink():
        return f"Error: no existe {p}"
    st = p.lstat()
    info = {
        "path": str(p),
        "exists": p.exists(),
        "is_dir": p.is_dir(),
        "is_file": p.is_file(),
        "is_symlink": p.is_symlink(),
        "size_bytes": st.st_size,
        "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }
    return json.dumps(info, ensure_ascii=False)

def describe_path(path: str, cwd: Optional[str] = None) -> str:
    """
    Devuelve una descripción legible (rápida) de una ruta.
    """
    try:
        resolved = resolve_path(path, cwd=cwd, must_exist=False)
        if resolved.startswith("Error:"):
            return resolved
        return _describe_path_cached(resolved)
    except Exception as e:
        return f"Error en describe_path: {e}"

def _describe_path_cached(resolved_abs_path: str) -> str:
    p = Path(resolved_abs_path)
    if not p.exists() and not p.is_symlink():
        return f"(no existe) {p}"
    st = p.lstat()
    kind = "dir" if p.is_dir() else "file" if p.is_file() else "other"
    hidden = p.name.startswith(".")
    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{kind} | hidden={hidden} | size={st.st_size} bytes | mtime={mtime} | {p}"

def estimate_dir(path: str, cwd: Optional[str] = None, max_entries: int = 5000) -> str:
    """
    Estima rápidamente el alcance de un directorio contando entradas inmediatas hasta `max_entries`.
    """
    try:
        resolved = resolve_path(path, cwd=cwd, must_exist=True)
        if resolved.startswith("Error:"):
            return resolved
        return _estimate_dir_cached(resolved, max_entries)
    except Exception as e:
        return f"Error en estimate_dir: {e}"

def _estimate_dir_cached(resolved_abs_path: str, max_entries: int) -> str:
    p = Path(resolved_abs_path)
    if not p.is_dir():
        return f"Error: {p} no es un directorio."
    entries = 0
    files = 0
    dirs = 0
    hidden = 0
    bytes_sum = 0
    for child in p.iterdir():
        entries += 1
        if child.name.startswith("."):
            hidden += 1
        if child.is_dir():
            dirs += 1
        elif child.is_file() or child.is_symlink():
            files += 1
            try:
                bytes_sum += child.lstat().st_size
            except Exception:
                pass
        if entries >= max_entries:
            break
    more = "" if entries < max_entries else " (posible más, no contamos todo)"
    info = {
        "dir": str(p),
        "entries_counted": entries,
        "files_counted": files,
        "dirs_counted": dirs,
        "hidden_counted": hidden,
        "size_bytes_sum_files_counted": bytes_sum,
        "note": more.strip(),
    }
    return json.dumps(info, ensure_ascii=False)

def disk_usage(path: str = "~") -> str:
    """
    Devuelve el uso de disco para la ruta.
    """
    try:
        resolved = resolve_path(path, must_exist=False)
        if resolved.startswith("Error:"):
            return resolved
        p = Path(resolved).resolve()
        usage = shutil.disk_usage(str(p))
        info = {
            "path": str(p),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
        }
        return json.dumps(info, ensure_ascii=False)
    except Exception as e:
        return f"Error en disk_usage: {e}"

def tail_file(path: str, lines: int = 200, max_bytes: int = 2_000_000) -> str:
    """
    Lee las últimas `lines` líneas de un archivo.
    """
    try:
        resolved = resolve_path(path, must_exist=True)
        if resolved.startswith("Error:"):
            return resolved
        p = Path(resolved)
        if not p.is_file():
            return f"Error: {p} no es un archivo."

        # Estrategia simple: buscamos desde el final hacia atrás.
        with p.open("rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            back = min(file_size, max_bytes)
            f.seek(file_size - back, os.SEEK_SET)
            chunk = f.read(back)

        text = chunk.decode("utf-8", errors="replace")
        all_lines = text.splitlines()
        tail = all_lines[-lines:] if lines > 0 else all_lines
        return "\n".join(tail)
    except Exception as e:
        return f"Error en tail_file: {e}"

def count_dir_children_matches(
    path: str,
    glob_filter: str,
    show_hidden: bool = False,
    cwd: Optional[str] = None,
) -> str:
    """
    Cuenta coincidencias inmediatas (solo hijos de 1 nivel) para un glob_filter.
    Útil para previsualizar `delete_path(..., recursive=true, glob_filter=...)`.
    """
    try:
        resolved = resolve_path(path, cwd=cwd, must_exist=True)
        if resolved.startswith("Error:"):
            return resolved
        p = Path(resolved).resolve()
        if not p.is_dir():
            return f"Error: {p} no es un directorio."
        count = 0
        matched_names: list[str] = []
        for child in p.iterdir():
            if not show_hidden and child.name.startswith("."):
                continue
            if fnmatch.fnmatch(child.name, glob_filter):
                count += 1
                if len(matched_names) < 30:
                    matched_names.append(child.name)
        return json.dumps(
            {"dir": str(p), "glob_filter": glob_filter, "count": count, "matched_names": matched_names},
            ensure_ascii=False,
        )
    except Exception as e:
        return f"Error en count_dir_children_matches: {e}"

def fuzzy_search_paths(
    query: str,
    root: str = ".",
    exts: Optional[str] = None,
    max_results: int = 30,
    max_files: int = 5000,
) -> str:
    """
    Búsqueda "fuzzy" por nombres de archivos/rutas para encontrar candidatos rápidos.
    """
    try:
        q = (query or "").strip()
        if not q:
            return "Error: query vacía."
        resolved_root = resolve_path(root, must_exist=True)
        if resolved_root.startswith("Error:"):
            return resolved_root
        base = Path(resolved_root).resolve()

        allowed_exts: Optional[set[str]] = None
        if exts:
            allowed_exts = {e.strip().lower() for e in exts.split(",") if e.strip()}

        qn = _norm_text(q)
        scored: list[tuple[float, str]] = []
        seen = 0
        for p in base.rglob("*"):
            if seen >= max_files:
                break
            if p.is_dir():
                continue
            if allowed_exts is not None:
                if p.suffix.lower() not in allowed_exts:
                    continue
            seen += 1
            name_norm = _norm_text(p.name)
            score = difflib.SequenceMatcher(None, qn, name_norm).ratio()
            if score >= 0.25:
                scored.append((score, str(p)))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:max_results]
        lines = [f"{s:.3f} {path}" for s, path in top]
        if not lines:
            return "Sin coincidencias relevantes."
        return "\n".join(lines)
    except Exception as e:
        return f"Error en fuzzy_search_paths: {e}"

def append_file(path: str, content: str) -> str:
    """
    Añade contenido al final de un archivo (crea directorios padre).
    """
    try:
        if _read_only_mode():
            return "Error: AARIS_READ_ONLY=true. append_file deshabilitado."
        resolved = resolve_path(path, must_exist=False)
        if resolved.startswith("Error:"):
            return resolved
        abs_path = resolved
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Para symlinks existentes, evitamos escapar del home.
        if os.path.isfile(abs_path):
            sym_err = _validate_symlink_for_path(abs_path, allow_escape=_allow_symlink_escape())
            if sym_err:
                return sym_err
        token = None
        if os.path.isfile(abs_path):
            token = _create_file_backup(Path(abs_path))
        with _path_lock(abs_path):
            with open(abs_path, "a", encoding="utf-8") as f:
                f.write(content)
        _read_file_cached.cache_clear()
        _exists_path_cached.cache_clear()
        if token:
            return f"Contenido añadido a {abs_path}. ROLLBACK_TOKEN={token}"
        return f"Contenido añadido a {abs_path}."
    except Exception as e:
        return f"Error en append_file: {e}"

def insert_after(path: str, anchor_text: str, insert_text: str, occurrence_index: int = 0) -> str:
    """
    Inserta `insert_text` justo después de la `occurrence_index`-ésima aparición de `anchor_text`.
    """
    try:
        if _read_only_mode():
            return "Error: AARIS_READ_ONLY=true. insert_after deshabilitado."
        resolved = resolve_path(path, must_exist=True)
        if resolved.startswith("Error:"):
            return resolved
        abs_path = resolved
        sym_err = _validate_symlink_for_path(abs_path, allow_escape=_allow_symlink_escape())
        if sym_err:
            return sym_err
        with _path_lock(abs_path):
            token = _create_file_backup(Path(abs_path))
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                data = f.read()
            idx = -1
            start = 0
            for i in range(occurrence_index + 1):
                idx = data.find(anchor_text, start)
                if idx == -1:
                    return "Error: anchor_text no encontrado (o occurrence_index fuera de rango)."
                start = idx + len(anchor_text)
            insert_pos = idx + len(anchor_text)
            new_data = data[:insert_pos] + insert_text + data[insert_pos:]
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_data)
            if abs_path.lower().endswith(".py"):
                rb = validate_python_syntax(abs_path)
                if rb.startswith("Error"):
                    rollback_res = rollback(token, overwrite=True)
                    return f"Error: validación Python falló en {abs_path}. {rollback_res}"
            if abs_path.lower().endswith(".json"):
                try:
                    json.loads(new_data)
                except Exception:
                    rollback_res = rollback(token, overwrite=True)
                    return f"Error: JSON inválido en {abs_path}. {rollback_res}"
            _read_file_cached.cache_clear()
            _exists_path_cached.cache_clear()
            return f"Insertado después de anchor_text en {abs_path}. ROLLBACK_TOKEN={token}"
    except Exception as e:
        return f"Error en insert_after: {e}"

def copy_path(from_path: str, to_path: str, overwrite: bool = False, allow_dangerous: bool = False) -> str:
    """
    Copia un archivo o carpeta a otra ubicación.
    """
    try:
        if _read_only_mode():
            return "Error: AARIS_READ_ONLY=true. copy_path deshabilitado."
        src = Path(resolve_path(from_path, must_exist=True))
        dst = Path(resolve_path(to_path, must_exist=False))
        if src.is_symlink():
            sym_err = _validate_symlink_for_path(str(src), allow_escape=_allow_symlink_escape())
            if sym_err:
                return sym_err
        err = _ensure_in_home_or_allow(src, allow_dangerous, "copy_path (origen)")
        if err:
            return err
        err = _ensure_in_home_or_allow(dst, allow_dangerous, "copy_path (destino)")
        if err:
            return err

        if dst.exists() and not overwrite:
            return f"Error: el destino ya existe: {dst}. Usa overwrite=true."

        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(str(src), str(dst), dirs_exist_ok=overwrite)
        else:
            shutil.copy2(str(src), str(dst))
        return f"Copia creada: {dst}"
    except Exception as e:
        return f"Error en copy_path: {e}"

def move_path(from_path: str, to_path: str, overwrite: bool = False, allow_dangerous: bool = False) -> str:
    """
    Mueve un archivo o carpeta a otra ubicación.
    """
    try:
        if _read_only_mode():
            return "Error: AARIS_READ_ONLY=true. move_path deshabilitado."
        src = Path(resolve_path(from_path, must_exist=True))
        dst = Path(resolve_path(to_path, must_exist=False))
        if src.is_symlink():
            sym_err = _validate_symlink_for_path(str(src), allow_escape=_allow_symlink_escape())
            if sym_err:
                return sym_err
        err = _ensure_in_home_or_allow(src, allow_dangerous, "move_path (origen)")
        if err:
            return err
        err = _ensure_in_home_or_allow(dst, allow_dangerous, "move_path (destino)")
        if err:
            return err

        if dst.exists():
            if not overwrite:
                return f"Error: el destino ya existe: {dst}. Usa overwrite=true."
            # Eliminamos destino para permitir el movimiento.
            if dst.is_dir():
                shutil.rmtree(str(dst))
            else:
                dst.unlink()

        token = _create_move_backup(src, dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Movido a: {dst}. ROLLBACK_TOKEN={token}"
    except Exception as e:
        return f"Error en move_path: {e}"

def _trash_enabled() -> bool:
    val = os.environ.get("AARIS_USE_TRASH", "true").strip().lower()
    return val not in ("0", "false", "no", "off")

def _trash_move(target: Path) -> str:
    """
    Mueve la ruta al directorio de papelera estándar (XDG Trash).
    Retorna un mensaje; si falla, lanza excepción para que el llamador haga fallback.
    """
    trash_base = Path.home().resolve() / ".local" / "share" / "Trash"
    files_dir = trash_base / "files"
    info_dir = trash_base / "info"
    files_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)

    original_path = str(target.resolve())
    uid = uuid.uuid4().hex
    dest_name = f"{target.name}.{uid}"
    dest = files_dir / dest_name

    shutil.move(str(target), str(dest))

    deletion_date = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    # Formato .trashinfo (simplificado pero compatible).
    info_text = (
        "[Trash Info]\n"
        f"Path={original_path}\n"
        f"DeletionDate={deletion_date}\n"
    )
    info_file = info_dir / f"{dest_name}.trashinfo"
    info_file.write_text(info_text, encoding="utf-8")
    return str(dest)

def delete_path(
    path: str,
    recursive: bool = False,
    confirm: bool = False,
    allow_dangerous: bool = False,
    glob_filter: Optional[str] = None,
    max_entries: Optional[int] = None,
) -> str:
    """
    Borra un archivo o carpeta.

    - Para carpetas usa `recursive=true`.
    - Para carpetas (y para cosas fuera de tu home) exige `confirm=true` y/o `allow_dangerous=true`.
    """
    try:
        if _read_only_mode():
            return "Error: AARIS_READ_ONLY=true. delete_path deshabilitado."
        resolved = resolve_path(path, must_exist=True)
        if resolved.startswith("Error:"):
            return resolved

        target = Path(resolved).resolve()
        home = Path.home().resolve()
        pol_reason = _policy_forbidden_reason(str(target))
        if pol_reason and not allow_dangerous:
            return pol_reason
        if _policy_require_confirm("delete_path") and not confirm and not allow_dangerous:
            return "Error: política requiere confirm=true para delete_path."

        # Evita accidentes catastróficos.
        if str(target) == "/":
            return "Error: no se permite borrar `/`."

        min_bytes_for_confirm = int(os.environ.get("AARIS_DELETE_CONFIRM_MIN_BYTES", "50000000"))
        min_entries_for_confirm = int(os.environ.get("AARIS_DELETE_CONFIRM_MIN_ENTRIES", "200"))
        sensitive_dir_names = {".ssh", ".gnupg", ".kube", ".kubernetes"}
        sensitive_file_names = {".bashrc", ".zshrc", ".profile", ".bash_profile", ".gitconfig", ".config"}

        def _maybe_require_confirm(reason: str) -> Optional[str]:
            if confirm:
                return None
            return (
                "Confirmación requerida: " + reason + ". "
                "Repite la petición con `confirm=true`."
            )

        if target.is_dir():
            if not recursive:
                return f"Error: {target} es un directorio. Usa `recursive=true`."
            if not _is_relative_to(target, home) and not allow_dangerous:
                return "Error: borrar directorios fuera de tu home requiere `allow_dangerous=true`."

            # Confirmación estricta: cualquier borrado recursivo requiere confirm=true.
            if not confirm:
                return (
                    f"Confirmación requerida: vas a borrar recursivamente `{target}`. "
                    "Repite la petición con `confirm=true`."
                )

            # Selección segura para directorios grandes (si no se especifica filtro).
            effective_threshold = max_entries if max_entries is not None else int(
                os.environ.get("AARIS_DELETE_LARGE_DIR_MAX_ENTRIES", "2000")
            )
            if glob_filter is None and effective_threshold > 0:
                immediate = 0
                try:
                    for _ in target.iterdir():
                        immediate += 1
                        if immediate > effective_threshold:
                            break
                except Exception:
                    immediate = effective_threshold + 1
                if immediate > effective_threshold:
                    return (
                        "Error: el directorio parece demasiado grande para borrado recursivo directo. "
                        "Usa una subruta más específica o pasa `glob_filter` para borrar solo partes."
                    )

            # Si hay filtro, borramos recursivamente SOLO los hijos inmediatos que coincidan.
            if glob_filter:
                matches: list[Path] = []
                for child in target.iterdir():
                    if fnmatch.fnmatch(child.name, glob_filter):
                        matches.append(child)
                if not matches:
                    return f"Sin coincidencias para glob_filter={glob_filter!r} en {target}."

                if _trash_enabled():
                    moved = []
                    tokens: list[str] = []
                    for m in matches:
                        try:
                            original = m.resolve()
                            moved_dest = _trash_move(m)
                            moved.append(moved_dest)
                            tokens.append(_create_trash_backup(original, Path(moved_dest)))
                        except Exception:
                            # Fallback permanente por cada entrada.
                            if m.is_dir():
                                shutil.rmtree(str(m))
                            else:
                                m.unlink()
                    tok_part = f" ROLLBACK_TOKENS={','.join(tokens)}" if tokens else ""
                    return f"Entrada(s) movida(s) a Trash: {len(moved)}.{tok_part}"
                else:
                    for m in matches:
                        if m.is_dir():
                            shutil.rmtree(str(m))
                        else:
                            m.unlink()
                    return f"Entrada(s) eliminada(s): {len(matches)}"

            # Sin filtro: eliminamos todo (a Trash si está activo).
            if _trash_enabled():
                try:
                    original = target.resolve()
                    dest = _trash_move(target)
                    token = _create_trash_backup(original, Path(dest))
                    return f"Directorio movido a Trash: {dest}. ROLLBACK_TOKEN={token}"
                except Exception:
                    # Fallback permanente.
                    shutil.rmtree(str(target))
                    return f"Directorio eliminado: {target}"

            shutil.rmtree(str(target))
            return f"Directorio eliminado: {target}"

        # Archivo (o enlace).
        if not target.exists():
            return f"Error: la ruta no existe: {target}"

        if not _is_relative_to(target, home) and not allow_dangerous:
            return "Error: borrar archivos fuera de tu home requiere `allow_dangerous=true`."

        if not confirm:
            name = target.name
            parent = target.parent.name
            try:
                size = target.lstat().st_size
            except Exception:
                size = 0

            if parent in sensitive_dir_names or name in sensitive_file_names:
                msg = _maybe_require_confirm(f"es un archivo sensible (`{parent}/{name}`)")
                if msg:
                    return msg
            if name.startswith("."):
                msg = _maybe_require_confirm(f"es un archivo oculto (`{name}`)")
                if msg:
                    return msg
            if size >= min_bytes_for_confirm:
                msg = _maybe_require_confirm(f"es grande (>= {min_bytes_for_confirm} bytes)")
                if msg:
                    return msg

        if _trash_enabled():
            try:
                original = target.resolve()
                dest = _trash_move(target)
                token = _create_trash_backup(original, Path(dest))
                return f"Archivo movido a Trash: {dest}. ROLLBACK_TOKEN={token}"
            except Exception:
                target.unlink()
                return f"Archivo eliminado: {target}"

        target.unlink()
        return f"Archivo eliminado: {target}"

    except Exception as e:
        return f"Error en delete_path: {e}"

def apply_unified_patch(
    path: str,
    patch_text: str,
    strip: int = 1,
    workdir: Optional[str] = None,
    confirm: bool = False,
    allow_dangerous: bool = False,
) -> str:
    """
    Aplica un diff unificado usando el binario `patch`.
    """
    try:
        if _read_only_mode():
            return "Error: AARIS_READ_ONLY=true. apply_unified_patch deshabilitado."
        if _policy_require_confirm("apply_unified_patch") and not confirm and not allow_dangerous:
            return "Error: política requiere confirm=true para apply_unified_patch."
        if not confirm and not allow_dangerous:
            return "Error: confirm=true requerido para apply_unified_patch."
        if not shutil.which("patch"):
            return "Error: no se encontró el binario `patch`."

        resolved_path = resolve_path(path, must_exist=True)
        if resolved_path.startswith("Error:"):
            return resolved_path
        target_file = Path(resolved_path)
        if not target_file.exists():
            return f"Error: no existe: {target_file}"
        token = _create_file_backup(target_file)
        pol_reason = _policy_forbidden_reason(str(target_file.resolve()))
        if pol_reason and not allow_dangerous:
            return pol_reason
        sym_err = _validate_symlink_for_path(str(target_file), allow_escape=_allow_symlink_escape())
        if sym_err:
            return sym_err

        if workdir is None:
            workdir = str(target_file.parent)
        resolved_workdir = resolve_path(workdir, must_exist=True)
        if resolved_workdir.startswith("Error:"):
            # si workdir no existe, usamos directorio padre del archivo
            resolved_workdir = str(target_file.parent.resolve())

        with _path_lock(str(target_file.resolve())):
            patch_tmp = Path(resolved_workdir) / f".aaris_patch_{uuid.uuid4().hex}.diff"
            patch_tmp.write_text(patch_text or "", encoding="utf-8")
            proc = subprocess.run(
                ["patch", f"-p{int(strip)}", "--batch", "-i", str(patch_tmp)],
                cwd=resolved_workdir,
                capture_output=True,
                text=True,
                timeout=300,
                env={**os.environ},
            )
            out = (proc.stdout or "") + (("\n--- stderr ---\n" + proc.stderr) if proc.stderr else "")
        try:
            if patch_tmp.exists():
                patch_tmp.unlink()
        except Exception:
            pass
        if proc.returncode != 0:
            return "Error apply_unified_patch:\n" + out[:12000]
        # Post-checks básicas.
        if str(target_file).lower().endswith(".json"):
            try:
                _ = json.loads(target_file.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                rollback_res = rollback(token, overwrite=True)
                return f"Error: apply_unified_patch dejó JSON inválido. {rollback_res}"
        if str(target_file).lower().endswith(".py"):
            rb = validate_python_syntax(str(target_file))
            if rb.startswith("Error"):
                rollback_res = rollback(token, overwrite=True)
                return f"Error: validación Python falló tras apply_unified_patch. {rollback_res}"
        return "OK apply_unified_patch.\n" + out[:12000] + f"\nROLLBACK_TOKEN={token}"
    except Exception as e:
        return f"Error en apply_unified_patch: {e}"

