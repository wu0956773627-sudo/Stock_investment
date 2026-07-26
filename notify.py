"""每日通知：Email（SMTP）與 LINE（Messaging API，Broadcast）。

帳密一律從本機 .env 讀取，絕不寫死在程式碼或提交進版本控制。
Gmail 需先開啟兩步驟驗證，並產生「應用程式密碼」（不是登入密碼）。

LINE 改用 Broadcast（廣播給所有已加好友的人），不需要查詢個人 User ID：
本專案的官方帳號設計為個人使用，好友只有自己，Broadcast 效果等同於 Push 給自己。
"""

import mimetypes
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO") or EMAIL_ADDRESS
SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_FOLLOWERS_URL = "https://api.line.me/v2/bot/followers/ids"


def _line_headers() -> dict:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise RuntimeError(
            "尚未設定 LINE_CHANNEL_ACCESS_TOKEN，"
            "請先在 LINE Developers Console 建立 Messaging API 頻道並發行 Channel Access Token，填入 .env。"
        )
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }


def get_follower_ids() -> list[str]:
    """取得目前所有已加官方帳號好友的 User ID 清單（不需要 webhook）。"""
    headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"} if LINE_CHANNEL_ACCESS_TOKEN else _line_headers()
    ids: list[str] = []
    params = {}
    while True:
        r = requests.get(LINE_FOLLOWERS_URL, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        ids.extend(data.get("userIds", []))
        next_token = data.get("next")
        if not next_token:
            break
        params = {"start": next_token}
    return ids


def send_line_push(user_id: str, message: str) -> None:
    """推播文字訊息給指定的單一 User ID（例如家人）。"""
    headers = _line_headers()
    payload = {"to": user_id, "messages": [{"type": "text", "text": message[:4900]}]}
    r = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=15)
    r.raise_for_status()


def send_email(
    subject: str,
    body: str,
    attachments: list[str] | None = None,
    to_address: str | None = None,
    bcc: str | None = None,
    html_body: str | None = None,
) -> None:
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        raise RuntimeError(
            "尚未設定 EMAIL_ADDRESS / EMAIL_APP_PASSWORD，"
            "請先在 .env 填入寄件 Gmail 帳號與應用程式密碼（非登入密碼）。"
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_address or EMAIL_TO
    if bcc:
        msg["Bcc"] = bcc
    msg.set_content(body)
    if html_body:
        # 純文字版當作備援（收信端不支援 HTML 時顯示），HTML 版才有顏色/字體大小樣式。
        msg.add_alternative(html_body, subtype="html")

    for path in attachments or []:
        p = Path(path)
        if not p.exists():
            continue
        # 用正確的 MIME type（例如 application/pdf）而不是一律 octet-stream：
        # 公司信箱等企業郵件伺服器的垃圾信/附件過濾器，對「型別標示不明的二進位檔」通常比較敏感。
        guessed_type, _ = mimetypes.guess_type(p.name)
        maintype, subtype = guessed_type.split("/", 1) if guessed_type else ("application", "octet-stream")
        msg.add_attachment(
            p.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=p.name,
        )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
        server.send_message(msg)


def send_line_broadcast(message: str) -> None:
    """廣播文字訊息給官方帳號的所有好友（個人使用時等同於寄給自己）。"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise RuntimeError(
            "尚未設定 LINE_CHANNEL_ACCESS_TOKEN，"
            "請先在 LINE Developers Console 建立 Messaging API 頻道並發行 Channel Access Token，填入 .env。"
        )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {"messages": [{"type": "text", "text": message[:4900]}]}

    r = requests.post(LINE_BROADCAST_URL, headers=headers, json=payload, timeout=15)
    r.raise_for_status()


if __name__ == "__main__":
    send_email("AI 投資顧問 - 測試信", "這是一封測試信，收到代表 Email 設定成功。")
    print("測試信已寄出，請檢查信箱。")

    if LINE_CHANNEL_ACCESS_TOKEN:
        send_line_broadcast("AI 投資顧問 - 測試訊息：收到代表 LINE 設定成功。")
        print("LINE 測試訊息已送出，請檢查 LINE。")
    else:
        print("尚未設定 LINE_CHANNEL_ACCESS_TOKEN，略過 LINE 測試。")
