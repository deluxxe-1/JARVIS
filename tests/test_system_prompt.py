"""Smoke: prompt del sistema y recarga."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_get_system_prompt_contains_workspace_hint():
    from aaris.prompts import get_system_prompt

    s = get_system_prompt()
    assert "A.A.R.I.S." in s or "AARIS" in s
    assert "Proyectos" in s or "proyectos" in s.lower()


def test_refresh_system_prompt_updates_engine_global():
    import aaris.engine as eng

    t = eng.refresh_system_prompt()
    assert isinstance(t, str) and len(t) > 500
    assert eng.SYSTEM_PROMPT is t
