"""
JARVIS Intelligence Module — OCR, Resumen de Documentos y Búsqueda Semántica.

Funcionalidades:
1. OCR: extracción de texto de pantalla/imágenes (pytesseract)
2. Documentos: extracción de texto de PDF/DOCX/TXT + resumen via Ollama
3. Búsqueda semántica: embeddings via Ollama + cosine similarity
"""

import json
import math
import os
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

EMBEDDINGS_CACHE_DIR = _JARVIS_DIR / "embeddings_cache"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
EMBED_MODEL = os.environ.get("JARVIS_EMBED_MODEL", "nomic-embed-text")


# ============================================================================
# 1. OCR — Optical Character Recognition
# ============================================================================

def screen_ocr(
    region: Optional[str] = None,
    lang: str = "spa+eng",
) -> str:
    """
    Captura una zona de la pantalla y extrae el texto usando OCR.

    Args:
        region: Región a capturar como "x,y,width,height" (ej: "100,100,800,600").
                Si vacío, captura toda la pantalla.
        lang: Idiomas para OCR (ej: "spa", "eng", "spa+eng"). Requiere packs de Tesseract.
    """
    try:
        try:
            import mss
        except ImportError:
            return "Error: librería 'mss' no instalada. Ejecuta: pip install mss"

        try:
            from PIL import Image
        except ImportError:
            return "Error: librería 'Pillow' no instalada. Ejecuta: pip install Pillow"

        try:
            import pytesseract
        except ImportError:
            return (
                "Error: librería 'pytesseract' no instalada. Ejecuta: pip install pytesseract\n"
                "También necesitas Tesseract-OCR instalado: winget install UB-Mannheim.TesseractOCR"
            )

        with mss.mss() as sct:
            if region:
                try:
                    parts = [int(x.strip()) for x in region.split(",")]
                    if len(parts) != 4:
                        return "Error: region debe ser 'x,y,width,height' (4 valores)."
                    monitor = {"left": parts[0], "top": parts[1], "width": parts[2], "height": parts[3]}
                except (ValueError, IndexError):
                    return "Error: region debe contener 4 enteros separados por comas."
            else:
                monitor = sct.monitors[0]  # pantalla completa

            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

        # OCR
        try:
            text = pytesseract.image_to_string(img, lang=lang)
        except Exception as e:
            if "tesseract" in str(e).lower():
                return (
                    "Error: Tesseract-OCR no encontrado. Instálalo:\n"
                    " - Windows: winget install UB-Mannheim.TesseractOCR\n"
                    " - O descarga de: https://github.com/UB-Mannheim/tesseract/wiki"
                )
            raise

        text = text.strip()
        if not text:
            return json.dumps({
                "status": "ok",
                "text": "",
                "message": "No se detectó texto en la imagen.",
                "region": region or "pantalla completa",
            }, ensure_ascii=False)

        return json.dumps({
            "status": "ok",
            "text": text[:10000],
            "chars": len(text),
            "region": region or "pantalla completa",
            "lang": lang,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en screen_ocr: {e}"


def image_ocr(
    image_path: str,
    lang: str = "spa+eng",
) -> str:
    """
    Extrae texto de un archivo de imagen usando OCR.

    Args:
        image_path: Ruta a la imagen (PNG, JPG, BMP, TIFF, etc.).
        lang: Idiomas para OCR (ej: "spa", "eng", "spa+eng").
    """
    try:
        abs_path = os.path.abspath(os.path.expanduser(image_path))
        if not os.path.isfile(abs_path):
            return f"Error: la imagen no existe: {abs_path}"

        try:
            from PIL import Image
        except ImportError:
            return "Error: librería 'Pillow' no instalada. Ejecuta: pip install Pillow"

        try:
            import pytesseract
        except ImportError:
            return (
                "Error: librería 'pytesseract' no instalada. Ejecuta: pip install pytesseract\n"
                "También necesitas Tesseract-OCR instalado."
            )

        img = Image.open(abs_path)
        text = pytesseract.image_to_string(img, lang=lang)
        text = text.strip()

        return json.dumps({
            "status": "ok",
            "text": text[:10000],
            "chars": len(text),
            "image": abs_path,
            "size": f"{img.width}x{img.height}",
            "lang": lang,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en image_ocr: {e}"


# ============================================================================
# 2. EXTRACCIÓN Y RESUMEN DE DOCUMENTOS
# ============================================================================

def _extract_pdf_text(file_path: str, max_chars: int = 50000) -> tuple[str, Optional[str]]:
    """Extrae texto de un PDF."""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        return "", "Error: librería 'PyPDF2' no instalada. Ejecuta: pip install PyPDF2"

    try:
        reader = PdfReader(file_path)
        text_parts = []
        total = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            total += len(page_text)
            if total > max_chars:
                break
        return "\n\n".join(text_parts)[:max_chars], None
    except Exception as e:
        return "", f"Error leyendo PDF: {e}"


def _extract_docx_text(file_path: str, max_chars: int = 50000) -> tuple[str, Optional[str]]:
    """Extrae texto de un DOCX."""
    try:
        import docx
    except ImportError:
        return "", "Error: librería 'python-docx' no instalada. Ejecuta: pip install python-docx"

    try:
        doc = docx.Document(file_path)
        text_parts = []
        total = 0
        for para in doc.paragraphs:
            text_parts.append(para.text)
            total += len(para.text)
            if total > max_chars:
                break
        return "\n".join(text_parts)[:max_chars], None
    except Exception as e:
        return "", f"Error leyendo DOCX: {e}"


def _extract_text_file(file_path: str, max_chars: int = 50000) -> tuple[str, Optional[str]]:
    """Extrae texto de un archivo de texto plano."""
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            text = f.read(max_chars)
        return text, None
    except Exception as e:
        return "", f"Error leyendo archivo: {e}"


def extract_document_text(
    file_path: str,
    max_chars: int = 50000,
) -> str:
    """
    Extrae texto de un documento (PDF, DOCX, TXT, MD, etc.).

    Args:
        file_path: Ruta al documento.
        max_chars: Máximo de caracteres a extraer.
    """
    try:
        abs_path = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.isfile(abs_path):
            return f"Error: archivo no existe: {abs_path}"

        ext = os.path.splitext(abs_path)[1].lower()

        if ext == ".pdf":
            text, err = _extract_pdf_text(abs_path, max_chars)
        elif ext in (".docx", ".doc"):
            text, err = _extract_docx_text(abs_path, max_chars)
        elif ext in (".txt", ".md", ".rst", ".csv", ".json", ".xml", ".html",
                      ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go",
                      ".rs", ".rb", ".php", ".sql", ".yaml", ".yml", ".toml",
                      ".ini", ".cfg", ".conf", ".log", ".sh", ".bat", ".ps1"):
            text, err = _extract_text_file(abs_path, max_chars)
        else:
            # Intentar como texto plano
            text, err = _extract_text_file(abs_path, max_chars)

        if err:
            return err
        if not text.strip():
            return f"Error: no se pudo extraer texto del archivo {abs_path}."

        return json.dumps({
            "status": "ok",
            "path": abs_path,
            "format": ext,
            "chars": len(text),
            "text": text,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en extract_document_text: {e}"


def summarize_document(
    file_path: str,
    max_words: int = 300,
    language: str = "español",
) -> str:
    """
    Resume un documento (PDF, DOCX, TXT) usando el modelo LLM local (Ollama).

    Args:
        file_path: Ruta al documento a resumir.
        max_words: Máximo de palabras del resumen.
        language: Idioma del resumen (español, english, etc.).
    """
    try:
        # Extraer texto
        extract_result = extract_document_text(file_path, max_chars=30000)
        try:
            extract_data = json.loads(extract_result)
            if extract_data.get("status") != "ok":
                return extract_result
            text = extract_data.get("text", "")
        except Exception:
            if extract_result.startswith("Error"):
                return extract_result
            text = extract_result

        if not text.strip():
            return "Error: el documento está vacío."

        # Truncar si es muy largo para el contexto del modelo
        if len(text) > 25000:
            text = text[:25000] + "\n\n[...documento truncado...]"

        # Resumir con Ollama
        try:
            from ollama import chat
        except ImportError:
            return "Error: librería 'ollama' no instalada."

        prompt = (
            f"Resume el siguiente documento en {language}, máximo {max_words} palabras. "
            f"Destaca los puntos clave, datos importantes y conclusiones principales.\n\n"
            f"---\n{text}\n---\n\n"
            f"Resumen:"
        )

        response = chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.3},
        )

        summary = response["message"].get("content", "").strip()

        abs_path = os.path.abspath(os.path.expanduser(file_path))
        return json.dumps({
            "status": "ok",
            "file": abs_path,
            "original_chars": len(text),
            "summary": summary,
            "summary_words": len(summary.split()),
            "language": language,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en summarize_document: {e}"


# ============================================================================
# 3. BÚSQUEDA SEMÁNTICA
# ============================================================================

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calcula la similitud coseno entre dos vectores."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_embedding(text: str) -> Optional[list[float]]:
    """Obtiene el embedding de un texto usando Ollama."""
    try:
        from ollama import embed
        result = embed(model=EMBED_MODEL, input=text)
        embeddings = result.get("embeddings", [])
        if embeddings:
            return embeddings[0]
        return None
    except Exception:
        return None


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Divide texto en chunks con overlap."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def index_directory(
    directory: str,
    extensions: str = ".txt,.md,.py,.js,.json,.csv,.log",
    max_files: int = 100,
) -> str:
    """
    Indexa archivos de un directorio para búsqueda semántica usando embeddings de Ollama.

    Args:
        directory: Ruta del directorio a indexar.
        extensions: Extensiones de archivo a incluir (separadas por comas).
        max_files: Máximo de archivos a indexar.
    """
    try:
        abs_dir = os.path.abspath(os.path.expanduser(directory))
        if not os.path.isdir(abs_dir):
            return f"Error: directorio no existe: {abs_dir}"

        exts = set(e.strip().lower() for e in extensions.split(",") if e.strip())
        files_indexed = 0
        chunks_indexed = 0
        index_data: list[dict[str, Any]] = []

        for root, dirs, files in os.walk(abs_dir):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if files_indexed >= max_files:
                    break
                ext = os.path.splitext(fname)[1].lower()
                if ext not in exts:
                    continue

                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="replace") as f:
                        content = f.read(20000)  # Max 20k chars per file
                except Exception:
                    continue

                if not content.strip():
                    continue

                # Dividir en chunks
                chunks = _chunk_text(content, chunk_size=300, overlap=30)
                for i, chunk in enumerate(chunks[:10]):  # Max 10 chunks per file
                    embedding = _get_embedding(chunk)
                    if embedding:
                        index_data.append({
                            "file": fpath,
                            "chunk_index": i,
                            "text": chunk[:500],
                            "embedding": embedding,
                        })
                        chunks_indexed += 1

                files_indexed += 1

        # Guardar índice
        EMBEDDINGS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dir_hash = abs_dir.replace(os.sep, "_").replace(":", "")
        cache_path = EMBEDDINGS_CACHE_DIR / f"{dir_hash}.json"

        # No guardar embeddings en JSON (son grandes), usar formato compacto
        cache_data = {
            "directory": abs_dir,
            "indexed_at": datetime.now().isoformat(timespec="seconds"),
            "files_count": files_indexed,
            "chunks_count": chunks_indexed,
            "entries": index_data,
        }
        cache_path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")

        return json.dumps({
            "status": "ok",
            "directory": abs_dir,
            "files_indexed": files_indexed,
            "chunks_indexed": chunks_indexed,
            "cache_path": str(cache_path),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en index_directory: {e}"


def semantic_search(
    query: str,
    directory: str = "",
    extensions: str = ".txt,.md,.py,.js,.json",
    max_results: int = 5,
) -> str:
    """
    Búsqueda semántica en archivos usando embeddings de Ollama.
    Busca archivos cuyo contenido sea semánticamente similar a la consulta.

    Args:
        query: Texto de búsqueda (lenguaje natural).
        directory: Directorio donde buscar. Si vacío, usa el cwd.
        extensions: Extensiones de archivo a buscar.
        max_results: Número máximo de resultados.
    """
    try:
        if not query or not query.strip():
            return "Error: query vacía."

        abs_dir = os.path.abspath(os.path.expanduser(directory)) if directory else os.getcwd()
        if not os.path.isdir(abs_dir):
            return f"Error: directorio no existe: {abs_dir}"

        # Buscar índice cacheado
        dir_hash = abs_dir.replace(os.sep, "_").replace(":", "")
        cache_path = EMBEDDINGS_CACHE_DIR / f"{dir_hash}.json"

        index_data = None
        if cache_path.is_file():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                # Verificar que no sea muy antiguo (>1 hora)
                indexed_at = datetime.fromisoformat(cached.get("indexed_at", ""))
                age = (datetime.now() - indexed_at).total_seconds()
                if age < 3600:
                    index_data = cached.get("entries", [])
            except Exception:
                pass

        # Si no hay índice, indexar ahora
        if not index_data:
            index_result = index_directory(abs_dir, extensions, max_files=50)
            try:
                idx = json.loads(index_result)
                if idx.get("status") != "ok":
                    return index_result
                # Recargar el caché
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                index_data = cached.get("entries", [])
            except Exception:
                return f"Error: no se pudo indexar el directorio."

        if not index_data:
            return "Error: no hay archivos indexados en este directorio."

        # Obtener embedding de la query
        query_embedding = _get_embedding(query)
        if not query_embedding:
            return "Error: no se pudo obtener embedding de la query. ¿Está Ollama corriendo con un modelo de embeddings?"

        # Buscar chunks similares
        scored: list[tuple[float, dict]] = []
        for entry in index_data:
            emb = entry.get("embedding")
            if not emb:
                continue
            score = _cosine_similarity(query_embedding, emb)
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:max_results]

        results = []
        for score, entry in top:
            results.append({
                "file": entry.get("file", ""),
                "score": round(score, 4),
                "chunk": entry.get("text", "")[:300],
            })

        return json.dumps({
            "query": query,
            "directory": abs_dir,
            "results": results,
            "total_chunks_searched": len(index_data),
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en semantic_search: {e}"
