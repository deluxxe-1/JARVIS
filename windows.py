"""
JARVIS Window Manager Module — Control de ventanas del escritorio.

Permite listar, mover, redimensionar y organizar ventanas abiertas.
"""

import json
import subprocess
import sys
from typing import Optional


def list_windows() -> str:
    """
    Lista todas las ventanas visibles del escritorio con su título y dimensiones.
    """
    try:
        if sys.platform == "win32":
            return _list_windows_win32()
        else:
            return _list_windows_linux()
    except Exception as e:
        return f"Error en list_windows: {e}"


def snap_window(
    title_contains: str,
    position: str = "left",
) -> str:
    """
    Posiciona una ventana en una zona del escritorio (snap).

    Args:
        title_contains: Parte del título de la ventana a mover.
        position: Posición: 'left', 'right', 'top', 'bottom', 'maximize', 'minimize',
                  'top-left', 'top-right', 'bottom-left', 'bottom-right', 'center'.
    """
    try:
        if sys.platform == "win32":
            return _snap_window_win32(title_contains, position)
        else:
            return _snap_window_linux(title_contains, position)
    except Exception as e:
        return f"Error en snap_window: {e}"


def minimize_all() -> str:
    """
    Minimiza todas las ventanas (muestra escritorio).
    """
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # Win key down
            ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)  # D key down
            ctypes.windll.user32.keybd_event(0x44, 0, 2, 0)  # D key up
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)  # Win key up
            return json.dumps({"status": "ok", "message": "Escritorio mostrado (Win+D)."}, ensure_ascii=False)
        else:
            try:
                subprocess.run(["wmctrl", "-k", "on"], timeout=3, capture_output=True)
                return json.dumps({"status": "ok", "message": "Escritorio mostrado."}, ensure_ascii=False)
            except FileNotFoundError:
                return "Error: wmctrl no instalado (sudo apt install wmctrl)."
    except Exception as e:
        return f"Error en minimize_all: {e}"


def close_window(title_contains: str) -> str:
    """
    Cierra una ventana por parte de su título.

    Args:
        title_contains: Parte del título de la ventana a cerrar.
    """
    try:
        if not title_contains:
            return "Error: título vacío."

        if sys.platform == "win32":
            return _close_window_win32(title_contains)
        else:
            return _close_window_linux(title_contains)
    except Exception as e:
        return f"Error en close_window: {e}"


def focus_window(title_contains: str) -> str:
    """
    Trae una ventana al frente (foco).

    Args:
        title_contains: Parte del título de la ventana.
    """
    try:
        if not title_contains:
            return "Error: título vacío."

        if sys.platform == "win32":
            return _focus_window_win32(title_contains)
        else:
            return _focus_window_linux(title_contains)
    except Exception as e:
        return f"Error en focus_window: {e}"


# ==========================================================================
# Windows implementations
# ==========================================================================

def _list_windows_win32() -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    windows = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if title.strip():
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    windows.append({
                        "title": title,
                        "x": rect.left, "y": rect.top,
                        "width": rect.right - rect.left,
                        "height": rect.bottom - rect.top,
                        "hwnd": hwnd,
                    })
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)

    # Filtrar ventanas del sistema
    filtered = [
        {k: v for k, v in w.items() if k != "hwnd"}
        for w in windows
        if w["width"] > 0 and w["height"] > 0
        and w["title"] not in ("Program Manager", "Microsoft Text Input Application")
    ]

    return json.dumps({"status": "ok", "windows": filtered, "count": len(filtered)}, ensure_ascii=False)


