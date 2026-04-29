"""
Contrato básico para la selección dinámica de tools.

La idea: dado un texto de usuario, `_select_tools` debe incluir herramientas
relevantes sin devolver siempre "todas".
"""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.tool_selector import _build_tool_groups, _select_tools


def _mk(name: str):
    def _fn(*args, **kwargs):
        raise RuntimeError("stub")

    _fn.__name__ = name
    return _fn


def test_select_tools_includes_files_by_default():
    tools = [_mk("create_file"), _mk("read_file"), _mk("append_file")]
    groups = _build_tool_groups(tools)
    selected = _select_tools("hola", tools, groups)
    names = {t.__name__ for t in selected}
    assert "create_file" in names
    assert "read_file" in names


def test_select_tools_ocr_intent_adds_ocr_tools():
    tools = [
        _mk("create_file"),
        _mk("read_file"),
        _mk("screen_ocr"),
        _mk("image_ocr"),
    ]
    groups = _build_tool_groups(tools)
    selected = _select_tools("haz ocr de pantalla", tools, groups)
    names = {t.__name__ for t in selected}
    assert "screen_ocr" in names


def test_select_tools_git_intent_adds_git_tools():
    tools = [
        _mk("create_file"),
        _mk("read_file"),
        _mk("git_status"),
        _mk("git_diff"),
    ]
    groups = _build_tool_groups(tools)
    selected = _select_tools("muestra git status y diff", tools, groups)
    names = {t.__name__ for t in selected}
    assert "git_status" in names
    assert "git_diff" in names

