import json
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from datetime import datetime, date, timedelta
from urllib.parse import quote_plus

import requests
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


DATA_FILE = Path("trips.json")
SETTINGS_FILE = Path("app_settings.json")
PHOTO_DIR = Path("trip_photos")
PHOTO_DIR.mkdir(exist_ok=True)

CATEGORIES = ["交通", "食事", "観光", "ホテル", "買い物", "その他"]
DEFAULT_PACKING_ITEMS = [
    "財布",
    "スマホ",
    "充電器",
    "モバイルバッテリー",
    "着替え",
    "下着",
    "ハンカチ",
    "ティッシュ",
    "薬",
    "コンタクト・眼鏡",
    "化粧品",
    "チケット・予約確認",
]

WEATHER_CODES = {
    0: "快晴 ☀️",
    1: "晴れ 🌤️",
    2: "一部くもり ⛅",
    3: "くもり ☁️",
    45: "霧 🌫️",
    48: "霧氷 🌫️",
    51: "弱い霧雨 🌦️",
    53: "霧雨 🌦️",
    55: "強い霧雨 🌧️",
    61: "弱い雨 🌦️",
    63: "雨 🌧️",
    65: "強い雨 🌧️",
    71: "弱い雪 🌨️",
    73: "雪 🌨️",
    75: "強い雪 🌨️",
    80: "弱いにわか雨 🌦️",
    81: "にわか雨 🌧️",
    82: "強いにわか雨 ⛈️",
    95: "雷雨 ⛈️",
    96: "雷雨・ひょう ⛈️",
    99: "強い雷雨・ひょう ⛈️",
}


# =========================
# データ操作
# =========================

def load_trips():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []


def save_trips(trips):
    """旅行データを軽量なJSONで保存する。indentを付けないので trips.json が巨大化しにくい。"""
    DATA_FILE.write_text(
        json.dumps(trips, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def load_settings():
    default_settings = {
        "app_name": "TripList",
        "person1_name": "",
        "person2_name": "",
        "participants": [],
        "anniversary_name": "記念日",
        "anniversary_date": "",
        "use_anniversary": True,
    }
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            default_settings.update(saved)
        except Exception:
            pass
    return normalize_settings(default_settings)


def save_settings(settings):
    settings = normalize_settings(settings)
    SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def get_participants(settings):
    """参加者リストを取得する。古い person1_name / person2_name 形式も自動で移行する。"""
    participants = settings.get("participants", [])
    if not isinstance(participants, list):
        participants = []

    cleaned = [str(name).strip() for name in participants if str(name).strip()]

    # 旧バージョン用：person1_name / person2_name しかない場合も読み込む
    if not cleaned:
        for key in ["person1_name", "person2_name"]:
            name = str(settings.get(key, "")).strip()
            if name:
                cleaned.append(name)

    return cleaned


def set_participants(settings, participants):
    cleaned = [str(name).strip() for name in participants if str(name).strip()]
    settings["participants"] = cleaned

    # 古いコードや古いJSONとの互換性のために残しておく
    settings["person1_name"] = cleaned[0] if len(cleaned) >= 1 else ""
    settings["person2_name"] = cleaned[1] if len(cleaned) >= 2 else ""
    return settings


def normalize_settings(settings):
    set_participants(settings, get_participants(settings))
    return settings


def file_size_text(path):
    if not path.exists():
        return "0 B"
    size = path.stat().st_size
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def compact_data_files():
    """既存の trips.json / app_settings.json を軽量形式で保存し直す。"""
    trips = load_trips()
    save_trips(trips)
    settings = load_settings()
    save_settings(settings)


def parse_date_text(value, default=None):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return default or date.today()


def app_title(settings):
    app_name = settings.get("app_name", "TripList").strip() or "TripList"
    participants = get_participants(settings)

    if len(participants) == 1:
        return f"{participants[0]}の旅行計画"
    if len(participants) == 2:
        return f"{participants[0]}・{participants[1]}の旅行計画"
    if len(participants) >= 3:
        return f"{participants[0]}・{participants[1]}ほか{len(participants) - 2}人の旅行計画"
    return app_name


def settings_is_complete(settings):
    participants_ok = len(get_participants(settings)) >= 1
    if not participants_ok:
        return False
    if not settings.get("use_anniversary", True):
        return True
    return bool(settings.get("anniversary_date", "").strip())


def next_yearly_anniversary(base_date, today):
    next_date = date(today.year, base_date.month, base_date.day)
    if next_date < today:
        next_date = date(today.year + 1, base_date.month, base_date.day)
    return next_date


def anniversary_label(base_date, target_date):
    years = target_date.year - base_date.year
    if years <= 0:
        return "最初の記念日"
    return f"{years}周年"


def yen(value):
    try:
        return int(value)
    except Exception:
        return 0


def timestamp():
    return datetime.now().strftime("%Y%m%d%H%M%S%f")


def normalize_trip(trip):
    trip.setdefault("title", "無題の旅行")
    trip.setdefault("plans", [])
    trip.setdefault("hotels", [])
    trip.setdefault("others", [])
    trip.setdefault("packing_items", [])
    trip.setdefault("photos", [])
    return trip


def sort_key(row):
    day = row.get("年月日") or "9999-99-99"
    time_text = row.get("時間") or "99:99"
    return (day, time_text)


def build_table_rows(trip):
    rows = []
    total = 0
    category_totals = defaultdict(int)

    for item in trip.get("plans", []):
        amount = yen(item.get("amount", 0))
        category = item.get("category", "その他")
        total += amount
        category_totals[category] += amount
        rows.append({
            "種類": "予定",
            "年月日": item.get("date", ""),
            "時間": item.get("time", ""),
            "カテゴリ": category,
            "内容": item.get("content", ""),
            "場所": item.get("place", ""),
            "金額": amount,
        })

    for item in trip.get("hotels", []):
        amount = yen(item.get("amount", 0))
        category = "宿泊"
        total += amount
        category_totals[category] += amount
        rows.append({
            "種類": "宿泊",
            "年月日": item.get("date", ""),
            "時間": "",
            "カテゴリ": category,
            "内容": item.get("hotel", ""),
            "場所": item.get("place", item.get("hotel", "")),
            "金額": amount,
        })

    for item in trip.get("others", []):
        amount = yen(item.get("amount", 0))
        category = item.get("category", "その他")
        total += amount
        category_totals[category] += amount
        rows.append({
            "種類": "その他",
            "年月日": "",
            "時間": "",
            "カテゴリ": category,
            "内容": item.get("content", ""),
            "場所": item.get("place", ""),
            "金額": amount,
        })

    rows.sort(key=sort_key)
    return rows, total, dict(category_totals)


def icon_for_category(category):
    icons = {
        "交通": "🚄",
        "食事": "🍽️",
        "観光": "📍",
        "宿泊": "🏨",
        "ホテル": "🏨",
        "買い物": "🛍️",
        "その他": "✨",
    }
    return icons.get(category, "✨")


def delete_file(path_text):
    if path_text and Path(path_text).exists():
        Path(path_text).unlink()



# =========================
# 天気予報
# =========================

@st.cache_data(ttl=60 * 60)
def geocode_place(place):
    """場所名から緯度経度を取得する。Open-Meteoの無料ジオコーディングを使う。"""
    if not place:
        return None

    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": place,
        "count": 1,
        "language": "ja",
        "format": "json",
    }

    try:
        response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        if not results:
            return None
        result = results[0]
        return {
            "name": result.get("name", place),
            "country": result.get("country", ""),
            "admin1": result.get("admin1", ""),
            "latitude": result.get("latitude"),
            "longitude": result.get("longitude"),
        }
    except Exception:
        return None


@st.cache_data(ttl=60 * 60)
def fetch_daily_forecast(latitude, longitude):
    """今日から16日分の天気予報を取得する。"""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "Asia/Tokyo",
        "forecast_days": 16,
    }

    try:
        response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
        return response.json().get("daily", {})
    except Exception:
        return {}


