import hashlib
import hmac
import io
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import qrcode
import streamlit as st

JST = timezone(timedelta(hours=9))

S = st.secrets
DB_PATH = "attendance.db"


# ---------- DB ----------
def db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "CREATE TABLE IF NOT EXISTS logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, room TEXT, "
        "action TEXT, ts TEXT)"
    )
    return con


def last_action(email, room):
    with db() as con:
        row = con.execute(
            "SELECT action, ts FROM logs WHERE email=? AND room=? ORDER BY id DESC LIMIT 1",
            (email, room),
        ).fetchone()
    # 💡 状態(入室/退室)と時間を返す
    return {"action": row[0], "ts": row[1]} if row else None


def record(email, room, action):
    ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    with db() as con:
        con.execute(
            "INSERT INTO logs(email, room, action, ts) VALUES (?,?,?,?)",
            (email, room, action, ts),
        )
    return action, ts


# ---------- QR / token ----------
def room_token(room):
    return hmac.new(S["ROOM_SECRET"].encode(), room.encode(), hashlib.sha256).hexdigest()[:16]


def room_url(room):
    return f"{S['BASE_URL']}/?room={room}&t={room_token(room)}"


def make_qr(url):
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------- ドメインチェックのみの簡易ログイン ----------
def email_allowed(email):
    domain = S.get("ALLOWED_DOMAIN", "")
    return "@" in email and (not domain or email.lower().endswith("@" + domain))


def login_ui():
    """メールアドレスを入力したら即ログイン状態にする"""
    if st.session_state.get("auth_email"):
        return st.session_state["auth_email"]

    email = st.text_input("メールアドレスを入力してください").strip().lower()
    
    if st.button("ログイン"):
        if not email:
            st.error("メールアドレスを入力してください。")
        elif not email_allowed(email):
            st.error(f"@{S.get('ALLOWED_DOMAIN', '')} のアドレスを入力してください。")
        else:
            st.session_state["auth_email"] = email
            st.rerun()
    return None


# ---------- 画面 ----------
st.set_page_config(page_title="教室 入退室記録", page_icon="🏫")
params = st.query_params
room = params.get("room")

if room:
    # 学生用: QR から来た場合
    st.title(f"🏫 {room}")
    if not hmac.compare_digest(params.get("t", ""), room_token(room)):
        st.error("QRコードが無効です。")
        st.stop()
    email = login_ui()
    if email:
        st.write(f"ログイン中: {email}")
        if st.button("ログアウト", type="secondary"):
            st.session_state.pop("auth_email", None)
            st.rerun()
            
        st.write("---")
        
        # 💡 現在のステータスを表示
        last = last_action(email, room)
        if last:
            st.info(f"現在の状態: **{last['action']}中** (最終記録: {last['ts']})")
        else:
            st.info("過去の入退室記録はありません。")

        # 💡 ボタンを別々に配置し、クリック時の処理をコールバック等に頼らず安全に実行
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🚪 入室する", type="primary", use_container_width=True):
                action, ts = record(email, room, "入室")
                st.success(f"【入室】を記録しました ({ts})")
                st.rerun()  # 画面を更新して「現在の状態」に反映
                
        with col2:
            # 入室していない状態でも押し忘れた時のために押せるように設定
            if st.button("🏃 退室する", type="secondary", use_container_width=True):
                action, ts = record(email, room, "退室")
                st.success(f"【退室】を記録しました ({ts})")
                st.rerun()  # 画面を更新して「現在の状態」に反映
else:
    # 管理者用
    st.title("管理画面")
    email = login_ui()
    if email:
        if email not in [a.lower() for a in S["ADMIN_EMAILS"]]:
            st.error("管理者ではありません。")
            st.stop()
            
        if st.button("ログアウト"):
            st.session_state.pop("auth_email", None)
            st.rerun()
            
        new_room = st.text_input("教室名(例: A101)")
        if new_room:
            url = room_url(new_room)
            st.code(url)
            png = make_qr(url)
            st.image(png, width=240)
            st.download_button("QRコードをダウンロード", png, f"{new_room}.png", "image/png")
        st.subheader("記録")
        with db() as con:
            df = pd.read_sql("SELECT * FROM logs ORDER BY id DESC", con)
        st.dataframe(df, use_container_width=True)
        st.download_button("CSVダウンロード", df.to_csv(index=False).encode("utf-8-sig"), "logs.csv")
