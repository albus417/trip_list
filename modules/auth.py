from __future__ import annotations

import time
from typing import Any

import streamlit as st
from supabase import create_client

try:
    from streamlit_cookies_controller import CookieController
except Exception:
    CookieController = None


ACCESS_COOKIE = "triplist_access_token"
REFRESH_COOKIE = "triplist_refresh_token"
COOKIE_MAX_AGE_DAYS = 30


@st.cache_resource
def get_supabase_client():
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_ANON_KEY", "")

    if not url or not key:
        st.error("SUPABASE_URL と SUPABASE_ANON_KEY が未設定です。")
        st.stop()

    return create_client(url, key)


def get_cookie_controller():
    if CookieController is None:
        return None

    if "cookie_controller" not in st.session_state:
        st.session_state["cookie_controller"] = CookieController()

    return st.session_state["cookie_controller"]


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _get_attr(obj: Any, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _get_session(result: Any):
    session = _get_attr(result, "session")
    if session is not None:
        return session
    return result


def _get_user_from_result(result: Any):
    user = _get_attr(result, "user")
    if user is not None:
        return user
    session = _get_session(result)
    return _get_attr(session, "user")


def _session_tokens(session: Any) -> tuple[str | None, str | None]:
    access = _get_attr(session, "access_token")
    refresh = _get_attr(session, "refresh_token")
    return access, refresh


def _set_cookie(name: str, value: str):
    controller = get_cookie_controller()
    if controller is None or not value:
        return
    try:
        controller.set(
            name,
            value,
            max_age=60 * 60 * 24 * COOKIE_MAX_AGE_DAYS,
            same_site="strict",
            secure=True,
        )
    except TypeError:
        # ライブラリのバージョン差対策
        controller.set(name, value, max_age=60 * 60 * 24 * COOKIE_MAX_AGE_DAYS)


def _get_cookie(name: str) -> str | None:
    controller = get_cookie_controller()
    if controller is None:
        return None

    try:
        value = controller.get(name)
    except Exception:
        value = None

    if not value:
        return None
    return value


def _remove_cookie(name: str):
    controller = get_cookie_controller()
    if controller is None:
        return
    try:
        controller.remove(name)
    except Exception:
        try:
            controller.set(name, "", max_age=0)
        except Exception:
            pass


def _save_session(session: Any):
    access_token, refresh_token = _session_tokens(session)

    if access_token:
        st.session_state["access_token"] = access_token
        _set_cookie(ACCESS_COOKIE, access_token)

    if refresh_token:
        st.session_state["refresh_token"] = refresh_token
        _set_cookie(REFRESH_COOKIE, refresh_token)

    user = _get_attr(session, "user")
    if user is not None:
        st.session_state["user"] = user


def restore_auth_session() -> bool:
    """Cookieに保存されたトークンから自動ログインする。"""
    if st.session_state.get("user") is not None:
        return True

    sb = get_supabase_client()

    access_token = st.session_state.get("access_token") or _get_cookie(ACCESS_COOKIE)
    refresh_token = st.session_state.get("refresh_token") or _get_cookie(REFRESH_COOKIE)

    if not refresh_token:
        return False

    try:
        # refresh_token から新しい session を発行する。
        result = sb.auth.refresh_session(refresh_token)
        session = _get_session(result)
        user = _get_user_from_result(result) or _get_attr(session, "user")

        if session is not None:
            _save_session(session)

        if user is None and access_token:
            try:
                sb.auth.set_session(access_token, refresh_token)
                user_result = sb.auth.get_user()
                user = _get_user_from_result(user_result) or _get_attr(user_result, "user")
            except Exception:
                user = None

        if user is not None:
            st.session_state["user"] = user
            return True

    except Exception:
        # Cookieが古い・無効など。掃除してログイン画面に戻す。
        _remove_cookie(ACCESS_COOKIE)
        _remove_cookie(REFRESH_COOKIE)
        st.session_state.pop("access_token", None)
        st.session_state.pop("refresh_token", None)
        st.session_state.pop("user", None)

    return False


def get_user():
    restore_auth_session()
    return st.session_state.get("user")


def logout():
    sb = get_supabase_client()
    try:
        sb.auth.sign_out()
    except Exception:
        pass

    _remove_cookie(ACCESS_COOKIE)
    _remove_cookie(REFRESH_COOKIE)

    for key in ["user", "access_token", "refresh_token", "selected_group_id", "selected_trip_id"]:
        st.session_state.pop(key, None)

    st.success("ログアウトしました。")
    time.sleep(0.4)
    st.rerun()


def _login_form():
    st.info("登録済みのメールアドレスとパスワードでログインしてください。")

    with st.form("triplist_login_form"):
        email = st.text_input("メールアドレス", key="login_email")
        password = st.text_input("パスワード", type="password", key="login_password")
        submitted = st.form_submit_button("ログイン")

    if submitted:
        sb = get_supabase_client()
        try:
            result = sb.auth.sign_in_with_password(
                {
                    "email": _normalize_email(email),
                    "password": password,
                }
            )
            session = _get_session(result)
            user = _get_user_from_result(result)

            if session is not None:
                _save_session(session)
            if user is not None:
                st.session_state["user"] = user

            st.success("ログインしました。次回からは自動ログインします。")
            time.sleep(0.5)
            st.rerun()
        except Exception as e:
            st.error(f"ログインできませんでした：{e}")


def _signup_form():
    st.info("新規登録します。登録後、同じ画面からログインしてください。")

    with st.form("triplist_signup_form"):
        email = st.text_input("メールアドレス", key="signup_email")
        password = st.text_input("パスワード", type="password", key="signup_password")
        password2 = st.text_input("パスワード確認", type="password", key="signup_password2")
        submitted = st.form_submit_button("新規登録")

    if submitted:
        email = _normalize_email(email)

        if not email:
            st.warning("メールアドレスを入力してください。")
            return
        if len(password) < 6:
            st.warning("パスワードは6文字以上にしてください。")
            return
        if password != password2:
            st.warning("パスワードが一致していません。")
            return

        sb = get_supabase_client()
        try:
            result = sb.auth.sign_up(
                {
                    "email": email,
                    "password": password,
                }
            )
            session = _get_session(result)
            user = _get_user_from_result(result)

            if session is not None:
                _save_session(session)
            if user is not None:
                st.session_state["user"] = user

            if session is not None:
                st.success("登録してログインしました。次回からは自動ログインします。")
                time.sleep(0.5)
                st.rerun()
            else:
                st.success("登録しました。確認メールが届いている場合は確認後にログインしてください。")
        except Exception as e:
            msg = str(e)
            if "rate limit" in msg.lower():
                st.error("登録メールを送りすぎたため、一時的に制限されています。少し待つか、管理者作成ユーザーでログインしてください。")
            else:
                st.error(f"登録できませんでした：{e}")


def _reset_password_form():
    st.info("パスワード再設定メールを送ります。")
    with st.form("triplist_reset_form"):
        email = st.text_input("メールアドレス", key="reset_email")
        submitted = st.form_submit_button("再設定メールを送る")

    if submitted:
        sb = get_supabase_client()
        try:
            sb.auth.reset_password_email(_normalize_email(email))
            st.success("再設定メールを送信しました。")
        except Exception as e:
            st.error(f"送信できませんでした：{e}")


def render_auth_gate() -> bool:
    # Cookieコンポーネントを初期化するため、ここで一度呼ぶ。
    get_cookie_controller()

    if restore_auth_session():
        return True

    st.markdown("<div class='big-title'>🌷 TripList 🌿</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='subtitle'>旅行を一緒に計画・共有するアプリ</div>",
        unsafe_allow_html=True,
    )

    if CookieController is None:
        st.warning(
            "自動ログイン機能を使うには requirements.txt に streamlit-cookies-controller を追加してください。"
        )

    tabs = st.tabs(["ログイン", "新規登録", "パスワード再設定"])
    with tabs[0]:
        _login_form()
    with tabs[1]:
        _signup_form()
    with tabs[2]:
        _reset_password_form()

    return False
