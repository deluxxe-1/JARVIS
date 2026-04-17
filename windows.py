"""
JARVIS Window Manager Module — Control de ventanas del escritorio.

Permite listar, mover, redimensionar y organizar ventanas abiertas.
Soporte multi-monitor: detecta monitores, mueve ventanas entre ellos.
"""

import json
import subprocess
import sys
from typing import Optional


# ==========================================================================
# Funciones públicas
# ==========================================================================

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


def list_monitors() -> str:
    """
    Lista todos los monitores conectados con su resolución, posición y si es primario.
    Devuelve un array numerado (monitor 1, 2, 3...) con los bounds de cada uno.
    """
    try:
        if sys.platform == "win32":
            return _list_monitors_win32()
        else:
            return json.dumps({
                "status": "error",
                "message": "list_monitors solo implementado en Windows."
            }, ensure_ascii=False)
    except Exception as e:
        return f"Error en list_monitors: {e}"


def move_to_monitor(
    title_contains: str,
    monitor: int = 2,
    maximize: bool = True,
) -> str:
    """
    Mueve una ventana a un monitor específico.

    Args:
        title_contains: Parte del título de la ventana a mover.
        monitor: Número del monitor destino (1=primario, 2=secundario, etc.).
        maximize: Si True, maximiza la ventana en el monitor destino.
    """
    try:
        if sys.platform == "win32":
            return _move_to_monitor_win32(title_contains, monitor, maximize)
        else:
            return json.dumps({
                "status": "error",
                "message": "move_to_monitor solo implementado en Windows."
            }, ensure_ascii=False)
    except Exception as e:
        return f"Error en move_to_monitor: {e}"


def snap_window(
    title_contains: str,
    position: str = "left",
    monitor: int = 0,
) -> str:
    """
    Posiciona una ventana en una zona del escritorio (snap).

    Args:
        title_contains: Parte del título de la ventana a mover.
        position: Posición: 'left', 'right', 'top', 'bottom', 'maximize', 'minimize',
                  'top-left', 'top-right', 'bottom-left', 'bottom-right', 'center'.
        monitor: Número del monitor (1, 2, 3...). Si 0, usa el monitor donde está la ventana actualmente.
    """
    try:
        if sys.platform == "win32":
            return _snap_window_win32(title_contains, position, monitor)
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
# Windows implementations — Multi-monitor
# ==========================================================================

