"""
Tests para JARVIS APIs Module.
Se mockean las llamadas HTTP para no depender de red.
"""

import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apis import (
    get_weather,
    get_news,
    web_search,
    wikipedia_search,
    translate_text,
    get_ip_info,
    get_crypto_price,
    get_datetime_info,
    _parse_rss_simple,
)


# ---------------------------------------------------------------------------
# Helper: mock _http_get
# ---------------------------------------------------------------------------

def _mock_http_get(status: int, body: str):
    """Crea un mock para _http_get que devuelve (status, body)."""
    return patch("apis._http_get", return_value=(status, body))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetWeather:
    def test_short_format(self):
        with _mock_http_get(200, "Madrid: ☀️ +22°C 40% →15km/h"):
            result = get_weather("Madrid", format="short")
            assert "Madrid" in result
            assert "22" in result

    def test_json_format(self):
        mock_data = {
            "current_condition": [{
                "temp_C": "22",
                "FeelsLikeC": "20",
                "humidity": "40",
                "windspeedKmph": "15",
                "winddir16Point": "N",
                "weatherDesc": [{"value": "Sunny"}],
                "visibility": "10",
                "uvIndex": "5",
                "pressure": "1015",
            }],
            "weather": [{
                "date": "2026-04-15",
                "maxtempC": "25",
                "mintempC": "12",
                "hourly": [{}, {}, {}, {}, {"weatherDesc": [{"value": "Clear"}]}],
            }],
        }
        with _mock_http_get(200, json.dumps(mock_data)):
            result = get_weather("Madrid", format="json", lang="en")
            data = json.loads(result)
            assert data["temperature_c"] == "22"
            assert data["location"] == "Madrid"

    def test_error_status(self):
        with _mock_http_get(500, "Server Error"):
            result = get_weather("UnknownPlace", format="short")
            assert "Error" in result

    def test_empty_location(self):
        with _mock_http_get(200, "Auto: ☀️ +20°C"):
            result = get_weather("", format="short")
            assert "20" in result


class TestGetNews:
    def test_parse_rss(self):
        xml = """
        <rss><channel>
        <item>
            <title>Breaking News</title>
            <link>https://example.com/news1</link>
            <description>Something happened</description>
            <pubDate>Mon, 15 Apr 2026 10:00:00 GMT</pubDate>
        </item>
        <item>
            <title>Tech Update</title>
            <link>https://example.com/news2</link>
            <description>New gadget released</description>
        </item>
        </channel></rss>
        """
        items = _parse_rss_simple(xml, max_items=10)
        assert len(items) == 2
        assert items[0]["title"] == "Breaking News"
        assert items[1]["title"] == "Tech Update"

    def test_get_news_success(self):
        xml = "<rss><channel><item><title>Headline</title><link>http://x.com</link><description>Desc</description></item></channel></rss>"
        with _mock_http_get(200, xml):
            result = get_news("general_es", max_items=5)
            data = json.loads(result)
            assert data["count"] == 1
            assert data["news"][0]["title"] == "Headline"

    def test_get_news_invalid_category(self):
        result = get_news("nonexistent_category")
        assert "Error" in result
        assert "Disponibles" in result

    def test_get_news_error(self):
        with _mock_http_get(500, ""):
            result = get_news("bbc_world")
            assert "Error" in result


class TestWebSearch:
    def test_success(self):
        mock_data = {
            "AbstractText": "Python is a programming language.",
            "AbstractURL": "https://en.wikipedia.org/wiki/Python",
            "AbstractSource": "Wikipedia",
            "Answer": "",
            "RelatedTopics": [
                {"Text": "Python tutorial", "FirstURL": "https://example.com/python"},
            ],
        }
        with _mock_http_get(200, json.dumps(mock_data)):
            result = web_search("Python programming")
            data = json.loads(result)
            assert data["count"] >= 1
            assert any("Python" in r["text"] for r in data["results"])

    def test_empty_query(self):
        result = web_search("")
        assert "Error" in result

    def test_no_results(self):
        mock_data = {
            "AbstractText": "",
            "Answer": "",
            "RelatedTopics": [],
            "Definition": "",
        }
        with _mock_http_get(200, json.dumps(mock_data)):
            result = web_search("xyznonexistent12345")
            assert "Sin resultados" in result


