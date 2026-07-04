from __future__ import annotations

import streamlit as st
from .config import get_supabase_client
from .utils import clean_email


def get_user():
    return st.session_state.get("user")


def set_session_from_auth_response(result):
    if getattr(result, "session", None):
        st.session_state["access_token"] = result.session.access_token
        st.session_state["refresh_token"] = result.session.refresh_token
    if getattr(result, "user", None):
        st.session_state["user"] = result.user


def restore_session():
    if st.session_state.get("user"):
        return
    access = st.session_state.get("access_token")
    refresh = st.session_state.get("refresh_token")
    if not access or not refresh:
        return
    try:
        sb = get_supabase_client()
        result = sb.auth.set_session(access, refresh)
        set_session_from_auth_response(result)
    except Exception:
        st.session_state.pop("user", None)


def logout():
    try:
        get_supabase_client().auth.sign_out()
    except Exception:
        pass
    for key in ["user", "access_token", "refresh_token", "selected_group_id", "selected_trip_id"]:
        st.session_state.pop(key, None)
    st.rerun()


def render_auth_gate() -> bool:
    restore_session()
    if get_user():
        return True

    st.markdown("""
    <div style='text-align:center; padding: 2.5rem 0 1rem 0;'>
      <h1 style='font-size:3rem;'>🌷 TripList 🌿</h1>
      <p style='font-size:1.1rem; color:#7a6256;'>ログインすると、旅行データをクラウド保存・共有できます。</p>
    </div>
    """, unsafe_allow_html=True)

    tab_login, tab_signup, tab_reset = st.tabs(["ログイン", "新規登録", "パスワード再設定"])
    sb = get_supabase_client()

    with tab_login:
        st.info("登録済みのメールアドレスとパスワードでログインしてください。")
        email = st.text_input("メールアドレス", key="login_email")
        password = st.text_input("パスワード", type="password", key="login_password")
        if st.button("ログイン", key="login_btn"):
            try:
                result = sb.auth.sign_in_with_password({
                    "email": clean_email(email),
                    "password": password,
                })
                set_session_from_auth_response(result)
                st.success("ログインしました。")
                st.rerun()
            except Exception as e:
                st.error(f"ログインできませんでした：{e}")

    with tab_signup:
        st.info("メール確認をONにしている場合、登録後に確認メールを開いてください。")
        email = st.text_input("メールアドレス", key="signup_email")
        password = st.text_input("パスワード", type="password", key="signup_password")
        password2 = st.text_input("パスワード確認", type="password", key="signup_password2")
        if st.button("新規登録", key="signup_btn"):
            if len(password) < 6:
                st.warning("パスワードは6文字以上にしてください。")
            elif password != password2:
                st.warning("パスワード確認が一致しません。")
            else:
                try:
                    result = sb.auth.sign_up({
                        "email": clean_email(email),
                        "password": password,
                    })
                    set_session_from_auth_response(result)
                    st.success("登録しました。確認メールが届いた場合は、メール内のリンクを開いてください。")
                    if get_user():
                        st.rerun()
                except Exception as e:
                    msg = str(e)
                    if "rate limit" in msg.lower():
                        st.error("短時間に登録メールを送りすぎたため、一時的に制限されています。少し待つか、Supabaseでメール確認をOFFにしてください。")
                    else:
                        st.error(f"登録できませんでした：{e}")

    with tab_reset:
        st.info("登録メールアドレスへパスワード再設定リンクを送ります。")
        email = st.text_input("メールアドレス", key="reset_email")
        if st.button("再設定メールを送る", key="reset_btn"):
            try:
                sb.auth.reset_password_email(clean_email(email))
                st.success("再設定メールを送信しました。")
            except Exception as e:
                st.error(f"送信できませんでした：{e}")

    return False
