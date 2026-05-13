"""
AARIS APIs Module — Integraciones con APIs externas.

Provee herramientas para consultar información del mundo exterior:
- Clima: wttr.in (sin key) u **OpenWeatherMap** si defines `AARIS_OPENWEATHER_API_KEY`
- Noticias: RSS (sin key) o **NewsAPI.org** si defines `AARIS_NEWSAPI_KEY` (`search=` o categorías `headlines_xx`)
- Búsqueda web (DuckDuckGo)
- Wikipedia
- Traducción (MyMemory)
- IP/Ubicación: ipinfo.io JSON sin token, o **IPinfo Lite** con `AARIS_IPINFO_TOKEN`
- Criptomonedas (CoinGecko)
- Fecha/hora mundial
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from urllib.parse import quote_plus

# duckduckgo-search avisa renombre a `ddgs` (RuntimeWarning); se suprime dentro de _ddgs_text_results.


def _http_get(url: str, timeout: int = 10, headers: Optional[dict] = None) -> tuple[int, str]:
    """
    Realiza una petición HTTP GET. Retorna (status_code, body).
    Usa requests si está disponible, sino urllib como fallback.
    """
    try:
        import requests
        h = headers or {}
        h.setdefault("User-Agent", "AARIS-Assistant/1.0")
        resp = requests.get(url, timeout=timeout, headers=h)
        return resp.status_code, resp.text
    except ImportError:
        # Fallback a urllib
        import urllib.request
        import urllib.error
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "AARIS-Assistant/1.0")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, f"Error HTTP: {e}"


def _openweather_key() -> str:
    return (
        os.environ.get("AARIS_OPENWEATHER_API_KEY", "")
        or os.environ.get("OPENWEATHER_API_KEY", "")
    ).strip()


def _newsapi_key() -> str:
    return (
        os.environ.get("AARIS_NEWSAPI_KEY", "")
        or os.environ.get("NEWSAPI_KEY", "")
    ).strip()


def _ipinfo_token() -> str:
    return (
        os.environ.get("AARIS_IPINFO_TOKEN", "")
        or os.environ.get("IPINFO_TOKEN", "")
    ).strip()


def _get_weather_openweather(location: str, format: str, lang: str) -> Optional[str]:
    """OpenWeatherMap 2.5 current weather. None = usar wttr.in."""
    key = _openweather_key()
    if not key:
        return None
    loc = (location or "").strip() or os.environ.get("AARIS_CITY", "Madrid").strip() or "Madrid"
    url = (
        "https://api.openweathermap.org/data/2.5/weather?"
        f"q={quote_plus(loc)}&appid={quote_plus(key)}&units=metric&lang={lang}"
    )
    status, body = _http_get(url, timeout=12)
    if status == 401:
        return "Error: OpenWeatherMap rechazó la API key (401). Comprueba AARIS_OPENWEATHER_API_KEY."
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    cod = data.get("cod")
    if str(cod) != "200":
        return None
    main = data.get("main") or {}
    wlist = data.get("weather") or [{}]
    w0 = wlist[0] if wlist else {}
    wind = data.get("wind") or {}
    name = data.get("name") or loc
    country = (data.get("sys") or {}).get("country") or ""
    temp = main.get("temp")
    feels = main.get("feels_like")
    hum = main.get("humidity")
    desc = w0.get("description") or w0.get("main") or ""
    spd = wind.get("speed")
    deg = wind.get("deg")

    if format == "json":
        out = {
            "source": "openweathermap.org",
            "location": name,
            "country": country,
            "temperature_c": temp,
            "temperature": temp,
            "feels_like_c": feels,
            "humidity": hum,
            "description": desc,
            "pressure_mb": main.get("pressure"),
            "wind_m_s": spd,
            "wind_deg": deg,
            "visibility_m": data.get("visibility"),
            "clouds_percent": (data.get("clouds") or {}).get("all")
            if isinstance(data.get("clouds"), dict)
            else data.get("clouds"),
        }
        return json.dumps(out, ensure_ascii=False)

    if format == "short":
        line = f"{name}: {desc}"
        if temp is not None:
            line += f" {temp:.0f}°C"
        if hum is not None:
            line += f" hum {hum}%"
        if spd is not None:
            line += f" viento {spd:.1f}m/s"
        return line.strip()

    lines = [
        f"Clima (OpenWeatherMap) — {name}, {country}".strip(" ,"),
        f"Condición: {desc}",
    ]
    if temp is not None:
        lines.append(f"Temperatura: {temp:.1f}°C (sensación {feels:.1f}°C)" if feels is not None else f"Temperatura: {temp:.1f}°C")
    if hum is not None:
        lines.append(f"Humedad: {hum}%")
    if main.get("pressure"):
        lines.append(f"Presión: {main['pressure']} hPa")
    if spd is not None:
        wdir = f", dirección {deg}°" if deg is not None else ""
        lines.append(f"Viento: {spd:.1f} m/s{wdir}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Clima — wttr.in (gratis, sin key) u OpenWeatherMap con AARIS_OPENWEATHER_API_KEY
# ---------------------------------------------------------------------------

def get_weather(location: str = "", format: str = "full", lang: str = "es") -> str:
    """
    Consulta el clima actual para una ubicación.

    Si existe ``AARIS_OPENWEATHER_API_KEY`` (o ``OPENWEATHER_API_KEY``), se usa
    OpenWeatherMap. Con ``location`` vacío se usa ``AARIS_CITY`` (por defecto Madrid).
    Si no hay clave, se usa wttr.in (ubicación vacía = detección aproximada por IP).

    Args:
        location: Ciudad o ubicación (ej: "Madrid", "New York", "Tokyo").
        format: "full" (detallado), "short" (una línea), "json" (datos crudos).
        lang: Código de idioma para la respuesta (ej: "es", "en", "fr").
    """
    try:
        ow = _get_weather_openweather(location, format, lang)
        if ow is not None:
            return ow

        loc = quote_plus(location.strip()) if location.strip() else ""

        if format == "short":
            url = f"https://wttr.in/{loc}?format=%l:+%C+%t+%h+%w&lang={lang}"
            status, body = _http_get(url)
            if status == 200 and body.strip():
                return body.strip()
            return f"Error: no se pudo obtener el clima (status={status})."

        if format == "json":
            url = f"https://wttr.in/{loc}?format=j1&lang={lang}"
            status, body = _http_get(url, timeout=15)
            if status == 200:
                try:
                    data = json.loads(body)
                    current = data.get("current_condition", [{}])[0]
                    weather_desc = current.get("lang_es", [{}])[0].get("value") if lang == "es" else current.get("weatherDesc", [{}])[0].get("value")
                    result = {
                        "location": location or "(auto)",
                        "temperature_c": current.get("temp_C"),
                        "feels_like_c": current.get("FeelsLikeC"),
                        "humidity": current.get("humidity"),
                        "wind_kmph": current.get("windspeedKmph"),
                        "wind_dir": current.get("winddir16Point"),
                        "description": weather_desc or current.get("weatherDesc", [{}])[0].get("value"),
                        "visibility_km": current.get("visibility"),
                        "uv_index": current.get("uvIndex"),
                        "pressure_mb": current.get("pressure"),
                    }
                    # Pronóstico
                    forecast = data.get("weather", [])
                    if forecast:
                        result["forecast"] = []
                        for day in forecast[:3]:
                            result["forecast"].append({
                                "date": day.get("date"),
                                "max_c": day.get("maxtempC"),
                                "min_c": day.get("mintempC"),
                                "description": day.get("hourly", [{}])[4].get("lang_es", [{}])[0].get("value") if lang == "es" else day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value"),
                            })
                    return json.dumps(result, ensure_ascii=False)
                except Exception:
                    return body[:8000]
            return f"Error: no se pudo obtener el clima (status={status})."

        # format == "full"
        url = f"https://wttr.in/{loc}?lang={lang}&F"
        status, body = _http_get(url, timeout=15)
        if status == 200 and body.strip():
            # Limpiar caracteres ANSI
            clean = re.sub(r"\x1b\[[0-9;]*m", "", body)
            lines = clean.strip().split("\n")
            # Limitar a algo razonable
            return "\n".join(lines[:40])
        return f"Error: no se pudo obtener el clima para '{location}' (status={status})."
    except Exception as e:
        return f"Error en get_weather: {e}"


# ---------------------------------------------------------------------------
# Noticias — RSS feeds (gratis, sin key)
# ---------------------------------------------------------------------------

def _parse_rss_simple(xml_text: str, max_items: int = 10) -> list[dict[str, str]]:
    """Parser RSS muy simple sin dependencias externas."""
    items = []
    # Extraer items con regex
    item_blocks = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)
    for block in item_blocks[:max_items]:
        title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.DOTALL)
        link_m = re.search(r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", block, re.DOTALL)
        desc_m = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, re.DOTALL)
        pub_m = re.search(r"<pubDate>(.*?)</pubDate>", block, re.DOTALL)

        title = title_m.group(1).strip() if title_m else ""
        link = link_m.group(1).strip() if link_m else ""
        desc = desc_m.group(1).strip() if desc_m else ""
        pub = pub_m.group(1).strip() if pub_m else ""

        # Limpiar HTML de la descripción
        desc = re.sub(r"<[^>]+>", "", desc)
        desc = desc[:300]

        if title:
            items.append({
                "title": title,
                "link": link,
                "description": desc,
                "published": pub,
            })
    return items


_RSS_FEEDS = {
    "general_es": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
    "tech_es": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/tecnologia/portada",
    "bbc_world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc_tech": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "reuters": "https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en",
    "hackernews": "https://hnrss.org/frontpage",
}

_NEWSAPI_HEADLINE_COUNTRIES: dict[str, str] = {
    "headlines_es": "es",
    "headlines_mx": "mx",
    "headlines_ar": "ar",
    "headlines_co": "co",
    "headlines_us": "us",
    "headlines_gb": "gb",
    "headlines_fr": "fr",
    "headlines_de": "de",
    "headlines_it": "it",
    "headlines_br": "br",
    "headlines_pt": "pt",
}


def _newsapi_article_to_item(a: dict) -> dict[str, str]:
    src = a.get("source") or {}
    src_name = src.get("name", "") if isinstance(src, dict) else str(src or "")
    return {
        "title": (a.get("title") or "").strip(),
        "link": (a.get("url") or "").strip(),
        "description": ((a.get("description") or "")[:300]),
        "published": (a.get("publishedAt") or "").strip(),
        "source": src_name,
    }


_NEWSAPI_EVERYTHING_HINT = (
    " Sugerencia: en plan gratuito `/v2/everything` a menudo está limitado; prueba "
    "`get_news(category='headlines_es')` o `headlines_us` (titulares por país)."
)


def _newsapi_everything(query: str, max_items: int, lang: str) -> str:
    key = _newsapi_key()
    lang_news = "es" if lang.startswith("es") else "en"
    n = min(max(1, max_items), 100)
    url = (
        "https://newsapi.org/v2/everything?"
        f"q={quote_plus(query)}&language={lang_news}&sortBy=publishedAt&pageSize={n}&apiKey={quote_plus(key)}"
    )
    status, body = _http_get(url, timeout=15)
    if status == 401:
        return "Error: NewsAPI rechazó la API key (401). Revisa AARIS_NEWSAPI_KEY."
    if status != 200:
        return f"Error: NewsAPI everything (status={status})." + _NEWSAPI_EVERYTHING_HINT
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "Error: respuesta NewsAPI no es JSON." + _NEWSAPI_EVERYTHING_HINT
    if data.get("status") != "ok":
        return f"Error NewsAPI: {data.get('message', body[:200])}" + _NEWSAPI_EVERYTHING_HINT
    raw = data.get("articles") or []
    items = [_newsapi_article_to_item(a) for a in raw if (a.get("title") or "").strip()]
    if not items:
        return "Sin artículos para esa búsqueda." + _NEWSAPI_EVERYTHING_HINT
    out = {
        "source": "newsapi.org",
        "category": f"everything:{query}",
        "count": len(items),
        "news": items,
        "articles": items,
    }
    return json.dumps(out, ensure_ascii=False)


def _newsapi_top_headlines(country: str, max_items: int, category: str) -> str:
    key = _newsapi_key()
    n = min(max(1, max_items), 100)
    url = (
        "https://newsapi.org/v2/top-headlines?"
        f"country={quote_plus(country)}&pageSize={n}&apiKey={quote_plus(key)}"
    )
    status, body = _http_get(url, timeout=15)
    if status == 401:
        return "Error: NewsAPI rechazó la API key (401). Revisa AARIS_NEWSAPI_KEY."
    if status != 200:
        return f"Error: NewsAPI top-headlines (status={status})."
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "Error: respuesta NewsAPI no es JSON."
    if data.get("status") != "ok":
        return f"Error NewsAPI: {data.get('message', body[:200])}"
    raw = data.get("articles") or []
    items = [_newsapi_article_to_item(a) for a in raw if (a.get("title") or "").strip()]
    if not items:
        return "Sin titulares disponibles para ese país."
    out = {
        "source": "newsapi.org",
        "category": category,
        "count": len(items),
        "news": items,
        "articles": items,
    }
    return json.dumps(out, ensure_ascii=False)


def get_news(
    category: str = "general_es",
    max_items: int = 8,
    custom_feed_url: Optional[str] = None,
    *,
    search: str = "",
    country_code: str = "",
    lang: str = "es",
) -> str:
    """
    Noticias: RSS (sin clave) o NewsAPI.org si defines ``AARIS_NEWSAPI_KEY``.

    Args:
        category: Feed RSS (general_es, tech_es, …) o titulares ``headlines_es``,
                  ``headlines_us``, etc. (requiere NewsAPI).
        max_items: Máximo de noticias.
        custom_feed_url: URL RSS (ignora category).
        search: Con NewsAPI, búsqueda ``/v2/everything`` (temas, nombres, empresas).
        country_code: ISO2 (ej. ``es``) para titulares vía NewsAPI.
        lang: Afecta el parámetro ``language`` de ``everything`` (es/en).
    """
    try:
        cat_l = category.strip().lower()
        sch = search.strip()
        cc = country_code.strip().lower()
        key = _newsapi_key()

        if key and sch:
            return _newsapi_everything(sch, max_items, lang)

        if key and len(cc) == 2:
            return _newsapi_top_headlines(cc, max_items, category=f"headlines:{cc}")

        if key and cat_l in _NEWSAPI_HEADLINE_COUNTRIES:
            return _newsapi_top_headlines(_NEWSAPI_HEADLINE_COUNTRIES[cat_l], max_items, category=cat_l)

        if custom_feed_url:
            url = custom_feed_url
        else:
            url = _RSS_FEEDS.get(cat_l)
            if not url:
                rss_keys = ", ".join(sorted(_RSS_FEEDS.keys()))
                hl_keys = ", ".join(sorted(_NEWSAPI_HEADLINE_COUNTRIES.keys()))
                extra = (
                    f" Con AARIS_NEWSAPI_KEY: categorías {hl_keys} o search=\"tema\"."
                    if not key
                    else f" Con NewsAPI: {hl_keys} o search=\"…\"."
                )
                return f"Error: categoría '{category}' no existe. RSS: {rss_keys}.{extra}"

        status, body = _http_get(url, timeout=15)
        if status != 200:
            return f"Error: no se pudo obtener el feed (status={status})."

        items = _parse_rss_simple(body, max_items=max_items)
        if not items:
            return "Sin noticias disponibles en este feed."

        result = {
            "source": category if not custom_feed_url else custom_feed_url,
            "count": len(items),
            "news": items,
            "articles": items,
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error en get_news: {e}"


# ---------------------------------------------------------------------------
# Búsqueda web — DuckDuckGo HTML (gratis, sin key)
# ---------------------------------------------------------------------------

def _ddgs_text_results(query: str, max_results: int = 8) -> list[dict[str, str]]:
    """
    Obtiene filas {title, url, snippet} desde DDGS con reintentos (región, backend, variantes).
    Sin región, consultas cortas en español a menudo devuelven 0 resultados (p. ej. «CEAC FP»).
    """
    q0 = (query or "").strip()
    if not q0:
        return []

    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []

    region_pref = (os.environ.get("AARIS_DDG_REGION", "es-es") or "").strip() or "es-es"
    regions_try: list[Optional[str]] = [region_pref, "es-es", "wt-es", None]
    regions_ordered: list[Optional[str]] = []
    for r in regions_try:
        if r not in regions_ordered:
            regions_ordered.append(r)

    backends_try = ["auto", "duckduckgo", "bing"]
    env_backends = os.environ.get("AARIS_DDG_BACKENDS", "").strip()
    if env_backends:
        backends_try = [b.strip() for b in env_backends.split(",") if b.strip()] + [
            b for b in backends_try if b not in env_backends
        ]

    variants = [q0]
    if len(q0) < 48:
        variants.extend(
            [
                f"{q0} España",
                f"{q0} formación profesional",
                f"{q0} FP España",
            ]
        )

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    ddgs = DDGS()

    for kw in variants:
        for region in regions_ordered:
            for backend in backends_try:
                try:
                    raw = ddgs.text(
                        kw,
                        region=region,
                        backend=backend,
                        max_results=max_results,
                    )
                except TypeError:
                    try:
                        raw = ddgs.text(kw, max_results=max_results)
                    except Exception:
                        continue
                except Exception:
                    continue
                for item in raw or []:
                    url = (item.get("href") or item.get("url") or "").strip()
                    title = (item.get("title") or "").strip()
                    snippet = (item.get("body") or item.get("snippet") or "").strip()
                    key = url or f"{title}|{snippet[:80]}"
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"title": title, "url": url, "snippet": snippet})
                    if len(out) >= max_results:
                        return out
        if len(out) >= min(3, max_results):
            break
    return out


def _wikipedia_fallback_rows(query: str) -> list[dict[str, str]]:
    """Si DDGS falla, al menos un resultado útil desde Wikipedia (es)."""
    raw = wikipedia_search(query, lang="es", sentences=8)
    if not raw or raw.startswith("Error:") or raw.startswith("Sin "):
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    title = (data.get("title") or "").strip()
    url = (data.get("url") or "").strip()
    extract = (data.get("extract") or "").strip()
    if not title and not extract:
        return []
    snippet = extract[:900] + ("…" if len(extract) > 900 else "")
    return [
        {
            "title": f"[Wikipedia] {title}" if title else "[Wikipedia]",
            "url": url or f"https://es.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}",
            "snippet": snippet,
        }
    ]


def web_search(query: str, max_results: int = 8) -> str:
    """
    Busca en la web usando DuckDuckGo (librería duckduckgo-search) y devuelve resultados.

    Args:
        query: Texto a buscar.
        max_results: Número máximo de resultados.
    """
    try:
        if not query or not query.strip():
            return "Error: query vacía."

        results = _ddgs_text_results(query, max_results=max_results)
        engine = "duckduckgo"
        if not results:
            results = _wikipedia_fallback_rows(query)
            engine = "wikipedia_fallback"

        if not results:
            return f"Sin resultados relevantes para '{query}'. Intenta con otra búsqueda."

        return json.dumps({
            "query": query,
            "engine": engine,
            "count": len(results),
            "results": results,
        }, ensure_ascii=False)
    except ImportError:
        return "Error: la librería 'duckduckgo-search' no está instalada. Instálala con: pip install -U duckduckgo-search"
    except Exception as e:
        return f"Error en web_search: {e}"


def web_search_full(query: str, max_results: int = 8) -> str:
    """
    Busca en la web y devuelve resultados de búsqueda reales
    con título, URL y snippet descriptivo.

    Usa Google Custom Search si AARIS_GOOGLE_API_KEY y AARIS_GOOGLE_CX están configurados,
    si no, usa DuckDuckGo (librería duckduckgo-search) como fallback gratuito.

    Esta herramienta es superior a web_search para obtener información real de internet.
    Úsala cuando el usuario pregunte por información actualizada o pida investigar un tema.

    Args:
        query: Texto a buscar en internet.
        max_results: Número máximo de resultados a devolver.
    """
    try:
        if not query or not query.strip():
            return "Error: query vacía."

        # ── Google Custom Search (si hay API key) ──
        google_api_key = os.environ.get("AARIS_GOOGLE_API_KEY", "").strip()
        google_cx = os.environ.get("AARIS_GOOGLE_CX", "").strip()

        if google_api_key and google_cx:
            try:
                gurl = (
                    f"https://www.googleapis.com/customsearch/v1"
                    f"?key={google_api_key}&cx={google_cx}"
                    f"&q={quote_plus(query)}&num={min(max_results, 10)}"
                    f"&lr=lang_es&gl=es"
                )
                status, body = _http_get(gurl, timeout=15)
                if status == 200:
                    data = json.loads(body)
                    items = data.get("items", [])
                    results = []
                    for item in items[:max_results]:
                        results.append({
                            "title": item.get("title", ""),
                            "url": item.get("link", ""),
                            "snippet": item.get("snippet", ""),
                        })
                    if results:
                        return json.dumps({
                            "query": query,
                            "engine": "google",
                            "count": len(results),
                            "results": results,
                        }, ensure_ascii=False)
            except Exception:
                pass  # Fallback a DuckDuckGo

        # ── DuckDuckGo / variantes (región es-es por defecto) + Wikipedia si sigue vacío ──
        results = _ddgs_text_results(query, max_results=max_results)
        engine = "duckduckgo"
        if not results:
            results = _wikipedia_fallback_rows(query)
            engine = "wikipedia_fallback"

        if not results:
            return f"Sin resultados relevantes para '{query}'. Intenta con otra búsqueda."

        return json.dumps({
            "query": query,
            "engine": engine,
            "count": len(results),
            "results": results,
        }, ensure_ascii=False)
    except ImportError:
        return "Error: la librería 'duckduckgo-search' no está instalada. Instálala con: pip install -U duckduckgo-search"
    except Exception as e:
        return f"Error en web_search_full: {e}"


def _clean_html_to_text(html: str) -> str:
    """Convierte HTML a texto limpio y estructurado."""
    text = html

    # 1. Eliminar scripts, styles, nav, footer, header, aside (ruido)
    for tag in ["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]:
        text = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>", "", text,
            flags=re.DOTALL | re.IGNORECASE,
        )

    # 2. Eliminar comentarios HTML
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    # 3. Convertir headers a formato legible
    for i in range(1, 7):
        text = re.sub(
            rf"<h{i}[^>]*>(.*?)</h{i}>",
            rf"\n\n{'#' * i} \1\n",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

    # 4. Convertir párrafos y divs a saltos de línea
    text = re.sub(r"<br[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|tr|blockquote)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)

    # 5. Eliminar todas las tags HTML restantes
    text = re.sub(r"<[^>]+>", "", text)

    # 6. Decodificar entidades HTML
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&quot;", '"').replace("&#39;", "'")
    text = text.replace("&mdash;", "—").replace("&ndash;", "–")
    text = text.replace("&laquo;", "«").replace("&raquo;", "»")

    # 7. Colapsar whitespace excesivo
    text = re.sub(r"\n\s*\n\s*\n", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n ", "\n", text)

    # 8. Eliminar líneas muy cortas al principio (menús, breadcrumbs)
    lines = text.strip().split("\n")
    content_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if len(stripped) > 60 or stripped.startswith("#"):
            content_start = max(0, i - 1)
            break
    lines = lines[content_start:]

    return "\n".join(lines).strip()


def _fetch_with_playwright(url: str, timeout_ms: int = 20000) -> Optional[str]:
    """
    Usa Playwright (si está instalado) para renderizar una página con JavaScript.
    Intenta conectarse a un Chrome local abierto con remote debugging (puerto 9222),
    si no puede, levanta una instancia headless.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as p:
            browser = None
            cdp_url = "http://localhost:9222"
            try:
                # Intentar conectar al Chrome del usuario
                browser = p.chromium.connect_over_cdp(cdp_url)
                # Usar el contexto por defecto para aprovechar cookies/sesión
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
            except Exception as cdp_err:
                # Fallback a headless normal
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "Chrome/120.0.0.0 Safari/537.36",
                )

            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Esperar un poco para que SPAs carguen contenido dinámico
            page.wait_for_timeout(2000)
            html = page.content()
            page.close()
            
            if browser and not browser.contexts: # Si fue headless
                browser.close()
                
            return html
    except Exception as e:
        print(f"Playwright error: {e}")
        return None


