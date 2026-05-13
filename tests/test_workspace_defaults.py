"""Tests para aaris.workspace_defaults."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_ensure_default_creates_dir(tmp_path, monkeypatch):
    target = str(tmp_path / "Documents" / "Proyectos")

    def _fake_resolve(path: str, cwd=None, must_exist=False):
        return target

    monkeypatch.setattr("aaris.tools.filesystem.resolve_path", _fake_resolve)
    from aaris.workspace_defaults import ensure_default_code_projects_parent

    r = ensure_default_code_projects_parent()
    assert r == target
    assert Path(target).is_dir()
