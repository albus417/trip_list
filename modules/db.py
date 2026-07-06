from __future__ import annotations

import streamlit as st
from .auth import get_user
from .config import get_supabase_client, DEFAULT_SETTINGS
from .utils import make_invite_code, now_iso

def get_authed_supabase_client():
    sb = get_authed_supabase_client()
    token = st.session_state.get("access_token")

    if token:
        sb.postgrest.auth(token)

    return sb

def current_user_id() -> str:
    user = get_user()
    if user is None:
        return ""

    if isinstance(user, dict):
        return user.get("id", "")

    return getattr(user, "id", "")


def list_my_groups() -> list[dict]:
    sb = get_authed_supabase_client()
    uid = current_user_id()
    if not uid:
        return []
    memberships = sb.table("trip_group_members").select("group_id, role, trip_groups(id,name,invite_code,created_at)").eq("user_id", uid).execute().data or []
    groups = []
    for row in memberships:
        g = row.get("trip_groups") or {}
        if g:
            g["role"] = row.get("role", "member")
            groups.append(g)
    groups.sort(key=lambda x: x.get("created_at", ""))
    return groups


def create_group(name: str) -> str:
    """Create a shared group. Joining requires only the invite_code."""
    sb = get_authed_supabase_client()
    uid = current_user_id()
    invite_code = make_invite_code()
    group = sb.table("trip_groups").insert({
        "name": name.strip() or "旅行グループ",
        "invite_code": invite_code,
        "created_by": uid,
    }).execute().data[0]
    group_id = group["id"]
    sb.table("trip_group_members").insert({
        "group_id": group_id,
        "user_id": uid,
        "role": "admin",
    }).execute()
    sb.table("trip_group_data").insert({
        "group_id": group_id,
        "trips": [],
        "settings": DEFAULT_SETTINGS,
    }).execute()
    return group_id


def join_group(invite_code: str) -> str | None:
    sb = get_authed_supabase_client()
    uid = current_user_id()
    code = (invite_code or "").strip().upper()

    if not code:
        st.error("招待コードが空です。")
        return None

    if not uid:
        st.error("ログイン中のユーザーIDが取得できていません。ログアウトして再ログインしてください。")
        return None

    groups = (
        sb.table("trip_groups")
        .select("id,name,invite_code")
        .eq("invite_code", code)
        .limit(1)
        .execute()
        .data
        or []
    )

    if not groups:
        return None

    group_id = groups[0]["id"]

    existing = (
        sb.table("trip_group_members")
        .select("group_id")
        .eq("group_id", group_id)
        .eq("user_id", uid)
        .execute()
        .data
        or []
    )

    if not existing:
        sb.table("trip_group_members").insert({
            "group_id": group_id,
            "user_id": uid,
            "role": "member",
        }).execute()

    return group_id

def get_group_data(group_id: str) -> dict:
    sb = get_authed_supabase_client()
    rows = sb.table("trip_group_data").select("trips,settings,updated_at").eq("group_id", group_id).limit(1).execute().data or []
    if not rows:
        sb.table("trip_group_data").insert({"group_id": group_id, "trips": [], "settings": DEFAULT_SETTINGS}).execute()
        return {"trips": [], "settings": DEFAULT_SETTINGS}
    return {"trips": rows[0].get("trips") or [], "settings": rows[0].get("settings") or DEFAULT_SETTINGS}


def save_group_data(group_id: str, trips: list[dict], settings: dict):
    sb = get_authed_supabase_client()
    sb.table("trip_group_data").upsert({
        "group_id": group_id,
        "trips": trips,
        "settings": settings or DEFAULT_SETTINGS,
        "updated_at": now_iso(),
    }).execute()


def rename_group(group_id: str, name: str):
    get_supabase_client().table("trip_groups").update({"name": name.strip()}).eq("id", group_id).execute()


def get_members(group_id: str) -> list[dict]:
    sb = get_authed_supabase_client()
    return sb.table("trip_group_members").select("user_id,role,joined_at").eq("group_id", group_id).execute().data or []
