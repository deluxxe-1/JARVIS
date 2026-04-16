"""
JARVIS System Guard Module — Vigía del sistema en background.

Monitoriza CPU, RAM, disco y batería. Dispara alertas/acciones automáticas
cuando se superan umbrales configurables.
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Any


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

_JARVIS_DIR = Path(os.environ.get(
    "JARVIS_APP_DIR",
    os.path.join(os.path.expanduser("~"), ".jarvis"),
))

GUARD_CONFIG_PATH = _JARVIS_DIR / "guard_config.json"
GUARD_LOG_PATH = _JARVIS_DIR / "guard_log.jsonl"

# Umbrales por defecto
_DEFAULT_THRESHOLDS = {
    "cpu_percent": 90,
    "ram_percent": 85,
    "disk_percent": 90,
    "battery_low": 15,
    "check_interval_seconds": 60,
}

_guard_thread: Optional[threading.Thread] = None
_guard_stop = threading.Event()


def _load_config() -> dict[str, Any]:
    """Carga la configuración del guard."""
    try:
        if GUARD_CONFIG_PATH.is_file():
            data = json.loads(GUARD_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = dict(_DEFAULT_THRESHOLDS)
                merged.update(data)
                return merged
    except Exception:
        pass
    return dict(_DEFAULT_THRESHOLDS)


def _save_config(config: dict[str, Any]) -> None:
    """Guarda la configuración del guard."""
    _JARVIS_DIR.mkdir(parents=True, exist_ok=True)
    GUARD_CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _log_alert(alert_type: str, message: str, data: dict) -> None:
    """Registra una alerta en el log."""
    try:
        _JARVIS_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "type": alert_type,
            "message": message,
            **data,
        }
        with open(GUARD_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _check_system(config: dict[str, Any]) -> list[dict]:
    """Revisa el estado del sistema y devuelve alertas activas."""
    alerts = []

    try:
        import psutil
    except ImportError:
        return [{"type": "error", "message": "psutil no instalado"}]

    # CPU
    try:
        cpu = psutil.cpu_percent(interval=1)
        if cpu > config.get("cpu_percent", 90):
            # Obtener procesos pesados
            top_procs = []
            for p in psutil.process_iter(["name", "cpu_percent"]):
                try:
                    if p.info["cpu_percent"] and p.info["cpu_percent"] > 5:
                        top_procs.append({
                            "name": p.info["name"],
                            "cpu": p.info["cpu_percent"],
                        })
                except Exception:
                    pass
            top_procs.sort(key=lambda x: x["cpu"], reverse=True)

            alerts.append({
                "type": "cpu_high",
                "message": f"⚠️ CPU al {cpu}% (umbral: {config['cpu_percent']}%)",
                "value": cpu,
                "top_processes": top_procs[:5],
            })
    except Exception:
        pass

    # RAM
    try:
        ram = psutil.virtual_memory()
        ram_pct = ram.percent
        if ram_pct > config.get("ram_percent", 85):
            top_procs = []
            for p in psutil.process_iter(["name", "memory_percent"]):
                try:
                    if p.info["memory_percent"] and p.info["memory_percent"] > 1:
                        top_procs.append({
                            "name": p.info["name"],
                            "mem_pct": round(p.info["memory_percent"], 1),
                        })
                except Exception:
                    pass
            top_procs.sort(key=lambda x: x["mem_pct"], reverse=True)

            alerts.append({
                "type": "ram_high",
                "message": f"⚠️ RAM al {ram_pct}% ({_human_bytes(ram.used)}/{_human_bytes(ram.total)})",
                "value": ram_pct,
                "top_processes": top_procs[:5],
            })
    except Exception:
        pass

    # Disco
    try:
        disk = psutil.disk_usage("/")
        disk_pct = disk.percent
        if disk_pct > config.get("disk_percent", 90):
            alerts.append({
                "type": "disk_high",
                "message": f"⚠️ Disco al {disk_pct}% ({_human_bytes(disk.used)}/{_human_bytes(disk.total)})",
                "value": disk_pct,
            })
    except Exception:
        pass

    # Batería
    try:
        battery = psutil.sensors_battery()
        if battery and not battery.power_plugged:
            if battery.percent <= config.get("battery_low", 15):
                alerts.append({
                    "type": "battery_low",
                    "message": f"🔋 Batería al {battery.percent}% ¡SIN CARGAR!",
                    "value": battery.percent,
                })
    except Exception:
        pass

    return alerts


def _guard_daemon():
    """Hilo daemon del guard."""
    # Cooldown: no repetir la misma alerta en menos de 5 min
    last_alerts: dict[str, float] = {}
    cooldown = 300  # 5 minutos

    while not _guard_stop.is_set():
        config = _load_config()
        alerts = _check_system(config)

        now = time.time()
        for alert in alerts:
            atype = alert["type"]
            if atype in last_alerts and (now - last_alerts[atype]) < cooldown:
                continue

            last_alerts[atype] = now
            _log_alert(atype, alert["message"], alert)

            # Notificación toast
            try:
                from automation import show_notification
                show_notification(
                    title="🛡️ JARVIS Guard",
                    message=alert["message"],
                    timeout=10,
                )
            except Exception:
                pass

        interval = config.get("check_interval_seconds", 60)
        _guard_stop.wait(interval)


def start_guard() -> str:
    """
    Inicia el guardián del sistema en segundo plano.
    Monitoriza CPU, RAM, disco y batería con alertas automáticas.
    """
    global _guard_thread

    if _guard_thread is not None and _guard_thread.is_alive():
        config = _load_config()
        return json.dumps({
            "status": "already_running",
            "thresholds": config,
        }, ensure_ascii=False)

    _guard_stop.clear()
    _guard_thread = threading.Thread(
        target=_guard_daemon, daemon=True, name="jarvis-guard",
    )
    _guard_thread.start()

    config = _load_config()
    return json.dumps({
        "status": "ok",
        "message": "System Guard activado.",
        "thresholds": config,
    }, ensure_ascii=False)


def stop_guard() -> str:
    """
    Detiene el guardián del sistema.
    """
    global _guard_thread
    _guard_stop.set()
    _guard_thread = None
    return "System Guard detenido."


def guard_status() -> str:
    """
    Estado actual del guard y resultados de la última comprobación.
    """
    try:
        config = _load_config()
        is_running = _guard_thread is not None and _guard_thread.is_alive()

        # Ejecutar check ahora
        alerts = _check_system(config)

        return json.dumps({
            "status": "ok",
            "guard_running": is_running,
            "thresholds": config,
            "current_alerts": alerts,
            "alerts_count": len(alerts),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en guard_status: {e}"


def set_guard_threshold(
    cpu_percent: Optional[int] = None,
    ram_percent: Optional[int] = None,
    disk_percent: Optional[int] = None,
    battery_low: Optional[int] = None,
    check_interval_seconds: Optional[int] = None,
) -> str:
    """
    Configura los umbrales del guardián del sistema.

    Args:
        cpu_percent: Umbral de CPU (0-100, default 90).
        ram_percent: Umbral de RAM (0-100, default 85).
        disk_percent: Umbral de disco (0-100, default 90).
        battery_low: Umbral de batería baja (0-100, default 15).
        check_interval_seconds: Intervalo de comprobación en segundos (default 60).
    """
    try:
        config = _load_config()

        if cpu_percent is not None:
            config["cpu_percent"] = max(10, min(100, cpu_percent))
        if ram_percent is not None:
            config["ram_percent"] = max(10, min(100, ram_percent))
        if disk_percent is not None:
            config["disk_percent"] = max(10, min(100, disk_percent))
        if battery_low is not None:
            config["battery_low"] = max(5, min(50, battery_low))
        if check_interval_seconds is not None:
            config["check_interval_seconds"] = max(10, min(600, check_interval_seconds))

        _save_config(config)

        return json.dumps({
            "status": "ok",
            "message": "Umbrales actualizados.",
            "thresholds": config,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en set_guard_threshold: {e}"


def guard_alerts_history(count: int = 20) -> str:
    """
    Muestra las últimas alertas del guard.

    Args:
        count: Número de alertas a mostrar.
    """
    try:
        if not GUARD_LOG_PATH.is_file():
            return json.dumps({"alerts": [], "total": 0}, ensure_ascii=False)

        lines = GUARD_LOG_PATH.read_text(encoding="utf-8").strip().split("\n")
        alerts = []
        for line in lines[-count:]:
            try:
                alerts.append(json.loads(line))
            except Exception:
                pass

        return json.dumps({
            "alerts": alerts,
            "total": len(lines),
            "showing": len(alerts),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en guard_alerts_history: {e}"


def _human_bytes(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"
