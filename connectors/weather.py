"""Optional weather and AQI summary for the daily briefing."""

from __future__ import annotations

from typing import Any

import httpx


def get_weather_summary(city: str, enabled: bool = True) -> str:
    """Return a compact weather/AQI summary when enabled and available.

    This connector is intentionally silent if the feature is disabled or the request fails.
    """
    if not enabled or not city or not city.strip():
        return ""

    query = city.strip()
    try:
        geo = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 1, "language": "en", "format": "json"},
            timeout=8.0,
        )
        geo.raise_for_status()
        payload = geo.json()
        results = payload.get("results") or []
        if not results:
            return ""
        place = results[0]
        latitude = place.get("latitude")
        longitude = place.get("longitude")
        if latitude is None or longitude is None:
            return ""

        forecast = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code",
                "hourly": "apparent_temperature",
                "timezone": "auto",
            },
            timeout=8.0,
        )
        forecast.raise_for_status()
        current = forecast.json().get("current") or {}
        temperature = current.get("temperature_2m")
        if temperature is None:
            return ""

        summary = f"Weather: {temperature}°C in {query}."
        return summary
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return ""
