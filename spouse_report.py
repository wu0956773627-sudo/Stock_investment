"""短線類股輪動觀察 — 獨立寄送給太太的報告（不含使用者本人的持股明細與金額）。"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from sector_rotation import (
    scan_sector_rotation,
    build_recommendations,
    build_report_text,
    build_report_html,
    build_top_stocks_by_price,
)
from rotation_tracking import (
    log_predictions,
    verify_due_predictions,
    maybe_send_summary,
    build_summary_text,
    build_summary_html,
)
import notify

if hasattr(sys.stdout, "reconfigure"):
    # 報告內容含 ⚠ 等符號，非 UTF-8 主控台（如 Windows cp950）印出時會 UnicodeEncodeError。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

SPOUSE_EMAIL = os.getenv("SPOUSE_EMAIL")


def main():
    if not SPOUSE_EMAIL:
        raise RuntimeError("尚未設定 SPOUSE_EMAIL，請先在 .env 填入要寄送的收件信箱。")

    # 背景驗證前幾天到期的預測（算落差＋推斷原因），結果只寫進 rotation_predictions.json，
    # 不放進太太今天收到的信——彙總報告是每週五單獨寄給使用者本人（見下方 maybe_send_summary）。
    verify_due_predictions()

    scan = scan_sector_rotation()
    recommendations = build_recommendations(scan)
    top_stocks = build_top_stocks_by_price(scan)
    body = build_report_text(recommendations, top_stocks)
    html_body = build_report_html(recommendations, top_stocks)
    subject = f"【短線輪動觀察】{datetime.now().strftime('%Y-%m-%d')}"

    notify.send_email(subject, body, to_address=SPOUSE_EMAIL, bcc=notify.EMAIL_TO, html_body=html_body)
    log_predictions(recommendations, top_stocks)
    print(f"短線輪動觀察已寄出至 {SPOUSE_EMAIL}（密件副本 BCC 給 {notify.EMAIL_TO}）")
    print(body)

    def _send_summary_to_user(pending: list[dict]) -> None:
        summary_subject = f"【輪動預測追蹤彙總】{datetime.now().strftime('%Y-%m-%d')}（{len(pending)}筆）"
        notify.send_email(
            summary_subject,
            build_summary_text(pending),
            to_address=notify.EMAIL_TO,
            html_body=build_summary_html(pending),
        )
        print(f"輪動預測追蹤彙總已寄給使用者本人（{len(pending)}筆）")

    if not maybe_send_summary(_send_summary_to_user):
        print("今天不是週五或沒有新驗證紀錄，本次不寄送追蹤彙總。")


if __name__ == "__main__":
    main()
