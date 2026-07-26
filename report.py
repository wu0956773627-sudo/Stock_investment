"""產出固定格式的「投資報告」檔案（Markdown），做為每次更新的投資檔案。"""

from datetime import datetime

from portfolio import build_report_context, weight, cost_weight


REPORT_PATH = "投資報告.md"

DISCLAIMER = (
    "本報告依公開市場資料與規則化邏輯自動產生，僅供個人投資參考，"
    "不構成任何形式的投資建議或保證，投資決策與風險請自行評估承擔。"
)


def _holding_table(holdings, total_value, total_cost) -> str:
    header = "| 代號 | 名稱 | 股數 | 平均成本 | 現價 | 市值 | 損益(率) | 市值佔比 | 成本佔比 |\n"
    header += "|---|---|---:|---:|---:|---:|---:|---:|---:|\n"
    rows = []
    for h in holdings:
        price = f"{h.price:,.2f}" if h.price is not None else "N/A"
        mv = f"{h.market_value:,.0f}" if h.market_value is not None else "N/A"
        pnl = f"{h.pnl:,.0f} ({h.pnl_pct:.1%})" if h.pnl is not None and h.pnl_pct is not None else "N/A"
        w = weight(h, total_value)
        cw = cost_weight(h, total_cost)
        w_str = f"{w:.1%}" if w is not None else "N/A"
        cw_str = f"{cw:.1%}" if cw is not None else "N/A"
        rows.append(f"| {h.code} | {h.name} | {h.shares:,.0f} | {h.avg_cost:,.2f} | {price} | {mv} | {pnl} | {w_str} | {cw_str} |")
    return header + "\n".join(rows)


def _fundamentals_table(holdings) -> str:
    header = "| 代號 | 名稱 | 產業 | 本益比(TTM/預估) | EPS(TTM/預估) | 法人目標價 | 法人評等 | 殖利率 |\n"
    header += "|---|---|---|---:|---:|---:|---|---:|\n"
    rows = []
    for h in holdings:
        pe = f"{h.trailing_pe:.1f}/{h.forward_pe:.1f}" if h.trailing_pe and h.forward_pe else "N/A"
        eps = f"{h.trailing_eps:.2f}/{h.forward_eps:.2f}" if h.trailing_eps and h.forward_eps else "N/A"
        target = f"{h.target_mean_price:,.1f}" if h.target_mean_price else "N/A"
        rec = h.recommendation or "N/A"
        div = f"{h.dividend_yield:.2f}%" if h.dividend_yield else "N/A"
        rows.append(f"| {h.code} | {h.name} | {h.industry or h.sector or 'N/A'} | {pe} | {eps} | {target} | {rec} | {div} |")
    return header + "\n".join(rows)


def _ai_scoring_section(holdings, ai_scoring: dict) -> list[str]:
    lines = []
    for h in holdings:
        r = ai_scoring.get(h.code)
        if not r:
            lines.append(f"- {h.code} {h.name}：尚無評分資料。")
            continue

        score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
        risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
        target_str = f"／法人目標價 {r['target_price']:,.1f}" if r.get("target_price") is not None else ""
        star = "⭐" if r.get("star") else ""

        lines.append(
            f"- {star}{r['signal']} **{h.code} {h.name}**：{r['label']}"
            f"（Investment Score {score_str}／Risk Score {risk_str}{target_str}）"
        )
        if r.get("reasons"):
            lines.append(f"  - 關鍵理由：{'；'.join(r['reasons'])}")
    if not lines:
        lines.append("- 暫無資料。")
    return lines


def _candidate_watchlist_section(candidates: list[dict]) -> list[str]:
    """目前沒有持有、評分較高的候選新標的（跟既有持股分開，回答「還有沒有值得考慮加入的新標的」，
    不是「該不該對目前持股採取行動」）。"""
    if not candidates:
        return ["- 目前抓不到候選新標的資料，或候選池股票都已在你的持股中。"]

    lines = []
    for tier, tier_label in (("high", "高價股"), ("low", "低價股")):
        group = [r for r in candidates if r.get("price_tier") == tier]
        if not group:
            continue
        lines.append(f"**{tier_label}**")
        for r in group:
            score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
            risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
            target_str = f"／法人目標價 {r['target_price']:,.1f}" if r.get("target_price") is not None else ""
            lines.append(
                f"- {r['conviction_stars']} **{r['code']} {r['name']}**　"
                f"股價 {r['price']:,.1f}（Investment Score {score_str}／Risk Score {risk_str}{target_str}）"
            )
            if r.get("reasons"):
                lines.append(f"  - 關鍵理由：{'；'.join(r['reasons'])}")
        lines.append("")
    return lines