def web_read_page(url: str, max_chars: int = 8000, force_browser: bool = False) -> str:
    """
    Lee una página web y devuelve su contenido como texto limpio y estructurado.
    Ideal para leer artículos, documentación, blogs, noticias, etc.

    Primero intenta con requests (rápido). Si el contenido es escaso o vacío
    (típico de webs SPA con JavaScript), automáticamente reintenta con Playwright
    (navegador real) si está instalado.

    Úsala después de web_search_full para profundizar en un resultado.
    También úsala cuando el usuario diga "lee esta página", "qué dice esta URL", etc.

    Args:
        url: URL de la página a leer.
        max_chars: Máximo de caracteres a devolver (default 8000 para no saturar contexto).
        force_browser: Si True, usa Playwright directamente sin intentar requests primero.
    """
    try:
        if not url or not url.strip():
            return "Error: URL vacía."

        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url

        html = None
        used_browser = False

        # ── Paso 1: Intentar con requests (rápido) ──
        if not force_browser:
            try:
                import requests
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                }
                response = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
                response.raise_for_status()
                html = response.text
            except ImportError:
                pass
            except Exception:
                html = None

        # ── Paso 2: Evaluar si el contenido es suficiente ──
        text = ""
        title = ""
        if html:
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            if title_match:
                title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
            text = _clean_html_to_text(html)

        # Si el texto extraído es muy corto, probablemente es una SPA → usar Playwright
        needs_browser = force_browser or (not text.strip()) or (len(text.strip()) < 200)

        # ── Paso 3: Fallback a Playwright si el contenido es insuficiente ──
        if needs_browser:
            pw_html = _fetch_with_playwright(url)
            if pw_html:
                used_browser = True
                html = pw_html
                title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
                if title_match:
                    title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
                text = _clean_html_to_text(html)

        # Truncar al máximo
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[... contenido truncado ...]"

        if not text.strip():
            return json.dumps({
                "status": "ok",
                "url": url,
                "title": title,
                "text": "",
                "used_browser": used_browser,
                "message": "No se pudo extraer texto útil de la página.",
            }, ensure_ascii=False)

        return json.dumps({
            "status": "ok",
            "url": url,
            "title": title,
            "chars": len(text),
            "used_browser": used_browser,
            "text": text,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en web_read_page: {e}"


# ---------------------------------------------------------------------------
# Wikipedia — API pública (gratis, sin key)



def wikipedia_search(query: str, lang: str = "es", sentences: int = 5) -> str:
    """
    Busca un artículo en Wikipedia y devuelve un resumen.

    Args:
        query: Término de búsqueda.
        lang: Código de idioma Wikipedia (es, en, fr, de, etc.).
        sentences: Número de oraciones del extracto.
    """
    try:
        if not query or not query.strip():
            return "Error: query vacía."

        # Primero buscamos el título correcto
        search_url = (
            f"https://{lang}.wikipedia.org/w/api.php?"
            f"action=query&list=search&srsearch={quote_plus(query)}"
            f"&srnamespace=0&srlimit=5&format=json"
        )
        status, body = _http_get(search_url, timeout=10)
        if status != 200:
            return f"Error: búsqueda Wikipedia falló (status={status})."

        search_data = json.loads(body)
        results = search_data.get("query", {}).get("search", [])
        if not results:
            return f"Sin resultados en Wikipedia ({lang}) para '{query}'."

        # Obtener el extracto del primer resultado
        title = results[0].get("title", "")
        extract_url = (
            f"https://{lang}.wikipedia.org/w/api.php?"
            f"action=query&titles={quote_plus(title)}"
            f"&prop=extracts&exintro=1&explaintext=1"
            f"&exsentences={sentences}&format=json"
        )
        status2, body2 = _http_get(extract_url, timeout=10)
        if status2 != 200:
            return f"Error: extracción Wikipedia falló (status={status2})."

        pages = json.loads(body2).get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            extract = page.get("extract", "").strip()
            if extract:
                wiki_url = f"https://{lang}.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}"
                # Otros resultados posibles
                other_titles = [r.get("title") for r in results[1:4] if r.get("title") != title]
                result = {
                    "title": title,
                    "extract": extract,
                    "url": wiki_url,
                    "language": lang,
                    "other_results": other_titles,
                }
                return json.dumps(result, ensure_ascii=False)

        return f"No se encontró extracto para '{title}' en Wikipedia ({lang})."
    except Exception as e:
        return f"Error en wikipedia_search: {e}"


# ---------------------------------------------------------------------------
# Traducción — MyMemory API (gratis, sin key, 1000 palabras/día)
# ---------------------------------------------------------------------------

def translate_text(
    text: str,
    from_lang: str = "auto",
    to_lang: str = "es",
) -> str:
    """
    Traduce texto entre idiomas usando MyMemory API (gratis).

    Args:
        text: Texto a traducir.
        from_lang: Idioma origen (ej: "en", "fr", "de"). "auto" para detección automática.
        to_lang: Idioma destino (ej: "es", "en", "fr").
    """
    try:
        if not text or not text.strip():
            return "Error: texto vacío."

        # Si el texto es muy largo, truncar
        text_to_translate = text[:500]

        src = from_lang if from_lang != "auto" else "autodetect"
        langpair = f"{src}|{to_lang}"
        url = f"https://api.mymemory.translated.net/get?q={quote_plus(text_to_translate)}&langpair={langpair}"

        status, body = _http_get(url, timeout=15)
        if status != 200:
            return f"Error: traducción falló (status={status})."

        data = json.loads(body)
        response_data = data.get("responseData", {})
        translated = response_data.get("translatedText", "")
        match_quality = response_data.get("match")

        if not translated:
            return "Error: no se pudo traducir el texto."

        # Alternativas
        matches = data.get("matches", [])
        alternatives = []
        for m in matches[:3]:
            seg = m.get("segment", "").strip()
            tran = m.get("translation", "").strip()
            quality = m.get("quality", "")
            if tran and tran != translated:
                alternatives.append({
                    "translation": tran,
                    "quality": quality,
                })

        result = {
            "original": text_to_translate,
            "translated": translated,
            "from": from_lang,
            "to": to_lang,
            "match_quality": match_quality,
            "alternatives": alternatives[:2],
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error en translate_text: {e}"


# ---------------------------------------------------------------------------
# IP / Ubicación — ipinfo.io (JSON) o IPinfo Lite con AARIS_IPINFO_TOKEN
# ---------------------------------------------------------------------------

def get_ip_info(ip: str = "") -> str:
    """
    Información de una IP o de la IP pública actual.

    Con ``AARIS_IPINFO_TOKEN`` (o ``IPINFO_TOKEN``) se usa primero la API **Lite**
    (ASN, país, continente, etc.). Si falla, se intenta el JSON clásico con el mismo token.
    Sin token, ``https://ipinfo.io/json`` (límites más bajos).
    """
    try:
        token = _ipinfo_token()
        target = ip.strip() if ip.strip() else ""

        if token:
            lite_url = (
                f"https://api.ipinfo.io/lite/{quote_plus(target)}?token={quote_plus(token)}"
                if target
                else f"https://api.ipinfo.io/lite?token={quote_plus(token)}"
            )
            status, body = _http_get(lite_url, timeout=10)
            if status == 200 and body.strip().startswith("{"):
                data = json.loads(body)
                result = {
                    "source": "ipinfo.io/lite",
                    "ip": data.get("ip"),
                    "asn": data.get("asn"),
                    "as_name": data.get("as_name"),
                    "as_domain": data.get("as_domain"),
                    "country_code": data.get("country_code"),
                    "country": data.get("country"),
                    "continent_code": data.get("continent_code"),
                    "continent": data.get("continent"),
                    "city": data.get("city"),
                    "region": data.get("region"),
                    "location": data.get("loc"),
                    "organization": data.get("org"),
                    "timezone": data.get("timezone"),
                    "postal": data.get("postal"),
                }
                return json.dumps(result, ensure_ascii=False)
            if status in (401, 403):
                return "Error: token IPinfo inválido o sin permiso (401/403). Revisa AARIS_IPINFO_TOKEN."

            base = f"https://ipinfo.io/{quote_plus(target)}/json" if target else "https://ipinfo.io/json"
            classic_url = f"{base}?token={quote_plus(token)}"
            status, body = _http_get(classic_url, timeout=10)
            if status == 200:
                data = json.loads(body)
                result = {
                    "source": "ipinfo.io",
                    "ip": data.get("ip"),
                    "city": data.get("city"),
                    "region": data.get("region"),
                    "country": data.get("country"),
                    "location": data.get("loc"),
                    "organization": data.get("org"),
                    "timezone": data.get("timezone"),
                    "postal": data.get("postal"),
                }
                return json.dumps(result, ensure_ascii=False)
            return f"Error: consulta IP falló (lite y json, status={status})."

        url = f"https://ipinfo.io/{quote_plus(target)}/json" if target else "https://ipinfo.io/json"
        status, body = _http_get(url, timeout=10)
        if status != 200:
            return f"Error: consulta IP falló (status={status})."

        data = json.loads(body)
        result = {
            "source": "ipinfo.io",
            "ip": data.get("ip"),
            "city": data.get("city"),
            "region": data.get("region"),
            "country": data.get("country"),
            "location": data.get("loc"),
            "organization": data.get("org"),
            "timezone": data.get("timezone"),
            "postal": data.get("postal"),
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error en get_ip_info: {e}"


# ---------------------------------------------------------------------------
# Criptomonedas — CoinGecko (gratis, sin key)
# ---------------------------------------------------------------------------

def get_crypto_price(
    coin: str = "bitcoin",
    currency: str = "eur",
) -> str:
    """
    Consulta el precio actual de una criptomoneda usando CoinGecko.

    Args:
        coin: Nombre/ID de la cripto (bitcoin, ethereum, solana, cardano, etc.).
        currency: Moneda fiat para el precio (eur, usd, gbp, etc.).
    """
    try:
        coin_id = coin.strip().lower()
        curr = currency.strip().lower()

        # Mapeo de nombres comunes a IDs de CoinGecko
        aliases = {
            "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
            "ada": "cardano", "dot": "polkadot", "doge": "dogecoin",
            "xrp": "ripple", "ltc": "litecoin", "bnb": "binancecoin",
            "matic": "matic-network", "avax": "avalanche-2",
            "link": "chainlink", "atom": "cosmos", "near": "near",
        }
        coin_id = aliases.get(coin_id, coin_id)

        url = (
            f"https://api.coingecko.com/api/v3/simple/price?"
            f"ids={coin_id}&vs_currencies={curr}"
            f"&include_24hr_change=true&include_market_cap=true"
            f"&include_24hr_vol=true"
        )
        status, body = _http_get(url, timeout=10)
        if status != 200:
            return f"Error: consulta CoinGecko falló (status={status})."

        data = json.loads(body)
        if coin_id not in data:
            return f"Error: no se encontró '{coin}' en CoinGecko. Usa el nombre completo (ej: bitcoin, ethereum)."

        prices = data[coin_id]
        result = {
            "coin": coin_id,
            "currency": curr,
            "price": prices.get(curr),
            "change_24h_percent": prices.get(f"{curr}_24h_change"),
            "market_cap": prices.get(f"{curr}_market_cap"),
            "volume_24h": prices.get(f"{curr}_24h_vol"),
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error en get_crypto_price: {e}"


# ---------------------------------------------------------------------------
# Fecha/Hora mundial
# ---------------------------------------------------------------------------

_TIMEZONE_OFFSETS: dict[str, float] = {
    "madrid": 1, "españa": 1, "spain": 1, "cet": 1, "cest": 2,
    "london": 0, "londres": 0, "uk": 0, "gmt": 0, "utc": 0,
    "new york": -5, "nueva york": -5, "est": -5, "edt": -4, "us east": -5,
    "los angeles": -8, "pst": -8, "pdt": -7, "us west": -8,
    "chicago": -6, "cst": -6, "cdt": -5,
    "tokyo": 9, "tokio": 9, "japan": 9, "japón": 9, "jst": 9,
    "beijing": 8, "pekín": 8, "pekin": 8, "china": 8, "shanghai": 8,
    "sydney": 10, "australia": 10, "aest": 10,
    "mumbai": 5.5, "india": 5.5, "ist": 5.5,
    "dubai": 4, "gst": 4,
    "moscow": 3, "moscú": 3, "moscu": 3, "msk": 3,
    "berlin": 1, "paris": 1, "rome": 1, "roma": 1,
    "são paulo": -3, "sao paulo": -3, "brasil": -3, "brazil": -3, "brt": -3,
    "mexico": -6, "méxico": -6, "ciudad de mexico": -6, "cdmx": -6,
    "bogota": -5, "bogotá": -5, "colombia": -5,
    "lima": -5, "perú": -5, "peru": -5,
    "buenos aires": -3, "argentina": -3,
    "santiago": -4, "chile": -4,
    "seoul": 9, "seúl": 9, "korea": 9, "corea": 9,
    "bangkok": 7, "thailand": 7, "ict": 7,
    "cairo": 2, "egypt": 2, "egipto": 2, "eet": 2,
    "johannesburg": 2, "south africa": 2, "sast": 2,
    "honolulu": -10, "hawaii": -10, "hst": -10,
    "anchorage": -9, "alaska": -9, "akst": -9,
}


def get_datetime_info(location: str = "") -> str:
    """
    Devuelve la fecha y hora actual, opcionalmente para una zona horaria/ciudad.

    Args:
        location: Ciudad o zona horaria (ej: "Tokyo", "New York", "UTC", "Madrid").
                  Si vacío, devuelve la hora local del sistema.
    """
    try:
        now_utc = datetime.now(tz=timezone.utc)
        now_local = datetime.now()

        if not location.strip():
            result = {
                "local_time": now_local.strftime("%Y-%m-%d %H:%M:%S"),
                "utc_time": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "day_of_week": now_local.strftime("%A"),
                "timezone": str(now_local.astimezone().tzinfo),
            }
            return json.dumps(result, ensure_ascii=False)

        loc_lower = location.strip().lower()
        offset = _TIMEZONE_OFFSETS.get(loc_lower)

        if offset is None:
            # Búsqueda parcial
            for key, val in _TIMEZONE_OFFSETS.items():
                if loc_lower in key or key in loc_lower:
                    offset = val
                    break

        if offset is None:
            available = sorted(set(_TIMEZONE_OFFSETS.keys()))
            return (
                f"Error: zona horaria no reconocida para '{location}'. "
                f"Algunas disponibles: {', '.join(available[:20])}"
            )

        # Calcular hora en esa zona
        hours = int(offset)
        minutes = int((offset - hours) * 60)
        tz_target = timezone(timedelta(hours=hours, minutes=minutes))
        now_target = now_utc.astimezone(tz_target)

        result = {
            "location": location,
            "time": now_target.strftime("%Y-%m-%d %H:%M:%S"),
            "utc_offset": f"UTC{'+' if offset >= 0 else ''}{offset}",
            "day_of_week": now_target.strftime("%A"),
            "local_time_for_reference": now_local.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error en get_datetime_info: {e}"
def extract_info_from_url(url: str, query: str) -> str:
    """
    Lee una página web completa y utiliza la IA local (Ollama) para extraer SOLO
    la información relevante según la consulta (query).
    
    Útil para resumir artículos largos o buscar datos específicos en la web
    sin saturar la memoria (contexto) principal del agente.
    """
    try:
        from ollama import chat
    except ImportError:
        return "Error: la librería `ollama` no está instalada. No se puede realizar extracción inteligente."
        
    # Leer la página
    text = web_read_page(url, max_chars=40000)
    if not text or text.startswith("Error"):
        return f"Error al leer la página: {text}"
        
    # Limitar a ~30k chars para que quepa en el contexto de Ollama
    text_slice = text[:30000]
    
    system_prompt = (
        "Eres un analizador de información web experto y preciso. Tu tarea es "
        "leer el siguiente texto de una página web y responder a la consulta "
        "del usuario extrayendo SOLO la información relevante. Escribe un resumen "
        "coherente. Si la información solicitada no se encuentra en el texto, "
        "indícalo claramente y no inventes datos."
    )
    
    prompt = f"Consulta a responder: {query}\\n\\n--- TEXTO DE LA WEB ---\\n{text_slice}\\n--- FIN DEL TEXTO ---"
    
    model = os.environ.get("AARIS_MODEL", "qwen2.5:14b")
    
    try:
        response = chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            options={"temperature": 0.1, "num_ctx": 16000}
        )
        return json.dumps({
            "url": url,
            "query": query,
            "extracted_info": response.get("message", {}).get("content", "Sin respuesta.")
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error al usar el LLM ({model}) para extraer info: {e}"
