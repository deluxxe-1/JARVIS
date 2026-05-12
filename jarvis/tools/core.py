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


_POLICY_CACHE: Optional[dict[str, Any]] = None
_XDG_USER_DIRS_CACHE: Optional[dict[str, str]] = None



def _norm_text(s: str) -> str:
    # Normaliza acentos y hace casefold para comparaciones robustas.
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.casefold()

def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except Exception:
        return False

def _read_only_mode() -> bool:
    val = os.environ.get("JARVIS_READ_ONLY", "false").strip().lower()
    return val in ("1", "true", "yes", "si", "sí", "on")

def _read_only_allow_undo() -> bool:
    val = os.environ.get("JARVIS_READ_ONLY_ALLOW_UNDO", "true").strip().lower()
    return val in ("1", "true", "yes", "si", "sí", "on")

def _load_policy() -> dict[str, Any]:
    """
    Carga políticas desde env `JARVIS_POLICY_JSON` (string JSON).
    Ejemplo:
      export JARVIS_POLICY_JSON='{"forbidden_path_prefixes":["/etc/"],"require_confirm_tools":["delete_path"]}'
    """
    global _POLICY_CACHE
    if _POLICY_CACHE is not None:
        return _POLICY_CACHE
    raw = os.environ.get("JARVIS_POLICY_JSON", "").strip()
    if not raw:
        # Si no hay env, intentamos con fichero.
        policy_path = os.environ.get(
            "JARVIS_POLICY_PATH",
            os.path.join(os.path.expanduser("~"), ".jarvis", "policy.json"),
        )
        try:
            p = Path(policy_path).expanduser()
            if p.is_file():
                raw = p.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            raw = ""

    if not raw:
        _POLICY_CACHE = {}
        return _POLICY_CACHE
    try:
        parsed = json.loads(raw)
        _POLICY_CACHE = parsed if isinstance(parsed, dict) else {}
    except Exception:
        _POLICY_CACHE = {}
    return _POLICY_CACHE

def _policy_forbidden_reason(abs_path: str) -> Optional[str]:
    policy = _load_policy()
    forbidden = policy.get("forbidden_path_prefixes") or []
    if not isinstance(forbidden, list):
        return None
    for pref in forbidden:
        if not isinstance(pref, str):
            continue
        if pref and abs_path.startswith(pref):
            return f"Error: política prohíbe tocar {pref}. Ruta: {abs_path}"
    return None

def _policy_require_confirm(tool_name: str) -> bool:
    policy = _load_policy()
    req = policy.get("require_confirm_tools") or []
    if not isinstance(req, list):
        return False
    return tool_name in req

def policy_show() -> str:
    """
    Devuelve la política actual (JSON) usada por el agente.
    """
    try:
        return json.dumps(_load_policy(), ensure_ascii=False)
    except Exception as e:
        return f"Error en policy_show: {e}"

