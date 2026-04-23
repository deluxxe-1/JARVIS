from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """
    Centraliza configuración por env vars (sin cambiar defaults actuales).
    Se irá adoptando incrementalmente por módulos.
    """

    # Core
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

    # App data
    jarvis_app_dir: str = os.environ.get(
        "JARVIS_APP_DIR",
        os.path.join(os.path.expanduser("~"), ".jarvis"),
    )

    # Tools runtime policies
    aaris_read_only: bool = os.environ.get("AARIS_READ_ONLY", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "si",
        "sí",
        "on",
    )


def get_settings() -> Settings:
    return Settings()

