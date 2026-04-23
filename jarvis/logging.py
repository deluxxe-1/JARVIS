from __future__ import annotations

import logging
import os
import json
from datetime import datetime, timezone
from typing import Optional


def configure_logging(level: Optional[str] = None) -> None:
    """
    Logging unificado:
    - Consola bonita con Rich (si está disponible)
    - JSONL opcional para auditoría/telemetría (si `JARVIS_JSONL_LOG_PATH` está seteado)
    """
    if level is None:
        level = os.environ.get("JARVIS_LOG_LEVEL", "INFO")

    lvl = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        return

    handlers: list[logging.Handler] = []

    # Console handler (prefer Rich)
    try:
        from rich.logging import RichHandler

        handlers.append(RichHandler(rich_tracebacks=True, markup=True))
        fmt = "%(message)s"
    except Exception:
        handlers.append(logging.StreamHandler())
        fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    # Optional JSONL audit log
    jsonl_path = os.environ.get("JARVIS_JSONL_LOG_PATH", "").strip()
    if jsonl_path:
        handlers.append(_JsonlHandler(jsonl_path))

    logging.basicConfig(level=lvl, format=fmt, handlers=handlers)


class _JsonlHandler(logging.Handler):
    def __init__(self, path: str):
        super().__init__()
        self._path = os.path.abspath(os.path.expanduser(path))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                payload["exc_info"] = self.formatException(record.exc_info)
            line = json.dumps(payload, ensure_ascii=False)

            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # Nunca romper el programa por logging.
            pass

