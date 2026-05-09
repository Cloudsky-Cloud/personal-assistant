import json
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_WTTR_URL = "https://wttr.in/{}?format=j1"


def get_weather(city: str, country: str = "") -> dict | None:
    """Fetch current conditions and today's forecast from wttr.in.

    Returns a flat dict with condition, temp_c, feels_like_c, humidity,
    wind_kmph, max_c, min_c — or None if the request fails.
    """
    location = f"{city},{country}" if country else city
    url = _WTTR_URL.format(urllib.parse.quote(location))
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        current = data["current_condition"][0]
        today = data["weather"][0]
        return {
            "condition": current["weatherDesc"][0]["value"],
            "temp_c": int(current["temp_C"]),
            "feels_like_c": int(current["FeelsLikeC"]),
            "humidity": int(current["humidity"]),
            "wind_kmph": int(current["windspeedKmph"]),
            "max_c": int(today["maxtempC"]),
            "min_c": int(today["mintempC"]),
        }
    except Exception as exc:
        logger.warning("Weather fetch failed for %r: %s", location, exc)
        return None