class TestWikipediaSearch:
    def test_success(self):
        search_response = json.dumps({
            "query": {"search": [{"title": "Fotosíntesis"}]}
        })
        extract_response = json.dumps({
            "query": {"pages": {"123": {
                "title": "Fotosíntesis",
                "extract": "La fotosíntesis es el proceso por el cual las plantas convierten luz solar en energía."
            }}}
        })

        call_count = [0]
        def mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (200, search_response)
            return (200, extract_response)

        with patch("apis._http_get", side_effect=mock_get):
            result = wikipedia_search("fotosíntesis")
            data = json.loads(result)
            assert data["title"] == "Fotosíntesis"
            assert "fotosíntesis" in data["extract"].lower()

    def test_empty_query(self):
        result = wikipedia_search("")
        assert "Error" in result

    def test_no_results(self):
        mock = json.dumps({"query": {"search": []}})
        with _mock_http_get(200, mock):
            result = wikipedia_search("xyzabc123nonexistent")
            assert "Sin resultados" in result


class TestTranslateText:
    def test_success(self):
        mock_data = {
            "responseData": {
                "translatedText": "Hola mundo",
                "match": 1.0,
            },
            "matches": [],
        }
        with _mock_http_get(200, json.dumps(mock_data)):
            result = translate_text("Hello world", from_lang="en", to_lang="es")
            data = json.loads(result)
            assert data["translated"] == "Hola mundo"
            assert data["to"] == "es"

    def test_empty_text(self):
        result = translate_text("")
        assert "Error" in result


class TestGetIpInfo:
    def test_success(self):
        mock_data = {
            "ip": "8.8.8.8",
            "city": "Mountain View",
            "region": "California",
            "country": "US",
            "loc": "37.3860,-122.0838",
            "org": "AS15169 Google LLC",
            "timezone": "America/Los_Angeles",
            "postal": "94035",
        }
        with _mock_http_get(200, json.dumps(mock_data)):
            result = get_ip_info()
            data = json.loads(result)
            assert data["ip"] == "8.8.8.8"
            assert data["city"] == "Mountain View"

    def test_specific_ip(self):
        mock_data = {"ip": "1.1.1.1", "city": "Sydney", "country": "AU"}
        with _mock_http_get(200, json.dumps(mock_data)):
            result = get_ip_info("1.1.1.1")
            data = json.loads(result)
            assert data["ip"] == "1.1.1.1"


class TestGetCryptoPrice:
    def test_bitcoin(self):
        mock_data = {
            "bitcoin": {
                "eur": 45000,
                "eur_24h_change": 2.5,
                "eur_market_cap": 900000000000,
                "eur_24h_vol": 30000000000,
            }
        }
        with _mock_http_get(200, json.dumps(mock_data)):
            result = get_crypto_price("bitcoin", "eur")
            data = json.loads(result)
            assert data["price"] == 45000
            assert data["coin"] == "bitcoin"

    def test_alias(self):
        mock_data = {"ethereum": {"usd": 3000}}
        with _mock_http_get(200, json.dumps(mock_data)):
            result = get_crypto_price("eth", "usd")
            data = json.loads(result)
            assert data["coin"] == "ethereum"

    def test_not_found(self):
        with _mock_http_get(200, json.dumps({})):
            result = get_crypto_price("nonexistentcoin")
            assert "Error" in result


class TestGetDatetimeInfo:
    def test_local(self):
        result = get_datetime_info()
        data = json.loads(result)
        assert "local_time" in data
        assert "utc_time" in data

    def test_city(self):
        result = get_datetime_info("Tokyo")
        data = json.loads(result)
        assert data["location"] == "Tokyo"
        assert "UTC+9" in data["utc_offset"]

    def test_unknown_timezone(self):
        result = get_datetime_info("Planet Mars")
        assert "Error" in result

    def test_partial_match(self):
        result = get_datetime_info("york")
        data = json.loads(result)
        assert "time" in data
