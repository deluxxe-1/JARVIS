"""
JARVIS Automation Module — Control y automatización del PC (Windows).

Provee herramientas para:
- Abrir/cerrar aplicaciones
- Control de volumen y audio
- Capturas de pantalla
- Cambiar wallpaper
- Portapapeles
- Notificaciones del sistema
- Abrir URLs
- Bloquear pantalla / sleep / shutdown
- Información del sistema (CPU, RAM, disco, batería)
- Control de brillo
- Vaciar papelera de reciclaje
"""

import json
import os
import platform
import shutil
import subprocess
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _powershell_cmd() -> str:
    """Detecta el ejecutable de PowerShell disponible."""
    for cmd in ["pwsh", "powershell"]:
        if shutil.which(cmd):
            return cmd
    return "powershell"


def _run_ps(script: str, timeout: int = 15) -> tuple[int, str, str]:
    """Ejecuta un script PowerShell. Retorna (returncode, stdout, stderr)."""
    ps = _powershell_cmd()
    try:
        proc = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ},
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout ejecutando PowerShell"
    except Exception as e:
        return -1, "", str(e)


# ---------------------------------------------------------------------------
# Aplicaciones conocidas (mapeo nombre amigable → ejecutable)
# ---------------------------------------------------------------------------

KNOWN_APPS: dict[str, str] = {
    # Navegadores
    "chrome": "chrome",
    "google chrome": "chrome",
    "firefox": "firefox",
    "mozilla": "firefox",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "brave": "brave",
    "opera": "opera",
    # Utilidades Windows
    "notepad": "notepad",
    "bloc de notas": "notepad",
    "calculator": "calc",
    "calculadora": "calc",
    "paint": "mspaint",
    "explorer": "explorer",
    "explorador": "explorer",
    "cmd": "cmd",
    "powershell": "powershell",
    "terminal": "wt",
    "task manager": "taskmgr",
    "administrador de tareas": "taskmgr",
    "snipping tool": "snippingtool",
    "recortes": "snippingtool",
    "settings": "ms-settings:",
    "configuración": "ms-settings:",
    "configuracion": "ms-settings:",
    "control panel": "control",
    "panel de control": "control",
    # Desarrollo
    "vscode": "code",
    "visual studio code": "code",
    "visual studio": "devenv",
    "git bash": "git-bash",
    # Office
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "onenote": "onenote",
    "access": "msaccess",
    # Apps comunes
    "spotify": "spotify",
    "discord": "discord",
    "steam": "steam",
    "slack": "slack",
    "teams": "ms-teams",
    "microsoft teams": "ms-teams",
    "zoom": "zoom",
    "telegram": "telegram",
    "whatsapp": "whatsapp",
    "obs": "obs64",
    "obs studio": "obs64",
    "vlc": "vlc",
    "gimp": "gimp",
    "audacity": "audacity",
    "blender": "blender",
    "notion": "notion",
}


# ---------------------------------------------------------------------------
# Abrir / cerrar aplicaciones
# ---------------------------------------------------------------------------

def open_application(app_name: str, args: str = "") -> str:
    """
    Abre una aplicación en Windows por nombre.

    Args:
        app_name: Nombre de la aplicación (ej: "Chrome", "Notepad", "VSCode", "Spotify").
        args: Argumentos opcionales para pasar a la aplicación.
    """
    try:
        name_lower = app_name.strip().lower()
        executable = KNOWN_APPS.get(name_lower, app_name.strip())

        # Si es un protocolo (ms-settings:, etc.)
        if executable.endswith(":"):
            rc, stdout, stderr = _run_ps(f'Start-Process "{executable}"')
            if rc == 0:
                return f"Abriendo {app_name}."
            return f"Error abriendo {app_name}: {stderr}"

        # Intentar con Start-Process (PowerShell)
        cmd = f'Start-Process "{executable}"'
        if args:
            cmd += f' -ArgumentList "{args}"'
        rc, stdout, stderr = _run_ps(cmd)

        if rc == 0:
            return f"Aplicación '{app_name}' abierta correctamente."

        # Fallback: buscar en PATH
        which = shutil.which(executable)
        if which:
            subprocess.Popen([which] + ([args] if args else []))
            return f"Aplicación '{app_name}' abierta correctamente (vía PATH)."

        # Intentar buscar con where
        rc2, stdout2, stderr2 = _run_ps(
            f'Get-Command "{executable}" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source'
        )
        if rc2 == 0 and stdout2.strip():
            full_path = stdout2.strip().split("\n")[0]
            subprocess.Popen([full_path] + ([args] if args else []))
            return f"Aplicación '{app_name}' abierta correctamente (vía Get-Command)."

        # Intentar buscar en Start Menu
        rc3, stdout3, _ = _run_ps(
            f'Get-ChildItem "$env:ProgramData\\Microsoft\\Windows\\Start Menu" -Recurse -Filter "*{app_name}*.lnk" '
            f'| Select-Object -First 1 -ExpandProperty FullName'
        )
        if rc3 == 0 and stdout3.strip():
            lnk = stdout3.strip().split("\n")[0]
            subprocess.Popen(["cmd", "/c", "start", "", lnk])
            return f"Aplicación '{app_name}' abierta (vía acceso directo del menú inicio)."

        return (
            f"Error: no pude encontrar '{app_name}'. "
            f"Aplicaciones conocidas: {', '.join(sorted(set(KNOWN_APPS.keys())))[:500]}"
        )
    except Exception as e:
        return f"Error en open_application: {e}"


