"""
JARVIS APIs Module — Integraciones con APIs externas gratuitas (sin API keys).

Provee herramientas para consultar información del mundo exterior:
- Clima (wttr.in)
- Noticias (RSS feeds)
- Búsqueda web (DuckDuckGo)
- Wikipedia
- Traducción (MyMemory)
- IP/Ubicación (ipinfo.io)
- Criptomonedas (CoinGecko)
- Fecha/hora mundial
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from urllib.parse import quote_plus


def _http_get(url: str, timeout: int = 10, headers: Optional[dict] = None) -> tuple[int, str]:
    """
    Realiza una petición HTTP GET. Retorna (status_code, body).
    Usa requests si está disponible, sino urllib como fallback.
    """
    try:
        import requests
        h = headers or {}
        h.setdefault("User-Agent", "JARVIS-Assistant/1.0")
        resp = requests.get(url, timeout=timeout, headers=h)
        return resp.status_code, resp.text
    except ImportError:
        # Fallback a urllib
        import urllib.request
        import urllib.error
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "JARVIS-Assistant/1.0")
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


# ---------------------------------------------------------------------------
# Clima — wttr.in (gratis, sin key)
# ---------------------------------------------------------------------------

def get_weather(location: str = "", format: str = "full", lang: str = "es") -> str:
    """
    Consulta el clima actual y pronóstico para una ubicación.

    Args:
        location: Ciudad o ubicación (ej: "Madrid", "New York", "Tokyo").
                  Si vacío, usa la ubicación detectada por IP.
        format: "full" (detallado), "short" (una línea), "json" (datos crudos).
        lang: Código de idioma para la respuesta (ej: "es", "en", "fr").
    """
    try:
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


def get_news(
    category: str = "general_es",
    max_items: int = 8,
    custom_feed_url: Optional[str] = None,
) -> str:
    """
    Obtiene noticias de feeds RSS.

    Args:
        category: Categoría/feed predefinido. Opciones:
                  "general_es" (El País), "tech_es" (El País Tech),
                  "bbc_world", "bbc_tech", "reuters", "hackernews".
        max_items: Número máximo de noticias a devolver.
        custom_feed_url: URL RSS personalizada (ignora category).
    """
    try:
        if custom_feed_url:
            url = custom_feed_url
        else:
            url = _RSS_FEEDS.get(category.strip().lower())
            if not url:
                available = ", ".join(sorted(_RSS_FEEDS.keys()))
                return f"Error: categoría '{category}' no existe. Disponibles: {available}"

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
        }
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"Error en get_news: {e}"


# ---------------------------------------------------------------------------
# Búsqueda web — DuckDuckGo HTML (gratis, sin key)
# ---------------------------------------------------------------------------

def web_search(query: str, max_results: int = 8) -> str:
    """
    Busca en la web usando DuckDuckGo y devuelve resultados.

    Args:
        query: Texto a buscar.
        max_results: Número máximo de resultados.
    """
    try:
        if not query or not query.strip():
            return "Error: query vacía."

        # DuckDuckGo Instant Answer API
        url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1"
        status, body = _http_get(url, timeout=15)

        if status != 200:
            return f"Error: búsqueda falló (status={status})."

        data = json.loads(body)
        results: list[dict[str, str]] = []

        # Abstract (respuesta directa)
        abstract = data.get("AbstractText", "").strip()
        abstract_url = data.get("AbstractURL", "")
        abstract_source = data.get("AbstractSource", "")
        if abstract:
            results.append({
                "type": "answer",
                "title": abstract_source or "Respuesta directa",
                "text": abstract,
                "url": abstract_url,
            })

        # Answer
        answer = data.get("Answer", "").strip()
        if answer:
            results.append({
                "type": "instant_answer",
                "title": "Respuesta instantánea",
                "text": answer,
                "url": "",
            })

        # Related topics
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict):
                text = topic.get("Text", "").strip()
                first_url = topic.get("FirstURL", "")
                if text:
                    results.append({
                        "type": "related",
                        "title": text[:120],
                        "text": text,
                        "url": first_url,
                    })
                # Sub-topics
                for sub in topic.get("Topics", []):
                    if isinstance(sub, dict):
                        sub_text = sub.get("Text", "").strip()
                        sub_url = sub.get("FirstURL", "")
                        if sub_text:
                            results.append({
                                "type": "related",
                                "title": sub_text[:120],
                                "text": sub_text,
                                "url": sub_url,
                            })

        results = results[:max_results]

        if not results:
            # Fallback: devolver el abstract si no hay resultados estructurados
            definition = data.get("Definition", "").strip()
            if definition:
                results.append({
                    "type": "definition",
                    "title": "Definición",
                    "text": definition,
                    "url": data.get("DefinitionURL", ""),
                })

        if not results:
            return f"Sin resultados relevantes para '{query}'. Intenta con otra búsqueda."

        return json.dumps({
            "query": query,
            "count": len(results),
            "results": results,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error en web_search: {e}"


# ---------------------------------------------------------------------------
# Wikipedia — API pública (gratis, sin key)
# ---------------------------------------------------------------------------

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
# IP / Ubicación — ipinfo.io (gratis, sin key, 50k req/mes)
# ---------------------------------------------------------------------------

def get_ip_info(ip: str = "") -> str:
    """
    Obtiene información sobre la IP pública actual o una IP específica.

    Args:
        ip: Dirección IP a consultar. Si vacío, usa la IP pública actual.
    """
    try:
        target = ip.strip() if ip.strip() else ""
        url = f"https://ipinfo.io/{target}/json" if target else "https://ipinfo.io/json"
        status, body = _http_get(url, timeout=10)
        if status != 200:
            return f"Error: consulta IP falló (status={status})."

        data = json.loads(body)
        result = {
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