def _snap_window_win32(title_contains: str, position: str) -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = _find_window_win32(title_contains)
    if not hwnd:
        return f"Error: no se encontró ventana con '{title_contains}'."

    # Obtener resolución de pantalla
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)

    SWP_NOZORDER = 0x0004
    SW_RESTORE = 9
    SW_MAXIMIZE = 3
    SW_MINIMIZE = 6

    # Restaurar si está maximizada
    user32.ShowWindow(hwnd, SW_RESTORE)

    positions = {
        "left":         (0, 0, screen_w // 2, screen_h),
        "right":        (screen_w // 2, 0, screen_w // 2, screen_h),
        "top":          (0, 0, screen_w, screen_h // 2),
        "bottom":       (0, screen_h // 2, screen_w, screen_h // 2),
        "top-left":     (0, 0, screen_w // 2, screen_h // 2),
        "top-right":    (screen_w // 2, 0, screen_w // 2, screen_h // 2),
        "bottom-left":  (0, screen_h // 2, screen_w // 2, screen_h // 2),
        "bottom-right": (screen_w // 2, screen_h // 2, screen_w // 2, screen_h // 2),
        "center":       (screen_w // 4, screen_h // 4, screen_w // 2, screen_h // 2),
    }

    pos = position.strip().lower()

    if pos == "maximize":
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        return json.dumps({"status": "ok", "action": "maximize"}, ensure_ascii=False)
    elif pos == "minimize":
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        return json.dumps({"status": "ok", "action": "minimize"}, ensure_ascii=False)
    elif pos in positions:
        x, y, w, h = positions[pos]
        user32.SetWindowPos(hwnd, None, x, y, w, h, SWP_NOZORDER)
        return json.dumps({"status": "ok", "position": pos, "rect": {"x": x, "y": y, "w": w, "h": h}}, ensure_ascii=False)
    else:
        return f"Error: posición '{pos}' no válida. Usa: {', '.join(list(positions.keys()) + ['maximize', 'minimize'])}"


def _find_window_win32(title_contains: str) -> Optional[int]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = [None]

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if title_contains.lower() in buf.value.lower():
                    found[0] = hwnd
                    return False
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0]


def _close_window_win32(title_contains: str) -> str:
    import ctypes
    hwnd = _find_window_win32(title_contains)
    if not hwnd:
        return f"Error: no se encontró ventana con '{title_contains}'."
    WM_CLOSE = 0x0010
    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    return json.dumps({"status": "ok", "message": f"Ventana '{title_contains}' cerrada."}, ensure_ascii=False)


def _focus_window_win32(title_contains: str) -> str:
    import ctypes
    hwnd = _find_window_win32(title_contains)
    if not hwnd:
        return f"Error: no se encontró ventana con '{title_contains}'."
    SW_RESTORE = 9
    ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    return json.dumps({"status": "ok", "message": f"Ventana '{title_contains}' al frente."}, ensure_ascii=False)


# ==========================================================================
# Linux implementations (wmctrl + xdotool)
# ==========================================================================

def _list_windows_linux() -> str:
    try:
        result = subprocess.run(
            ["wmctrl", "-lG"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return "Error: wmctrl no disponible (sudo apt install wmctrl)."

        windows = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split(None, 7)
            if len(parts) >= 8:
                windows.append({
                    "title": parts[7],
                    "x": int(parts[2]), "y": int(parts[3]),
                    "width": int(parts[4]), "height": int(parts[5]),
                })

        return json.dumps({"status": "ok", "windows": windows, "count": len(windows)}, ensure_ascii=False)
    except FileNotFoundError:
        return "Error: wmctrl no instalado."


def _snap_window_linux(title_contains: str, position: str) -> str:
    try:
        # Obtain screen size
        result = subprocess.run(
            ["xdpyinfo"], capture_output=True, text=True, timeout=3,
        )
        import re
        match = re.search(r"dimensions:\s+(\d+)x(\d+)", result.stdout)
        if not match:
            return "Error: no se pudo detectar la resolución."
        screen_w, screen_h = int(match.group(1)), int(match.group(2))

        positions = {
            "left":     f"0,0,0,{screen_w // 2},{screen_h}",
            "right":    f"0,{screen_w // 2},0,{screen_w // 2},{screen_h}",
            "maximize": "-1,-1,-1,-1,-1",
        }

        pos = position.strip().lower()
        if pos == "maximize":
            subprocess.run(["wmctrl", "-r", title_contains, "-b", "add,maximized_vert,maximized_horz"], timeout=3)
        elif pos in positions:
            subprocess.run(["wmctrl", "-r", title_contains, "-e", positions[pos]], timeout=3)
        else:
            return f"Error: posición '{pos}' no implementada en Linux."

        return json.dumps({"status": "ok", "position": pos}, ensure_ascii=False)
    except FileNotFoundError:
        return "Error: wmctrl no instalado."


def _close_window_linux(title_contains: str) -> str:
    try:
        subprocess.run(["wmctrl", "-c", title_contains], timeout=3)
        return json.dumps({"status": "ok", "message": f"Ventana '{title_contains}' cerrada."}, ensure_ascii=False)
    except FileNotFoundError:
        return "Error: wmctrl no instalado."


def _focus_window_linux(title_contains: str) -> str:
    try:
        subprocess.run(["wmctrl", "-a", title_contains], timeout=3)
        return json.dumps({"status": "ok", "message": f"Ventana '{title_contains}' al frente."}, ensure_ascii=False)
    except FileNotFoundError:
        return "Error: wmctrl no instalado."