def close_application(app_name: str, force: bool = False, confirm: bool = False) -> str:
    """
    Cierra una aplicación en ejecución.

    Args:
        app_name: Nombre del proceso a cerrar (ej: "chrome", "notepad", "spotify").
        force: Si True, fuerza el cierre (taskkill /F).
        confirm: Requerido para cerrar la aplicación.
    """
    try:
        if not confirm:
            return f"Confirmación requerida: ¿cerrar '{app_name}'? Repite con confirm=true."

        name_lower = app_name.strip().lower()
        # Mapeo a nombre de proceso real
        process_names: dict[str, str] = {
            "chrome": "chrome", "firefox": "firefox", "edge": "msedge",
            "notepad": "notepad", "spotify": "Spotify", "discord": "Discord",
            "steam": "steam", "vscode": "Code", "visual studio code": "Code",
            "teams": "Teams", "slack": "slack", "zoom": "Zoom",
            "word": "WINWORD", "excel": "EXCEL", "powerpoint": "POWERPNT",
            "outlook": "OUTLOOK", "explorer": "explorer",
            "vlc": "vlc", "obs": "obs64",
        }
        process = process_names.get(name_lower, app_name.strip())

        force_flag = "/F " if force else ""
        rc, stdout, stderr = _run_ps(
            f'Stop-Process -Name "{process}" {"-Force" if force else ""} -ErrorAction SilentlyContinue -PassThru'
        )

        if rc == 0 and stdout.strip():
            return f"Aplicación '{app_name}' cerrada correctamente."

        # Fallback con taskkill
        taskkill_cmd = f'taskkill {"/F " if force else ""}/IM "{process}.exe" /T'
        proc = subprocess.run(
            taskkill_cmd, shell=True, capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            return f"Aplicación '{app_name}' cerrada correctamente (vía taskkill)."

        return f"Error: no se pudo cerrar '{app_name}'. ¿Está ejecutándose? Proceso buscado: {process}"
    except Exception as e:
        return f"Error en close_application: {e}"


# ---------------------------------------------------------------------------
# Control de volumen
# ---------------------------------------------------------------------------

_VOLUME_PS_SCRIPT = '''
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
    int _0(); int _1(); int _2(); int _3();
    int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);
    int _5();
    int GetMasterVolumeLevelScalar(out float pfLevel);
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, System.Guid pguidEventContext);
    int GetMute(out bool pbMute);
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    int Activate(ref System.Guid iid, int dwClsCtx, IntPtr pActivationParams, [MarshalAs(UnmanagedType.IUnknown)] out object ppInterface);
}

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice ppDevice);
}

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumerator {}

public static class AudioManager {
    public static IAudioEndpointVolume GetMasterVolume() {
        var enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumerator());
        IMMDevice device;
        enumerator.GetDefaultAudioEndpoint(0, 1, out device);
        System.Guid IID = typeof(IAudioEndpointVolume).GUID;
        object o;
        device.Activate(ref IID, 23, IntPtr.Zero, out o);
        return (IAudioEndpointVolume)o;
    }
}
"@ -ErrorAction SilentlyContinue
'''


def get_volume() -> str:
    """
    Obtiene el nivel de volumen actual del sistema (0-100).
    """
    try:
        script = _VOLUME_PS_SCRIPT + '''
$vol = [AudioManager]::GetMasterVolume()
$level = 0.0
$vol.GetMasterVolumeLevelScalar([ref]$level)
$muted = $false
$vol.GetMute([ref]$muted)
Write-Output (ConvertTo-Json @{volume=[math]::Round($level * 100); muted=$muted})
'''
        rc, stdout, stderr = _run_ps(script, timeout=10)
        if rc == 0 and stdout.strip():
            try:
                data = json.loads(stdout.strip())
                return json.dumps(data, ensure_ascii=False)
            except Exception:
                return stdout.strip()
        # Fallback without COM
        return json.dumps({"volume": "no disponible (COM no soportado)", "note": stderr[:200]}, ensure_ascii=False)
    except Exception as e:
        return f"Error en get_volume: {e}"


def set_volume(level: int) -> str:
    """
    Establece el volumen del sistema.

    Args:
        level: Nivel de volumen (0-100).
    """
    try:
        if not 0 <= level <= 100:
            return "Error: el volumen debe estar entre 0 y 100."
        scalar = level / 100.0
        script = _VOLUME_PS_SCRIPT + f'''
$vol = [AudioManager]::GetMasterVolume()
$vol.SetMasterVolumeLevelScalar({scalar}, [System.Guid]::Empty)
Write-Output "Volumen establecido al {level}%"
'''
        rc, stdout, stderr = _run_ps(script, timeout=10)
        if rc == 0:
            return f"Volumen establecido al {level}%."
        return f"Error al establecer volumen: {stderr[:300]}"
    except Exception as e:
        return f"Error en set_volume: {e}"


def toggle_mute(mute: Optional[bool] = None) -> str:
    """
    Silencia o activa el audio del sistema.

    Args:
        mute: True para silenciar, False para activar. None para alternar.
    """
    try:
        if mute is None:
            # Alternar
            script = _VOLUME_PS_SCRIPT + '''
$vol = [AudioManager]::GetMasterVolume()
$muted = $false
$vol.GetMute([ref]$muted)
$vol.SetMute(-not $muted, [System.Guid]::Empty)
Write-Output $(if (-not $muted) {"Silenciado"} else {"Audio activado"})
'''
        else:
            mute_val = "$true" if mute else "$false"
            script = _VOLUME_PS_SCRIPT + f'''
$vol = [AudioManager]::GetMasterVolume()
$vol.SetMute({mute_val}, [System.Guid]::Empty)
Write-Output $(if ({mute_val}) {{"Silenciado"}} else {{"Audio activado"}})
'''
        rc, stdout, stderr = _run_ps(script, timeout=10)
        if rc == 0 and stdout.strip():
            return stdout.strip()
        return f"Error en toggle_mute: {stderr[:300]}"
    except Exception as e:
        return f"Error en toggle_mute: {e}"


# ---------------------------------------------------------------------------
# Capturas de pantalla
# ---------------------------------------------------------------------------

def take_screenshot(
    save_path: Optional[str] = None,
    monitor: int = 0,
) -> str:
    """
    Toma una captura de pantalla y la guarda como archivo PNG.

    Args:
        save_path: Ruta donde guardar la imagen. Si vacío, se guarda en Desktop.
        monitor: Índice del monitor (0 = todos, 1 = primero, 2 = segundo, etc.).
    """
    try:
        try:
            import mss
        except ImportError:
            return "Error: la librería 'mss' no está instalada. Ejecuta: pip install mss"

        # Determinar ruta de guardado
        if save_path:
            output = os.path.abspath(os.path.expanduser(save_path))
        else:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.isdir(desktop):
                desktop = os.path.expanduser("~")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output = os.path.join(desktop, f"jarvis_screenshot_{timestamp}.png")

        # Crear directorio padre si no existe
        os.makedirs(os.path.dirname(output), exist_ok=True)

        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor < 0 or monitor >= len(monitors):
                return f"Error: monitor {monitor} no existe. Disponibles: {len(monitors) - 1} (0=todos)."
            sct_img = sct.grab(monitors[monitor])
            # Guardar como PNG
            mss.tools.to_png(sct_img.rgb, sct_img.size, output=output)

        size = os.path.getsize(output)
        return json.dumps({
            "status": "ok",
            "path": output,
            "size_bytes": size,
            "monitor": monitor,
            "resolution": f"{sct_img.width}x{sct_img.height}",
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en take_screenshot: {e}"


# ---------------------------------------------------------------------------
# Wallpaper
# ---------------------------------------------------------------------------

def set_wallpaper(image_path: str) -> str:
    """
    Cambia el fondo de escritorio de Windows.

    Args:
        image_path: Ruta absoluta a la imagen (JPG, PNG, BMP).
    """
    try:
        abs_path = os.path.abspath(os.path.expanduser(image_path))
        if not os.path.isfile(abs_path):
            return f"Error: la imagen no existe: {abs_path}"

        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'):
            return f"Error: formato no soportado: {ext}. Usa JPG, PNG o BMP."

        # Usar ctypes en Windows
        try:
            import ctypes
            SPI_SETDESKWALLPAPER = 0x0014
            SPIF_UPDATEINIFILE = 0x01
            SPIF_SENDCHANGE = 0x02
            result = ctypes.windll.user32.SystemParametersInfoW(
                SPI_SETDESKWALLPAPER, 0, abs_path,
                SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
            )
            if result:
                return f"Fondo de escritorio cambiado a: {abs_path}"
            return "Error: SystemParametersInfoW devolvió False."
        except AttributeError:
            # No estamos en Windows real (Linux/WSL), usar PowerShell como fallback
            script = f'''
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Wallpaper {{
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern int SystemParametersInfo(int uAction, int uParam, string lpvParam, int fuWinIni);
}}
"@
[Wallpaper]::SystemParametersInfo(0x0014, 0, "{abs_path}", 0x01 | 0x02)
'''
            rc, stdout, stderr = _run_ps(script, timeout=10)
            if rc == 0:
                return f"Fondo de escritorio cambiado a: {abs_path}"
            return f"Error al cambiar wallpaper: {stderr[:300]}"
    except Exception as e:
        return f"Error en set_wallpaper: {e}"


# ---------------------------------------------------------------------------
# Portapapeles
# ---------------------------------------------------------------------------

def get_clipboard() -> str:
    """
    Obtiene el contenido actual del portapapeles.
    """
    try:
        rc, stdout, stderr = _run_ps("Get-Clipboard", timeout=5)
        if rc == 0:
            content = stdout.strip()
            if not content:
                return "(portapapeles vacío)"
            if len(content) > 10000:
                content = content[:10000] + "\n[…truncado…]"
            return content
        return f"Error al leer portapapeles: {stderr[:200]}"
    except Exception as e:
        return f"Error en get_clipboard: {e}"


def set_clipboard(text: str) -> str:
    """
    Copia texto al portapapeles.

    Args:
        text: Texto a copiar al portapapeles.
    """
    try:
        if not text:
            return "Error: texto vacío."
        # Escapar comillas para PowerShell
        escaped = text.replace("'", "''")
        rc, stdout, stderr = _run_ps(f"Set-Clipboard -Value '{escaped}'", timeout=5)
        if rc == 0:
            return f"Texto copiado al portapapeles ({len(text)} caracteres)."
        return f"Error al escribir portapapeles: {stderr[:200]}"
    except Exception as e:
        return f"Error en set_clipboard: {e}"


# ---------------------------------------------------------------------------
# Notificaciones del sistema
# ---------------------------------------------------------------------------

def show_notification(
    title: str = "JARVIS",
    message: str = "",
    timeout: int = 10,
) -> str:
    """
    Muestra una notificación del sistema (toast notification en Windows).

    Args:
        title: Título de la notificación.
        message: Cuerpo del mensaje.
        timeout: Duración en segundos.
    """
    try:
        if not message:
            return "Error: message vacío."

        # Intentar con plyer
        try:
            from plyer import notification
            notification.notify(
                title=title,
                message=message,
                timeout=timeout,
                app_name="JARVIS",
            )
            return f"Notificación mostrada: '{title}'"
        except ImportError:
            pass

        # Fallback: PowerShell BurntToast o notificación básica
        script = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>{title}</text>
            <text>{message}</text>
        </binding>
    </visual>
</toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("JARVIS").Show($toast)
'''
        rc, stdout, stderr = _run_ps(script, timeout=10)
        if rc == 0:
            return f"Notificación mostrada: '{title}'"

        # Último fallback: msg command
        subprocess.Popen(
            ["msg", "*", f"{title}: {message}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return f"Notificación enviada (msg): '{title}'"
    except Exception as e:
        return f"Error en show_notification: {e}"


# ---------------------------------------------------------------------------
# Abrir URLs
# ---------------------------------------------------------------------------

_URL_SHORTCUTS: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
    "reddit": "https://www.reddit.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "twitch": "https://www.twitch.tv",
    "netflix": "https://www.netflix.com",
    "spotify web": "https://open.spotify.com",
    "linkedin": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "whatsapp web": "https://web.whatsapp.com",
    "telegram web": "https://web.telegram.org",
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
    "amazon": "https://www.amazon.es",
    "wikipedia": "https://es.wikipedia.org",
}


def open_url(url: str) -> str:
    """
    Abre una URL en el navegador predeterminado.

    Args:
        url: URL completa o nombre corto (youtube, google, github, etc.).
    """
    try:
        if not url or not url.strip():
            return "Error: URL vacía."

        target = url.strip()
        # Comprobar atajos
        shortcut = _URL_SHORTCUTS.get(target.lower())
        if shortcut:
            target = shortcut

        # Si no tiene esquema, añadir https://
        if not target.startswith(("http://", "https://", "ftp://")):
            # Si parece un dominio
            if "." in target and " " not in target:
                target = f"https://{target}"
            else:
                # Buscar en Google
                from urllib.parse import quote_plus
                target = f"https://www.google.com/search?q={quote_plus(target)}"

        webbrowser.open(target)
        return f"URL abierta en el navegador: {target}"
    except Exception as e:
        return f"Error en open_url: {e}"


# ---------------------------------------------------------------------------
# Sistema: lock, sleep, shutdown
# ---------------------------------------------------------------------------

def lock_screen(confirm: bool = False) -> str:
    """
    Bloquea la pantalla de Windows.

    Args:
        confirm: Requerido para confirmar la acción.
    """
    try:
        if not confirm:
            return "Confirmación requerida: ¿bloquear la pantalla? Repite con confirm=true."
        rc, stdout, stderr = _run_ps("rundll32.exe user32.dll,LockWorkStation", timeout=5)
        if rc == 0:
            return "Pantalla bloqueada."
        return f"Error al bloquear pantalla: {stderr[:200]}"
    except Exception as e:
        return f"Error en lock_screen: {e}"


# ---------------------------------------------------------------------------
# Información del sistema
# ---------------------------------------------------------------------------

def system_info() -> str:
    """
    Devuelve información completa del sistema: CPU, RAM, disco, red, OS.
    """
    try:
        import psutil

        # CPU
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False)
        cpu_percent = psutil.cpu_percent(interval=0.5)
        try:
            cpu_freq = psutil.cpu_freq()
            cpu_freq_mhz = cpu_freq.current if cpu_freq else None
        except Exception:
            cpu_freq_mhz = None

        # RAM
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # Disco
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent_used": usage.percent,
                })
            except Exception:
                continue

        # Red
        net = psutil.net_io_counters()

        # Uptime
        boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
        uptime_seconds = (datetime.now(tz=timezone.utc) - boot_time).total_seconds()
        uptime_hours = round(uptime_seconds / 3600, 1)

        result = {
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "hostname": platform.node(),
            },
            "cpu": {
                "physical_cores": cpu_count_physical,
                "logical_cores": cpu_count_logical,
                "usage_percent": cpu_percent,
                "frequency_mhz": cpu_freq_mhz,
            },
            "memory": {
                "total_gb": round(mem.total / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "used_gb": round(mem.used / (1024**3), 2),
                "percent_used": mem.percent,
                "swap_total_gb": round(swap.total / (1024**3), 2),
                "swap_used_gb": round(swap.used / (1024**3), 2),
            },
            "disks": disks,
            "network": {
                "bytes_sent_mb": round(net.bytes_sent / (1024**2), 2),
                "bytes_recv_mb": round(net.bytes_recv / (1024**2), 2),
            },
            "uptime_hours": uptime_hours,
            "boot_time": boot_time.isoformat(timespec="seconds"),
        }

        return json.dumps(result, ensure_ascii=False)
    except ImportError:
        return "Error: psutil no instalado. Ejecuta: pip install psutil"
    except Exception as e:
        return f"Error en system_info: {e}"


def get_battery() -> str:
    """
    Devuelve información sobre la batería del equipo (si existe).
    """
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery is None:
            return json.dumps({"status": "no_battery", "message": "Este equipo no tiene batería (o no es detectable)."}, ensure_ascii=False)

        result = {
            "percent": battery.percent,
            "plugged_in": battery.power_plugged,
            "seconds_left": battery.secsleft if battery.secsleft != psutil.POWER_TIME_UNLIMITED else None,
            "minutes_left": round(battery.secsleft / 60, 1) if battery.secsleft not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN) else None,
            "status": "charging" if battery.power_plugged else "discharging",
        }
        return json.dumps(result, ensure_ascii=False)
    except ImportError:
        return "Error: psutil no instalado."
    except Exception as e:
        return f"Error en get_battery: {e}"


# ---------------------------------------------------------------------------
# Brillo de pantalla
# ---------------------------------------------------------------------------

def set_brightness(level: int) -> str:
    """
    Ajusta el brillo de la pantalla (solo portátiles / monitores compatibles).

    Args:
        level: Nivel de brillo (0-100).
    """
    try:
        if not 0 <= level <= 100:
            return "Error: el brillo debe estar entre 0 y 100."

        # Usar WMI via PowerShell
        script = f'''
$brightness = {level}
$namespaceName = "root\\WMI"
$wmiInstance = Get-WmiObject -Namespace $namespaceName -Class WmiMonitorBrightnessMethods
if ($wmiInstance) {{
    $wmiInstance.WmiSetBrightness(1, $brightness)
    Write-Output "Brillo establecido al $brightness%"
}} else {{
    Write-Output "Error: no se puede controlar el brillo en este equipo"
}}
'''
        rc, stdout, stderr = _run_ps(script, timeout=10)
        if rc == 0 and "Error:" not in stdout:
            return f"Brillo establecido al {level}%."
        if "Error:" in stdout:
            return stdout.strip()
        return f"Error al ajustar brillo: {stderr[:300]}"
    except Exception as e:
        return f"Error en set_brightness: {e}"


def get_brightness() -> str:
    """
    Obtiene el nivel de brillo actual de la pantalla.
    """
    try:
        script = '''
$namespaceName = "root\\WMI"
$brightness = Get-WmiObject -Namespace $namespaceName -Class WmiMonitorBrightness
if ($brightness) {
    Write-Output (ConvertTo-Json @{brightness=$brightness.CurrentBrightness; levels=$brightness.Level})
} else {
    Write-Output '{"error": "No se puede leer el brillo en este equipo"}'
}
'''
        rc, stdout, stderr = _run_ps(script, timeout=10)
        if rc == 0 and stdout.strip():
            return stdout.strip()
        return json.dumps({"error": f"No se pudo leer brillo: {stderr[:200]}"}, ensure_ascii=False)
    except Exception as e:
        return f"Error en get_brightness: {e}"


# ---------------------------------------------------------------------------
# Papelera de reciclaje
# ---------------------------------------------------------------------------

def empty_recycle_bin(confirm: bool = False) -> str:
    """
    Vacía la Papelera de Reciclaje de Windows.

    Args:
        confirm: Requerido para confirmar la acción destructiva.
    """
    try:
        if not confirm:
            return "Confirmación requerida: ¿vaciar la Papelera de Reciclaje? Repite con confirm=true."

        script = '''
$shell = New-Object -ComObject Shell.Application
$recycleBin = $shell.Namespace(0xa)
$items = $recycleBin.Items()
$count = $items.Count
Clear-RecycleBin -Force -ErrorAction SilentlyContinue
Write-Output "Papelera vaciada. Elementos eliminados: $count"
'''
        rc, stdout, stderr = _run_ps(script, timeout=30)
        if rc == 0:
            return stdout.strip() if stdout.strip() else "Papelera vaciada."
        return f"Error al vaciar papelera: {stderr[:300]}"
    except Exception as e:
        return f"Error en empty_recycle_bin: {e}"