@st.cache_data(ttl=60 * 60 * 24)
def fetch_daily_archive(latitude, longitude, start_date, end_date):
    """過去の天気実績を取得する。"""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "Asia/Tokyo",
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("daily", {})
    except Exception:
        return {}


def most_common(values):
    counts = defaultdict(int)
    for value in values:
        if value is not None:
            counts[value] += 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def safe_avg(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 1)


def weather_for(place, date_text):
    """場所と日付から天気を返す。

    - 今日から16日以内: 予報
    - 過去: 実績
    - 16日より先: 過去5年の同日の参考値
    """
    if not place or not date_text:
        return None

    try:
        target_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    except Exception:
        return None

    geo = geocode_place(place)
    if not geo:
        return {
            "status": "not_found",
            "message": "場所が見つかりませんでした。",
        }

    today = date.today()

    # 1. 近い未来は予報を表示
    if today <= target_date <= today + timedelta(days=15):
        daily = fetch_daily_forecast(geo["latitude"], geo["longitude"])
        dates = daily.get("time", [])
        if date_text not in dates:
            return {
                "status": "not_found",
                "message": "その日の天気予報が見つかりませんでした。",
            }

        idx = dates.index(date_text)
        code = daily.get("weather_code", [None])[idx]
        return {
            "status": "ok",
            "kind": "予報",
            "place_name": geo.get("name", place),
            "admin1": geo.get("admin1", ""),
            "weather": WEATHER_CODES.get(code, f"天気コード {code}"),
            "temp_max": daily.get("temperature_2m_max", [None])[idx],
            "temp_min": daily.get("temperature_2m_min", [None])[idx],
            "rain_prob": daily.get("precipitation_probability_max", [None])[idx],
            "precipitation": None,
        }

    # 2. 過去は実績を表示
    if target_date < today:
        daily = fetch_daily_archive(
            geo["latitude"],
            geo["longitude"],
            date_text,
            date_text,
        )
        dates = daily.get("time", [])
        if date_text not in dates:
            return {
                "status": "not_found",
                "message": "過去の天気実績が見つかりませんでした。",
            }

        idx = dates.index(date_text)
        code = daily.get("weather_code", [None])[idx]
        return {
            "status": "ok",
            "kind": "過去の実績",
            "place_name": geo.get("name", place),
            "admin1": geo.get("admin1", ""),
            "weather": WEATHER_CODES.get(code, f"天気コード {code}"),
            "temp_max": daily.get("temperature_2m_max", [None])[idx],
            "temp_min": daily.get("temperature_2m_min", [None])[idx],
            "rain_prob": None,
            "precipitation": daily.get("precipitation_sum", [None])[idx],
        }

    # 3. 遠い未来は過去5年の同日の参考値を表示
    sample_dates = []
    for year in range(today.year - 5, today.year):
        try:
            sample_dates.append(date(year, target_date.month, target_date.day))
        except ValueError:
            # 2/29などは存在しない年がある
            pass

    if not sample_dates:
        return {
            "status": "not_found",
            "message": "参考天気を作るための過去データがありませんでした。",
        }

    codes = []
    max_temps = []
    min_temps = []
    precipitations = []

    for sample_date in sample_dates:
        d = sample_date.isoformat()
        daily = fetch_daily_archive(geo["latitude"], geo["longitude"], d, d)
        dates = daily.get("time", [])
        if d not in dates:
            continue
        idx = dates.index(d)
        codes.append(daily.get("weather_code", [None])[idx])
        max_temps.append(daily.get("temperature_2m_max", [None])[idx])
        min_temps.append(daily.get("temperature_2m_min", [None])[idx])
        precipitations.append(daily.get("precipitation_sum", [None])[idx])

    if not max_temps and not min_temps:
        return {
            "status": "not_found",
            "message": "参考天気を作るための過去データが見つかりませんでした。",
        }

    code = most_common(codes)
    return {
        "status": "ok",
        "kind": "過去5年の同日参考",
        "place_name": geo.get("name", place),
        "admin1": geo.get("admin1", ""),
        "weather": WEATHER_CODES.get(code, f"天気コード {code}"),
        "temp_max": safe_avg(max_temps),
        "temp_min": safe_avg(min_temps),
        "rain_prob": None,
        "precipitation": safe_avg(precipitations),
    }


