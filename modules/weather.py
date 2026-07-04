from __future__ import annotations

from datetime import date, datetime, timedelta
import requests
import streamlit as st

WEATHER_CODES = {
    0: "快晴 ☀️", 1: "晴れ 🌤️", 2: "一部くもり 🌥️", 3: "くもり ☁️",
    45: "霧 🌫️", 48: "霧氷 🌫️", 51: "弱い霧雨 🌦️", 53: "霧雨 🌦️", 55: "強い霧雨 🌧️",
    61: "弱い雨 🌦️", 63: "雨 🌧️", 65: "強い雨 🌧️", 71: "弱い雪 🌨️", 73: "雪 🌨️", 75: "強い雪 ❄️",
    80: "弱いにわか雨 🌦️", 81: "にわか雨 🌧️", 82: "強いにわか雨 ⛈️", 95: "雷雨 ⛈️",
}

@st.cache_data(ttl=60*60*24, show_spinner=False)
def geocode(place: str):
    if not place:
        return None
    try:
        r = requests.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": place, "count": 1, "language": "ja", "format": "json"}, timeout=8)
        data = r.json()
        results = data.get("results") or []
        if not results:
            return None
        x = results[0]
        return {"lat": x["latitude"], "lon": x["longitude"], "name": x.get("name", place), "country": x.get("country", "")}
    except Exception:
        return None

@st.cache_data(ttl=60*30, show_spinner=False)
def fetch_forecast(lat: float, lon: float, target_date: str):
    r = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon, "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max", "timezone": "Asia/Tokyo",
        "start_date": target_date, "end_date": target_date,
    }, timeout=10)
    d = r.json().get("daily", {})
    if not d.get("time"):
        return None
    return {
        "kind": "予報", "date": target_date,
        "weather": WEATHER_CODES.get(d["weather_code"][0], str(d["weather_code"][0])),
        "max": d["temperature_2m_max"][0], "min": d["temperature_2m_min"][0],
        "pop": d.get("precipitation_probability_max", [None])[0]
    }

@st.cache_data(ttl=60*60*24, show_spinner=False)
def fetch_archive(lat: float, lon: float, target_date: str):
    r = requests.get("https://archive-api.open-meteo.com/v1/archive", params={
        "latitude": lat, "longitude": lon, "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum", "timezone": "Asia/Tokyo",
        "start_date": target_date, "end_date": target_date,
    }, timeout=10)
    d = r.json().get("daily", {})
    if not d.get("time"):
        return None
    return {
        "kind": "過去実績", "date": target_date,
        "weather": WEATHER_CODES.get(d["weather_code"][0], str(d["weather_code"][0])),
        "max": d["temperature_2m_max"][0], "min": d["temperature_2m_min"][0],
        "rain": d.get("precipitation_sum", [None])[0]
    }


def get_weather_for(place: str, target_date: str):
    loc = geocode(place)
    if not loc:
        return None, "場所が見つかりませんでした。"
    try:
        d = datetime.fromisoformat(target_date).date()
    except Exception:
        return None, "日付が正しくありません。"
    today = date.today()
    try:
        if d < today:
            return fetch_archive(loc["lat"], loc["lon"], target_date), None
        if d <= today + timedelta(days=16):
            return fetch_forecast(loc["lat"], loc["lon"], target_date), None
        samples = []
        for y in range(today.year - 5, today.year):
            try:
                past = date(y, d.month, d.day).isoformat()
                w = fetch_archive(loc["lat"], loc["lon"], past)
                if w:
                    samples.append(w)
            except ValueError:
                pass
        if not samples:
            return None, "参考天気を取得できませんでした。"
        avg_max = sum(x["max"] for x in samples if x.get("max") is not None) / len(samples)
        avg_min = sum(x["min"] for x in samples if x.get("min") is not None) / len(samples)
        return {"kind": "参考値", "date": target_date, "weather": "過去5年の同日参考", "max": round(avg_max, 1), "min": round(avg_min, 1)}, None
    except Exception as e:
        return None, str(e)
