"""
JARVIS Clipboard Intelligence Module.

Analiza el contenido del portapapeles y sugiere/ejecuta acciones inteligentes
basadas en el tipo de contenido detectado (URL, código, email, JSON, texto...).
"""

import json
import os
import re
from typing import Any


# ---------------------------------------------------------------------------
# Detección de tipos
# ---------------------------------------------------------------------------

_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.IGNORECASE
)
_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE
)
_PHONE_PATTERN = re.compile(
    r"[\+]?[0-9]{1,4}[\s\-]?[\(]?[0-9]{1,4}[\)]?[\s\-]?[0-9]{3,10}"
)
_IP_PATTERN = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
)

# Indicadores de código
_CODE_INDICATORS = [
    "def ", "class ", "import ", "from ", "return ",
    "function ", "const ", "let ", "var ",
    "public ", "private ", "static ",
    "if (", "for (", "while (", "switch (",
    "<?php", "<!DOCTYPE", "<html",
    "#include", "int main(",
]


def _detect_content_type(text: str) -> dict[str, Any]:
    """Detecta el tipo de contenido del texto."""
    text_stripped = text.strip()

    if not text_stripped:
        return {"type": "empty", "details": "Portapapeles vacío"}

    # JSON
    if text_stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(text_stripped)
            items = len(parsed) if isinstance(parsed, (list, dict)) else 1
            return {
                "type": "json",
                "details": f"JSON válido ({type(parsed).__name__}, {items} elementos)",
                "parsed": True,
            }
        except (json.JSONDecodeError, ValueError):
            pass

    # URL
    urls = _URL_PATTERN.findall(text_stripped)
    if urls and len(text_stripped) < 2000:
        return {
            "type": "url",
            "details": f"{len(urls)} URL(s) detectada(s)",
            "urls": urls[:5],
        }

    # Email
    emails = _EMAIL_PATTERN.findall(text_stripped)
    if emails and len(text_stripped) < 500:
        return {
            "type": "email",
            "details": f"{len(emails)} email(s)",
            "emails": emails[:5],
        }

    # Dirección IP
    ips = _IP_PATTERN.findall(text_stripped)
    if ips and len(text_stripped) < 200:
        return {
            "type": "ip_address",
            "details": f"{len(ips)} IP(s): {', '.join(ips[:3])}",
            "ips": ips[:5],
        }

    # Teléfono
    phones = _PHONE_PATTERN.findall(text_stripped)
    if phones and len(text_stripped) < 200:
        return {
            "type": "phone",
            "details": f"Número(s) de teléfono: {', '.join(phones[:3])}",
            "phones": phones[:5],
        }

    # Código fuente
    lines = text_stripped.split("\n")
    code_score = sum(
        1 for indicator in _CODE_INDICATORS
        if indicator in text_stripped
    )
    if code_score >= 2 or (len(lines) > 3 and any(
        line.strip().startswith(("#", "//", "/*", "'''", '"""'))
        for line in lines[:5]
    )):
        # Intentar detectar lenguaje
        lang = "desconocido"
        if "def " in text_stripped and "import " in text_stripped:
            lang = "Python"
        elif "function " in text_stripped or "const " in text_stripped:
            lang = "JavaScript"
        elif "public class" in text_stripped:
            lang = "Java"
        elif "#include" in text_stripped:
            lang = "C/C++"
        elif "<?php" in text_stripped:
            lang = "PHP"
        elif "<html" in text_stripped.lower():
            lang = "HTML"

        return {
            "type": "code",
            "details": f"Código fuente ({lang}, {len(lines)} líneas)",
            "language": lang,
            "lines": len(lines),
        }

    # Ruta de archivo
    if os.path.sep in text_stripped and len(lines) == 1 and len(text_stripped) < 500:
        is_path = text_stripped.startswith(("/", "C:", "D:", "~", "."))
        if is_path:
            exists = os.path.exists(os.path.expanduser(text_stripped))
            return {
                "type": "file_path",
                "details": f"Ruta de archivo {'(existe)' if exists else '(no existe)'}",
                "path": text_stripped,
                "exists": exists,
            }

    # Texto largo vs corto
    word_count = len(text_stripped.split())
    if word_count > 100:
        return {
            "type": "long_text",
            "details": f"Texto largo ({word_count} palabras, {len(text_stripped)} chars)",
            "words": word_count,
        }

    return {
        "type": "short_text",
        "details": f"Texto corto ({word_count} palabras)",
        "words": word_count,
    }


def _suggest_actions(content_type: dict[str, Any]) -> list[str]:
    """Sugiere acciones basadas en el tipo de contenido."""
    t = content_type.get("type", "")

    suggestions = {
        "url": [
            "Abrir en el navegador (open_url)",
            "Resumir contenido web (summarize_document)",
            "Buscar más info (web_search)",
        ],
        "email": [
            "Guardar en el vault (save_password)",
            "Copiar al portapapeles formateado",
        ],
        "code": [
            "Analizar/explicar el código",
            "Detectar errores o mejoras",
            "Formatear el código",
            "Guardar como archivo (create_file)",
        ],
        "json": [
            "Formatear JSON bonito",
            "Analizar estructura",
            "Guardar como archivo .json",
        ],
        "long_text": [
            "Resumir el texto",
            "Traducir el texto (translate_text)",
            "Guardar como archivo .txt",
        ],
        "short_text": [
            "Traducir el texto",
            "Buscar en la web (web_search)",
            "Buscar en Wikipedia (wikipedia_search)",
        ],
        "file_path": [
            "Leer el archivo (read_file)",
            "Describir el archivo (describe_path)",
            "Abrir con la app predeterminada",
        ],
        "ip_address": [
            "Obtener info de la IP (get_ip_info)",
            "Hacer ping",
            "Escanear puertos",
        ],
        "phone": [
            "Guardar en contactos",
            "Copiar formateado",
        ],
        "empty": [
            "No hay contenido en el portapapeles",
        ],
    }

    return suggestions.get(t, ["No hay acciones sugeridas"])


