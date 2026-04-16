"""
JARVIS Web Scraper Module — Extracción inteligente de datos web.

Extrae texto, imágenes, enlaces y datos estructurados de páginas web.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from urllib.parse import urljoin, urlparse


def scrape_text(
    url: str,
    max_chars: int = 10000,
) -> str:
    """
    Extrae el texto principal de una página web.

    Args:
        url: URL de la página a scrapear.
        max_chars: Máximo de caracteres a extraer.
    """
    try:
        if not url or not url.strip():
            return "Error: URL vacía."

        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url

        try:
            import requests
        except ImportError:
            return "Error: librería 'requests' no instalada."

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        }

        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()

        html = response.text
        text = _html_to_text(html)

        if not text.strip():
            return json.dumps({
                "status": "ok",
                "url": url,
                "text": "",
                "message": "No se pudo extraer texto de la página.",
            }, ensure_ascii=False)

        return json.dumps({
            "status": "ok",
            "url": url,
            "title": _extract_title(html),
            "text": text[:max_chars],
            "chars": len(text),
            "truncated": len(text) > max_chars,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en scrape_text: {e}"


def scrape_links(
    url: str,
    filter_domain: bool = False,
) -> str:
    """
    Extrae todos los enlaces de una página web.

    Args:
        url: URL de la página.
        filter_domain: Si True, solo devuelve links del mismo dominio.
    """
    try:
        if not url or not url.strip():
            return "Error: URL vacía."

        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url

        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        html = response.text

        # Extraer links con regex (sin depender de BeautifulSoup)
        link_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
        raw_links = link_pattern.findall(html)

        parsed_base = urlparse(url)
        base_domain = parsed_base.netloc

        links = []
        seen = set()
        for href in raw_links:
            # Resolver URLs relativas
            full_url = urljoin(url, href)
            parsed = urlparse(full_url)

            # Filtrar
            if parsed.scheme not in ("http", "https"):
                continue
            if filter_domain and parsed.netloc != base_domain:
                continue
            if full_url in seen:
                continue

            seen.add(full_url)
            links.append({
                "url": full_url,
                "domain": parsed.netloc,
                "path": parsed.path,
            })

        return json.dumps({
            "status": "ok",
            "source_url": url,
            "links_found": len(links),
            "links": links[:100],
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en scrape_links: {e}"


def scrape_images(
    url: str,
    download: bool = False,
    download_dir: str = "",
    max_images: int = 20,
) -> str:
    """
    Extrae las URLs de imágenes de una página web. Opcionalmente las descarga.

    Args:
        url: URL de la página.
        download: Si True, descarga las imágenes.
        download_dir: Directorio donde guardar. Si vacío, usa ~/Downloads/jarvis_images/.
        max_images: Máximo de imágenes a procesar.
    """
    try:
        if not url or not url.strip():
            return "Error: URL vacía."

        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url

        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        html = response.text

        # Extraer imágenes
        img_pattern = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
        raw_srcs = img_pattern.findall(html)

        images = []
        seen = set()
        for src in raw_srcs:
            full_url = urljoin(url, src)
            if full_url in seen:
                continue
            seen.add(full_url)

            # Filtrar SVGs y pequeños iconos
            ext = os.path.splitext(urlparse(full_url).path)[1].lower()
            if ext in (".svg", ".ico"):
                continue

            images.append({"url": full_url, "ext": ext or ".jpg"})

            if len(images) >= max_images:
                break

        downloaded = []
        if download and images:
            if not download_dir:
                download_dir = os.path.join(os.path.expanduser("~"), "Downloads", "jarvis_images")
            os.makedirs(download_dir, exist_ok=True)

            for i, img in enumerate(images):
                try:
                    resp = requests.get(img["url"], headers=headers, timeout=10)
                    if resp.status_code == 200:
                        fname = f"img_{i+1}{img['ext']}"
                        fpath = os.path.join(download_dir, fname)
                        with open(fpath, "wb") as f:
                            f.write(resp.content)
                        downloaded.append(fpath)
                except Exception:
                    pass

        return json.dumps({
            "status": "ok",
            "source_url": url,
            "images_found": len(images),
            "images": [img["url"] for img in images],
            "downloaded": downloaded if download else [],
            "download_dir": download_dir if download else "",
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en scrape_images: {e}"


def monitor_price(
    url: str,
    target_price: float = 0,
    css_hint: str = "",
) -> str:
    """
    Extrae el precio de un producto de una URL de tienda online.
    Busca patrones de precio en el HTML.

    Args:
        url: URL del producto.
        target_price: Si > 0, indica el precio objetivo para notificar.
        css_hint: Pista CSS selector (ej: '#price', '.precio') — no se usa con regex,
                  pero se incluye en el resultado para referencia.
    """
    try:
        if not url:
            return "Error: URL vacía."

        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        response = requests.get(url.strip(), headers=headers, timeout=15)
        response.raise_for_status()
        html = response.text

        # Patrones de precio comunes
        price_patterns = [
            r'(?:price|precio|Price)[\s":]*[$€£]?\s*([\d.,]+)',
            r'[$€£]\s*([\d.,]+)',
            r'([\d.,]+)\s*[$€£]',
            r'data-price=["\']?([\d.,]+)',
            r'class="[^"]*price[^"]*"[^>]*>([\d.,€$£\s]+)<',
        ]

        prices = []
        for pattern in price_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for match in matches:
                # Limpiar
                cleaned = re.sub(r'[€$£\s]', '', match).replace(",", ".")
                try:
                    price = float(cleaned)
                    if 0.01 < price < 100000:  # Rango razonable
                        prices.append(price)
                except ValueError:
                    pass

        if not prices:
            return json.dumps({
                "status": "ok",
                "url": url,
                "prices_found": 0,
                "message": "No se detectaron precios en la página.",
            }, ensure_ascii=False)

        # Eliminar duplicados y ordenar
        unique_prices = sorted(set(prices))
        best_price = min(unique_prices)

        below_target = target_price > 0 and best_price <= target_price

        result = {
            "status": "ok",
            "url": url,
            "prices_found": len(unique_prices),
            "prices": unique_prices[:10],
            "lowest_price": best_price,
            "title": _extract_title(html),
        }

        if target_price > 0:
            result["target_price"] = target_price
            result["below_target"] = below_target
            if below_target:
                result["alert"] = f"🎉 ¡Precio ({best_price}) por debajo del objetivo ({target_price})!"

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error en monitor_price: {e}"


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _html_to_text(html: str) -> str:
    """Convierte HTML a texto plano (sin dependencias externas)."""
    # Eliminar scripts y styles
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Convertir <br>, <p>, <div> a newlines
    text = re.sub(r'<br[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(p|div|h[1-6]|li|tr)>', '\n', text, flags=re.IGNORECASE)
    # Eliminar tags HTML
    text = re.sub(r'<[^>]+>', '', text)
    # Decodificar entidades comunes
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&quot;", '"').replace("&#39;", "'")
    # Limpiar espacios
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def _extract_title(html: str) -> str:
    """Extrae el <title> del HTML."""
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""
