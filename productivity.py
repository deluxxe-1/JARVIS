"""
JARVIS Productivity Module — Recordatorios, Macros y Gestor de Contraseñas.

Subsistemas:
1. Reminders: recordatorios con daemon thread, notificaciones toast
2. Macros: secuencias de acciones reutilizables (built-in + custom)
3. Passwords: generación y almacenamiento encriptado (Fernet/AES)
"""

import json
import os
import secrets
import string
import threading
import time
import base64
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Any


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

_JARVIS_DIR = Path(os.environ.get(
    "JARVIS_APP_DIR",
    os.path.join(os.path.expanduser("~"), ".jarvis"),
))

REMINDERS_PATH = _JARVIS_DIR / "reminders.json"
MACROS_PATH = _JARVIS_DIR / "macros.json"
VAULT_PATH = _JARVIS_DIR / "vault.enc"
REMINDER_CHECK_INTERVAL = 30  # segundos


# ---------------------------------------------------------------------------
# Utilidades de persistencia
# ---------------------------------------------------------------------------

def _ensure_dir():
    """Asegura que el directorio .jarvis existe."""
    _JARVIS_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> Any:
    """Carga un archivo JSON. Devuelve [] o {} si no existe."""
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return [] if "reminders" in str(path) else {}


def _save_json(path: Path, data: Any) -> None:
    """Guarda datos a un archivo JSON de forma atómica."""
    _ensure_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ============================================================================
# 1. RECORDATORIOS / TEMPORIZADORES
# ============================================================================

_reminder_thread: Optional[threading.Thread] = None
_reminder_stop = threading.Event()


def _generate_reminder_id() -> str:
    """Genera un ID corto único para un recordatorio."""
    return secrets.token_hex(4)


