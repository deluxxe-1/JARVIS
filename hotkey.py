"""
JARVIS Hotkey Module — Atajo de teclado global (Win+J).

Permite invocar a JARVIS desde cualquier aplicación sin necesidad
de tener la terminal enfocada. Al pulsar la combinación de teclas,
se activa el micrófono o se muestra un prompt de texto según la config.
"""

import os
import threading
from typing import Optional, Callable


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

HOTKEY_COMBO = os.environ.get("JARVIS_HOTKEY", "win+j")
_hotkey_active = threading.Event()
_hotkey_thread: Optional[threading.Thread] = None
_hotkey_callback: Optional[Callable] = None


def start_hotkey_listener() -> str:
    """
    Inicia el listener de hotkey global en segundo plano.
    Cuando se detecta la combinación (por defecto Win+J), ejecuta el callback por defecto.
    """
    global _hotkey_thread, _hotkey_callback

    try:
        import keyboard
    except ImportError:
        return (
            "Error: librería 'keyboard' no instalada. Ejecuta: pip install keyboard\n"
            "Nota: en Linux requiere ejecutar como root."
        )

    if _hotkey_thread is not None and _hotkey_thread.is_alive():
        return f"El listener de hotkey ya está activo (combo: {HOTKEY_COMBO})."

    _hotkey_callback = None

    def _default_callback():
        """Callback por defecto: muestra notificación."""
        try:
            from automation import show_notification
            show_notification(
                title="🎤 JARVIS Activado",
                message="Di tu comando o escribe en la terminal.",
                timeout=5,
            )
        except Exception:
            pass

    def _listener():
        """Hilo que escucha el hotkey."""
        try:
            import keyboard
            cb = _hotkey_callback or _default_callback
            keyboard.add_hotkey(HOTKEY_COMBO, cb, suppress=False)
            _hotkey_active.set()
            keyboard.wait()  # bloquea hasta keyboard.unhook_all()
        except Exception:
            pass
        finally:
            _hotkey_active.clear()

    _hotkey_thread = threading.Thread(
        target=_listener, daemon=True, name="jarvis-hotkey"
    )
    _hotkey_thread.start()

    return f"Hotkey global '{HOTKEY_COMBO}' activado. Pulsa {HOTKEY_COMBO} desde cualquier app."


def stop_hotkey_listener() -> str:
    """
    Detiene el listener de hotkey global.
    """
    global _hotkey_thread

    try:
        import keyboard
        keyboard.unhook_all()
    except Exception:
        pass

    _hotkey_active.clear()
    _hotkey_thread = None
    return "Hotkey listener detenido."


def get_hotkey_status() -> str:
    """
    Devuelve el estado actual del listener de hotkey.
    """
    import json
    return json.dumps({
        "active": _hotkey_active.is_set(),
        "combo": HOTKEY_COMBO,
    }, ensure_ascii=False)


def change_hotkey(new_combo: str) -> str:
    """
    Cambia la combinación de hotkey (ej: 'ctrl+shift+j', 'win+k').

    Args:
        new_combo: Nueva combinación de teclas.
    """
    global HOTKEY_COMBO

    if not new_combo or not new_combo.strip():
        return "Error: combinación vacía."

    was_active = _hotkey_active.is_set()
    if was_active:
        stop_hotkey_listener()

    HOTKEY_COMBO = new_combo.strip().lower()

    if was_active:
        start_hotkey_listener(_hotkey_callback)

    return f"Hotkey cambiado a '{HOTKEY_COMBO}'."
