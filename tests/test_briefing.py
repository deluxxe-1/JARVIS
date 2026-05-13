"""Tests ligeros del briefing (mocks, sin red)."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@patch("apis.get_news")
@patch("apis.get_weather")
def test_daily_briefing_weather_and_news_json(mock_weather, mock_news):
    mock_weather.return_value = json.dumps(
        {
            "location": "Madrid",
            "temperature": 20,
            "temperature_c": 20,
            "description": "soleado",
            "humidity": 40,
        }
    )
    mock_news.return_value = json.dumps(
        {
            "news": [
                {"title": "Titular 1", "source": "Medio"},
                {"title": "Titular 2", "source": ""},
            ]
        }
    )

    from briefing import daily_briefing

    out = daily_briefing(city="Madrid", include_crypto=False, include_system=False)
    assert "Madrid" in out or "clima" in out.lower() or "Clima" in out
    assert "Titular" in out
