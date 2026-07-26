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
import notify

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

    lines.append("")
    lines.append("完整報告請見附件（PDF／Excel）。")
    return "\n".join(lines)


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
    holdings = load_portfolio()
    enrich_with_market_data(holdings)

    ctx = build_report_context(holdings)

    content = generate_investment_report(holdings, ctx)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    generate_excel_report(EXCEL_REPORT_PATH, holdings, ctx)
    generate_pdf_report(holdings, ctx, PDF_REPORT_PATH)

    email_summary = build_email_summary(ctx)
    subject = f"【投資日報】{datetime.now().strftime('%Y-%m-%d')} 投資組合摘要"

    notify.send_email(subject, email_summary, attachments=[PDF_REPORT_PATH, EXCEL_REPORT_PATH])
    print(f"每日報告已產生並寄出 Email：{subject}")

    if notify.LINE_CHANNEL_ACCESS_TOKEN:
        line_summary = build_line_summary(ctx)
        notify.send_line_broadcast(line_summary)
        print(f"已同步發送 LINE 通知：{line_summary}")
    else:
        print("尚未設定 LINE_CHANNEL_ACCESS_TOKEN，略過 LINE 通知。")


if __name__ == "__main__":
    main()