def policy_set(policy_json: str, allow_dangerous: bool = False) -> str:
    """
    Sobrescribe la política en el fichero JARVIS_POLICY_PATH.

    Requiere allow_dangerous=true (esta tool escribe disco).
    """
    try:
        if not allow_dangerous:
            return "Error: policy_set escribe disco. Usa allow_dangerous=true."
        if not policy_json or not policy_json.strip():
            return "Error: policy_json vacío."
        parsed = json.loads(policy_json)
        if not isinstance(parsed, dict):
            return "Error: policy_json debe ser un objeto JSON."
        policy_path = os.environ.get(
            "JARVIS_POLICY_PATH",
            os.path.join(os.path.expanduser("~"), ".jarvis", "policy.json"),
        )
        p = Path(policy_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
        # Limpia cache para recargar.
        global _POLICY_CACHE
        _POLICY_CACHE = None
        return f"OK policy_set en {p}"
    except Exception as e:
        return f"Error en policy_set: {e}"

def policy_reset(allow_dangerous: bool = False) -> str:
    """
    Resetea la política borrando el fichero de política (si existe).
    """
    try:
        if not allow_dangerous:
            return "Error: policy_reset escribe/borrado disco. Usa allow_dangerous=true."
        policy_path = os.environ.get(
            "JARVIS_POLICY_PATH",
            os.path.join(os.path.expanduser("~"), ".jarvis", "policy.json"),
        )
        p = Path(policy_path).expanduser()
        if p.is_file():
            p.unlink()
        global _POLICY_CACHE
        _POLICY_CACHE = None
        return f"OK policy_reset ({p})"
    except Exception as e:
        return f"Error en policy_reset: {e}"

def _allow_symlink_escape() -> bool:
    val = os.environ.get("JARVIS_ALLOW_SYMLINK_ESCAPE", "false").strip().lower()
    return val in ("1", "true", "yes", "si", "sí", "on")

def _symlink_escapes_home(abs_path: str) -> bool:
    try:
        home = Path.home().resolve()
        p = Path(abs_path)
        if not p.is_symlink():
            return False
        target = p.resolve()
        return not _is_relative_to(target, home)
    except Exception:
        return True

def _validate_symlink_for_path(abs_path: str, allow_escape: bool = False) -> Optional[str]:
    if allow_escape:
        return None
    try:
        home = Path.home().resolve()
        p = Path(abs_path)
        # Recorremos componentes y bloqueamos si cualquier componente es symlink
        # que resuelva fuera del home (deep escape).
        cur = Path(p.root)
        for part in p.parts[1:]:
            cur = cur / part
            if cur.is_symlink():
                try:
                    target = cur.resolve()
                except Exception:
                    return f"Error: no pude resolver symlink: {cur}"
                if not _is_relative_to(target, home):
                    return f"Error: un componente es symlink y escapa del home. Ruta: {abs_path} (via {cur} -> {target})"
        # Si el path final también es symlink, mantenemos el check.
        if p.is_symlink() and _symlink_escapes_home(abs_path):
            return f"Error: la ruta es un symlink y apunta fuera de tu home. Ruta: {abs_path}"
        return None
    except Exception:
        # Si algo falla en el check, preferimos permitir para no romper flujos,
        # pero podrías endurecer si lo quieres.
        return None

def _backup_base_dir() -> Path:
    # Por defecto intentamos guardar backups dentro del cwd para compatibilidad con sandboxes.
    # El usuario puede forzar otra ubicación con `JARVIS_BACKUP_PATH`.
    if os.environ.get("JARVIS_BACKUP_PATH"):
        return Path(os.environ.get("JARVIS_BACKUP_PATH", "")).expanduser().resolve()
    app_dir = os.environ.get("JARVIS_APP_DIR")
    if app_dir:
        return Path(app_dir).expanduser().resolve() / "backups"
    return Path(os.getcwd()).resolve() / ".jarvis" / "backups"

def _ensure_backup_dirs() -> tuple[Path, Path]:
    base = _backup_base_dir()
    files_dir = base / "files"
    meta_dir = base / "meta"
    files_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    return files_dir, meta_dir

def _lock_base_dir() -> Path:
    # Prefer a path inside the current working directory for sandbox compatibility.
    if os.environ.get("JARVIS_LOCK_PATH"):
        return Path(os.environ.get("JARVIS_LOCK_PATH", "")).expanduser().resolve()
    return Path(os.getcwd()).resolve() / ".jarvis" / "locks"

def _acquire_path_lock(abs_path: str, timeout_seconds: int = 25) -> Optional[Path]:
    """
    Bloqueo simple por ruta (archivo lock) para evitar condiciones de carrera.
    """
    try:
        lock_dir = _lock_base_dir()
        lock_dir.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(abs_path.encode("utf-8", errors="replace")).hexdigest()
        lock_file = lock_dir / f"{h}.lock"
        start = time.time()
        while True:
            try:
                fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, b"lock")
                os.close(fd)
                return lock_file
            except FileExistsError:
                if (time.time() - start) >= timeout_seconds:
                    return None
                time.sleep(0.1)
    except Exception:
        return None

def _release_path_lock(lock_file: Path) -> None:
    try:
        if lock_file.exists():
            lock_file.unlink()
    except Exception:
        pass

@contextmanager
def _path_lock(abs_path: str):
    lock_file = _acquire_path_lock(abs_path)
    if lock_file is None:
        raise RuntimeError("No pude adquirir lock de ruta (timeout).")
    try:
        yield
    finally:
        _release_path_lock(lock_file)

