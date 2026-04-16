"""
JARVIS Network Module — Escáner de red local y utilidades de conectividad.

Escanea dispositivos en la LAN, hace ping, comprueba puertos abiertos
y diagnóstica la conexión a internet.
"""

import json
import os
import socket
import subprocess
import sys
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional


def scan_network(
    subnet: Optional[str] = None,
    timeout: float = 1.0,
) -> str:
    """
    Escanea la red local para descubrir dispositivos conectados.
    Detecta automáticamente la subred si no se especifica.

    Args:
        subnet: Subred a escanear (ej: '192.168.1'). Si vacío, se auto-detecta.
        timeout: Timeout en segundos para cada ping.
    """
    try:
        # Auto-detectar subred
        if not subnet:
            subnet = _detect_subnet()
            if not subnet:
                return "Error: no se pudo detectar la subred automáticamente. Especifica una (ej: '192.168.1')."

        subnet = subnet.strip().rstrip(".")

        devices = []

        def _ping_host(ip: str) -> Optional[dict]:
            try:
                if sys.platform == "win32":
                    cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
                else:
                    cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout))), ip]

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout + 2,
                    **(_no_window_kwargs()),
                )
                if result.returncode == 0:
                    # Intentar obtener hostname
                    hostname = _resolve_hostname(ip)
                    return {"ip": ip, "hostname": hostname, "status": "online"}
            except Exception:
                pass
            return None

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = {
                executor.submit(_ping_host, f"{subnet}.{i}"): i
                for i in range(1, 255)
            }
            for future in as_completed(futures):
                result = future.result()
                if result:
                    devices.append(result)

        # Ordenar por IP
        devices.sort(key=lambda d: [int(x) for x in d["ip"].split(".")])

        return json.dumps({
            "status": "ok",
            "subnet": subnet,
            "devices_found": len(devices),
            "devices": devices,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en scan_network: {e}"


def ping_host(host: str, count: int = 4) -> str:
    """
    Hace ping a un host y devuelve estadísticas.

    Args:
        host: IP o dominio a pingear (ej: 'google.com', '192.168.1.1').
        count: Número de pings a enviar.
    """
    try:
        if not host or not host.strip():
            return "Error: host vacío."

        host = host.strip()
        count = min(max(1, count), 20)

        if sys.platform == "win32":
            cmd = ["ping", "-n", str(count), host]
        else:
            cmd = ["ping", "-c", str(count), host]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=count * 5 + 10,
            **(_no_window_kwargs()),
        )

        output = result.stdout + result.stderr

        # Parsear estadísticas
        stats = _parse_ping_stats(output)

        return json.dumps({
            "status": "ok" if result.returncode == 0 else "unreachable",
            "host": host,
            "reachable": result.returncode == 0,
            "stats": stats,
            "raw_output": output[-2000:],
        }, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({
            "status": "timeout",
            "host": host,
            "reachable": False,
            "message": f"Ping a {host} excedió el timeout.",
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en ping_host: {e}"


def scan_ports(
    host: str,
    ports: str = "22,80,443,3000,3306,5432,8080,8443",
    timeout: float = 1.0,
) -> str:
    """
    Escanea puertos de un host para comprobar cuáles están abiertos.

    Args:
        host: IP o dominio a escanear.
        ports: Puertos separados por comas (ej: '80,443,8080') o rango 'inicio-fin' (ej: '80-100').
        timeout: Timeout por puerto en segundos.
    """
    try:
        if not host or not host.strip():
            return "Error: host vacío."

        host = host.strip()

        # Parsear puertos
        port_list = _parse_ports(ports)
        if not port_list:
            return "Error: no se pudieron parsear los puertos."
        if len(port_list) > 1000:
            return "Error: máximo 1000 puertos por escaneo."

        # Resolver host
        try:
            ip = socket.gethostbyname(host)
        except socket.gaierror:
            return f"Error: no se pudo resolver '{host}'."

        open_ports = []
        closed_ports = []

        _COMMON_SERVICES = {
            21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
            80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS",
            993: "IMAPS", 995: "POP3S", 3000: "Node.js/Dev", 3306: "MySQL",
            3389: "RDP", 5432: "PostgreSQL", 5900: "VNC", 6379: "Redis",
            8000: "Dev Server", 8080: "HTTP Proxy", 8443: "HTTPS Alt",
            27017: "MongoDB",
        }

        def _check_port(port: int) -> dict:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                sock.close()
                service = _COMMON_SERVICES.get(port, "")
                return {
                    "port": port,
                    "open": result == 0,
                    "service": service,
                }
            except Exception:
                return {"port": port, "open": False, "service": ""}

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(_check_port, p) for p in port_list]
            for future in as_completed(futures):
                result = future.result()
                if result["open"]:
                    open_ports.append(result)
                else:
                    closed_ports.append(result)

        open_ports.sort(key=lambda x: x["port"])

        return json.dumps({
            "status": "ok",
            "host": host,
            "ip": ip,
            "scanned_ports": len(port_list),
            "open_ports": open_ports,
            "open_count": len(open_ports),
            "closed_count": len(closed_ports),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en scan_ports: {e}"


def check_internet(timeout: float = 5.0) -> str:
    """
    Comprueba si hay conexión a internet haciendo pruebas a servicios conocidos.

    Args:
        timeout: Timeout en segundos.
    """
    try:
        targets = [
            ("8.8.8.8", 53, "Google DNS"),
            ("1.1.1.1", 53, "Cloudflare DNS"),
            ("208.67.222.222", 53, "OpenDNS"),
        ]

        results = []
        for ip, port, name in targets:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                start = __import__("time").time()
                result = sock.connect_ex((ip, port))
                elapsed = round((__import__("time").time() - start) * 1000, 1)
                sock.close()
                results.append({
                    "service": name,
                    "reachable": result == 0,
                    "latency_ms": elapsed if result == 0 else None,
                })
            except Exception:
                results.append({"service": name, "reachable": False, "latency_ms": None})

        connected = any(r["reachable"] for r in results)

        # Public IP
        public_ip = None
        if connected:
            try:
                import requests
                resp = requests.get("https://api.ipify.org", timeout=3)
                if resp.status_code == 200:
                    public_ip = resp.text.strip()
            except Exception:
                pass

        return json.dumps({
            "status": "ok",
            "connected": connected,
            "public_ip": public_ip,
            "tests": results,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en check_internet: {e}"


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _no_window_kwargs() -> dict:
    """Kwargs para subprocess que evitan mostrar ventana en Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _detect_subnet() -> Optional[str]:
    """Auto-detecta la subred local."""
    try:
        # Método 1: conectar a un servidor externo para saber la IP local
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        parts = local_ip.split(".")
        if len(parts) == 4:
            return ".".join(parts[:3])
    except Exception:
        pass
    return None


def _resolve_hostname(ip: str) -> str:
    """Intenta resolver el hostname de una IP."""
    try:
        hostname = socket.gethostbyaddr(ip)[0]
        return hostname
    except Exception:
        return ""


def _parse_ports(ports_str: str) -> list[int]:
    """Parsea una cadena de puertos en una lista de enteros."""
    result = []
    for part in ports_str.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                for p in range(int(start), int(end) + 1):
                    if 1 <= p <= 65535:
                        result.append(p)
            except ValueError:
                continue
        else:
            try:
                p = int(part)
                if 1 <= p <= 65535:
                    result.append(p)
            except ValueError:
                continue
    return result


def _parse_ping_stats(output: str) -> dict:
    """Parsea estadísticas de ping."""
    stats = {}

    # Windows: Minimum = 1ms, Maximum = 5ms, Average = 3ms
    avg_match = re.search(r"Average\s*=\s*(\d+)ms", output, re.IGNORECASE)
    if avg_match:
        stats["avg_ms"] = int(avg_match.group(1))

    # Linux: min/avg/max/mdev = 1.234/2.345/3.456/0.567 ms
    linux_match = re.search(r"([\d.]+)/([\d.]+)/([\d.]+)", output)
    if linux_match:
        stats["min_ms"] = float(linux_match.group(1))
        stats["avg_ms"] = float(linux_match.group(2))
        stats["max_ms"] = float(linux_match.group(3))

    # Packet loss
    loss_match = re.search(r"(\d+)%\s*(packet\s*)?loss", output, re.IGNORECASE)
    if loss_match:
        stats["packet_loss_pct"] = int(loss_match.group(1))

    return stats
