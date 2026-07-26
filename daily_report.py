"""v5.0：每日排程入口 — 產生投資報告並寄送 Email／LINE（供 Windows工作排程器每日呼叫）。

方案B（雙軌分眾）：
- Email：保留較完整的摘要（總覽＋本月建議＋風險提醒），排版更緊湊。
- LINE：只送一行極簡訊息，適合手機一眼看完，詳細內容導回 Email。
"""

import sys
from datetime import datetime

from portfolio import load_portfolio, enrich_with_market_data, build_report_context
from report import generate_investment_report, REPORT_PATH
from excel_report import generate_excel_report, EXCEL_REPORT_PATH
from pdf_report import generate_pdf_report, PDF_REPORT_PATH
import etf_quality_tracking
import notify

# 太太的 Email 用的股票/ETF 名稱玫瑰紅、代號寶藍配色與表格樣式（sector_rotation.py 已驗證過的
# 規格，也已把太太的短線輪動信改成表格化呈現），同步套用到使用者自己的每日報告 HTML 版本。
from sector_rotation import (
    HTML_BASE_FONT_PX, HTML_HEADER_FONT_PX, HTML_NAME_COLOR, HTML_CODE_COLOR,
    HTML_TABLE_HEAD_BG, HTML_TABLE_GRID,
)

PNL_RED = "#e03131"    # 台股慣例：紅漲／正向
PNL_GREEN = "#2f9e44"  # 台股慣例：綠跌／負向
SIGNAL_COLORS = {"🟢": "#2e7d32", "🟡": "#b8860b", "🟠": "#d2691e", "🔴": "#c62828"}

if hasattr(sys.stdout, "reconfigure"):
    # 命令列輸出含 emoji（LINE 摘要），非 UTF-8 主控台（如 Windows cp950）印出時會 UnicodeEncodeError
    # 而中止程式；此時 Email／LINE 通常都已寄送成功，只是收尾的 print() 崩潰，故強制輸出走 UTF-8。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _notable_signals(ctx: dict) -> list[tuple]:
    """回傳每日通知該提醒的持股：訊號非🟡（持有觀察）、不在極端虧損安靜期內、資料覆蓋率不會太低
    （避免 ETF 因為缺基本面/籌碼面資料而每天洗版一堆低信心的🔴）。
    """
    ai_scoring = ctx.get("ai_scoring", {})
    notable = []
    for h in ctx.get("holdings", []):
        r = ai_scoring.get(h.code)
        if not r or r.get("quiet"):
            continue
        if r.get("signal") not in ("🟢", "🟠", "🔴"):
            continue
        coverage = r.get("data_coverage")
        if coverage is not None and coverage < 0.5:
            continue
        notable.append((h, r))
    return notable


def build_email_summary(ctx: dict) -> str:
    total_pnl_pct_str = f"{ctx['total_pnl_pct']:+.1%}" if ctx["total_pnl_pct"] is not None else "N/A"

    real_risks = [r for r in ctx["risk"] if "無明顯" not in r]
    risk_line = "；".join(real_risks) if real_risks else "無明顯集中度風險。"

    lines = [
        f"投資日報（{datetime.now().strftime('%Y-%m-%d %H:%M')}）",
        f"總市值 {ctx['total_value']:,.0f}　總成本 {ctx['total_cost']:,.0f}　總報酬 {ctx['total_pnl']:,.0f}（{total_pnl_pct_str}）",
    ]

    goal = ctx.get("goal") or {}
    if goal:
        progress_str = f"{goal['profit_progress_pct']:+.1%}" if goal.get("profit_progress_pct") is not None else "N/A"
        pace_str = "符合預期" if goal.get("on_pace") else "落後預期"
        floor_note = "　⚠️已跌破基準總市值下限！" if goal.get("floor_breached") else ""
        lines.append(
            f"目標進度：獲利達成率 {progress_str}（{pace_str}，剩餘 {goal['days_remaining']} 天）{floor_note}"
        )

    lines.extend([
        "",
        "本月建議：",
        *[f"- {m}" for m in ctx["monthly_allocation"]],
        "",
        f"風險提醒：{risk_line}",
    ])

    notable = _notable_signals(ctx)
    if notable:
        lines.append("")
        lines.append("AI 行動建議提醒（極端虧損股在安靜期內不重複提醒，詳見附件完整報告）：")
        lines.extend(f"- {r['signal']} {h.code} {h.name}：{r['label']}" for h, r in notable)

    candidates = ctx.get("candidate_watchlist") or []
    if candidates:
        lines.append("")
        lines.append("潛力新標的觀察（目前未持有，僅供觀察，詳見附件完整報告第十節）：")
        lines.extend(
            f"- {r['conviction_stars']} {r['code']} {r['name']}　股價 {r['price']:,.1f}"
            f"（Investment Score {r['investment_score']:.0f}）"
            for r in candidates
        )

    candidates_etf = ctx.get("candidate_watchlist_etf") or []
    if candidates_etf:
        lines.append("")
        lines.append("潛力新標的觀察（ETF，目前未持有，僅供觀察，詳見附件完整報告第十節）：")
        lines.extend(
            f"- {r['conviction_stars']} {r['code']} {r['name']}　股價 {r['price']:,.1f}"
            f"（Investment Score {r['investment_score']:.0f}）"
            for r in candidates_etf
        )

    lines.append("")
    lines.append("完整報告請見附件（PDF／Excel）。")
    return "\n".join(lines)


# ── 表格化呈現（沿用 sector_rotation.py 已驗證過的表格樣式，Email HTML 版用） ──────────────
def _th(text: str) -> str:
    return (
        f'<th style="padding:6px 8px;border:1px solid {HTML_TABLE_GRID};'
        f'background:{HTML_TABLE_HEAD_BG};color:#ffffff;font-size:{HTML_BASE_FONT_PX}px;'
        f'white-space:nowrap;">{text}</th>'
    )


def _td(html_content: str) -> str:
    return (
        f'<td style="padding:6px 8px;border:1px solid {HTML_TABLE_GRID};'
        f'font-size:{HTML_BASE_FONT_PX}px;white-space:nowrap;">{html_content}</td>'
    )


def _wrap_table(header_cells: list[str], row_htmls: list[str]) -> str:
    header = "".join(_th(c) for c in header_cells)
    body = "".join(row_htmls)
    return (
        '<div style="overflow-x:auto;"><table style="border-collapse:collapse;margin:8px 0;">'
        f'<tr>{header}</tr>{body}</table></div>'
    )


def _signal_table_html(notable: list[tuple]) -> str:
    header = ["訊號", "股票名稱", "股票代號", "損益率", "Investment Score", "Risk Score", "建議"]
    rows = []
    for h, r in notable:
        marker_color = SIGNAL_COLORS.get(r["signal"], "#333333")
        pnl_pct = h.pnl_pct
        pnl_str = f"{pnl_pct:+.1%}" if pnl_pct is not None else "N/A"
        pnl_color = PNL_RED if (pnl_pct or 0) >= 0 else PNL_GREEN
        score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
        risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
        cells = [
            f'<span style="color:{marker_color};font-weight:900;">{r["signal"]}</span>',
            f'<span style="color:{HTML_NAME_COLOR};font-weight:700;">{h.name}</span>',
            f'<span style="color:{HTML_CODE_COLOR};font-weight:700;">{h.code}</span>',
            f'<span style="color:{pnl_color};font-weight:900;">{pnl_str}</span>',
            score_str,
            risk_str,
            r["label"],
        ]
        rows.append(f"<tr>{''.join(_td(c) for c in cells)}</tr>")
    return _wrap_table(header, rows)


def _candidate_table_html(candidates: list[dict]) -> str:
    header = ["星等", "名稱", "代號", "股價", "Investment Score", "Risk Score", "法人目標價", "關鍵理由"]
    rows = []
    for r in candidates:
        score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
        risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
        target_str = f"{r['target_price']:,.1f}" if r.get("target_price") is not None else "－"
        reasons_str = "；".join(r.get("reasons") or []) or "－"
        cells = [
            r.get("conviction_stars") or "－",
            f'<span style="color:{HTML_NAME_COLOR};font-weight:700;">{r["name"]}</span>',
            f'<span style="color:{HTML_CODE_COLOR};font-weight:700;">{r["code"]}</span>',
            f'{r["price"]:,.1f}',
            score_str,
            risk_str,
            target_str,
            reasons_str,
        ]
        rows.append(f"<tr>{''.join(_td(c) for c in cells)}</tr>")
    return _wrap_table(header, rows)


def build_email_html(ctx: dict) -> str:
    """`build_email_summary()` 的 HTML 版本，套用跟太太短線輪動信一致的配色與表格規格：
    股票/ETF 名稱玫瑰紅、代號寶藍（見 sector_rotation.py 的 HTML_NAME_COLOR/HTML_CODE_COLOR），
    損益/漲跌台股慣例紅漲綠跌，AI 行動建議提醒與潛力新標的觀察都改成實際 HTML `<table>` 表格
    （取代原本逐行條列），方便在手機上快速掃視比較。純文字版 `build_email_summary()` 維持條列
    格式，繼續當 multipart/alternative 的備援內容（收信端不支援 HTML 時顯示）。
    """
    total_pnl_pct_str = f"{ctx['total_pnl_pct']:+.1%}" if ctx["total_pnl_pct"] is not None else "N/A"
    pnl_color = PNL_RED if ctx["total_pnl"] >= 0 else PNL_GREEN

    parts = [
        '<div style="font-family:\'Microsoft JhengHei\',Arial,sans-serif;'
        f'font-size:{HTML_BASE_FONT_PX}px;color:#212529;line-height:1.7;">',
        f'<div style="font-size:{HTML_HEADER_FONT_PX}px;font-weight:700;margin-bottom:10px;">'
        f'投資日報（{datetime.now().strftime("%Y-%m-%d %H:%M")}）</div>',
        f'<div>總市值 {ctx["total_value"]:,.0f}　總成本 {ctx["total_cost"]:,.0f}　'
        f'總報酬 <span style="color:{pnl_color};font-weight:700;">{ctx["total_pnl"]:,.0f}'
        f'（{total_pnl_pct_str}）</span></div>',
    ]

    goal = ctx.get("goal") or {}
    if goal:
        progress_str = f"{goal['profit_progress_pct']:+.1%}" if goal.get("profit_progress_pct") is not None else "N/A"
        pace_color = PNL_RED if goal.get("on_pace") else PNL_GREEN
        pace_str = "符合預期" if goal.get("on_pace") else "落後預期"
        floor_note = ""
        if goal.get("floor_breached"):
            floor_note = f'　<span style="color:{PNL_GREEN};font-weight:700;">⚠️已跌破基準總市值下限！</span>'
        parts.append(
            f'<div>目標進度：獲利達成率 <span style="color:{pace_color};font-weight:700;">{progress_str}</span>'
            f'（{pace_str}，剩餘 {goal["days_remaining"]} 天）{floor_note}</div>'
        )

    real_risks = [r for r in ctx["risk"] if "無明顯" not in r]
    risk_line = "；".join(real_risks) if real_risks else "無明顯集中度風險。"
    parts.append(f'<div style="margin-top:10px;">風險提醒：{risk_line}</div>')

    parts.append(f'<div style="font-size:{HTML_HEADER_FONT_PX}px;font-weight:700;margin:16px 0 4px;">本月建議</div>')
    for m in ctx["monthly_allocation"]:
        if m:
            parts.append(f"<div>{m}</div>")

    notable = _notable_signals(ctx)
    if notable:
        parts.append(f'<div style="font-size:{HTML_HEADER_FONT_PX}px;font-weight:700;margin:16px 0 4px;">'
                      "AI 行動建議提醒（極端虧損股在安靜期內不重複提醒，詳見附件完整報告）</div>")
        parts.append(_signal_table_html(notable))

    def _candidate_block(title: str, candidates: list[dict]) -> None:
        if not candidates:
            return
        parts.append(f'<div style="font-size:{HTML_HEADER_FONT_PX}px;font-weight:700;margin:16px 0 4px;">{title}</div>')
        parts.append(_candidate_table_html(candidates))

    _candidate_block("潛力新標的觀察（個股，詳見附件完整報告第十節）", ctx.get("candidate_watchlist") or [])
    _candidate_block("潛力新標的觀察（ETF，詳見附件完整報告第十節）", ctx.get("candidate_watchlist_etf") or [])

    parts.append('<div style="margin-top:16px;color:#495057;">完整報告請見附件（PDF／Excel）。</div>')
    parts.append("</div>")
    return "".join(parts)


def build_line_summary(ctx: dict) -> str:
    """LINE 是廣播訊息，任何加好友的人都看得到，因此刻意不放市值等金額資訊，只放報酬率。"""
    total_pnl_pct_str = f"{ctx['total_pnl_pct']:+.1%}" if ctx["total_pnl_pct"] is not None else "N/A"
    notable_count = len(_notable_signals(ctx))
    date_str = datetime.now().strftime("%m/%d")

    parts = [f"📊 投資日報 {date_str}", f"報酬率{total_pnl_pct_str}"]
    if notable_count:
        parts.append(f"{notable_count}檔AI提醒")
    parts.append("詳見Email")
    return "｜".join(parts)


def main():
    # 背景驗證 90 天前記錄的 ETF 觀察名單（算規模/費用率/配息政策變化＋推斷原因），結果只寫進
    # etf_recommendations.json，不放進今天的日報——彙總報告是每月1日單獨寄給使用者本人
    # （見下方 maybe_send_summary，比照 spouse_report.py 對 rotation_tracking 的用法）。
    etf_quality_tracking.verify_due_recommendations()

    holdings = load_portfolio()
    enrich_with_market_data(holdings)

    ctx = build_report_context(holdings)
    etf_quality_tracking.log_recommendations(ctx.get("candidate_watchlist_etf") or [])

    content = generate_investment_report(holdings, ctx)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    generate_excel_report(EXCEL_REPORT_PATH, holdings, ctx)
    generate_pdf_report(holdings, ctx, PDF_REPORT_PATH)

    email_summary = build_email_summary(ctx)
    email_html = build_email_html(ctx)
    subject = f"【投資日報】{datetime.now().strftime('%Y-%m-%d')} 投資組合摘要"

    notify.send_email(subject, email_summary, attachments=[PDF_REPORT_PATH, EXCEL_REPORT_PATH], html_body=email_html)
    print(f"每日報告已產生並寄出 Email：{subject}")

    if notify.LINE_CHANNEL_ACCESS_TOKEN:
        line_summary = build_line_summary(ctx)
        notify.send_line_broadcast(line_summary)
        print(f"已同步發送 LINE 通知：{line_summary}")
    else:
        print("尚未設定 LINE_CHANNEL_ACCESS_TOKEN，略過 LINE 通知。")

    def _send_etf_summary_to_user(pending: list[dict]) -> None:
        summary_subject = f"【ETF觀察名單】品質追蹤月報 {datetime.now().strftime('%Y-%m-%d')}（{len(pending)}筆）"
        notify.send_email(
            summary_subject,
            etf_quality_tracking.build_summary_text(pending),
            html_body=etf_quality_tracking.build_summary_html(pending),
        )
        print(f"ETF觀察名單品質追蹤月報已寄給使用者本人（{len(pending)}筆）")

    if not etf_quality_tracking.maybe_send_summary(_send_etf_summary_to_user):
        print("今天不是每月1日或沒有新驗證紀錄，本次不寄送 ETF 品質追蹤月報。")


if __name__ == "__main__":
    main()