def set_reminder(
    message: str,
    minutes: Optional[float] = None,
    at_time: Optional[str] = None,
) -> str:
    """
    Crea un recordatorio que se disparará como notificación del sistema.

    Args:
        message: Mensaje del recordatorio.
        minutes: Minutos desde ahora (ej: 30, 0.5).
        at_time: Hora específica en formato HH:MM (ej: "14:30"). Se ignora si se especifica minutes.
    """
    try:
        if not message or not message.strip():
            return "Error: message vacío."

        now = datetime.now()

        if minutes is not None:
            if minutes <= 0:
                return "Error: los minutos deben ser positivos."
            trigger_at = now + timedelta(minutes=float(minutes))
        elif at_time:
            try:
                parts = at_time.strip().split(":")
                h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
                trigger_at = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if trigger_at <= now:
                    trigger_at += timedelta(days=1)
            except (ValueError, IndexError):
                return "Error: formato de hora inválido. Usa HH:MM (ej: '14:30')."
        else:
            return "Error: debes especificar 'minutes' o 'at_time'."

        reminder_id = _generate_reminder_id()
        reminder = {
            "id": reminder_id,
            "message": message.strip(),
            "trigger_at": trigger_at.isoformat(timespec="seconds"),
            "created_at": now.isoformat(timespec="seconds"),
            "triggered": False,
        }

        reminders = _load_json(REMINDERS_PATH)
        if not isinstance(reminders, list):
            reminders = []
        reminders.append(reminder)
        _save_json(REMINDERS_PATH, reminders)

        _ensure_reminder_daemon()

        time_str = trigger_at.strftime("%H:%M:%S")
        return json.dumps({
            "status": "ok",
            "id": reminder_id,
            "message": message.strip(),
            "trigger_at": time_str,
            "in_minutes": round(float(minutes) if minutes else (trigger_at - now).total_seconds() / 60, 1),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en set_reminder: {e}"


def set_timer(label: str = "Timer", minutes: float = 5) -> str:
    """
    Establece un temporizador simple.

    Args:
        label: Etiqueta del timer (ej: "Descanso", "Reunión").
        minutes: Minutos para el timer.
    """
    return set_reminder(f"⏰ Timer: {label}", minutes=minutes)


def list_reminders() -> str:
    """
    Lista todos los recordatorios pendientes y completados.
    """
    try:
        reminders = _load_json(REMINDERS_PATH)
        if not isinstance(reminders, list):
            reminders = []

        now = datetime.now()
        pending = []
        completed = []

        for r in reminders:
            trigger = datetime.fromisoformat(r["trigger_at"])
            entry = {
                "id": r["id"],
                "message": r["message"],
                "trigger_at": r["trigger_at"],
                "triggered": r.get("triggered", False),
            }
            if not r.get("triggered", False) and trigger > now:
                remaining = (trigger - now).total_seconds()
                entry["remaining_minutes"] = round(remaining / 60, 1)
                pending.append(entry)
            else:
                completed.append(entry)

        return json.dumps({
            "pending": pending,
            "completed": completed[-10:],  # últimos 10 completados
            "total_pending": len(pending),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en list_reminders: {e}"


def cancel_reminder(reminder_id: str) -> str:
    """
    Cancela un recordatorio pendiente.

    Args:
        reminder_id: ID del recordatorio (obtenido con list_reminders o set_reminder).
    """
    try:
        if not reminder_id:
            return "Error: reminder_id vacío."

        reminders = _load_json(REMINDERS_PATH)
        if not isinstance(reminders, list):
            return "Error: no hay recordatorios."

        found = False
        new_list = []
        for r in reminders:
            if r.get("id") == reminder_id.strip():
                found = True
                continue
            new_list.append(r)

        if not found:
            return f"Error: no se encontró recordatorio con ID '{reminder_id}'."

        _save_json(REMINDERS_PATH, new_list)
        return f"Recordatorio '{reminder_id}' cancelado."
    except Exception as e:
        return f"Error en cancel_reminder: {e}"


def _check_and_trigger_reminders():
    """Revisa y dispara recordatorios vencidos."""
    try:
        reminders = _load_json(REMINDERS_PATH)
        if not isinstance(reminders, list) or not reminders:
            return

        now = datetime.now()
        modified = False

        for r in reminders:
            if r.get("triggered", False):
                continue
            trigger = datetime.fromisoformat(r["trigger_at"])
            if now >= trigger:
                r["triggered"] = True
                modified = True
                # Disparar notificación
                try:
                    from automation import show_notification
                    show_notification(
                        title="🔔 JARVIS Recordatorio",
                        message=r["message"],
                        timeout=15,
                    )
                except Exception:
                    pass

        if modified:
            # Limpiar recordatorios antiguos (>24h completados)
            cutoff = now - timedelta(hours=24)
            cleaned = [
                r for r in reminders
                if not r.get("triggered") or datetime.fromisoformat(r["trigger_at"]) > cutoff
            ]
            _save_json(REMINDERS_PATH, cleaned)
    except Exception:
        pass


def _reminder_daemon():
    """Hilo daemon que revisa recordatorios periódicamente."""
    while not _reminder_stop.is_set():
        _check_and_trigger_reminders()
        _reminder_stop.wait(REMINDER_CHECK_INTERVAL)


def _ensure_reminder_daemon():
    """Inicia el daemon de recordatorios si no está corriendo."""
    global _reminder_thread
    if _reminder_thread is not None and _reminder_thread.is_alive():
        return
    _reminder_stop.clear()
    _reminder_thread = threading.Thread(target=_reminder_daemon, daemon=True, name="jarvis-reminders")
    _reminder_thread.start()


def stop_reminder_daemon():
    """Detiene el daemon de recordatorios."""
    _reminder_stop.set()


# ============================================================================
# 2. MACROS
# ============================================================================

_BUILTIN_MACROS: dict[str, dict[str, Any]] = {
    "trabajo": {
        "description": "Modo trabajo: Chrome + VSCode + Teams, volumen al 30%",
        "steps": [
            {"action": "open_application", "args": {"app_name": "Chrome"}},
            {"action": "open_application", "args": {"app_name": "VSCode"}},
            {"action": "open_application", "args": {"app_name": "Teams"}},
            {"action": "set_volume", "args": {"level": 30}},
        ],
        "builtin": True,
    },
    "gaming": {
        "description": "Modo gaming: Steam + Discord, volumen al 80%",
        "steps": [
            {"action": "open_application", "args": {"app_name": "Steam"}},
            {"action": "open_application", "args": {"app_name": "Discord"}},
            {"action": "set_volume", "args": {"level": 80}},
        ],
        "builtin": True,
    },
    "estudio": {
        "description": "Modo estudio: Chrome + Notepad, volumen al 20%",
        "steps": [
            {"action": "open_application", "args": {"app_name": "Chrome"}},
            {"action": "open_application", "args": {"app_name": "Notepad"}},
            {"action": "set_volume", "args": {"level": 20}},
        ],
        "builtin": True,
    },
    "presentacion": {
        "description": "Modo presentación: PowerPoint, volumen silenciado",
        "steps": [
            {"action": "open_application", "args": {"app_name": "PowerPoint"}},
            {"action": "toggle_mute", "args": {"mute": True}},
        ],
        "builtin": True,
    },
}


def _get_all_macros() -> dict[str, dict]:
    """Combina macros built-in con las del usuario."""
    user_macros = _load_json(MACROS_PATH)
    if not isinstance(user_macros, dict):
        user_macros = {}
    combined = dict(_BUILTIN_MACROS)
    combined.update(user_macros)
    return combined


# Mapeo de acciones válidas para macros
_MACRO_ACTION_MAP: dict[str, Any] = {}


def _init_macro_actions():
    """Inicializa el mapeo de acciones para macros (lazy load)."""
    global _MACRO_ACTION_MAP
    if _MACRO_ACTION_MAP:
        return
    try:
        from automation import (
            open_application, close_application, set_volume, toggle_mute,
            open_url, set_brightness, take_screenshot, show_notification,
            set_clipboard, get_clipboard,
        )
        _MACRO_ACTION_MAP = {
            "open_application": open_application,
            "close_application": close_application,
            "set_volume": set_volume,
            "toggle_mute": toggle_mute,
            "open_url": open_url,
            "set_brightness": set_brightness,
            "take_screenshot": take_screenshot,
            "show_notification": show_notification,
            "set_clipboard": set_clipboard,
        }
    except Exception:
        pass
    try:
        from tools import run_command
        _MACRO_ACTION_MAP["run_command"] = run_command
    except Exception:
        pass


def create_macro(name: str, steps: list[dict[str, Any]], description: str = "") -> str:
    """
    Crea una macro personalizada (secuencia de acciones reutilizable).

    Args:
        name: Nombre único de la macro (ej: "mi_workflow").
        steps: Lista de pasos. Cada paso es {"action": "nombre_funcion", "args": {...}}.
               Acciones disponibles: open_application, close_application, set_volume,
               toggle_mute, open_url, set_brightness, take_screenshot, show_notification,
               set_clipboard, run_command.
        description: Descripción de qué hace la macro.
    """
    try:
        if not name or not name.strip():
            return "Error: nombre de macro vacío."
        name = name.strip().lower().replace(" ", "_")

        if name in _BUILTIN_MACROS:
            return f"Error: '{name}' es una macro built-in y no puede sobreescribirse."

        if not steps or not isinstance(steps, list):
            return "Error: steps debe ser una lista de acciones."

        _init_macro_actions()
        valid_actions = set(_MACRO_ACTION_MAP.keys())

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                return f"Error: paso {i+1} no es un diccionario."
            action = step.get("action", "")
            if action not in valid_actions:
                return f"Error: acción '{action}' no válida en paso {i+1}. Disponibles: {sorted(valid_actions)}"

        macro = {
            "description": description or f"Macro personalizada: {name}",
            "steps": steps,
            "builtin": False,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

        user_macros = _load_json(MACROS_PATH)
        if not isinstance(user_macros, dict):
            user_macros = {}
        user_macros[name] = macro
        _save_json(MACROS_PATH, user_macros)

        return json.dumps({
            "status": "ok",
            "name": name,
            "steps_count": len(steps),
            "description": macro["description"],
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en create_macro: {e}"


def run_macro(name: str) -> str:
    """
    Ejecuta una macro guardada (secuencia de acciones).

    Args:
        name: Nombre de la macro a ejecutar.
    """
    try:
        if not name:
            return "Error: nombre de macro vacío."
        name = name.strip().lower().replace(" ", "_")

        all_macros = _get_all_macros()
        if name not in all_macros:
            available = sorted(all_macros.keys())
            return f"Error: macro '{name}' no existe. Disponibles: {available}"

        _init_macro_actions()
        macro = all_macros[name]
        steps = macro.get("steps", [])
        results = []

        for i, step in enumerate(steps):
            action = step.get("action", "")
            args = step.get("args", {})

            func = _MACRO_ACTION_MAP.get(action)
            if func is None:
                results.append(f"Paso {i+1} ({action}): SKIP — función no disponible")
                continue

            try:
                # close_application necesita confirm=True
                if action == "close_application" and "confirm" not in args:
                    args["confirm"] = True
                result = func(**args)
                results.append(f"Paso {i+1} ({action}): OK — {str(result)[:100]}")
            except Exception as e:
                results.append(f"Paso {i+1} ({action}): ERROR — {e}")

            # Pausa breve entre acciones para que las apps carguen
            time.sleep(0.5)

        return json.dumps({
            "macro": name,
            "description": macro.get("description", ""),
            "steps_executed": len(results),
            "results": results,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en run_macro: {e}"


def list_macros() -> str:
    """
    Lista todas las macros disponibles (built-in y personalizadas).
    """
    try:
        all_macros = _get_all_macros()
        listing = []
        for name, macro in sorted(all_macros.items()):
            listing.append({
                "name": name,
                "description": macro.get("description", ""),
                "steps": len(macro.get("steps", [])),
                "builtin": macro.get("builtin", False),
            })
        return json.dumps({"macros": listing, "total": len(listing)}, ensure_ascii=False)
    except Exception as e:
        return f"Error en list_macros: {e}"


def delete_macro(name: str, confirm: bool = False) -> str:
    """
    Elimina una macro personalizada.

    Args:
        name: Nombre de la macro.
        confirm: Requerido para confirmar la eliminación.
    """
    try:
        if not confirm:
            return f"Confirmación requerida: ¿eliminar macro '{name}'? Repite con confirm=true."
        name = name.strip().lower().replace(" ", "_")

        if name in _BUILTIN_MACROS:
            return f"Error: '{name}' es una macro built-in y no puede eliminarse."

        user_macros = _load_json(MACROS_PATH)
        if not isinstance(user_macros, dict) or name not in user_macros:
            return f"Error: macro '{name}' no existe."

        del user_macros[name]
        _save_json(MACROS_PATH, user_macros)
        return f"Macro '{name}' eliminada."
    except Exception as e:
        return f"Error en delete_macro: {e}"


# ============================================================================
# 3. GESTOR DE CONTRASEÑAS
# ============================================================================

def _derive_key(master: str) -> bytes:
    """Deriva una clave Fernet a partir de una master password."""
    # PBKDF2-like: SHA256 con salt fijo (simple pero funcional para uso personal)
    salt = b"JARVIS_VAULT_SALT_2026"
    dk = hashlib.pbkdf2_hmac("sha256", master.encode("utf-8"), salt, iterations=100_000)
    return base64.urlsafe_b64encode(dk)


def _get_master_key() -> Optional[str]:
    """Obtiene la master key del vault."""
    key = os.environ.get("JARVIS_VAULT_KEY", "").strip()
    if key:
        return key
    return None


def _get_fernet():
    """Crea un objeto Fernet con la master key."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None, "Error: librería 'cryptography' no instalada. Ejecuta: pip install cryptography"

    master = _get_master_key()
    if not master:
        return None, "Error: JARVIS_VAULT_KEY no configurado. Set JARVIS_VAULT_KEY=tu_clave_maestra"

    key = _derive_key(master)
    return Fernet(key), None


def _load_vault() -> tuple[dict[str, Any], Optional[str]]:
    """Carga el vault desencriptado. Devuelve (datos, error)."""
    fernet, err = _get_fernet()
    if err:
        return {}, err

    _ensure_dir()
    if not VAULT_PATH.is_file():
        return {}, None

    try:
        encrypted = VAULT_PATH.read_bytes()
        decrypted = fernet.decrypt(encrypted)
        data = json.loads(decrypted.decode("utf-8"))
        return data if isinstance(data, dict) else {}, None
    except Exception as e:
        return {}, f"Error al desencriptar vault (¿master key incorrecta?): {e}"


def _save_vault(data: dict[str, Any]) -> Optional[str]:
    """Guarda el vault encriptado."""
    fernet, err = _get_fernet()
    if err:
        return err

    _ensure_dir()
    try:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        encrypted = fernet.encrypt(payload)
        tmp = VAULT_PATH.with_suffix(".tmp")
        tmp.write_bytes(encrypted)
        tmp.replace(VAULT_PATH)
        return None
    except Exception as e:
        return f"Error al guardar vault: {e}"


def generate_password(
    length: int = 16,
    include_special: bool = True,
    count: int = 1,
) -> str:
    """
    Genera una o varias contraseñas seguras.

    Args:
        length: Longitud de la contraseña (mín 8, máx 128).
        include_special: Si incluir caracteres especiales (!@#$%...).
        count: Número de contraseñas a generar.
    """
    try:
        if length < 8:
            return "Error: longitud mínima es 8."
        if length > 128:
            return "Error: longitud máxima es 128."
        if count < 1 or count > 20:
            return "Error: count debe estar entre 1 y 20."

        alphabet = string.ascii_letters + string.digits
        if include_special:
            alphabet += "!@#$%&*+-=?"

        passwords = []
        for _ in range(count):
            while True:
                pw = "".join(secrets.choice(alphabet) for _ in range(length))
                # Validar que tenga al menos 1 mayúscula, 1 minúscula, 1 dígito
                has_upper = any(c.isupper() for c in pw)
                has_lower = any(c.islower() for c in pw)
                has_digit = any(c.isdigit() for c in pw)
                has_special = any(c in "!@#$%&*+-=?" for c in pw) if include_special else True
                if has_upper and has_lower and has_digit and has_special:
                    break
            passwords.append(pw)

        if count == 1:
            return json.dumps({
                "password": passwords[0],
                "length": length,
                "strength": "fuerte" if length >= 16 else "media",
            }, ensure_ascii=False)

        return json.dumps({
            "passwords": passwords,
            "count": count,
            "length": length,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en generate_password: {e}"


def save_password(
    service: str,
    username: str = "",
    password: str = "",
) -> str:
    """
    Guarda las credenciales de un servicio en el vault encriptado.

    Args:
        service: Nombre del servicio (ej: "gmail", "github", "netflix").
        username: Nombre de usuario o email.
        password: Contraseña. Si vacío, se genera una de 20 chars automáticamente.
    """
    try:
        if not service or not service.strip():
            return "Error: nombre de servicio vacío."

        service = service.strip().lower()

        if not password:
            pw_result = generate_password(20, include_special=True)
            try:
                pw_data = json.loads(pw_result)
                password = pw_data.get("password", "")
            except Exception:
                return "Error: no se pudo generar una contraseña."

        vault, err = _load_vault()
        if err:
            return err

        vault[service] = {
            "username": username,
            "password": password,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

        save_err = _save_vault(vault)
        if save_err:
            return save_err

        return json.dumps({
            "status": "ok",
            "service": service,
            "username": username,
            "password_saved": True,
            "password_length": len(password),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en save_password: {e}"


def get_password(service: str) -> str:
    """
    Recupera las credenciales de un servicio del vault.

    Args:
        service: Nombre del servicio a buscar.
    """
    try:
        if not service:
            return "Error: nombre de servicio vacío."

        vault, err = _load_vault()
        if err:
            return err

        service = service.strip().lower()
        if service not in vault:
            # Búsqueda fuzzy
            matches = [k for k in vault.keys() if service in k or k in service]
            if matches:
                return f"Error: servicio '{service}' no encontrado. ¿Quizás: {matches}?"
            return f"Error: servicio '{service}' no encontrado en el vault."

        entry = vault[service]
        return json.dumps({
            "service": service,
            "username": entry.get("username", ""),
            "password": entry.get("password", ""),
            "created_at": entry.get("created_at", ""),
            "updated_at": entry.get("updated_at", ""),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en get_password: {e}"


def list_passwords() -> str:
    """
    Lista todos los servicios guardados en el vault (sin mostrar contraseñas).
    """
    try:
        vault, err = _load_vault()
        if err:
            return err

        services = []
        for name, entry in sorted(vault.items()):
            services.append({
                "service": name,
                "username": entry.get("username", ""),
                "password_length": len(entry.get("password", "")),
                "updated_at": entry.get("updated_at", ""),
            })

        return json.dumps({
            "services": services,
            "total": len(services),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en list_passwords: {e}"


def delete_password(service: str, confirm: bool = False) -> str:
    """
    Elimina las credenciales de un servicio del vault.

    Args:
        service: Nombre del servicio.
        confirm: Requerido para confirmar la eliminación.
    """
    try:
        if not confirm:
            return f"Confirmación requerida: ¿eliminar credenciales de '{service}'? Repite con confirm=true."

        vault, err = _load_vault()
        if err:
            return err

        service = service.strip().lower()
        if service not in vault:
            return f"Error: servicio '{service}' no encontrado."

        del vault[service]
        save_err = _save_vault(vault)
        if save_err:
            return save_err

        return f"Credenciales de '{service}' eliminadas del vault."
    except Exception as e:
        return f"Error en delete_password: {e}"