def _goal_section(goal: dict) -> list[str]:
    if not goal:
        return []
    progress_str = f"{goal['profit_progress_pct']:+.1%}" if goal.get("profit_progress_pct") is not None else "N/A"
    pace_str = "✅ 進度符合預期" if goal.get("on_pace") else "⚠️ 進度落後預期"
    floor_str = "⚠️ 已跌破基準總市值下限！" if goal.get("floor_breached") else "✅ 總市值仍在基準之上"
    return [
        f"- 目標期間：{goal['baseline_date']} ~ {goal['target_date']}（剩餘 {goal['days_remaining']} 天）",
        f"- 基準總市值：新台幣 {goal['baseline_value']:,.0f} 元",
        f"- 獲利目標：累積獲利達新台幣 {goal['profit_target']:,.0f} 元（目前累積獲利 {goal['current_pnl']:,.0f} 元，達成率 {progress_str}）",
        f"- 進度評估：{pace_str}",
        f"- 下限檢查（總市值不得低於基準）：{floor_str}（目前總市值 {goal['current_value']:,.0f} 元）",
    ]


def _market_intel_section(holdings, market_intel: dict) -> list[str]:
    lines = []
    for h in holdings:
        info = market_intel.get(h.code)
        if not info:
            continue

        parts = [f"**{h.code} {h.name}**"]

        rev = info.get("monthly_revenue")
        if rev:
            yoy = rev.get("營業收入-去年同月增減(%)")
            month = rev.get("資料年月")
            if yoy not in (None, ""):
                parts.append(f"月營收({month})年增率 {float(yoy):+.1f}%")

        inc = info.get("income_statement") or {}
        if inc.get("revenue") is not None:
            revenue_str = f"{float(inc['revenue']):,.0f}仟元"
            parts.append(
                f"{inc.get('quarter', '最新季')}營收 {revenue_str}"
                + (f"／EPS {inc['eps']}元" if inc.get("eps") else "")
            )

        material_news = info.get("material_news") or []
        if material_news:
            parts.append(f"今日重大訊息 {len(material_news)} 則：" + "；".join(n.get("主旨", "").strip() for n in material_news[:2]))

        conf = info.get("investor_conference")
        if conf:
            parts.append(f"下一場法說會 {conf['date']} {conf['time']}，地點：{conf['location']}")

        flow = info.get("institutional_flow")
        if flow and flow.get("total_net") is not None:
            if flow.get("foreign_net") is not None:
                parts.append(
                    f"三大法人買賣超 {flow['total_net']:+,.0f} 股"
                    f"（外資 {flow['foreign_net']:+,.0f}／投信 {flow['trust_net']:+,.0f}／自營商 {flow['dealer_net']:+,.0f}）"
                )
            else:
                parts.append(f"三大法人買賣超合計 {flow['total_net']:+,.0f} 股")

        lines.append("- " + "，".join(parts))

        for n in (info.get("general_news") or [])[:3]:
            lines.append(f"  - [{n['title']}]({n['link']})")

    if not lines:
        lines.append("- 暫無資料。")
    return lines