def _create_file_backup(src: Path) -> str:
    """
    Crea un backup de un archivo existente para rollback.
    Retorna un token.
    """
    files_dir, meta_dir = _ensure_backup_dirs()
    token = uuid.uuid4().hex
    backup_path = files_dir / f"{token}.bak"

    # Copiamos bytes para soportar cualquier contenido.
    backup_path.write_bytes(src.read_bytes())
    meta_path = meta_dir / f"{token}.json"
    meta = {
        "type": "file",
        "original_path": str(src.resolve()),
        "backup_path": str(backup_path),
        "created_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return token

def _create_move_backup(from_path: Path, to_path: Path) -> str:
    files_dir, meta_dir = _ensure_backup_dirs()
    token = uuid.uuid4().hex
    _ = files_dir  # solo para asegurar dirs
    meta_path = meta_dir / f"{token}.json"
    meta = {
        "type": "move",
        "from_path": str(from_path.resolve()),
        "to_path": str(to_path.resolve()),
        "created_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return token

def _create_trash_backup(original_path: Path, trash_dest: Path) -> str:
    files_dir, meta_dir = _ensure_backup_dirs()
    _ = files_dir
    token = uuid.uuid4().hex
    meta_path = meta_dir / f"{token}.json"
    meta = {
        "type": "trash",
        "original_path": str(original_path.resolve()),
        "trash_dest": str(trash_dest.resolve()),
        "created_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return token

def rollback(token: str, overwrite: bool = False) -> str:
    """
    Restaura una acción respaldada por token (últimos cambios con backup).
    """
    try:
        if _read_only_mode() and not _read_only_allow_undo():
            return "Error: JARVIS_READ_ONLY=true. rollback deshabilitado."
        base = _backup_base_dir()
        meta_path = base / "meta" / f"{token}.json"
        if not meta_path.is_file():
            return f"Error: token no existe: {token}"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        mtype = meta.get("type")

        if mtype == "file":
            original_path = Path(str(meta.get("original_path") or "")).expanduser()
            backup_path = Path(str(meta.get("backup_path") or "")).expanduser()
            if not backup_path.is_file():
                return f"Error: backup no existe: {backup_path}"
            if original_path.exists() and not overwrite:
                return f"Error: destino existe: {original_path}. Usa overwrite=true."
            original_path.parent.mkdir(parents=True, exist_ok=True)
            original_path.write_bytes(backup_path.read_bytes())
            return f"Rollback OK: restaurado {original_path}"

        if mtype == "move":
            from_path = Path(str(meta.get("from_path") or "")).expanduser()
            to_path = Path(str(meta.get("to_path") or "")).expanduser()
            if not to_path.exists():
                return f"Error: no existe la ruta donde estaba movido: {to_path}"
            if from_path.exists() and not overwrite:
                return f"Error: destino existe: {from_path}. Usa overwrite=true."
            from_path.parent.mkdir(parents=True, exist_ok=True)
            if from_path.exists() and overwrite:
                if from_path.is_dir():
                    shutil.rmtree(str(from_path))
                else:
                    from_path.unlink()
            shutil.move(str(to_path), str(from_path))
            return f"Rollback OK: movido de vuelta a {from_path}"

        if mtype == "trash":
            original_path = Path(str(meta.get("original_path") or "")).expanduser()
            trash_dest = Path(str(meta.get("trash_dest") or "")).expanduser()
            if not trash_dest.exists():
                return f"Error: la entrada de Trash no existe: {trash_dest}"
            if original_path.exists() and not overwrite:
                return f"Error: destino existe: {original_path}. Usa overwrite=true."
            original_path.parent.mkdir(parents=True, exist_ok=True)
            if original_path.exists() and overwrite:
                if original_path.is_dir():
                    shutil.rmtree(str(original_path))
                else:
                    original_path.unlink()
            shutil.move(str(trash_dest), str(original_path))
            return f"Rollback OK: restaurado desde Trash a {original_path}"

        return f"Error: tipo de token no soportado: {mtype}"
    except Exception as e:
        return f"Error en rollback: {e}"

def rollback_tokens(tokens: str, overwrite: bool = False) -> str:
    """
    Restaura múltiples tokens generados por borrados/ediciones (p.ej. Trash masivo).
    `tokens` puede ser una lista separada por comas o espacios.
    """
    try:
        if _read_only_mode() and not _read_only_allow_undo():
            return "Error: JARVIS_READ_ONLY=true. rollback_tokens deshabilitado."
        raw = (tokens or "").strip()
        if not raw:
            return "Error: tokens vacío."
        parts = [p.strip() for p in raw.replace(";", ",").replace("|", ",").split(",") if p.strip()]
        # Si viene como "a b c" (sin comas), fallback.
        if len(parts) <= 1 and " " in raw and "," not in raw:
            parts = [p.strip() for p in raw.split() if p.strip()]

        results: list[str] = []
        for t in parts:
            results.append(f"{t}: {rollback(t, overwrite=overwrite)}")
        ok = sum(1 for r in results if "Rollback OK" in r)
        return json.dumps({"tokens": parts, "ok": ok, "results": results}, ensure_ascii=False)
    except Exception as e:
        return f"Error en rollback_tokens: {e}"

def _load_xdg_user_dirs() -> dict[str, str]:
    """
    Lee `~/.config/user-dirs.dirs` (XDG user dirs) y devuelve un mapeo por categoría.

    Categorías soportadas: documents, downloads, desktop, music, pictures, videos, public.
    """
    global _XDG_USER_DIRS_CACHE
    if _XDG_USER_DIRS_CACHE is not None:
        return _XDG_USER_DIRS_CACHE

    home = Path.home().resolve()
    xdg_file = home / ".config" / "user-dirs.dirs"
    result: dict[str, str] = {}
    if not xdg_file.is_file():
        _XDG_USER_DIRS_CACHE = result
        return result

    var_map = {
        "documents": "XDG_DOCUMENTS_DIR",
        "downloads": "XDG_DOWNLOAD_DIR",
        "desktop": "XDG_DESKTOP_DIR",
        "music": "XDG_MUSIC_DIR",
        "pictures": "XDG_PICTURES_DIR",
        "videos": "XDG_VIDEOS_DIR",
        "public": "XDG_PUBLICSHARE_DIR",
    }

    try:
        text = xdg_file.read_text(encoding="utf-8", errors="replace")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")

            # Solo nos interesan las variables del mapa.
            cat: Optional[str] = None
            for c, v in var_map.items():
                if v == key:
                    cat = c
                    break
            if not cat:
                continue

            # Sustituye $HOME y expande el resto de variables.
            if "$HOME" in val:
                val = val.replace("$HOME", str(home))
            expanded = os.path.expandvars(val)
            expanded = os.path.abspath(expanded)

            if expanded.startswith(str(home)):
                result[cat] = expanded
    except Exception:
        # Si hay corrupción/encoding raro, simplemente caemos en el mapeo fuzzy.
        result = {}

    _XDG_USER_DIRS_CACHE = result
    return result

def _ensure_in_home_or_allow(target: Path, allow_dangerous: bool, action: str) -> Optional[str]:
    home = Path.home().resolve()
    if _is_relative_to(target, home):
        return None
    if allow_dangerous:
        return None
    return f"Error: {action} fuera de tu home requiere allow_dangerous=true."


def tool_result(status: str, data: Any = None, message: str = "") -> str:
    """
    Standard wrapper for tool returns.
    Returns a JSON string representing the execution result so the LLM
    can parse it easily.
    """
    result = {"status": status}
    if data is not None:
        result["data"] = data
    if message:
        result["message"] = message
    return json.dumps(result, ensure_ascii=False)


__all__ = [
    "_POLICY_CACHE",
    "_norm_text",
    "_is_relative_to",
    "_read_only_mode",
    "_read_only_allow_undo",
    "_load_policy",
    "_policy_forbidden_reason",
    "_policy_require_confirm",
    "policy_show",
    "policy_set",
    "policy_reset",
    "_allow_symlink_escape",
    "_symlink_escapes_home",
    "_validate_symlink_for_path",
    "_backup_base_dir",
    "_ensure_backup_dirs",
    "_lock_base_dir",
    "_acquire_path_lock",
    "_release_path_lock",
    "_path_lock",
    "_create_file_backup",
    "_create_move_backup",
    "_create_trash_backup",
    "_load_xdg_user_dirs",
    "_ensure_in_home_or_allow",
    "rollback",
    "rollback_tokens",
    "tool_result",
]