# ---------------------------------------------------------------------------
# Herramientas públicas
# ---------------------------------------------------------------------------

def analyze_clipboard() -> str:
    """
    Analiza el contenido actual del portapapeles y sugiere acciones inteligentes.
    Detecta automáticamente: URLs, emails, código fuente, JSON, IPs, texto largo/corto, rutas de archivo.
    """
    try:
        try:
            from automation import get_clipboard
        except ImportError:
            return "Error: módulo automation no disponible."

        clip_result = get_clipboard()
        try:
            clip_data = json.loads(clip_result)
            text = clip_data.get("content", "")
        except (json.JSONDecodeError, TypeError):
            text = clip_result if isinstance(clip_result, str) else ""

        content_type = _detect_content_type(text)
        suggestions = _suggest_actions(content_type)

        return json.dumps({
            "status": "ok",
            "content_preview": text[:200] + ("..." if len(text) > 200 else ""),
            "content_length": len(text),
            "detected_type": content_type,
            "suggested_actions": suggestions,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en analyze_clipboard: {e}"


def smart_clipboard_action(action: str) -> str:
    """
    Ejecuta una acción inteligente sobre el contenido del portapapeles.

    Args:
        action: Acción a ejecutar. Opciones:
            - "format_json": Formatea JSON bonito y lo copia al portapapeles.
            - "open_urls": Abre las URLs detectadas en el navegador.
            - "summarize": Resume el texto usando el LLM.
            - "translate": Traduce el texto (español↔inglés).
            - "save_as": Guarda el contenido como archivo.
            - "analyze_code": Analiza el código y da sugerencias.
    """
    try:
        try:
            from automation import get_clipboard, set_clipboard
        except ImportError:
            return "Error: módulo automation no disponible."

        clip_result = get_clipboard()
        try:
            clip_data = json.loads(clip_result)
            text = clip_data.get("content", "")
        except (json.JSONDecodeError, TypeError):
            text = clip_result if isinstance(clip_result, str) else ""

        if not text.strip():
            return "Error: portapapeles vacío."

        action = action.strip().lower()

        if action == "format_json":
            try:
                parsed = json.loads(text)
                formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
                set_clipboard(formatted)
                return json.dumps({
                    "status": "ok",
                    "action": "format_json",
                    "message": "JSON formateado y copiado al portapapeles.",
                    "preview": formatted[:300],
                }, ensure_ascii=False)
            except json.JSONDecodeError:
                return "Error: el contenido del portapapeles no es JSON válido."

        elif action == "open_urls":
            urls = _URL_PATTERN.findall(text)
            if not urls:
                return "Error: no se detectaron URLs en el portapapeles."
            try:
                from automation import open_url
                results = []
                for url in urls[:5]:
                    res = open_url(url)
                    results.append(f"{url}: {res}")
                return json.dumps({
                    "status": "ok",
                    "action": "open_urls",
                    "urls_opened": len(urls[:5]),
                    "results": results,
                }, ensure_ascii=False)
            except ImportError:
                return "Error: función open_url no disponible."

        elif action == "translate":
            try:
                from apis import translate_text
                # Auto-detect: si parece español, traducir a inglés y viceversa
                spanish_words = ["el", "la", "de", "que", "en", "un", "es", "por", "con", "para"]
                words = text.lower().split()[:20]
                is_spanish = sum(1 for w in words if w in spanish_words) >= 2
                target = "en" if is_spanish else "es"
                source = "es" if is_spanish else "en"
                result = translate_text(text[:2000], target_lang=target, source_lang=source)
                return result
            except ImportError:
                return "Error: módulo apis no disponible."

        elif action == "save_as":
            content_type = _detect_content_type(text)
            t = content_type.get("type", "text")
            ext_map = {
                "json": ".json", "code": ".txt", "url": ".txt",
                "long_text": ".txt", "short_text": ".txt",
            }
            ext = ext_map.get(t, ".txt")
            from datetime import datetime
            filename = f"clipboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
            filepath = os.path.join(os.path.expanduser("~"), "Desktop", filename)
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(text)
                return json.dumps({
                    "status": "ok",
                    "action": "save_as",
                    "path": filepath,
                    "size": len(text),
                }, ensure_ascii=False)
            except Exception as e:
                return f"Error guardando archivo: {e}"

        else:
            return f"Error: acción '{action}' no reconocida. Opciones: format_json, open_urls, summarize, translate, save_as, analyze_code"

    except Exception as e:
        return f"Error en smart_clipboard_action: {e}"
