"""
JARVIS Media Controller Module — Control de reproducción multimedia.

Controla la reproducción de música/vídeo del sistema usando teclas multimedia
virtuales (funciona con Spotify, YouTube, VLC, Windows Media Player, etc.).
"""

import json
import sys
import subprocess
from typing import Optional


# ---------------------------------------------------------------------------
# Teclas multimedia (keycodes)
# ---------------------------------------------------------------------------

def _send_media_key(key_name: str) -> str:
    """Envía una tecla multimedia al sistema."""
    try:
        if sys.platform == "win32":
            return _send_media_key_windows(key_name)
        else:
            return _send_media_key_linux(key_name)
    except Exception as e:
        return f"Error enviando tecla multimedia: {e}"


def _send_media_key_windows(key_name: str) -> str:
    """Envía tecla multimedia en Windows usando ctypes."""
    try:
        import ctypes
        from ctypes import wintypes

        VK_MEDIA_MAP = {
            "play_pause": 0xB3,     # VK_MEDIA_PLAY_PAUSE
            "next": 0xB0,           # VK_MEDIA_NEXT_TRACK
            "previous": 0xB1,       # VK_MEDIA_PREV_TRACK
            "stop": 0xB2,           # VK_MEDIA_STOP
            "volume_up": 0xAF,      # VK_VOLUME_UP
            "volume_down": 0xAE,    # VK_VOLUME_DOWN
            "mute": 0xAD,           # VK_VOLUME_MUTE
        }

        vk_code = VK_MEDIA_MAP.get(key_name)
        if vk_code is None:
            return f"Error: tecla '{key_name}' no reconocida."

        # Simular keypress y release
        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002

        user32 = ctypes.windll.user32
        user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY, 0)
        user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

        return "ok"
    except Exception as e:
        return f"Error en Windows media key: {e}"


def _send_media_key_linux(key_name: str) -> str:
    """Envía tecla multimedia en Linux usando xdotool o playerctl."""
    key_map_playerctl = {
        "play_pause": "play-pause",
        "next": "next",
        "previous": "previous",
        "stop": "stop",
    }

    # Intentar con playerctl primero
    playerctl_cmd = key_map_playerctl.get(key_name)
    if playerctl_cmd:
        try:
            result = subprocess.run(
                ["playerctl", playerctl_cmd],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                return "ok"
        except FileNotFoundError:
            pass

    # Fallback a xdotool
    xdotool_map = {
        "play_pause": "XF86AudioPlay",
        "next": "XF86AudioNext",
        "previous": "XF86AudioPrev",
        "stop": "XF86AudioStop",
        "volume_up": "XF86AudioRaiseVolume",
        "volume_down": "XF86AudioLowerVolume",
        "mute": "XF86AudioMute",
    }

    xkey = xdotool_map.get(key_name)
    if xkey:
        try:
            subprocess.run(
                ["xdotool", "key", xkey],
                capture_output=True, text=True, timeout=3,
            )
            return "ok"
        except FileNotFoundError:
            return "Error: ni playerctl ni xdotool están instalados."

    return f"Error: tecla '{key_name}' no soportada en Linux."


# ---------------------------------------------------------------------------
# Herramientas públicas
# ---------------------------------------------------------------------------

def media_play_pause() -> str:
    """
    Reproducir/pausar la música o vídeo actual.
    Funciona con cualquier reproductor multimedia (Spotify, VLC, YouTube en navegador, etc.).
    """
    result = _send_media_key("play_pause")
    if result == "ok":
        return json.dumps({
            "status": "ok",
            "action": "play_pause",
            "message": "▶️⏸️ Reproducción alternada (play/pause).",
        }, ensure_ascii=False)
    return result


def media_next() -> str:
    """
    Salta a la siguiente pista/canción.
    """
    result = _send_media_key("next")
    if result == "ok":
        return json.dumps({
            "status": "ok",
            "action": "next_track",
            "message": "⏭️ Siguiente pista.",
        }, ensure_ascii=False)
    return result


def media_previous() -> str:
    """
    Vuelve a la pista/canción anterior.
    """
    result = _send_media_key("previous")
    if result == "ok":
        return json.dumps({
            "status": "ok",
            "action": "previous_track",
            "message": "⏮️ Pista anterior.",
        }, ensure_ascii=False)
    return result


def media_stop() -> str:
    """
    Detiene la reproducción completamente.
    """
    result = _send_media_key("stop")
    if result == "ok":
        return json.dumps({
            "status": "ok",
            "action": "stop",
            "message": "⏹️ Reproducción detenida.",
        }, ensure_ascii=False)
    return result


def now_playing() -> str:
    """
    Intenta detectar qué está reproduciéndose actualmente.
    Funciona mejor en Linux con playerctl. En Windows intenta leer el título de la ventana del reproductor.
    """
    try:
        if sys.platform != "win32":
            # Linux: usar playerctl
            try:
                artist = subprocess.run(
                    ["playerctl", "metadata", "artist"],
                    capture_output=True, text=True, timeout=3,
                ).stdout.strip()
                title = subprocess.run(
                    ["playerctl", "metadata", "title"],
                    capture_output=True, text=True, timeout=3,
                ).stdout.strip()
                player = subprocess.run(
                    ["playerctl", "status"],
                    capture_output=True, text=True, timeout=3,
                ).stdout.strip()

                if title:
                    return json.dumps({
                        "status": "ok",
                        "playing": True,
                        "title": title,
                        "artist": artist or "Desconocido",
                        "player_status": player,
                    }, ensure_ascii=False)
                else:
                    return json.dumps({
                        "status": "ok",
                        "playing": False,
                        "message": "No se detectó reproducción activa.",
                    }, ensure_ascii=False)
            except FileNotFoundError:
                return "Error: playerctl no instalado (sudo apt install playerctl)."

        else:
            # Windows: buscar ventanas de reproductores conocidos
            try:
                import ctypes
                from ctypes import wintypes

                user32 = ctypes.windll.user32
                EnumWindows = user32.EnumWindows
                GetWindowTextW = user32.GetWindowTextW
                GetWindowTextLengthW = user32.GetWindowTextLengthW
                IsWindowVisible = user32.IsWindowVisible

                players = ["Spotify", "VLC", "Windows Media Player",
                           "YouTube", "Music", "Groove"]

                titles = []
                WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

                def enum_callback(hwnd, _):
                    if IsWindowVisible(hwnd):
                        length = GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buf = ctypes.create_unicode_buffer(length + 1)
                            GetWindowTextW(hwnd, buf, length + 1)
                            title = buf.value
                            for player in players:
                                if player.lower() in title.lower():
                                    titles.append({"player": player, "title": title})
                    return True

                EnumWindows(WNDENUMPROC(enum_callback), 0)

                if titles:
                    return json.dumps({
                        "status": "ok",
                        "playing": True,
                        "detected": titles[:3],
                    }, ensure_ascii=False)
                else:
                    return json.dumps({
                        "status": "ok",
                        "playing": False,
                        "message": "No se detectaron reproductores activos.",
                    }, ensure_ascii=False)
            except Exception as e:
                return f"Error detectando reproductor en Windows: {e}"

    except Exception as e:
        return f"Error en now_playing: {e}"
