from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import pandas as pd
import requests
import streamlit as st

from modules.auth import render_auth_gate, logout, get_user
from modules.config import DEFAULT_SETTINGS
from modules.db import (
    create_group, join_group, list_my_groups, get_group_data, save_group_data,
    rename_group, get_members,
)
from modules.pdf_utils import make_pdf
from modules.utils import new_id, yen, safe_filename, sort_key_date_time, today_iso
from modules.weather import get_weather_for

st.set_page_config(page_title="TripList", page_icon="🌷", layout="wide")
st.markdown("""
<style>
.stApp {
    background: #FFF8F1;
    color: #2F2F36;
}

/* 全体の文字色を固定 */
html, body, [class*="css"], .stMarkdown, .stText, p, span, div, label {
    color: #2F2F36 !important;
}

/* 入力欄 */
input, textarea {
    color: #2F2F36 !important;
    background-color: #FFFFFF !important;
}

/* selectboxなど */
[data-baseweb="select"] * {
    color: #2F2F36 !important;
}

/* サイドバー */
section[data-testid="stSidebar"] {
    background: #F4E8DA;
}

section[data-testid="stSidebar"] * {
    color: #2F2F36 !important;
}

/* ボタン */
.stButton > button {
    background: #C8A97E;
    color: white !important;
    border-radius: 12px;
    border: none;
}
</style>
""", unsafe_allow_html=True)
CSS = """
<style>
.stApp { background: linear-gradient(135deg, #fff7f0 0%, #f7fbff 100%); }
h1, h2, h3 { color: #735343; }
[data-testid="stSidebar"] { background: rgba(255,255,255,0.88); }
.trip-card { background: rgba(255,255,255,0.90); border: 1px solid #ead7c5; border-radius: 18px; padding: 18px; margin: 12px 0; box-shadow: 0 6px 18px rgba(120, 80, 60, 0.10); }
.small-muted { color: #7d6b61; font-size: 0.92rem; }
.big-title { text-align:center; font-size: 3.0rem; color: #735343; font-weight: 800; margin-bottom: 0.2rem; }
.subtitle { text-align:center; color:#7d6b61; margin-bottom: 1.5rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

CATEGORIES = ["交通", "宿泊", "食事", "観光", "買い物", "チケット", "その他"]
ICONS = {"交通":"🚄", "宿泊":"🏨", "食事":"🍽️", "観光":"📍", "買い物":"🛍️", "チケット":"🎫", "その他":"📝"}
DEFAULT_PACKING = ["財布", "スマホ", "充電器", "モバイルバッテリー", "着替え", "下着", "洗面用具", "薬", "保険証", "ハンカチ"]

# ------------------------- helpers -------------------------

def normalize_trip(trip: dict) -> dict:
    trip.setdefault("id", new_id())
    trip.setdefault("title", "無題の旅行")
    trip.setdefault("participants", [])
    trip.setdefault("anniversary_name", "")
    trip.setdefault("anniversary_date", "")
    trip.setdefault("use_anniversary", False)
    trip.setdefault("plans", [])
    trip.setdefault("hotels", [])
    trip.setdefault("others", [])
    trip.setdefault("packing", [])
    trip.setdefault("photos", [])
    return trip


def total_amount(trip: dict) -> int:
    total = 0
    for section in ["plans", "hotels", "others"]:
        total += sum(yen(x.get("amount")) for x in trip.get(section, []))
    return total


def category_totals(trip: dict) -> dict[str, int]:
    totals = {c: 0 for c in CATEGORIES}
    for p in trip.get("plans", []):
        totals[p.get("category", "その他")] = totals.get(p.get("category", "その他"), 0) + yen(p.get("amount"))
    for h in trip.get("hotels", []):
        totals["宿泊"] = totals.get("宿泊", 0) + yen(h.get("amount"))
    for o in trip.get("others", []):
        cat = o.get("category", "その他")
        totals[cat] = totals.get(cat, 0) + yen(o.get("amount"))
    return {k:v for k,v in totals.items() if v}


def build_rows(trip: dict) -> list[dict]:
    rows = []
    for p in trip.get("plans", []):
        rows.append({"種類":"予定", "年月日":p.get("date",""), "時間":p.get("time",""), "カテゴリ":p.get("category",""), "内容":p.get("content",""), "場所":p.get("place",""), "金額":yen(p.get("amount"))})
    for h in trip.get("hotels", []):
        rows.append({"種類":"宿泊", "年月日":h.get("date",""), "時間":"", "カテゴリ":"宿泊", "内容":h.get("hotel",""), "場所":h.get("place",""), "金額":yen(h.get("amount"))})
    for o in trip.get("others", []):
        rows.append({"種類":"その他", "年月日":"", "時間":"", "カテゴリ":o.get("category","その他"), "内容":o.get("content",""), "場所":"", "金額":yen(o.get("amount"))})
    return sorted(rows, key=lambda r: (r.get("年月日") or "9999-99-99", r.get("時間") or "99:99"))


def save_current(group_id: str, trips: list[dict], settings: dict):
    save_group_data(group_id, trips, settings)


def selected_trip_index(trips: list[dict]) -> int | None:
    if not trips:
        return None
    sid = st.session_state.get("selected_trip_id")
    if sid:
        for i, t in enumerate(trips):
            if t.get("id") == sid:
                return i
    st.session_state["selected_trip_id"] = trips[0].get("id")
    return 0

# ------------------------- group UI -------------------------

def render_group_gate() -> str | None:
    st.sidebar.header("共有グループ")
    groups = list_my_groups()

    if groups:
        labels = [f"{g.get('name','旅行グループ')}  /  招待コード:{g.get('invite_code','')}" for g in groups]
        current = st.session_state.get("selected_group_id")
        default_index = 0
        for i, g in enumerate(groups):
            if g.get("id") == current:
                default_index = i
        choice = st.sidebar.selectbox("使うグループ", list(range(len(groups))), format_func=lambda i: labels[i], index=default_index)
        group_id = groups[choice]["id"]
        st.session_state["selected_group_id"] = group_id
        st.sidebar.caption(f"招待コード：`{groups[choice].get('invite_code')}`")
        with st.sidebar.expander("グループ名を変更"):
            new_name = st.text_input("グループ名", value=groups[choice].get("name", ""), key="rename_group")
            if st.button("変更", key="rename_group_btn"):
                rename_group(group_id, new_name)
                st.rerun()
        return group_id

    st.info("最初に共有グループを作成するか、招待コードで参加してください。")
    tab_create, tab_join = st.tabs(["グループ作成", "グループに参加"])
    with tab_create:
        name = st.text_input("グループ名", placeholder="例：陽咲・雷人旅行")
        st.caption("グループを作成すると、招待コードが自動で発行されます。相手にはその招待コードだけ共有してください。")
        if st.button("グループを作成"):
            gid = create_group(name)
            st.session_state["selected_group_id"] = gid
            st.success("グループを作成しました。サイドバーに表示される招待コードを共有してください。")
            st.rerun()
    with tab_join:
        code = st.text_input("招待コード")
        if st.button("参加する"):
            gid = join_group(code)
            if gid:
                st.session_state["selected_group_id"] = gid
                st.success("グループに参加しました。")
                st.rerun()
            else:
                st.error("招待コードが見つかりません。")
    return None

# ------------------------- trip operations -------------------------

def add_trip(trips: list[dict], title: str):
    trips.append(normalize_trip({"id": new_id(), "title": title.strip() or "新しい旅行"}))
    st.session_state["selected_trip_id"] = trips[-1]["id"]


def delete_item(items: list[dict], item_id: str):
    items[:] = [x for x in items if x.get("id") != item_id]


def render_trip_sidebar(group_id: str, trips: list[dict], settings: dict):
    st.sidebar.header("旅行一覧")
    new_title = st.sidebar.text_input("新しい旅行タイトル")
    if st.sidebar.button("旅行を作成"):
        add_trip(trips, new_title)
        save_current(group_id, trips, settings)
        st.rerun()

    if trips:
        ids = [t["id"] for t in trips]
        titles = [t.get("title", "無題") for t in trips]
        current = st.session_state.get("selected_trip_id", ids[0])
        index = ids.index(current) if current in ids else 0
        selected = st.sidebar.radio("選択中の旅行", ids, format_func=lambda x: titles[ids.index(x)], index=index)
        st.session_state["selected_trip_id"] = selected
        i = ids.index(selected)
        c1, c2 = st.sidebar.columns(2)
        with c1:
            if i > 0 and st.button("⬆️ 上へ"):
                trips[i-1], trips[i] = trips[i], trips[i-1]
                save_current(group_id, trips, settings)
                st.rerun()
        with c2:
            if i < len(trips)-1 and st.button("⬇️ 下へ"):
                trips[i+1], trips[i] = trips[i], trips[i+1]
                save_current(group_id, trips, settings)
                st.rerun()

# ------------------------- cards -------------------------

def render_plan_card(group_id: str, trips: list[dict], settings: dict, trip: dict, p: dict):
    with st.container(border=True):
        st.markdown(f"### {ICONS.get(p.get('category','その他'),'📝')} {p.get('content','予定')}")
        st.write(f"📅 {p.get('date','')} {p.get('time','')}　📍 {p.get('place','')}　💰 {yen(p.get('amount')):,}円")
        if p.get("memo"): st.caption(p.get("memo"))
        cols = st.columns([1,1,1,6])
        if p.get("place"):
            cols[0].link_button("地図", f"https://www.google.com/maps/search/{p.get('place')}")
        if p.get("url"):
            cols[1].link_button("URL", p.get("url"))
        if cols[2].button("編集", key=f"edit_plan_{p['id']}"):
            st.session_state[f"editing_plan_{p['id']}"] = not st.session_state.get(f"editing_plan_{p['id']}", False)
        if st.session_state.get(f"editing_plan_{p['id']}", False):
            with st.form(f"form_plan_{p['id']}"):
                d = st.date_input("年月日", value=datetime.fromisoformat(p.get("date") or today_iso()).date())
                tm = st.time_input("時間", value=datetime.strptime(p.get("time") or "09:00", "%H:%M").time())
                cat = st.selectbox("カテゴリ", CATEGORIES, index=CATEGORIES.index(p.get("category", "その他")) if p.get("category", "その他") in CATEGORIES else len(CATEGORIES)-1)
                content = st.text_input("内容", value=p.get("content", ""))
                place = st.text_input("場所", value=p.get("place", ""))
                amount = st.number_input("金額", min_value=0, step=100, value=yen(p.get("amount")))
                memo = st.text_area("メモ", value=p.get("memo", ""))
                url = st.text_input("URL", value=p.get("url", ""))
                c1, c2 = st.columns(2)
                if c1.form_submit_button("保存"):
                    p.update({"date": d.isoformat(), "time": tm.strftime("%H:%M"), "category": cat, "content": content, "place": place, "amount": int(amount), "memo": memo, "url": url})
                    save_current(group_id, trips, settings); st.session_state[f"editing_plan_{p['id']}"] = False; st.rerun()
                if c2.form_submit_button("削除"):
                    delete_item(trip["plans"], p["id"]); save_current(group_id, trips, settings); st.rerun()


def render_hotel_card(group_id: str, trips: list[dict], settings: dict, trip: dict, h: dict):
    with st.container(border=True):
        st.markdown(f"### 🏨 {h.get('hotel','宿泊')}")
        st.write(f"📅 {h.get('date','')}　📍 {h.get('place','')}　💰 {yen(h.get('amount')):,}円")
        if h.get("memo"): st.caption(h.get("memo"))
        cols = st.columns([1,1,6])
        if h.get("place"):
            cols[0].link_button("地図", f"https://www.google.com/maps/search/{h.get('place')}")
        if cols[1].button("編集", key=f"edit_hotel_{h['id']}"):
            st.session_state[f"editing_hotel_{h['id']}"] = not st.session_state.get(f"editing_hotel_{h['id']}", False)
        if st.session_state.get(f"editing_hotel_{h['id']}", False):
            with st.form(f"form_hotel_{h['id']}"):
                d = st.date_input("宿泊日", value=datetime.fromisoformat(h.get("date") or today_iso()).date())
                hotel = st.text_input("宿泊施設", value=h.get("hotel", ""))
                place = st.text_input("場所", value=h.get("place", ""))
                amount = st.number_input("金額", min_value=0, step=100, value=yen(h.get("amount")))
                memo = st.text_area("メモ", value=h.get("memo", ""))
                c1, c2 = st.columns(2)
                if c1.form_submit_button("保存"):
                    h.update({"date": d.isoformat(), "hotel": hotel, "place": place, "amount": int(amount), "memo": memo})
                    save_current(group_id, trips, settings); st.session_state[f"editing_hotel_{h['id']}"] = False; st.rerun()
                if c2.form_submit_button("削除"):
                    delete_item(trip["hotels"], h["id"]); save_current(group_id, trips, settings); st.rerun()


def render_other_card(group_id: str, trips: list[dict], settings: dict, trip: dict, o: dict):
    with st.container(border=True):
        st.markdown(f"### 📝 {o.get('content','その他')}")
        st.write(f"カテゴリ：{o.get('category','その他')}　💰 {yen(o.get('amount')):,}円")
        if o.get("memo"): st.caption(o.get("memo"))
        if st.button("編集", key=f"edit_other_{o['id']}"):
            st.session_state[f"editing_other_{o['id']}"] = not st.session_state.get(f"editing_other_{o['id']}", False)
        if st.session_state.get(f"editing_other_{o['id']}", False):
            with st.form(f"form_other_{o['id']}"):
                content = st.text_input("内容", value=o.get("content", ""))
                cat = st.selectbox("カテゴリ", CATEGORIES, index=CATEGORIES.index(o.get("category", "その他")) if o.get("category", "その他") in CATEGORIES else len(CATEGORIES)-1)
                amount = st.number_input("金額", min_value=0, step=100, value=yen(o.get("amount")))
                memo = st.text_area("メモ", value=o.get("memo", ""))
                c1, c2 = st.columns(2)
                if c1.form_submit_button("保存"):
                    o.update({"content": content, "category": cat, "amount": int(amount), "memo": memo})
                    save_current(group_id, trips, settings); st.session_state[f"editing_other_{o['id']}"] = False; st.rerun()
                if c2.form_submit_button("削除"):
                    delete_item(trip["others"], o["id"]); save_current(group_id, trips, settings); st.rerun()

# ------------------------- tabs -------------------------

def tab_schedule(group_id: str, trips: list[dict], settings: dict, trip: dict):
    st.subheader("予定を追加")

    if "last_plan_date" not in st.session_state:
        st.session_state["last_plan_date"] = date.today()
    if "last_hotel_date" not in st.session_state:
        st.session_state["last_hotel_date"] = date.today()

    with st.form("add_plan_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([1,1,1])
        d = c1.date_input("年月日", value=st.session_state["last_plan_date"])
        tm = c2.time_input("時間")
        cat = c3.selectbox("カテゴリ", CATEGORIES)
        content = st.text_input("内容")
        place = st.text_input("場所")
        amount = st.number_input("金額", min_value=0, step=100)
        memo = st.text_area("メモ")
        url = st.text_input("URL")
        if st.form_submit_button("予定を追加"):
            trip["plans"].append({"id":new_id(), "date":d.isoformat(), "time":tm.strftime("%H:%M"), "category":cat, "content":content, "place":place, "amount":int(amount), "memo":memo, "url":url})
            st.session_state["last_plan_date"] = d
            save_current(group_id, trips, settings); st.rerun()

    st.subheader("宿泊を追加")
    with st.form("add_hotel_form", clear_on_submit=True):
        d = st.date_input("宿泊日", value=st.session_state["last_hotel_date"], key="hotel_add_date")
        hotel = st.text_input("宿泊施設")
        place = st.text_input("宿泊場所")
        amount = st.number_input("宿泊金額", min_value=0, step=100)
        memo = st.text_area("宿泊メモ")
        if st.form_submit_button("宿泊を追加"):
            trip["hotels"].append({"id":new_id(), "date":d.isoformat(), "hotel":hotel, "place":place, "amount":int(amount), "memo":memo})
            st.session_state["last_hotel_date"] = d
            save_current(group_id, trips, settings); st.rerun()

    st.subheader("その他費用を追加")
    with st.form("add_other_form", clear_on_submit=True):
        content = st.text_input("内容")
        cat = st.selectbox("カテゴリ", CATEGORIES, key="other_cat")
        amount = st.number_input("金額", min_value=0, step=100, key="other_amount")
        memo = st.text_area("メモ", key="other_memo")
        if st.form_submit_button("その他を追加"):
            trip["others"].append({"id":new_id(), "content":content, "category":cat, "amount":int(amount), "memo":memo})
            save_current(group_id, trips, settings); st.rerun()

    st.subheader("タイムライン")
    timeline_items = []

    for p in trip.get("plans", []):
        timeline_items.append({
            "type": "plan",
            "date": p.get("date", ""),
            "time": p.get("time", ""),
            "sort_time": p.get("time", "99:98"),
            "data": p,
        })

    for h in trip.get("hotels", []):
        timeline_items.append({
            "type": "hotel",
            "date": h.get("date", ""),
            "time": "",
            "sort_time": "99:99",  # 同じ日の最後に宿泊を置く
            "data": h,
        })

    timeline_items = sorted(
        timeline_items,
        key=lambda x: (
            x["date"] or "9999-99-99",
            x["sort_time"] or "99:98",
        )
    )

    if not timeline_items and not trip.get("others"):
        st.info("まだ日程はありません。")

    for item in timeline_items:
        if item["type"] == "plan":
            render_plan_card(group_id, trips, settings, trip, item["data"])
        elif item["type"] == "hotel":
            render_hotel_card(group_id, trips, settings, trip, item["data"])

    for o in trip.get("others", []):
        render_other_card(group_id, trips, settings, trip, o)


def tab_packing(group_id: str, trips: list[dict], settings: dict, trip: dict):
    st.subheader("持ち物チェックリスト")
    done = sum(1 for x in trip.get("packing", []) if x.get("checked"))
    total = len(trip.get("packing", []))
    if total:
        st.progress(done / total, text=f"{done}/{total} 準備済み")
    c1, c2 = st.columns([3,1])
    item = c1.text_input("持ち物を追加")
    if c2.button("追加") and item:
        trip["packing"].append({"id":new_id(), "name":item, "checked":False})
        save_current(group_id, trips, settings); st.rerun()
    if st.button("定番セットを追加"):
        existing = {x.get("name") for x in trip.get("packing", [])}
        for name in DEFAULT_PACKING:
            if name not in existing:
                trip["packing"].append({"id":new_id(), "name":name, "checked":False})
        save_current(group_id, trips, settings); st.rerun()
    for x in trip.get("packing", []):
        c1, c2, c3 = st.columns([1,6,1])
        checked = c1.checkbox("", value=x.get("checked", False), key=f"pack_check_{x['id']}")
        if checked != x.get("checked", False):
            x["checked"] = checked; save_current(group_id, trips, settings); st.rerun()
        new_name = c2.text_input("", value=x.get("name", ""), key=f"pack_name_{x['id']}", label_visibility="collapsed")
        if new_name != x.get("name", ""):
            x["name"] = new_name; save_current(group_id, trips, settings)
        if c3.button("削除", key=f"pack_del_{x['id']}"):
            delete_item(trip["packing"], x["id"]); save_current(group_id, trips, settings); st.rerun()


def tab_cost(group_id: str, trips: list[dict], settings: dict, trip: dict):
    st.subheader("費用")
    total = total_amount(trip)
    people = max(1, len(trip.get("participants", [])) or 2)
    people = st.number_input("割り勘人数", min_value=1, value=people)
    c1, c2 = st.columns(2)
    c1.metric("合計", f"{total:,}円")
    c2.metric("一人当たり", f"{total//people:,}円")
    totals = category_totals(trip)
    if totals:
        df = pd.DataFrame([{"カテゴリ":k, "金額":v} for k,v in totals.items()])
        st.bar_chart(df, x="カテゴリ", y="金額")
        st.dataframe(df, use_container_width=True, hide_index=True)
    rows = build_rows(trip)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)


def tab_photos(group_id: str, trips: list[dict], settings: dict, trip: dict):
    st.subheader("写真")
    st.info("この版では写真URLを保存します。Supabase Storage直アップロードは次の拡張で追加できます。")
    with st.form("add_photo_url", clear_on_submit=True):
        url = st.text_input("写真URL")
        caption = st.text_input("メモ")
        if st.form_submit_button("写真を追加") and url:
            trip["photos"].append({"id":new_id(), "url":url, "caption":caption, "date":today_iso()})
            save_current(group_id, trips, settings); st.rerun()
    cols = st.columns(3)
    for i, ph in enumerate(trip.get("photos", [])):
        with cols[i % 3]:
            try:
                st.image(ph.get("url"), caption=ph.get("caption", ""), use_container_width=True)
            except Exception:
                st.write(ph.get("url"))
            if st.button("削除", key=f"photo_del_{ph['id']}"):
                delete_item(trip["photos"], ph["id"]); save_current(group_id, trips, settings); st.rerun()


def tab_weather(trip: dict):
    st.subheader("天気")
    targets = []
    for p in trip.get("plans", []):
        if p.get("date") and p.get("place"):
            targets.append((p.get("date"), p.get("place"), p.get("content", "予定")))
    for h in trip.get("hotels", []):
        if h.get("date") and h.get("place"):
            targets.append((h.get("date"), h.get("place"), h.get("hotel", "宿泊")))
    if not targets:
        st.info("予定や宿泊に日付と場所を入れると天気が表示されます。")
        return
    for d, place, label in sorted(set(targets)):
        with st.container(border=True):
            st.markdown(f"### {d} / {label}")
            st.write(f"📍 {place}")
            w, err = get_weather_for(place, d)
            if err:
                st.warning(err)
            elif w:
                st.write(f"{w.get('kind')}：{w.get('weather')}")
                st.write(f"最高 {w.get('max')}℃ / 最低 {w.get('min')}℃")
                if w.get("pop") is not None: st.write(f"降水確率 {w.get('pop')}%")
                if w.get("rain") is not None: st.write(f"降水量 {w.get('rain')}mm")

# ------------------------- main trip view -------------------------

def render_selected_trip(group_id: str, trips: list[dict], settings: dict):
    idx = selected_trip_index(trips)
    if idx is None:
        st.info("左側のサイドバーから旅行を作成してください。")
        return
    trip = normalize_trip(trips[idx])

    col_title, col_pdf, col_delete = st.columns([5,1,1])
    with col_title:
        new_title = st.text_input("旅行タイトル", value=trip.get("title", ""), key=f"title_{trip['id']}")
        if new_title != trip.get("title", ""):
            trip["title"] = new_title
            save_current(group_id, trips, settings)
    with col_pdf:
        pdf = make_pdf(trip, settings.get("app_title", "TripList"))
        st.download_button("PDF", data=pdf, file_name=f"{safe_filename(trip.get('title'))}.pdf", mime="application/pdf")
    with col_delete:
        if st.button("旅行削除", type="secondary"):
            trips.pop(idx); save_current(group_id, trips, settings); st.session_state.pop("selected_trip_id", None); st.rerun()

    with st.expander("参加者・記念日設定"):
        participants_text = st.text_input("参加者（カンマ区切り）", value=", ".join(trip.get("participants", [])))
        use_anniv = st.checkbox("記念日を使う", value=bool(trip.get("use_anniversary", False)))
        anniv_name = st.text_input("記念日の表示名", value=trip.get("anniversary_name", ""))
        anniv_date = st.date_input("記念日", value=datetime.fromisoformat(trip.get("anniversary_date") or today_iso()).date())
        if st.button("設定を保存"):
            trip["participants"] = [x.strip() for x in participants_text.split(",") if x.strip()]
            trip["use_anniversary"] = use_anniv
            trip["anniversary_name"] = anniv_name
            trip["anniversary_date"] = anniv_date.isoformat()
            save_current(group_id, trips, settings); st.rerun()
        if trip.get("use_anniversary") and trip.get("anniversary_date"):
            d = datetime.fromisoformat(trip["anniversary_date"]).date()
            days = (date.today() - d).days
            st.success(f"{trip.get('anniversary_name','記念日')}から {days} 日")

    tabs = st.tabs(["📅 日程", "🎒 持ち物", "💴 費用", "🌤️ 天気", "📸 写真"])
    with tabs[0]: tab_schedule(group_id, trips, settings, trip)
    with tabs[1]: tab_packing(group_id, trips, settings, trip)
    with tabs[2]: tab_cost(group_id, trips, settings, trip)
    with tabs[3]: tab_weather(trip)
    with tabs[4]: tab_photos(group_id, trips, settings, trip)

# ------------------------- app -------------------------

def main():
    if not render_auth_gate():
        return

    user = get_user()
    st.sidebar.success(f"ログイン中：{getattr(user, 'email', '')}")
    if st.sidebar.button("ログアウト"):
        logout()

    st.markdown("<div class='big-title'>🌷 TripList 🌿</div>", unsafe_allow_html=True)
    st.markdown("<div class='subtitle'>旅行を一緒に計画・共有するアプリ</div>", unsafe_allow_html=True)

    group_id = render_group_gate()
    if not group_id:
        return

    data = get_group_data(group_id)
    trips = [normalize_trip(t) for t in data.get("trips", [])]
    settings = data.get("settings") or DEFAULT_SETTINGS

    with st.sidebar.expander("アプリ設定"):
        app_title = st.text_input("アプリタイトル", value=settings.get("app_title", "TripList"))
        note = st.text_input("説明", value=settings.get("theme_note", ""))
        if st.button("設定保存"):
            settings["app_title"] = app_title
            settings["theme_note"] = note
            save_current(group_id, trips, settings); st.rerun()

    with st.sidebar.expander("メンバー"):
        members = get_members(group_id)
        st.write(f"{len(members)}人参加中")
        for m in members:
            st.caption(f"{m.get('role','member')} / {m.get('user_id')}")

    render_trip_sidebar(group_id, trips, settings)
    render_selected_trip(group_id, trips, settings)

if __name__ == "__main__":
    main()
