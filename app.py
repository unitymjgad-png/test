import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
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
    return {"action": row[0], "ts": row[1]} if row else None


def record(email, room, action):
    ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    with db() as con:
        con.execute(
            "INSERT INTO logs(email, room, action, ts) VALUES (?,?,?,?)",
            (email, room, action, ts),
        )
    return action, ts


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


# ---------- 画面表示 ----------
st.set_page_config(page_title="教室 入退室記録システム", page_icon="🏫")
st.title("🏫 教室 入退室記録")

# 1. まずはログイン
email = login_ui()

if email:
    st.write(f"👤 ログイン中: {email}")
    if st.button("ログアウト", type="secondary"):
        st.session_state.pop("auth_email", None)
        st.rerun()
        
    st.write("---")
    
    # 2. 記録対象の教室を入力・または選択
    # （よく使う教室が決まっている場合は、st.selectbox(["120", "A101"], index=0) に変更も可能です）
    room = st.text_input("教室名を入力してください (例: 120, A101)").strip()
    
    if room:
        # 現在のステータスを表示
        last = last_action(email, room)
        if last:
            st.info(f"💡 現在のステータス: **{last['action']}中** (最終記録: {last['ts']})")
        else:
            st.info("💡 この教室の過去の入退室記録はありません。")

        # 3. 「入室」「退室」ボタンを横並びで配置
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🚪 入室を記録する", type="primary", use_container_width=True):
                action, ts = record(email, room, "入室")
                st.success(f"【入室】を記録しました ({ts})")
                st.rerun()
                
        with col2:
            if st.button("🏃 退室を記録する", type="secondary", use_container_width=True):
                action, ts = record(email, room, "退室")
                st.success(f"【退室】を記録しました ({ts})")
                st.rerun()

    st.write("---")
    
    # 4. 画面の下部に全員の全記録ログを表示（誰でも確認・CSVダウンロード可能）
    st.subheader("📊 全体の入退室記録一覧")
    with db() as con:
        df = pd.read_sql("SELECT id, email, room, action, ts FROM logs ORDER BY id DESC", con)
    
    st.dataframe(df, use_container_width=True)
    st.download_button(
        "CSVとしてダウンロード", 
        df.to_csv(index=False).encode("utf-8-sig"), 
        "attendance_logs.csv",
        "text/csv"
    )