def generate_investment_report(holdings=None, ctx=None) -> str:
    if holdings is None:
        from portfolio import load_portfolio, enrich_with_market_data
        holdings = load_portfolio()
        enrich_with_market_data(holdings)

    if ctx is None:
        ctx = build_report_context(holdings)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append(f"# 投資報告\n")
    lines.append(f"更新時間：{now}\n")

    lines.append("## 個人短期目標追蹤\n")
    lines.extend(_goal_section(ctx.get("goal", {})))
    lines.append("")

    lines.append("## 一、投資組合總覽\n")
    total_pnl_pct_str = f"{ctx['total_pnl_pct']:.1%}" if ctx["total_pnl_pct"] is not None else "N/A"
    lines.append(f"- 總成本：新台幣 {ctx['total_cost']:,.0f} 元")
    lines.append(f"- 總市值：新台幣 {ctx['total_value']:,.0f} 元")
    lines.append(f"- 總報酬：新台幣 {ctx['total_pnl']:,.0f} 元（{total_pnl_pct_str}）")
    idx = ctx.get("market_index")
    if idx and idx.get("close") is not None:
        change_str = f"{idx['change_points']:+,.2f}（{idx['change_pct']:+.2f}%）" if idx.get("change_points") is not None else "N/A"
        lines.append(f"- 大盤{idx['name']}：{idx['close']:,.2f} 點，漲跌 {change_str}（{idx.get('date', '')}）\n")
    else:
        lines.append("")
    lines.append(_holding_table(holdings, ctx["total_value"], ctx["total_cost"]))
    lines.append("")

    lines.append("## 二、個股分析\n")
    lines.append(_fundamentals_table(holdings))
    lines.append("")

    lines.append("## 三、合理買點\n")
    for bp in ctx["buy_points"]:
        lines.append(f"- {bp}")
    lines.append("")

    lines.append("## 四、AI 綜合評分與行動建議\n")
    lines.append(
        "*AI 的目標不是預測股價，而是回答「該不該採取行動」：結合股票本身的六構面加權評分"
        "（基本面30%／成長性20%／籌碼面15%／技術面15%／估值10%／市場環境10%，缺資料的子項目"
        "會標註「資料覆蓋率低」而非硬湊分數）與目前的持股狀態，換算成 Investment Score(0-100)"
        "＋獨立的 Risk Score(0-100，越高風險越高)，最終只給四種結論：🟢加碼買進／🟡持有觀察／"
        "🟠分批獲利了結／🔴全數賣出。極端虧損部位（≤-70%）除非出現重大利多/利空新聞，"
        "不會每天重複提醒同一個「建議停損」。*\n"
    )
    cash = ctx.get("available_cash", 0)
    lines.append(
        f"- 個人化設定：可投入現金 新台幣 {cash:,.0f} 元／風險承受能力 {ctx.get('risk_tolerance', 'N/A')}"
        f"／投資期限 {ctx.get('investment_horizon', 'N/A')}\n"
    )
    lines.extend(_ai_scoring_section(holdings, ctx.get("ai_scoring", {})))
    lines.append("")

    lines.append("## 五、產業配置建議\n")
    for sector, w in ctx["sector_allocation"].items():
        lines.append(f"- {sector}：{w:.1%}")
    lines.append("")
    for advice in ctx["sector_advice"]:
        lines.append(f"- {advice}")
    lines.append("")

    lines.append("## 六、風險評估與再平衡\n")
    lines.append("**風險評估：**")
    for r in ctx["risk"]:
        lines.append(f"- {r}")
    lines.append("\n**再平衡建議：**")
    for r in ctx["rebalance"]:
        lines.append(f"- {r}")
    lines.append("")

    lines.append("## 七、每月投資建議\n")
    lines.extend(ctx["monthly_allocation"])
    lines.append("")

    lines.append("## 八、後續追蹤重點\n")
    for f in ctx["monthly_focus"]:
        lines.append(f"- {f}")
    lines.append("")

    lines.append("## 九、市場情報：月營收、財報、新聞、法說會、三大法人買賣超\n")
    lines.append(
        "*月營收／財報資料來源：台灣證交所 OpenAPI（僅涵蓋上市公司）；新聞來源：Google 新聞；"
        "法說會來源：公開資訊觀測站；三大法人買賣超來源：證交所（上市，含細項）／櫃買中心（上櫃，僅合計）。*\n"
    )
    lines.extend(_market_intel_section(holdings, ctx.get("market_intel", {})))
    lines.append("")

    lines.append("## 十、潛力新標的觀察\n")
    lines.append(
        "*人工整理的權值股／優質股／熱門ETF候選池，篩掉目前追高的標的，"
        "依 Investment Score 分「高價股」「低價股」各挑出評分最高的幾檔，僅供觀察參考，非買進建議。*\n"
    )
    lines.extend(_candidate_watchlist_section(ctx.get("candidate_watchlist", [])))
    lines.append("")

    lines.append("---")
    lines.append(f"*{DISCLAIMER}*")

    return "\n".join(lines)


def save_report(path: str = REPORT_PATH) -> str:
    content = generate_investment_report()
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


if __name__ == "__main__":
    saved_path = save_report()
    print(f"投資報告已產生：{saved_path}")
