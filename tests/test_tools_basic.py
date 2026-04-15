"""
Tests básicos para JARVIS tools — adaptados a Windows.
"""

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

import pytest

# Añadimos el directorio padre al path para importar tools
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import (
    create_file,
    read_file,
    edit_file,
    search_replace_in_file,
    create_folder,
    list_directory,
    exists_path,
    describe_path,
    resolve_path,
    append_file,
    insert_after,
    copy_path,
    move_path,
    delete_path,
    glob_find,
    rollback,
    detect_project,
    validate_python_syntax,
    disk_usage,
    stat_path,
    estimate_dir,
    tail_file,
    count_dir_children_matches,
    fuzzy_search_paths,
    policy_show,
    _norm_text,
)


@pytest.fixture
def tmp_workspace(tmp_path):
    """Crea un workspace temporal para tests."""
    original_cwd = os.getcwd()
    os.chdir(str(tmp_path))
    yield tmp_path
    os.chdir(original_cwd)


class TestNormText:
    def test_basic(self):
        assert _norm_text("Hello") == "hello"

    def test_accents(self):
        assert _norm_text("Café") == "cafe"
        assert _norm_text("Música") == "musica"
        assert _norm_text("Imágenes") == "imagenes"

    def test_case(self):
        assert _norm_text("DOCUMENTS") == "documents"
        assert _norm_text("Descargas") == "descargas"


class TestCreateFile:
    def test_create_simple(self, tmp_workspace):
        result = create_file(str(tmp_workspace / "test.txt"), "Hola JARVIS")
        assert "creado correctamente" in result.lower() or "creado" in result.lower()
        assert (tmp_workspace / "test.txt").read_text(encoding="utf-8") == "Hola JARVIS"

    def test_create_with_dirs(self, tmp_workspace):
        result = create_file(str(tmp_workspace / "sub" / "dir" / "file.txt"), "contenido")
        assert "creado" in result.lower()
        assert (tmp_workspace / "sub" / "dir" / "file.txt").exists()

    def test_create_empty(self, tmp_workspace):
        result = create_file(str(tmp_workspace / "empty.txt"))
        assert "creado" in result.lower()
        assert (tmp_workspace / "empty.txt").read_text(encoding="utf-8") == ""


class TestReadFile:
    def test_read_existing(self, tmp_workspace):
        (tmp_workspace / "data.txt").write_text("contenido de prueba", encoding="utf-8")
        result = read_file(str(tmp_workspace / "data.txt"))
        assert result == "contenido de prueba"

    def test_read_nonexistent(self, tmp_workspace):
        result = read_file(str(tmp_workspace / "no_existe.txt"))
        assert "error" in result.lower()

    def test_read_empty(self, tmp_workspace):
        (tmp_workspace / "vacio.txt").write_text("", encoding="utf-8")
        result = read_file(str(tmp_workspace / "vacio.txt"))
        assert "vacío" in result.lower() or result == ""


class TestEditFile:
    def test_edit_basic(self, tmp_workspace):
        (tmp_workspace / "edit_me.txt").write_text("original", encoding="utf-8")
        result = edit_file(str(tmp_workspace / "edit_me.txt"), "modificado")
        assert "actualizado" in result.lower()
        assert (tmp_workspace / "edit_me.txt").read_text(encoding="utf-8") == "modificado"
        assert "ROLLBACK_TOKEN=" in result

    def test_edit_nonexistent(self, tmp_workspace):
        result = edit_file(str(tmp_workspace / "no_existe.txt"), "contenido")
        assert "error" in result.lower()


class TestSearchReplace:
    def test_replace_first(self, tmp_workspace):
        (tmp_workspace / "sr.txt").write_text("foo bar foo baz", encoding="utf-8")
        result = search_replace_in_file(str(tmp_workspace / "sr.txt"), "foo", "qux")
        assert "reemplazada" in result.lower()
        content = (tmp_workspace / "sr.txt").read_text(encoding="utf-8")
        assert content == "qux bar foo baz"

    def test_replace_all(self, tmp_workspace):
        (tmp_workspace / "sr2.txt").write_text("foo bar foo baz", encoding="utf-8")
        result = search_replace_in_file(str(tmp_workspace / "sr2.txt"), "foo", "qux", replace_all=True)
        assert "2" in result
        content = (tmp_workspace / "sr2.txt").read_text(encoding="utf-8")
        assert content == "qux bar qux baz"

    def test_replace_not_found(self, tmp_workspace):
        (tmp_workspace / "sr3.txt").write_text("hello world", encoding="utf-8")
        result = search_replace_in_file(str(tmp_workspace / "sr3.txt"), "xyz", "abc")
        assert "error" in result.lower()


class TestCreateFolder:
    def test_create(self, tmp_workspace):
        result = create_folder(str(tmp_workspace / "nueva_carpeta"))
        assert "carpeta" in result.lower()
        assert (tmp_workspace / "nueva_carpeta").is_dir()

    def test_create_nested(self, tmp_workspace):
        result = create_folder(str(tmp_workspace / "a" / "b" / "c"))
        assert "carpeta" in result.lower()
        assert (tmp_workspace / "a" / "b" / "c").is_dir()

    def test_create_existing(self, tmp_workspace):
        (tmp_workspace / "existe").mkdir()
        result = create_folder(str(tmp_workspace / "existe"))
        assert "carpeta" in result.lower()  # No debería fallar


class TestListDirectory:
    def test_list_basic(self, tmp_workspace):
        (tmp_workspace / "file1.txt").touch()
        (tmp_workspace / "file2.txt").touch()
        (tmp_workspace / "subdir").mkdir()
        result = list_directory(str(tmp_workspace))
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "subdir" in result

    def test_list_hidden(self, tmp_workspace):
        (tmp_workspace / ".hidden").touch()
        (tmp_workspace / "visible.txt").touch()
        result_no_hidden = list_directory(str(tmp_workspace), show_hidden=False)
        assert ".hidden" not in result_no_hidden
        result_hidden = list_directory(str(tmp_workspace), show_hidden=True)
        assert ".hidden" in result_hidden


class TestExistsPath:
    def test_exists(self, tmp_workspace):
        (tmp_workspace / "existe.txt").touch()
        assert exists_path(str(tmp_workspace / "existe.txt")) == "true"

    def test_not_exists(self, tmp_workspace):
        assert exists_path(str(tmp_workspace / "no_existe.txt")) == "false"


class TestAppendFile:
    def test_append(self, tmp_workspace):
        (tmp_workspace / "append.txt").write_text("inicio", encoding="utf-8")
        result = append_file(str(tmp_workspace / "append.txt"), " + final")
        assert "añadido" in result.lower()
        assert (tmp_workspace / "append.txt").read_text(encoding="utf-8") == "inicio + final"

    def test_append_creates(self, tmp_workspace):
        result = append_file(str(tmp_workspace / "nuevo.txt"), "contenido nuevo")
        assert "añadido" in result.lower()
        assert (tmp_workspace / "nuevo.txt").read_text(encoding="utf-8") == "contenido nuevo"


class TestInsertAfter:
    def test_insert(self, tmp_workspace):
        (tmp_workspace / "insert.txt").write_text("AAA---BBB", encoding="utf-8")
        result = insert_after(str(tmp_workspace / "insert.txt"), "AAA", "XXX")
        assert "insertado" in result.lower()
        assert (tmp_workspace / "insert.txt").read_text(encoding="utf-8") == "AAAXXXXX---BBB" or \
               (tmp_workspace / "insert.txt").read_text(encoding="utf-8") == "AAAXXX---BBB"


class TestCopyPath:
    def test_copy_file(self, tmp_workspace):
        (tmp_workspace / "src.txt").write_text("copia", encoding="utf-8")
        result = copy_path(str(tmp_workspace / "src.txt"), str(tmp_workspace / "dst.txt"), allow_dangerous=True)
        assert "copia" in result.lower()
        assert (tmp_workspace / "dst.txt").read_text(encoding="utf-8") == "copia"

    def test_copy_exists_no_overwrite(self, tmp_workspace):
        (tmp_workspace / "a.txt").write_text("a", encoding="utf-8")
        (tmp_workspace / "b.txt").write_text("b", encoding="utf-8")
        result = copy_path(str(tmp_workspace / "a.txt"), str(tmp_workspace / "b.txt"), allow_dangerous=True)
        assert "error" in result.lower()


class TestMovePath:
    def test_move_file(self, tmp_workspace):
        (tmp_workspace / "move_src.txt").write_text("mover", encoding="utf-8")
        result = move_path(str(tmp_workspace / "move_src.txt"), str(tmp_workspace / "move_dst.txt"), allow_dangerous=True)
        assert "movido" in result.lower()
        assert not (tmp_workspace / "move_src.txt").exists()
        assert (tmp_workspace / "move_dst.txt").read_text(encoding="utf-8") == "mover"


class TestDeletePath:
    def test_delete_file_no_confirm_hidden(self, tmp_workspace):
        (tmp_workspace / ".secret").write_text("x", encoding="utf-8")
        result = delete_path(str(tmp_workspace / ".secret"), allow_dangerous=True)
        # Debería pedir confirmación para archivos ocultos (fuera de home necesita allow_dangerous)
        assert "confirm" in result.lower() or "confirmación" in result.lower()

    def test_delete_dir_no_recursive(self, tmp_workspace):
        (tmp_workspace / "mydir").mkdir()
        result = delete_path(str(tmp_workspace / "mydir"))
        assert "recursive" in result.lower()


class TestGlobFind:
    def test_find_py(self, tmp_workspace):
        (tmp_workspace / "a.py").touch()
        (tmp_workspace / "b.py").touch()
        (tmp_workspace / "c.txt").touch()
        result = glob_find("*.py", str(tmp_workspace))
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result


class TestRollback:
    def test_rollback_edit(self, tmp_workspace):
        (tmp_workspace / "rollback.txt").write_text("original", encoding="utf-8")
        result = edit_file(str(tmp_workspace / "rollback.txt"), "modificado")
        assert "ROLLBACK_TOKEN=" in result
        import re
        token = re.search(r"ROLLBACK_TOKEN=([a-fA-F0-9]+)", result).group(1)
        rb_result = rollback(token, overwrite=True)
        assert "rollback ok" in rb_result.lower()
        assert (tmp_workspace / "rollback.txt").read_text(encoding="utf-8") == "original"


class TestDetectProject:
    def test_python_project(self, tmp_workspace):
        (tmp_workspace / "requirements.txt").touch()
        result = detect_project(str(tmp_workspace))
        data = json.loads(result)
        assert data["type"] == "python"

    def test_node_project(self, tmp_workspace):
        (tmp_workspace / "package.json").write_text("{}", encoding="utf-8")
        result = detect_project(str(tmp_workspace))
        data = json.loads(result)
        assert data["type"] == "node"

    def test_unknown_project(self, tmp_workspace):
        result = detect_project(str(tmp_workspace))
        data = json.loads(result)
        assert data["type"] == "unknown"


class TestDiskUsage:
    def test_basic(self):
        result = disk_usage("~")
        data = json.loads(result)
        assert "total_bytes" in data
        assert data["total_bytes"] > 0


class TestDescribePath:
    def test_describe_file(self, tmp_workspace):
        (tmp_workspace / "desc.txt").write_text("test", encoding="utf-8")
        result = describe_path(str(tmp_workspace / "desc.txt"))
        assert "file" in result
        assert "desc.txt" in result or "size=" in result

    def test_describe_nonexistent(self, tmp_workspace):
        result = describe_path(str(tmp_workspace / "no_existe.txt"))
        assert "no existe" in result.lower()


class TestEstimateDir:
    def test_estimate(self, tmp_workspace):
        (tmp_workspace / "a.txt").touch()
        (tmp_workspace / "b.txt").touch()
        (tmp_workspace / "sub").mkdir()
        result = estimate_dir(str(tmp_workspace))
        data = json.loads(result)
        assert data["entries_counted"] >= 2


class TestTailFile:
    def test_tail(self, tmp_workspace):
        lines = "\n".join([f"line {i}" for i in range(100)])
        (tmp_workspace / "log.txt").write_text(lines, encoding="utf-8")
        result = tail_file(str(tmp_workspace / "log.txt"), lines=5)
        assert "line 99" in result
        assert "line 95" in result


class TestFuzzySearch:
    def test_basic(self, tmp_workspace):
        (tmp_workspace / "myfile.py").touch()
        (tmp_workspace / "other.txt").touch()
        result = fuzzy_search_paths("myfile", str(tmp_workspace))
        assert "myfile" in result


class TestPolicyShow:
    def test_policy_empty(self):
        result = policy_show()
        # Cuando no hay política, devuelve {} o la política actual
        data = json.loads(result)
        assert isinstance(data, dict)


class TestResolvePath:
    def test_absolute(self, tmp_workspace):
        abs_path = str(tmp_workspace / "test.txt")
        result = resolve_path(abs_path)
        assert result == os.path.abspath(abs_path)

    def test_relative(self, tmp_workspace):
        result = resolve_path("subdir")
        assert os.path.isabs(result)

    def test_empty(self):
        result = resolve_path("")
        assert "error" in result.lower()


class TestValidatePythonSyntax:
    def test_valid(self, tmp_workspace):
        (tmp_workspace / "valid.py").write_text("x = 1\nprint(x)\n", encoding="utf-8")
        result = validate_python_syntax(str(tmp_workspace / "valid.py"))
        assert "ok" in result.lower()

    def test_invalid(self, tmp_workspace):
        (tmp_workspace / "invalid.py").write_text("def foo(\n", encoding="utf-8")
        result = validate_python_syntax(str(tmp_workspace / "invalid.py"))
        assert "error" in result.lower()
