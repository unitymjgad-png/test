import hashlib
import hmac
import io
import secrets
import smtplib
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pandas as pd
import qrcode
import streamlit as st

JST = timezone(timedelta(hours=9))
OTP_TTL = 600  # 秒
MAX_ATTEMPTS = 5

S = st.secrets
DB_PATH = "attendance.db"  # 試作用。本番は Supabase / Google Sheets などに置き換え


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
            "SELECT action FROM logs WHERE email=? AND room=? ORDER BY id DESC LIMIT 1",
            (email, room),
        ).fetchone()
    return row[0] if row else None


def record(email, room):
    action = "退室" if last_action(email, room) == "入室" else "入室"
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


# ---------- メール認証 ----------
def send_otp(email, code):
    msg = EmailMessage()
    msg["Subject"] = "入退室記録の認証コード"
    msg["From"] = S["FROM_ADDR"]
    msg["To"] = email
    msg.set_content(f"認証コード: {code}\n有効期限は {OTP_TTL // 60} 分です。")
    with smtplib.SMTP(S["SMTP_HOST"], int(S["SMTP_PORT"])) as smtp:
        smtp.starttls()
        smtp.login(S["SMTP_USER"], S["SMTP_PASSWORD"])
        smtp.send_message(msg)


def hash_code(code, email):
    return hashlib.sha256(f"{code}:{email}:{S['ROOM_SECRET']}".encode()).hexdigest()


def email_allowed(email):
    domain = S.get("ALLOWED_DOMAIN", "")
    return "@" in email and (not domain or email.lower().endswith("@" + domain))


def login_ui():
    """認証済みならメールアドレスを返す。未認証なら入力UIを出して None。"""
    if st.session_state.get("auth_email"):
        return st.session_state["auth_email"]

    email = st.text_input("メールアドレス").strip().lower()
    if st.button("認証コードを送信"):
        if not email_allowed(email):
            st.error(f"@{S.get('ALLOWED_DOMAIN', '')} のアドレスを入力してください。")
        else:
            code = f"{secrets.randbelow(10**6):06d}"
            send_otp(email, code)
            st.session_state["otp"] = {
                "email": email,
                "hash": hash_code(code, email),
                "exp": time.time() + OTP_TTL,
                "tries": 0,
            }
            st.success("コードを送信しました。メールを確認してください。")

    otp = st.session_state.get("otp")
    if otp:
        code_in = st.text_input("6桁のコード", max_chars=6)
        if st.button("確認"):
            otp["tries"] += 1
            if time.time() > otp["exp"] or otp["tries"] > MAX_ATTEMPTS:
                st.session_state.pop("otp")
                st.error("コードが無効です。最初からやり直してください。")
            elif hmac.compare_digest(hash_code(code_in, otp["email"]), otp["hash"]):
                st.session_state["auth_email"] = otp["email"]
                st.session_state.pop("otp")
                st.rerun()
            else:
                st.error("コードが違います。")
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
        nxt = "退室" if last_action(email, room) == "入室" else "入室"
        if st.button(f"{nxt}を記録する", type="primary"):
            action, ts = record(email, room)
            st.success(f"{action}を記録しました({ts})")
else:
    # 管理者用
    st.title("管理画面")
    email = login_ui()
    if email:
        if email not in [a.lower() for a in S["ADMIN_EMAILS"]]:
            st.error("管理者ではありません。")
            st.stop()
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