def format_weather_text(weather):
    if not weather:
        return ""
    if weather.get("status") != "ok":
        return weather.get("message", "")
    place = weather.get("place_name", "")
    area = weather.get("admin1", "")
    location = f"{area} {place}".strip()
    kind = weather.get("kind", "天気")

    if weather.get("rain_prob") is not None:
        rain_text = f"降水確率{weather.get('rain_prob')}%"
    elif weather.get("precipitation") is not None:
        rain_text = f"降水量{weather.get('precipitation')}mm"
    else:
        rain_text = "降水情報なし"

    return (
        f"{location}：{kind} / {weather.get('weather', '')} / "
        f"最高{weather.get('temp_max')}℃・最低{weather.get('temp_min')}℃ / "
        f"{rain_text}"
    )

# =========================
# PDF作成
# =========================

def make_pdf(trip, settings=None):
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "HeiseiKakuGo-W5"
    styles["Normal"].fontName = "HeiseiKakuGo-W5"

    table_rows, total, category_totals = build_table_rows(trip)

    if settings is None:
        settings = load_settings()

    story = []
    story.append(Paragraph(app_title(settings), styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"旅行タイトル：{trip.get('title', '')}", styles["Normal"]))
    story.append(Spacer(1, 12))

    rows = [["種類", "年月日", "時間", "カテゴリ", "内容", "場所", "金額"]]
    for item in table_rows:
        rows.append([
            item.get("種類", ""),
            item.get("年月日", ""),
            item.get("時間", ""),
            item.get("カテゴリ", ""),
            item.get("内容", ""),
            item.get("場所", ""),
            f"{yen(item.get('金額', 0)):,}円",
        ])

    table = Table(rows, colWidths=[42, 65, 42, 50, 170, 95, 60])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "HeiseiKakuGo-W5"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    story.append(table)
    story.append(Spacer(1, 16))
    story.append(Paragraph(f"合計金額：{total:,}円", styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("カテゴリ別費用", styles["Normal"]))

    category_rows = [["カテゴリ", "金額"]]
    for category, amount in sorted(category_totals.items()):
        category_rows.append([category, f"{amount:,}円"])

    category_table = Table(category_rows, colWidths=[160, 120])
    category_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "HeiseiKakuGo-W5"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(category_table)

    packing_items = trip.get("packing_items", [])
    if packing_items:
        story.append(Spacer(1, 12))
        story.append(Paragraph("持ち物チェックリスト", styles["Normal"]))
        packing_rows = [["チェック", "持ち物"]]
        for item in packing_items:
            mark = "✓" if item.get("checked", False) else "□"
            packing_rows.append([mark, item.get("name", "")])

        packing_table = Table(packing_rows, colWidths=[60, 260])
        packing_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "HeiseiKakuGo-W5"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(packing_table)

    doc.build(story)
    buffer.seek(0)
    return buffer


# =========================
# デザイン
# =========================

def apply_style():
    st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(135deg, #fff7f0 0%, #f7fbff 100%);
    }
    h1 {
        text-align: center;
        color: #7a4f3b;
        font-size: 42px !important;
        letter-spacing: 2px;
    }
    h2, h3 {
        color: #7a4f3b;
    }
    .stButton button {
        background: linear-gradient(90deg, #d8a48f, #a3b18a);
        color: white;
        border: none;
        border-radius: 999px;
        padding: 0.5em 1.4em;
        font-weight: bold;
    }
    .stButton button:hover {
        background: linear-gradient(90deg, #c98f78, #8fa176);
        color: white;
    }
    [data-testid="stMetric"] {
        background-color: white;
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 4px 14px rgba(0,0,0,0.08);
    }
    input, textarea {
        border-radius: 12px !important;
    }
    [data-testid="stDataFrame"] {
        border-radius: 16px;
        overflow: hidden;
    }
    .timeline-card {
        background: white;
        border-left: 5px solid #d8a48f;
        border-radius: 14px;
        padding: 12px 16px;
        margin: 10px 0;
        box-shadow: 0 4px 12px rgba(120,80,60,0.10);
    }
    .timeline-date {
        font-weight: bold;
        color: #7a4f3b;
        margin-top: 18px;
    }
    .sidebar-help {
        color: #8a6f60;
        font-size: 13px;
    }
    .weather-card {
        background: rgba(255,255,255,0.88);
        border-radius: 16px;
        padding: 12px 16px;
        margin: 8px 0;
        box-shadow: 0 4px 12px rgba(80, 100, 120, 0.10);
        border: 1px solid #e4eef8;
    }
    </style>
    """, unsafe_allow_html=True)


def show_header(settings):
    title = app_title(settings)
    st.markdown(f"""
    <h1>🌷 {title} 🌿</h1>
    <p style="text-align:center; color:#8a6f60;">
    旅行の予定・持ち物・写真・費用をまとめる旅のしおり
    </p>
    """, unsafe_allow_html=True)


def render_initial_setup(settings):
    if settings_is_complete(settings):
        return True

    st.markdown("""
    <h1>🌷 TripList 初期設定 🌿</h1>
    <p style="text-align:center; color:#8a6f60;">
    最初にアプリ名・参加者・記念日を登録してください。
    </p>
    """, unsafe_allow_html=True)

    current_participants = get_participants(settings)
    default_count = max(2, len(current_participants) or 2)

    with st.form("initial_setup_form"):
        app_name = st.text_input("アプリ名", value=settings.get("app_name", "TripList"))
        participant_count = st.number_input(
            "参加者数",
            min_value=1,
            max_value=20,
            value=default_count,
            step=1,
        )

        participant_names = []
        for idx in range(int(participant_count)):
            default_name = current_participants[idx] if idx < len(current_participants) else ""
            participant_names.append(
                st.text_input(
                    f"参加者{idx + 1}の名前",
                    value=default_name,
                    key=f"initial_participant_{idx}",
                )
            )

        use_anniversary = st.checkbox(
            "記念日カウントダウンを使う",
            value=settings.get("use_anniversary", True),
        )
        anniversary_name = st.text_input(
            "記念日の表示名",
            value=settings.get("anniversary_name", "記念日"),
            disabled=not use_anniversary,
        )
        anniversary_date = st.date_input(
            "記念日",
            value=parse_date_text(settings.get("anniversary_date", ""), date.today()),
            disabled=not use_anniversary,
        )
        submitted = st.form_submit_button("初期設定を保存")

    if submitted:
        cleaned_names = [name.strip() for name in participant_names if name.strip()]
        if len(cleaned_names) != int(participant_count):
            st.warning("選んだ人数分の参加者名を入力してください。")
            return False

        settings["app_name"] = app_name.strip() or "TripList"
        set_participants(settings, cleaned_names)
        settings["use_anniversary"] = bool(use_anniversary)
        settings["anniversary_name"] = anniversary_name.strip() or "記念日"
        settings["anniversary_date"] = str(anniversary_date) if use_anniversary else ""
        save_settings(settings)
        st.success("初期設定を保存しました。")
        st.rerun()

    return False

def render_anniversary_countdown(settings):
    if not settings.get("use_anniversary", True):
        return

    anniversary_date_text = settings.get("anniversary_date", "")
    if not anniversary_date_text:
        return

    today = date.today()
    base_date = parse_date_text(anniversary_date_text, today)
    days_since = max((today - base_date).days + 1, 0)
    next_date = next_yearly_anniversary(base_date, today)
    days_left = (next_date - today).days
    label = anniversary_label(base_date, next_date)

    if days_left == 0:
        countdown_text = f"今日は{label}です 🎉"
    else:
        countdown_text = f"{label}まであと {days_left} 日"

    anniversary_name = settings.get("anniversary_name", "記念日")
    st.info(
        f"💐 {anniversary_name}から {days_since:,} 日 ／ "
        f"{countdown_text} ／ 記念日 {base_date.strftime('%Y年%m月%d日')}"
    )


def render_personal_settings(settings):
    with st.sidebar.expander("アプリ設定"):
        app_name = st.text_input(
            "アプリ名",
            value=settings.get("app_name", "TripList"),
            key="settings_app_name",
        )

        current_participants = get_participants(settings)
        default_count = max(1, len(current_participants) or 2)
        participant_count = st.number_input(
            "参加者数",
            min_value=1,
            max_value=20,
            value=default_count,
            step=1,
            key="settings_participant_count",
        )

        participant_names = []
        for idx in range(int(participant_count)):
            default_name = current_participants[idx] if idx < len(current_participants) else ""
            participant_names.append(
                st.text_input(
                    f"参加者{idx + 1}の名前",
                    value=default_name,
                    key=f"settings_participant_{idx}",
                )
            )

        use_anniversary = st.checkbox(
            "記念日カウントダウンを使う",
            value=settings.get("use_anniversary", True),
            key="settings_use_anniversary",
        )
        anniversary_name = st.text_input(
            "記念日の表示名",
            value=settings.get("anniversary_name", "記念日"),
            key="settings_anniversary_name",
            disabled=not use_anniversary,
        )
        anniversary_date = st.date_input(
            "記念日",
            value=parse_date_text(settings.get("anniversary_date", ""), date.today()),
            key="settings_anniversary_date",
            disabled=not use_anniversary,
        )

        if st.button("設定を保存", key="save_personal_settings"):
            cleaned_names = [name.strip() for name in participant_names if name.strip()]
            if len(cleaned_names) != int(participant_count):
                st.warning("選んだ人数分の参加者名を入力してください。")
                return

            settings["app_name"] = app_name.strip() or "TripList"
            set_participants(settings, cleaned_names)
            settings["use_anniversary"] = bool(use_anniversary)
            settings["anniversary_name"] = anniversary_name.strip() or "記念日"
            settings["anniversary_date"] = str(anniversary_date) if use_anniversary else ""
            save_settings(settings)
            st.success("設定を保存しました。")
            st.rerun()

def render_data_management(trips):
    with st.sidebar.expander("データ管理"):
        st.caption("trips.json が大きくなったときは軽量化できます。")
        st.write("trips.json:", file_size_text(DATA_FILE))
        st.write("app_settings.json:", file_size_text(SETTINGS_FILE))

        if st.button("JSONを軽量化", key="compact_json"):
            before = file_size_text(DATA_FILE)
            compact_data_files()
            after = file_size_text(DATA_FILE)
            st.success(f"軽量化しました：{before} → {after}")
            st.rerun()

        st.divider()
        st.caption("公開前にサンプルデータを消したい場合だけ使ってください。")
        confirm_reset = st.checkbox("すべての旅行データを削除する", key="confirm_reset_data")
        if st.button("旅行データを全削除", key="reset_trips_data", disabled=not confirm_reset):
            for trip in trips:
                for photo in trip.get("photos", []):
                    delete_file(photo.get("path", ""))
            save_trips([])
            st.session_state["selected_trip_index"] = 0
            st.success("旅行データを削除しました。")
            st.rerun()


# =========================
# サイドバー
# =========================

def render_sidebar(trips, settings):
    st.sidebar.title("旅行一覧")
    render_personal_settings(settings)
    render_data_management(trips)

    with st.sidebar.expander("新規旅行を作成", expanded=not trips):
        new_trip_title = st.text_input("新規旅行タイトル", key="new_trip_title")
        if st.button("旅行を作成", key="create_trip"):
            if not new_trip_title.strip():
                st.warning("旅行タイトルを入力してください")
            else:
                trips.append({
                    "title": new_trip_title.strip(),
                    "plans": [],
                    "hotels": [],
                    "others": [],
                    "packing_items": [],
                    "photos": [],
                })
                save_trips(trips)
                st.session_state["selected_trip_index"] = len(trips) - 1
                st.rerun()

    if not trips:
        st.sidebar.info("まだ旅行はありません")
        return None

    search = st.sidebar.text_input("旅行名で検索", key="trip_search")
    visible_indices = [
        i for i, trip in enumerate(trips)
        if not search or search.lower() in trip.get("title", "").lower()
    ]

    if not visible_indices:
        st.sidebar.warning("該当する旅行がありません")
        return None

    current_index = st.session_state.get("selected_trip_index", visible_indices[0])
    if current_index not in visible_indices:
        current_index = visible_indices[0]

    selected_title = st.sidebar.radio(
        "開く旅行",
        options=visible_indices,
        index=visible_indices.index(current_index),
        format_func=lambda i: trips[i].get("title", "無題の旅行"),
        key="selected_trip_index",
    )

    st.sidebar.caption("旅行の順番")
    col_up, col_down = st.sidebar.columns(2)
    with col_up:
        if st.button("⬆️ 上へ", key="move_trip_up") and selected_title > 0:
            trips[selected_title], trips[selected_title - 1] = trips[selected_title - 1], trips[selected_title]
            save_trips(trips)
            st.session_state["selected_trip_index"] = selected_title - 1
            st.rerun()
    with col_down:
        if st.button("⬇️ 下へ", key="move_trip_down") and selected_title < len(trips) - 1:
            trips[selected_title], trips[selected_title + 1] = trips[selected_title + 1], trips[selected_title]
            save_trips(trips)
            st.session_state["selected_trip_index"] = selected_title + 1
            st.rerun()

    st.sidebar.markdown("<p class='sidebar-help'>追加・削除しても、選択中の旅行画面のまま使えます。</p>", unsafe_allow_html=True)
    return selected_title


# =========================
# 日程タブ
# =========================

def render_add_plan_form(trips, trip, trip_index):
    with st.expander("予定を追加", expanded=True):
        plan_date = st.date_input("年月日", key=f"plan_date_{trip_index}")
        plan_time = st.time_input("時間", key=f"plan_time_{trip_index}")
        plan_category = st.selectbox("カテゴリ", CATEGORIES, key=f"category_{trip_index}")
        plan_content = st.text_input("内容", key=f"plan_content_{trip_index}")
        plan_place = st.text_input("場所", key=f"plan_place_{trip_index}")
        plan_amount = st.number_input("金額", min_value=0, step=100, key=f"plan_amount_{trip_index}")

        if st.button("予定を追加", key=f"add_plan_{trip_index}"):
            trip.setdefault("plans", []).append({
                "date": str(plan_date),
                "time": plan_time.strftime("%H:%M"),
                "category": plan_category,
                "content": plan_content,
                "place": plan_place,
                "amount": int(plan_amount),
            })
            save_trips(trips)
            st.rerun()


def render_add_hotel_form(trips, trip, trip_index):
    with st.expander("宿泊を追加"):
        hotel_date = st.date_input("宿泊日", key=f"hotel_date_{trip_index}")
        hotel_name = st.text_input("宿泊施設", key=f"hotel_name_{trip_index}")
        hotel_place = st.text_input("宿泊場所", key=f"hotel_place_{trip_index}")
        hotel_amount = st.number_input("宿泊金額", min_value=0, step=100, key=f"hotel_amount_{trip_index}")

        if st.button("宿泊を追加", key=f"add_hotel_{trip_index}"):
            trip.setdefault("hotels", []).append({
                "date": str(hotel_date),
                "hotel": hotel_name,
                "place": hotel_place or hotel_name,
                "amount": int(hotel_amount),
            })
            save_trips(trips)
            st.rerun()


def render_add_other_form(trips, trip, trip_index):
    with st.expander("その他を追加"):
        other_category = st.selectbox("その他カテゴリ", CATEGORIES, key=f"other_category_{trip_index}")
        other_content = st.text_input("その他の内容", key=f"other_content_{trip_index}")
        other_amount = st.number_input("その他の金額", min_value=0, step=100, key=f"other_amount_{trip_index}")

        if st.button("その他を追加", key=f"add_other_{trip_index}"):
            trip.setdefault("others", []).append({
                "category": other_category,
                "content": other_content,
                "amount": int(other_amount),
            })
            save_trips(trips)
            st.rerun()


def render_edit_plan_form(trips, trip, trip_index, plan_i, item):
    """追加済みの予定を編集する。"""
    with st.form(key=f"edit_plan_form_{trip_index}_{plan_i}"):
        current_date = item.get("date", str(date.today()))
        try:
            current_date_value = datetime.strptime(current_date, "%Y-%m-%d").date()
        except Exception:
            current_date_value = date.today()

        current_time = item.get("time", "09:00")
        try:
            h, m = current_time.split(":")
            current_time_value = datetime.strptime(f"{h}:{m}", "%H:%M").time()
        except Exception:
            current_time_value = datetime.strptime("09:00", "%H:%M").time()

        new_date = st.date_input("年月日", value=current_date_value, key=f"edit_plan_date_{trip_index}_{plan_i}")
        new_time = st.time_input("時間", value=current_time_value, key=f"edit_plan_time_{trip_index}_{plan_i}")
        new_category = st.selectbox(
            "カテゴリ",
            CATEGORIES,
            index=CATEGORIES.index(item.get("category", "その他")) if item.get("category", "その他") in CATEGORIES else CATEGORIES.index("その他"),
            key=f"edit_plan_category_{trip_index}_{plan_i}",
        )
        new_content = st.text_input("内容", value=item.get("content", ""), key=f"edit_plan_content_{trip_index}_{plan_i}")
        new_place = st.text_input("場所", value=item.get("place", ""), key=f"edit_plan_place_{trip_index}_{plan_i}")
        new_amount = st.number_input("金額", min_value=0, step=100, value=yen(item.get("amount", 0)), key=f"edit_plan_amount_{trip_index}_{plan_i}")

        col_save, col_cancel = st.columns(2)
        with col_save:
            submitted = st.form_submit_button("保存")
        with col_cancel:
            cancelled = st.form_submit_button("キャンセル")

        if submitted:
            trip["plans"][plan_i] = {
                "date": str(new_date),
                "time": new_time.strftime("%H:%M"),
                "category": new_category,
                "content": new_content,
                "place": new_place,
                "amount": int(new_amount),
            }
            save_trips(trips)
            st.session_state[f"editing_plan_{trip_index}_{plan_i}"] = False
            st.rerun()

        if cancelled:
            st.session_state[f"editing_plan_{trip_index}_{plan_i}"] = False
            st.rerun()


def render_edit_hotel_form(trips, trip, trip_index, hotel_i, item):
    """追加済みの宿泊を編集する。"""
    with st.form(key=f"edit_hotel_form_{trip_index}_{hotel_i}"):
        current_date = item.get("date", str(date.today()))
        try:
            current_date_value = datetime.strptime(current_date, "%Y-%m-%d").date()
        except Exception:
            current_date_value = date.today()

        new_date = st.date_input("宿泊日", value=current_date_value, key=f"edit_hotel_date_{trip_index}_{hotel_i}")
        new_hotel = st.text_input("宿泊施設", value=item.get("hotel", ""), key=f"edit_hotel_name_{trip_index}_{hotel_i}")
        new_place = st.text_input("宿泊場所", value=item.get("place", item.get("hotel", "")), key=f"edit_hotel_place_{trip_index}_{hotel_i}")
        new_amount = st.number_input("宿泊金額", min_value=0, step=100, value=yen(item.get("amount", 0)), key=f"edit_hotel_amount_{trip_index}_{hotel_i}")

        col_save, col_cancel = st.columns(2)
        with col_save:
            submitted = st.form_submit_button("保存")
        with col_cancel:
            cancelled = st.form_submit_button("キャンセル")

        if submitted:
            trip["hotels"][hotel_i] = {
                "date": str(new_date),
                "hotel": new_hotel,
                "place": new_place or new_hotel,
                "amount": int(new_amount),
            }
            save_trips(trips)
            st.session_state[f"editing_hotel_{trip_index}_{hotel_i}"] = False
            st.rerun()

        if cancelled:
            st.session_state[f"editing_hotel_{trip_index}_{hotel_i}"] = False
            st.rerun()


def render_edit_other_form(trips, trip, trip_index, other_i, item):
    """追加済みのその他項目を編集する。"""
    with st.form(key=f"edit_other_form_{trip_index}_{other_i}"):
        new_category = st.selectbox(
            "カテゴリ",
            CATEGORIES,
            index=CATEGORIES.index(item.get("category", "その他")) if item.get("category", "その他") in CATEGORIES else CATEGORIES.index("その他"),
            key=f"edit_other_category_{trip_index}_{other_i}",
        )
        new_content = st.text_input("内容", value=item.get("content", ""), key=f"edit_other_content_{trip_index}_{other_i}")
        new_amount = st.number_input("金額", min_value=0, step=100, value=yen(item.get("amount", 0)), key=f"edit_other_amount_{trip_index}_{other_i}")

        col_save, col_cancel = st.columns(2)
        with col_save:
            submitted = st.form_submit_button("保存")
        with col_cancel:
            cancelled = st.form_submit_button("キャンセル")

        if submitted:
            trip["others"][other_i] = {
                "category": new_category,
                "content": new_content,
                "amount": int(new_amount),
            }
            save_trips(trips)
            st.session_state[f"editing_other_{trip_index}_{other_i}"] = False
            st.rerun()

        if cancelled:
            st.session_state[f"editing_other_{trip_index}_{other_i}"] = False
            st.rerun()


def render_delete_items(trips, trip, trip_index):
    st.subheader("追加済み内容")

    if not trip.get("plans") and not trip.get("hotels") and not trip.get("others"):
        st.write("まだ内容はありません")
        return

    if trip.get("plans"):
        st.write("予定")
        for plan_i, item in enumerate(trip.get("plans", [])):
            place_text = f" @ {item.get('place', '')}" if item.get('place') else ""
            label = f"{item.get('date', '')} {item.get('time', '')} {item.get('content', '')}{place_text}（{yen(item.get('amount', 0)):,}円）"
            col1, col2, col3 = st.columns([5, 1, 1])
            with col1:
                st.write(label)
            with col2:
                if st.button("編集", key=f"edit_plan_{trip_index}_{plan_i}"):
                    st.session_state[f"editing_plan_{trip_index}_{plan_i}"] = True
                    st.rerun()
            with col3:
                if st.button("削除", key=f"delete_plan_{trip_index}_{plan_i}"):
                    trip["plans"].pop(plan_i)
                    save_trips(trips)
                    st.rerun()

            if st.session_state.get(f"editing_plan_{trip_index}_{plan_i}", False):
                render_edit_plan_form(trips, trip, trip_index, plan_i, item)

    if trip.get("hotels"):
        st.write("宿泊")
        for hotel_i, item in enumerate(trip.get("hotels", [])):
            place_text = f" @ {item.get('place', '')}" if item.get('place') else ""
            label = f"{item.get('date', '')} {item.get('hotel', '')}{place_text}（{yen(item.get('amount', 0)):,}円）"
            col1, col2, col3 = st.columns([5, 1, 1])
            with col1:
                st.write(label)
            with col2:
                if st.button("編集", key=f"edit_hotel_{trip_index}_{hotel_i}"):
                    st.session_state[f"editing_hotel_{trip_index}_{hotel_i}"] = True
                    st.rerun()
            with col3:
                if st.button("削除", key=f"delete_hotel_{trip_index}_{hotel_i}"):
                    trip["hotels"].pop(hotel_i)
                    save_trips(trips)
                    st.rerun()

            if st.session_state.get(f"editing_hotel_{trip_index}_{hotel_i}", False):
                render_edit_hotel_form(trips, trip, trip_index, hotel_i, item)

    if trip.get("others"):
        st.write("その他")
        for other_i, item in enumerate(trip.get("others", [])):
            label = f"{item.get('category', 'その他')} {item.get('content', '')}（{yen(item.get('amount', 0)):,}円）"
            col1, col2, col3 = st.columns([5, 1, 1])
            with col1:
                st.write(label)
            with col2:
                if st.button("編集", key=f"edit_other_{trip_index}_{other_i}"):
                    st.session_state[f"editing_other_{trip_index}_{other_i}"] = True
                    st.rerun()
            with col3:
                if st.button("削除", key=f"delete_other_{trip_index}_{other_i}"):
                    trip["others"].pop(other_i)
                    save_trips(trips)
                    st.rerun()

            if st.session_state.get(f"editing_other_{trip_index}_{other_i}", False):
                render_edit_other_form(trips, trip, trip_index, other_i, item)


def render_timeline(table_rows):
    st.subheader("タイムライン")

    if not table_rows:
        st.write("まだタイムラインはありません")
        return

    current_date = None
    for row in table_rows:
        row_date = row.get("年月日", "") or "日付未定"
        if row_date != current_date:
            current_date = row_date
            st.markdown(f"<div class='timeline-date'>📅 {current_date}</div>", unsafe_allow_html=True)

        icon = icon_for_category(row.get("カテゴリ", "その他"))
        time_text = row.get("時間", "")
        amount = yen(row.get("金額", 0))
        place_text = row.get("場所", "")
        place_line = f"<br>📍 {place_text}" if place_text else ""
        st.markdown(
            f"""
            <div class="timeline-card">
                <b>{icon} {time_text} {row.get("内容", "")}</b>{place_line}<br>
                <span style="color:#8a6f60;">
                    {row.get("種類", "")} / {row.get("カテゴリ", "")} / {amount:,}円
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )



def collect_weather_targets(trip):
    targets = []
    seen = set()

    for item in trip.get("plans", []):
        date_text = item.get("date", "")
        place = item.get("place", "")
        content = item.get("content", "")
        if date_text and place:
            key = (date_text, place)
            if key not in seen:
                seen.add(key)
                targets.append({"date": date_text, "place": place, "content": content})

    for item in trip.get("hotels", []):
        date_text = item.get("date", "")
        place = item.get("place", item.get("hotel", ""))
        content = item.get("hotel", "")
        if date_text and place:
            key = (date_text, place)
            if key not in seen:
                seen.add(key)
                targets.append({"date": date_text, "place": place, "content": content})

    targets.sort(key=lambda x: x.get("date", ""))
    return targets


def render_weather_tab(trip):
    st.subheader("天気予報")
    st.caption("予定・宿泊に入力した場所から天気を表示します。16日以内は予報、過去は実績、遠い未来は過去5年の同日参考値です。")

    targets = collect_weather_targets(trip)
    if not targets:
        st.info("日程タブで、予定や宿泊に『場所』を入力すると天気予報を表示できます。")
        return

    for target in targets:
        weather = weather_for(target["place"], target["date"])
        text = format_weather_text(weather)
        title = f"{target['date']}　{target['place']}"
        if target.get("content"):
            title += f"（{target['content']}）"

        if weather and weather.get("status") == "ok":
            st.markdown(
                f"""
                <div class="weather-card">
                    <b>🌤️ {title}</b><br>
                    {text}
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.warning(f"{title}：{text or '天気を取得できませんでした。'}")


def render_schedule_tab(trips, trip, trip_index):
    st.subheader("日程")
    render_add_plan_form(trips, trip, trip_index)
    render_add_hotel_form(trips, trip, trip_index)
    render_add_other_form(trips, trip, trip_index)

    table_rows, _, _ = build_table_rows(trip)
    render_timeline(table_rows)

    st.subheader("日程表")
    if table_rows:
        st.dataframe(table_rows, use_container_width=True)
    else:
        st.write("まだ内容はありません")

    render_delete_items(trips, trip, trip_index)


# =========================
# 持ち物タブ
# =========================

def render_packing_tab(trips, trip, trip_index):
    st.subheader("持ち物チェックリスト")
    trip.setdefault("packing_items", [])

    col_template, col_input = st.columns([1, 2])
    with col_template:
        if st.button("定番セットを追加", key=f"add_default_packing_{trip_index}"):
            existing_names = {item.get("name", "") for item in trip["packing_items"]}
            for name in DEFAULT_PACKING_ITEMS:
                if name not in existing_names:
                    trip["packing_items"].append({"name": name, "checked": False})
            save_trips(trips)
            st.rerun()

    with col_input:
        new_item = st.text_input("持ち物を追加", key=f"new_packing_item_{trip_index}")
        if st.button("追加", key=f"add_packing_item_{trip_index}"):
            if new_item.strip():
                trip["packing_items"].append({"name": new_item.strip(), "checked": False})
                save_trips(trips)
                st.rerun()
            else:
                st.warning("持ち物名を入力してください")

    if not trip["packing_items"]:
        st.write("まだ持ち物はありません")
        return

    checked_count = sum(1 for item in trip["packing_items"] if item.get("checked", False))
    total_count = len(trip["packing_items"])
    st.caption(f"準備済み：{checked_count} / {total_count}")
    st.progress(checked_count / total_count if total_count else 0)

    for item_i, item in enumerate(trip["packing_items"]):
        col_check, col_edit, col_delete = st.columns([5, 1, 1])
        with col_check:
            checked = st.checkbox(
                item.get("name", "無題"),
                value=item.get("checked", False),
                key=f"packing_check_{trip_index}_{item_i}",
            )
            if checked != item.get("checked", False):
                trip["packing_items"][item_i]["checked"] = checked
                save_trips(trips)
                st.rerun()
        with col_edit:
            if st.button("編集", key=f"edit_packing_{trip_index}_{item_i}"):
                st.session_state[f"editing_packing_{trip_index}_{item_i}"] = True
                st.rerun()
        with col_delete:
            if st.button("削除", key=f"delete_packing_{trip_index}_{item_i}"):
                trip["packing_items"].pop(item_i)
                save_trips(trips)
                st.rerun()

        if st.session_state.get(f"editing_packing_{trip_index}_{item_i}", False):
            with st.form(key=f"edit_packing_form_{trip_index}_{item_i}"):
                new_name = st.text_input(
                    "持ち物名を編集",
                    value=item.get("name", ""),
                    key=f"edit_packing_name_{trip_index}_{item_i}",
                )
                col_save, col_cancel = st.columns(2)
                with col_save:
                    submitted = st.form_submit_button("保存")
                with col_cancel:
                    cancelled = st.form_submit_button("キャンセル")

                if submitted:
                    if new_name.strip():
                        trip["packing_items"][item_i]["name"] = new_name.strip()
                        save_trips(trips)
                        st.session_state[f"editing_packing_{trip_index}_{item_i}"] = False
                        st.rerun()
                    else:
                        st.warning("持ち物名を入力してください")

                if cancelled:
                    st.session_state[f"editing_packing_{trip_index}_{item_i}"] = False
                    st.rerun()


# =========================
# 費用タブ
# =========================

def render_cost_tab(trips, trip, trip_index):
    st.subheader("費用")
    table_rows, total, category_totals = build_table_rows(trip)

    col_total, col_person = st.columns(2)
    with col_total:
        st.metric("合計金額", f"{total:,}円")
    with col_person:
        default_people = max(1, len(get_participants(load_settings())))
        people = st.number_input("人数", min_value=1, value=default_people, key=f"people_{trip_index}")
        st.metric("一人当たり", f"{total // people:,}円")

    st.subheader("カテゴリ別費用")
    if category_totals:
        category_rows = [
            {"カテゴリ": category, "金額": amount}
            for category, amount in sorted(category_totals.items())
        ]
        st.dataframe(category_rows, use_container_width=True)
    else:
        st.write("まだ費用はありません")

    st.subheader("費用明細")
    if table_rows:
        st.dataframe(table_rows, use_container_width=True)
    else:
        st.write("まだ内容はありません")

    st.subheader("PDF")
    pdf_data = make_pdf(trip, load_settings())
    st.download_button(
        label="PDFをダウンロード",
        data=pdf_data,
        file_name=f"{trip.get('title', '旅行計画')}.pdf",
        mime="application/pdf",
        key=f"pdf_{trip_index}",
    )


# =========================
# 写真タブ
# =========================

def render_photo_tab(trips, trip, trip_index):
    st.subheader("写真")
    trip.setdefault("photos", [])

    uploaded_photos = st.file_uploader(
        "写真を追加",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key=f"photo_uploader_{trip_index}",
    )
    photo_caption = st.text_input("写真メモ", key=f"photo_caption_{trip_index}")

    if st.button("写真を保存", key=f"save_photos_{trip_index}"):
        if not uploaded_photos:
            st.warning("写真を選択してください")
        else:
            for photo in uploaded_photos:
                save_path = PHOTO_DIR / f"{timestamp()}_{photo.name}"
                with open(save_path, "wb") as f:
                    f.write(photo.getbuffer())
                trip["photos"].append({
                    "path": str(save_path),
                    "caption": photo_caption,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })
            save_trips(trips)
            st.rerun()

    if not trip["photos"]:
        st.write("まだ写真はありません")
        return

    for photo_i, photo in enumerate(trip["photos"]):
        path_text = photo.get("path", "")
        with st.container():
            if path_text and Path(path_text).exists():
                st.image(path_text, caption=photo.get("caption", ""), use_column_width=True)
            else:
                st.warning("写真ファイルが見つかりません")
            st.caption(photo.get("created_at", ""))

            col_edit, col_delete = st.columns(2)
            with col_edit:
                if st.button("写真メモを編集", key=f"edit_photo_{trip_index}_{photo_i}"):
                    st.session_state[f"editing_photo_{trip_index}_{photo_i}"] = True
                    st.rerun()
            with col_delete:
                if st.button("写真を削除", key=f"delete_photo_{trip_index}_{photo_i}"):
                    delete_file(path_text)
                    trip["photos"].pop(photo_i)
                    save_trips(trips)
                    st.rerun()

            if st.session_state.get(f"editing_photo_{trip_index}_{photo_i}", False):
                with st.form(key=f"edit_photo_form_{trip_index}_{photo_i}"):
                    new_caption = st.text_input(
                        "写真メモを編集",
                        value=photo.get("caption", ""),
                        key=f"edit_photo_caption_{trip_index}_{photo_i}",
                    )
                    col_save, col_cancel = st.columns(2)
                    with col_save:
                        submitted = st.form_submit_button("保存")
                    with col_cancel:
                        cancelled = st.form_submit_button("キャンセル")
                    if submitted:
                        trip["photos"][photo_i]["caption"] = new_caption
                        save_trips(trips)
                        st.session_state[f"editing_photo_{trip_index}_{photo_i}"] = False
                        st.rerun()
                    if cancelled:
                        st.session_state[f"editing_photo_{trip_index}_{photo_i}"] = False
                        st.rerun()


# =========================
# 旅行画面
# =========================

def render_trip_title_editor(trips, trip, trip_index):
    col_title, col_delete = st.columns([4, 1])
    with col_title:
        new_title = st.text_input("旅行タイトル", value=trip.get("title", ""), key=f"trip_title_{trip_index}")
        if new_title != trip.get("title", ""):
            trip["title"] = new_title
            save_trips(trips)
    with col_delete:
        st.write("")
        st.write("")
        if st.button("旅行を削除", key=f"delete_trip_{trip_index}"):
            for photo in trip.get("photos", []):
                delete_file(photo.get("path", ""))
            trips.pop(trip_index)
            save_trips(trips)
            st.session_state["selected_trip_index"] = max(0, trip_index - 1)
            st.rerun()


def render_selected_trip(trips, trip_index):
    trip = normalize_trip(trips[trip_index])

    st.subheader(f"🌸 {trip.get('title', '無題の旅行')}")
    render_trip_title_editor(trips, trip, trip_index)

    schedule_tab, weather_tab, packing_tab, cost_tab, photo_tab = st.tabs(["📅 日程", "🌤️ 天気", "🎒 持ち物", "💴 費用", "📸 写真"])

    with schedule_tab:
        render_schedule_tab(trips, trip, trip_index)

    with weather_tab:
        render_weather_tab(trip)

    with packing_tab:
        render_packing_tab(trips, trip, trip_index)

    with cost_tab:
        render_cost_tab(trips, trip, trip_index)

    with photo_tab:
        render_photo_tab(trips, trip, trip_index)


# =========================
# メイン処理
# =========================

def main():
    settings = load_settings()
    st.set_page_config(page_title=app_title(settings), page_icon="🌷", layout="wide")
    apply_style()

    if not render_initial_setup(settings):
        return

    show_header(settings)
    render_anniversary_countdown(settings)

    trips = load_trips()
    for trip in trips:
        normalize_trip(trip)

    selected_index = render_sidebar(trips, settings)

    if selected_index is None:
        st.info("左側のサイドバーから旅行を作成してください。")
        return

    render_selected_trip(trips, selected_index)


if __name__ == "__main__":
    main()