def _get_monitors_win32() -> list[dict]:
    """Enumera todos los monitores con ctypes (EnumDisplayMonitors)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    monitors = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    MONITORINFOF_PRIMARY = 0x00000001

    def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))

        rc = info.rcMonitor
        work = info.rcWork
        monitors.append({
            "device": info.szDevice,
            "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
            "x": rc.left,
            "y": rc.top,
            "width": rc.right - rc.left,
            "height": rc.bottom - rc.top,
            "work_x": work.left,
            "work_y": work.top,
            "work_width": work.right - work.left,
            "work_height": work.bottom - work.top,
        })
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)

    # Ordenar: primario primero, luego por posición X
    monitors.sort(key=lambda m: (not m["primary"], m["x"]))

    # Añadir número (1-indexed)
    for i, m in enumerate(monitors):
        m["number"] = i + 1

    return monitors


def _list_monitors_win32() -> str:
    monitors = _get_monitors_win32()
    # Limpiar campos internos para la salida
    output = []
    for m in monitors:
        output.append({
            "monitor": m["number"],
            "device": m["device"],
            "primary": m["primary"],
            "resolution": f"{m['width']}x{m['height']}",
            "position": {"x": m["x"], "y": m["y"]},
            "work_area": {
                "x": m["work_x"], "y": m["work_y"],
                "width": m["work_width"], "height": m["work_height"],
            },
        })
    return json.dumps({
        "status": "ok",
        "monitors": output,
        "count": len(output),
    }, ensure_ascii=False)


def _move_to_monitor_win32(title_contains: str, monitor: int, maximize: bool) -> str:
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = _find_window_win32(title_contains)
    if not hwnd:
        return f"Error: no se encontró ventana con '{title_contains}'."

    monitors = _get_monitors_win32()
    if not monitors:
        return "Error: no se detectaron monitores."

    if monitor < 1 or monitor > len(monitors):
        names = ", ".join(
            f"{m['number']} ({'primario' if m['primary'] else m['device']})"
            for m in monitors
        )
        return f"Error: monitor {monitor} no existe. Monitores disponibles: {names}"

    target = monitors[monitor - 1]
    SWP_NOZORDER = 0x0004
    SW_RESTORE = 9
    SW_MAXIMIZE = 3

    # Restaurar si está maximizada (necesario para moverla)
    user32.ShowWindow(hwnd, SW_RESTORE)

    if maximize:
        # Mover al centro del monitor destino, luego maximizar
        cx = target["work_x"] + target["work_width"] // 4
        cy = target["work_y"] + target["work_height"] // 4
        w = target["work_width"] // 2
        h = target["work_height"] // 2
        user32.SetWindowPos(hwnd, None, cx, cy, w, h, SWP_NOZORDER)
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
    else:
        # Mover centrada en el monitor destino
        w = min(1024, target["work_width"])
        h = min(768, target["work_height"])
        cx = target["work_x"] + (target["work_width"] - w) // 2
        cy = target["work_y"] + (target["work_height"] - h) // 2
        user32.SetWindowPos(hwnd, None, cx, cy, w, h, SWP_NOZORDER)

    # Traer al frente
    user32.SetForegroundWindow(hwnd)

    return json.dumps({
        "status": "ok",
        "message": f"Ventana '{title_contains}' movida al monitor {monitor}.",
        "monitor": {
            "number": target["number"],
            "device": target["device"],
            "resolution": f"{target['width']}x{target['height']}",
        },
        "maximized": maximize,
    }, ensure_ascii=False)


# ==========================================================================
# Windows implementations — Core
# ==========================================================================

def _list_windows_win32() -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    monitors = _get_monitors_win32()
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
                    # Detectar en qué monitor está
                    win_cx = (rect.left + rect.right) // 2
                    win_cy = (rect.top + rect.bottom) // 2
                    mon_num = 1
                    for m in monitors:
                        if (m["x"] <= win_cx < m["x"] + m["width"]
                                and m["y"] <= win_cy < m["y"] + m["height"]):
                            mon_num = m["number"]
                            break
                    windows.append({
                        "title": title,
                        "x": rect.left, "y": rect.top,
                        "width": rect.right - rect.left,
                        "height": rect.bottom - rect.top,
                        "monitor": mon_num,
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


def _snap_window_win32(title_contains: str, position: str, monitor: int = 0) -> str:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = _find_window_win32(title_contains)
    if not hwnd:
        return f"Error: no se encontró ventana con '{title_contains}'."

    # Determinar monitor objetivo
    monitors = _get_monitors_win32()
    if monitor > 0:
        if monitor > len(monitors):
            return f"Error: monitor {monitor} no existe. Hay {len(monitors)} monitores."
        target = monitors[monitor - 1]
    else:
        # Usar el monitor donde está la ventana actualmente
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        win_cx = (rect.left + rect.right) // 2
        win_cy = (rect.top + rect.bottom) // 2
        target = monitors[0]  # fallback al primario
        for m in monitors:
            if (m["x"] <= win_cx < m["x"] + m["width"]
                    and m["y"] <= win_cy < m["y"] + m["height"]):
                target = m
                break

    # Usar work area del monitor objetivo (excluye la barra de tareas)
    sx = target["work_x"]
    sy = target["work_y"]
    screen_w = target["work_width"]
    screen_h = target["work_height"]

    SWP_NOZORDER = 0x0004
    SW_RESTORE = 9
    SW_MAXIMIZE = 3
    SW_MINIMIZE = 6

    # Restaurar si está maximizada
    user32.ShowWindow(hwnd, SW_RESTORE)

    positions = {
        "left":         (sx, sy, screen_w // 2, screen_h),
        "right":        (sx + screen_w // 2, sy, screen_w // 2, screen_h),
        "top":          (sx, sy, screen_w, screen_h // 2),
        "bottom":       (sx, sy + screen_h // 2, screen_w, screen_h // 2),
        "top-left":     (sx, sy, screen_w // 2, screen_h // 2),
        "top-right":    (sx + screen_w // 2, sy, screen_w // 2, screen_h // 2),
        "bottom-left":  (sx, sy + screen_h // 2, screen_w // 2, screen_h // 2),
        "bottom-right": (sx + screen_w // 2, sy + screen_h // 2, screen_w // 2, screen_h // 2),
        "center":       (sx + screen_w // 4, sy + screen_h // 4, screen_w // 2, screen_h // 2),
    }

    pos = position.strip().lower()

    if pos == "maximize":
        # Mover al monitor objetivo primero, luego maximizar
        cx = sx + screen_w // 4
        cy = sy + screen_h // 4
        user32.SetWindowPos(hwnd, None, cx, cy, screen_w // 2, screen_h // 2, SWP_NOZORDER)
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        return json.dumps({"status": "ok", "action": "maximize", "monitor": target["number"]}, ensure_ascii=False)
    elif pos == "minimize":
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        return json.dumps({"status": "ok", "action": "minimize"}, ensure_ascii=False)
    elif pos in positions:
        x, y, w, h = positions[pos]
        user32.SetWindowPos(hwnd, None, x, y, w, h, SWP_NOZORDER)
        return json.dumps({
            "status": "ok", "position": pos,
            "monitor": target["number"],
            "rect": {"x": x, "y": y, "w": w, "h": h},
        }, ensure_ascii=False)
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
