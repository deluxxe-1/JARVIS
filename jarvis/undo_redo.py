"""
JARVIS Undo/Redo State — persistent undo/redo tracking via JSON.

Manages a stack of rollback tokens so users can undo/redo file operations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_APP_DIR = os.environ.get("JARVIS_APP_DIR", os.path.join(os.getcwd(), ".jarvis"))
UNDO_REDO_PATH = os.environ.get("JARVIS_UNDO_REDO_PATH", os.path.join(DEFAULT_APP_DIR, "undo_redo.json"))


def _load_undo_redo_state() -> dict[str, Any]:
    try:
        p = Path(UNDO_REDO_PATH).expanduser()
        if not p.is_file():
            return {"undo": [], "redo": []}
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"undo": [], "redo": []}
        data.setdefault("undo", [])
        data.setdefault("redo", [])
        return data
    except Exception:
        return {"undo": [], "redo": []}


def _save_undo_redo_state(state: dict[str, Any]) -> None:
    try:
        p = Path(UNDO_REDO_PATH).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass
