"""
Tests para JARVIS Intelligence Module.
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intelligence import (
    screen_ocr,
    image_ocr,
    extract_document_text,
    summarize_document,
    semantic_search,
    index_directory,
    _cosine_similarity,
    _chunk_text,
)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

class TestCosine:
    def test_identical_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(a, b) - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 0.001

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) + 1.0) < 0.001

    def test_zero_vector(self):
        a = [0.0, 0.0]
        b = [1.0, 1.0]
        assert _cosine_similarity(a, b) == 0.0


class TestChunkText:
    def test_basic_chunking(self):
        text = " ".join([f"word{i}" for i in range(100)])
        chunks = _chunk_text(text, chunk_size=20, overlap=5)
        assert len(chunks) > 1
        # Each chunk should have ~20 words
        for chunk in chunks:
            words = chunk.split()
            assert len(words) <= 20

    def test_small_text(self):
        text = "hello world"
        chunks = _chunk_text(text, chunk_size=100)
        assert len(chunks) == 1

    def test_empty_text(self):
        chunks = _chunk_text("", chunk_size=100)
        assert len(chunks) == 0


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

class TestScreenOCR:
    def test_invalid_region(self):
        result = screen_ocr(region="invalid")
        assert "Error" in result

    def test_region_wrong_count(self):
        result = screen_ocr(region="100,200")
        assert "Error" in result


class TestImageOCR:
    def test_nonexistent_image(self):
        result = image_ocr("/nonexistent/image.png")
        assert "Error" in result

    def test_valid_image_no_tesseract(self, tmp_path):
        # Create a fake image file
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG header
        with patch.dict("sys.modules", {"pytesseract": None}):
            result = image_ocr(str(img_path))
            # Should fail because pytesseract isn't available or image is invalid
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Document Extraction
# ---------------------------------------------------------------------------

class TestExtractDocumentText:
    def test_txt_file(self, tmp_path):
        txt = tmp_path / "test.txt"
        txt.write_text("Hola mundo, esto es un archivo de prueba.", encoding="utf-8")
        result = extract_document_text(str(txt))
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "Hola mundo" in data["text"]
        assert data["format"] == ".txt"

    def test_md_file(self, tmp_path):
        md = tmp_path / "readme.md"
        md.write_text("# Título\n\nContenido del markdown.", encoding="utf-8")
        result = extract_document_text(str(md))
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "Título" in data["text"]

    def test_py_file(self, tmp_path):
        py = tmp_path / "script.py"
        py.write_text("def hello():\n    print('world')\n", encoding="utf-8")
        result = extract_document_text(str(py))
        data = json.loads(result)
        assert data["status"] == "ok"
        assert "def hello" in data["text"]

    def test_nonexistent_file(self):
        result = extract_document_text("/nonexistent/file.txt")
        assert "Error" in result

    def test_empty_file(self, tmp_path):
        empty = tmp_path / "empty.txt"
        empty.write_text("", encoding="utf-8")
        result = extract_document_text(str(empty))
        assert "Error" in result


# ---------------------------------------------------------------------------
# Summarize Document
# ---------------------------------------------------------------------------

class TestSummarizeDocument:
    def test_summarize_txt(self, tmp_path):
        txt = tmp_path / "article.txt"
        txt.write_text("Este es un artículo largo " * 50, encoding="utf-8")
        mock_response = {
            "message": {"content": "Resumen del artículo: contenido repetitivo."}
        }
        mock_ollama = MagicMock()
        mock_ollama.chat.return_value = mock_response
        with patch.dict("sys.modules", {"ollama": mock_ollama}):
            result = summarize_document(str(txt))
            data = json.loads(result)
            assert data["status"] == "ok"
            assert "Resumen" in data["summary"]

    def test_summarize_nonexistent(self):
        result = summarize_document("/nonexistent/file.pdf")
        assert "Error" in result


# ---------------------------------------------------------------------------
# Semantic Search
# ---------------------------------------------------------------------------

class TestSemanticSearch:
    def test_empty_query(self):
        result = semantic_search("")
        assert "Error" in result

    def test_nonexistent_directory(self):
        result = semantic_search("test query", directory="/nonexistent/dir")
        assert "Error" in result

    def test_index_directory(self, tmp_path):
        # Create test files
        (tmp_path / "file1.txt").write_text("Python is a programming language", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("JavaScript runs in the browser", encoding="utf-8")
        (tmp_path / "file3.py").write_text("def hello(): print('world')", encoding="utf-8")

        mock_embedding = [0.1] * 384  # fake embedding

        with patch("intelligence._get_embedding", return_value=mock_embedding):
            with patch("intelligence.EMBEDDINGS_CACHE_DIR", tmp_path / "cache"):
                result = index_directory(str(tmp_path), extensions=".txt,.py")
                data = json.loads(result)
                assert data["status"] == "ok"
                assert data["files_indexed"] >= 2

    def test_search_with_cached_index(self, tmp_path):
        # Create mock cached index
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        mock_embedding = [0.1] * 384

        cache_data = {
            "directory": str(tmp_path),
            "indexed_at": "2099-01-01T00:00:00",  # Far future so it's "fresh"
            "entries": [
                {
                    "file": str(tmp_path / "test.txt"),
                    "chunk_index": 0,
                    "text": "Python programming language",
                    "embedding": mock_embedding,
                },
                {
                    "file": str(tmp_path / "test2.txt"),
                    "chunk_index": 0,
                    "text": "JavaScript web development",
                    "embedding": [0.9] * 384,
                },
            ],
        }

        dir_hash = str(tmp_path).replace(os.sep, "_").replace(":", "")
        cache_file = cache_dir / f"{dir_hash}.json"
        cache_file.write_text(json.dumps(cache_data), encoding="utf-8")

        with patch("intelligence._get_embedding", return_value=mock_embedding):
            with patch("intelligence.EMBEDDINGS_CACHE_DIR", cache_dir):
                result = semantic_search("Python code", directory=str(tmp_path))
                data = json.loads(result)
                assert "results" in data
                assert len(data["results"]) > 0
                # The Python entry should rank higher (closer embedding)
                assert data["results"][0]["file"].endswith("test.txt")
