from __future__ import annotations

import streamlit as st
from supabase import create_client, Client

APP_NAME = "TripList"
DEFAULT_SETTINGS = {
    "app_title": "TripList",
    "theme_note": "旅行計画をクラウドで共有できます。",
}

@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Client:
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        st.error("SUPABASE_URL と SUPABASE_ANON_KEY が未設定です。Streamlit Cloud の Secrets を確認してください。")
        st.stop()
    return create_client(url, key)
