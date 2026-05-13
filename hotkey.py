"""
AARIS Voice Wake Word Listener — Escucha continua por micrófono.

Escucha constantemente el micrófono en segundo plano. Cuando detecta
la wake word "AARIS", captura el comando de voz y ejecuta el callback.
"""

import os
import threading
import json
from typing import Optional
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

WAKE_WORD = os.environ.get("AARIS_WAKE_WORD", "aaris").lower()
_listener_active = threading.Event()
_listener_thread: Optional[threading.Thread] = None
_listener_callback = None

# Hotkey (persistencia simple)
_AARIS_DIR = Path(os.environ.get("AARIS_APP_DIR", os.path.join(os.path.expanduser("~"), ".aaris")))
_HOTKEY_PATH = _AARIS_DIR / "hotkey.json"
_hotkey_combo = os.environ.get("AARIS_HOTKEY", "win+j").strip().lower() or "win+j"


def _ensure_dir() -> None:
    _AARIS_DIR.mkdir(parents=True, exist_ok=True)


def _load_hotkey() -> str:
    global _hotkey_combo
    try:
        if _HOTKEY_PATH.is_file():
            obj = json.loads(_HOTKEY_PATH.read_text(encoding="utf-8"))
            combo = (obj.get("combo") or "").strip().lower()
            if combo:
                _hotkey_combo = combo
    except Exception:
        pass
    return _hotkey_combo


def set_voice_callback(callback) -> None:
    """Configura el callback que se ejecuta cuando se detecta un comando de voz."""
    global _listener_callback
    _listener_callback = callback


def start_voice_listener() -> str:
    """
    Inicia el listener de voz continuo en segundo plano.
    Cuando detecta la wake word (por defecto "AARIS"), ejecuta el callback
    configurado con set_voice_callback(), o muestra una notificación por defecto.
    """
    global _listener_thread

    if _listener_thread is not None and _listener_thread.is_alive():
        return f"El listener de voz ya está activo (wake word: '{WAKE_WORD}')."

    def _default_callback(command: str):
        """Callback por defecto: muestra notificación."""
        try:
            from automation import show_notification
            show_notification(
                title="🎤 AARIS Activado",
                message=f"Comando detectado: {command}",
                timeout=5,
            )
        except Exception:
            print(f"[VoiceListener] Comando detectado: {command}")

    def _listener():
        """Hilo que escucha continuamente el micrófono."""
        try:
            from voice import create_listener
            listener = create_listener()

            if not listener.is_available():
                print("[VoiceListener] No hay micrófono disponible.")
                return

            print(f"[VoiceListener] Escuchando wake word '{WAKE_WORD}'...")
            _listener_active.set()

            cb = _listener_callback or _default_callback

            while _listener_active.is_set():
                try:
                    command = listener.listen_for_wake_word(WAKE_WORD)
                    if command and _listener_active.is_set():
                        print(f"[VoiceListener] Comando: {command}")
                        try:
                            cb(command)
                        except Exception as e:
                            print(f"[VoiceListener] Error en callback: {e}")
                except Exception as e:
                    # Timeout, no speech detected, etc — continuar escuchando
                    pass

        except ImportError as e:
            print(f"[VoiceListener] Dependencia faltante: {e}")
            print("[VoiceListener] Instala: pip install speechrecognition pyttsx3")
        except Exception as e:
            print(f"[VoiceListener] Error: {e}")
        finally:
            _listener_active.clear()

    _listener_thread = threading.Thread(
        target=_listener, daemon=True, name="aaris-voice-listener"
    )
    _listener_thread.start()

    return f"Listener de voz activado. Di '{WAKE_WORD}' seguido de tu comando."


def stop_voice_listener() -> str:
    """
    Detiene el listener de voz continuo.
    """
    global _listener_thread

    _listener_active.clear()
    _listener_thread = None
    return "Listener de voz detenido."


def get_listener_status() -> str:
    """
    Devuelve el estado actual del listener de voz.
    """
    return json.dumps({
        "active": _listener_active.is_set(),
        "wake_word": WAKE_WORD,
        "type": "voice",
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Hotkey API (compatibilidad con tests / README)
# ---------------------------------------------------------------------------


def get_hotkey_status() -> str:
    """
    Devuelve el estado del hotkey global (config y si hay listener activo).
    Nota: este módulo no registra un hotkey real del sistema; expone la config.
    """
    combo = _load_hotkey()
    return json.dumps(
        {
            "active": bool(_listener_active.is_set()),
            "combo": combo,
            "type": "hotkey",
        },
        ensure_ascii=False,
    )


def change_hotkey(combo: str) -> str:
    """
    Cambia el combo de hotkey persistiendo en `AARIS_APP_DIR/hotkey.json`.
    """
    global _hotkey_combo
    try:
        new_combo = (combo or "").strip().lower()
        if not new_combo:
            return "Error: combo vacío."
        _hotkey_combo = new_combo
        _ensure_dir()
        _HOTKEY_PATH.write_text(json.dumps({"combo": _hotkey_combo}, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"OK: hotkey cambiado a '{_hotkey_combo}'."
    except Exception as e:
        return f"Error en change_hotkey: {e}"
