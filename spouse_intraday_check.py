"""盤中開盤強弱檢查 — 09:35（開盤30分鐘確認）／11:30（盤中觀察）各觸發一次排程，
只針對太太的短線輪動觀察標的（當天動能排名的候選股）加碼盤中訊號，寄一則簡短更新。

跟 `spouse_report.py`（05:00 的完整輪動報告）是獨立的排程。這裡重新呼叫
`sector_rotation.scan_sector_rotation()` 取得候選股，不需要額外存狀態同步早上的名單——
排名依據是日線動能（前一交易日收盤前的資料），盤中重跑理論上會得到同一組候選股。

**使用者要求範圍**：盤中強弱判斷只用在太太的短線輪動觀察，不影響使用者本人長期持股的
月度配置決策（那是完全不同性質的規則，長期持有不該被盤中噪音牽著走）。
"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from sector_rotation import (
    scan_sector_rotation,
    build_recommendations,
    HTML_TABLE_GRID,
    wrap_html_document,
)
import microstructure
import notify

if hasattr(sys.stdout, "reconfigure"):
    # 輸出含中文與符號，非 UTF-8 主控台（如 Windows cp950）印出時會 UnicodeEncodeError。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()
SPOUSE_EMAIL = os.getenv("SPOUSE_EMAIL")

MICRO_DISCLAIMER = (
    "盤中強弱評分是規則型的粗略觀察因子（開盤溢價率／30分鐘量能確認／盤中拉回幅度），"
    "沒有經過統計驗證，不是必勝公式，僅供參考，不建議單獨依此追高或殺低。"
)

# 跟 sector_rotation.py 用同一套配色與字級規則，讓太太收到的兩封信視覺一致。
HTML_BASE_FONT_PX = 15
HTML_HEADER_FONT_PX = 17
HTML_STOCK_FONT_PX = 16
HTML_NAME_COLOR = "#c2255c"
HTML_CODE_COLOR = "#1864ab"


def _collect_intraday_results(recommendations: list[dict]) -> list[dict]:
    """對每檔候選股（去重）呼叫一次 microstructure.evaluate()，結果同時供文字版與 HTML 版使用，
    避免兩份 render 各自重打一次 API。"""
    seen: set[str] = set()
    results = []
    for r in recommendations:
        code = r["code"]
        if code in seen:
            continue
        seen.add(code)

        result = microstructure.evaluate(code, None)
        if result["score"] is None:
            continue
        results.append({"code": code, "name": r["name"], **result})
    return results


def build_intraday_text(results: list[dict]) -> str:
    now = datetime.now()
    lines = [f"盤中開盤強弱觀察（{now.strftime('%Y-%m-%d %H:%M')}）", ""]

    if not results:
        lines.append("目前抓不到盤中資料（可能非交易時段或資料尚未更新），暫無更新。")
        lines.append("")
    else:
        for r in results:
            premium_str = f"{r['premium']:+.1%}" if r["premium"] is not None else "N/A"
            lines.append(f"■ {r['name']}（{r['code']}）　開盤溢價：{premium_str}　盤中強弱分數：{r['score']:.0f}/100")
            if r["flags"]:
                lines.extend(f"　・{flag}" for flag in r["flags"])
            else:
                lines.append("　・目前無特別訊號")
            lines.append("")

    lines.append(MICRO_DISCLAIMER)
    return "\n".join(lines)


def _intraday_card_html(r: dict) -> str:
    """每檔股票一張卡片（純 `<div>` 堆疊，不用 `<table>`）。跟 sector_rotation._format_stock_html()
    同一套做法——`<table>` + overflow-x:auto 橫向捲動、`<table>` + media query 響應式卡片化
    兩種都實測過，手機版 Gmail App 會把超出螢幕寬度的欄位直接裁掉，只有純 `<div>` 堆疊能保證
    不會裁切。"""
    premium_str = f"{r['premium']:+.1%}" if r["premium"] is not None else "N/A"
    flags_html = "".join(f'<div style="margin-top:2px;">・{flag}</div>' for flag in r["flags"]) if r["flags"] else '<div style="margin-top:2px;">・目前無特別訊號</div>'

    return (
        f'<div style="border:1px solid {HTML_TABLE_GRID};border-radius:8px;'
        f'padding:8px 10px;margin:8px 0;font-size:{HTML_BASE_FONT_PX}px;line-height:1.6;">'
        f'<div style="margin-bottom:3px;">'
        f'<span style="color:{HTML_NAME_COLOR};font-weight:700;font-size:{HTML_STOCK_FONT_PX}px;">{r["name"]}</span>'
        f'（<span style="color:{HTML_CODE_COLOR};font-weight:700;font-size:{HTML_STOCK_FONT_PX}px;">{r["code"]}</span>）'
        f'</div>'
        f'<div>開盤溢價：{premium_str}　盤中強弱分數：{r["score"]:.0f}/100</div>'
        f'{flags_html}'
        f'</div>'
    )


def build_intraday_html(results: list[dict]) -> str:
    """跟 build_intraday_text() 內容相同，改用逐檔卡片（`<div>` 堆疊）呈現，跟
    sector_rotation.build_report_html() 的做法一致，股票名稱／代號沿用醒目對比色，
    字體全面加大（14.5~16px 以上）。"""
    now = datetime.now()
    parts = [
        '<div style="font-family:\'Microsoft JhengHei\',Arial,sans-serif;'
        f'font-size:{HTML_BASE_FONT_PX}px;color:#212529;line-height:1.7;">',
        f'<div style="font-size:{HTML_HEADER_FONT_PX}px;font-weight:700;margin-bottom:10px;">'
        f'盤中開盤強弱觀察（{now.strftime("%Y-%m-%d %H:%M")}）</div>',
    ]

    if not results:
        parts.append(f'<div style="font-size:{HTML_BASE_FONT_PX}px;">目前抓不到盤中資料（可能非交易時段或資料尚未更新），暫無更新。</div>')
    else:
        parts.extend(_intraday_card_html(r) for r in results)

    parts.append(f'<div style="font-size:14.5px;color:#495057;margin-top:16px;">{MICRO_DISCLAIMER}</div>')
    parts.append("</div>")
    return wrap_html_document("".join(parts))


def main():
    if not SPOUSE_EMAIL:
        raise RuntimeError("尚未設定 SPOUSE_EMAIL，請先在 .env 填入要寄送的收件信箱。")

    if not microstructure.is_trading_session_now():
        print("目前非交易時段（週末／國定假日／尚未開盤或已收盤），略過本次盤中觀察，不寄送。")
        return

    scan = scan_sector_rotation()
    recommendations = build_recommendations(scan)
    results = _collect_intraday_results(recommendations)
    body = build_intraday_text(results)
    html_body = build_intraday_html(results)
    subject = f"【盤中觀察】{datetime.now().strftime('%Y-%m-%d %H:%M')}"

    notify.send_email(subject, body, to_address=SPOUSE_EMAIL, bcc=notify.EMAIL_TO, html_body=html_body)
    print(f"盤中觀察已寄出至 {SPOUSE_EMAIL}（BCC 給 {notify.EMAIL_TO}）")
    print(body)


if __name__ == "__main__":
    main()
