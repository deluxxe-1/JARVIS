"""
JARVIS Voice Wake Word Listener — Escucha continua por micrófono.

Escucha constantemente el micrófono en segundo plano. Cuando detecta
la wake word "JARVIS", captura el comando de voz y ejecuta el callback.
"""

import os
import threading
import json
from typing import Optional

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

WAKE_WORD = os.environ.get("JARVIS_WAKE_WORD", "jarvis").lower()
_listener_active = threading.Event()
_listener_thread: Optional[threading.Thread] = None
_listener_callback = None


def set_voice_callback(callback) -> None:
    """Configura el callback que se ejecuta cuando se detecta un comando de voz."""
    global _listener_callback
    _listener_callback = callback


def start_voice_listener() -> str:
    """
    Inicia el listener de voz continuo en segundo plano.
    Cuando detecta la wake word (por defecto "JARVIS"), ejecuta el callback
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
                title="🎤 JARVIS Activado",
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
        target=_listener, daemon=True, name="jarvis-voice-listener"
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
