"""產出固定格式的「投資報告」檔案（Markdown），做為每次更新的投資檔案。"""

from datetime import datetime

from portfolio import (
    build_report_context,
    weight,
    cost_weight,
    current_price_display,
    industry_or_sector_label_zh,
    market_intel_highlight,
    MAX_CARRYOVER_MONTHS,
)


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
    header = "| 代號 | 名稱 | 產業 | 本益比(TTM/預估) | EPS(TTM/預估) | 目前股價 | 法人目標價 | 法人評等 | 殖利率 |\n"
    header += "|---|---|---|---:|---:|---:|---:|---|---:|\n"
    rows = []
    for h in holdings:
        pe = f"{h.trailing_pe:.1f}/{h.forward_pe:.1f}" if h.trailing_pe and h.forward_pe else "N/A"
        eps = f"{h.trailing_eps:.2f}/{h.forward_eps:.2f}" if h.trailing_eps and h.forward_eps else "N/A"
        current_price = current_price_display(h)
        target = f"{h.target_mean_price:,.1f}" if h.target_mean_price else "N/A"
        rec = h.recommendation or "N/A"
        div = f"{h.dividend_yield:.2f}%" if h.dividend_yield else "N/A"
        rows.append(
            f"| {h.code} | {h.name} | {industry_or_sector_label_zh(h)} | {pe} | {eps} | {current_price} | {target} | {rec} | {div} |"
        )
    return header + "\n".join(rows)


def _buy_points_table(buy_points_data: list[dict]) -> str:
    header = "| 代號 | 名稱 | 近一年區間 | 建議承接區間 | 現價位置 | 法人目標價 | 上漲空間 |\n"
    header += "|---|---|---|---|---|---:|---:|\n"
    rows = []
    for bp in buy_points_data:
        week52 = bp.get("week52_range") or "N/A"
        zone = bp.get("suggested_zone") or "N/A"
        pos = bp.get("price_position") or "N/A"
        target = f"{bp['target_price']:,.1f}" if bp.get("target_price") is not None else "N/A"
        upside = f"{bp['upside_pct']:+.1%}" if bp.get("upside_pct") is not None else "N/A"
        rows.append(f"| {bp['code']} | {bp['name']} | {week52} | {zone} | {pos} | {target} | {upside} |")
    if not rows:
        rows.append("| N/A | N/A | N/A | N/A | 暫無資料。 | N/A | N/A |")
    return header + "\n".join(rows)


def _ai_scoring_table(holdings, ai_scoring: dict) -> str:
    header = "| 訊號 | 代號 | 名稱 | 說明 | Investment Score | Risk Score | 法人目標價 | 關鍵理由 |\n"
    header += "|---|---|---|---|---:|---:|---:|---|\n"
    rows = []
    for h in holdings:
        r = ai_scoring.get(h.code)
        if not r:
            rows.append(f"| N/A | {h.code} | {h.name} | 尚無評分資料。 | N/A | N/A | N/A | N/A |")
            continue

        star = "⭐" if r.get("star") else ""
        signal = f"{star}{r['signal']}"
        score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
        risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
        target_str = f"{r['target_price']:,.1f}" if r.get("target_price") is not None else "N/A"
        reasons = "<br>".join(r.get("reasons") or []) or "N/A"
        rows.append(f"| {signal} | {h.code} | {h.name} | {r['label']} | {score_str} | {risk_str} | {target_str} | {reasons} |")
    if not rows:
        rows.append("| N/A | N/A | N/A | 暫無資料。 | N/A | N/A | N/A | N/A |")
    return header + "\n".join(rows)


def _candidate_table(candidates: list[dict]) -> str:
    header = "| 星等 | 代號 | 名稱 | 股價 | Investment Score | Risk Score | 法人目標價 | 關鍵理由 |\n"
    header += "|---|---|---|---:|---:|---:|---:|---|\n"
    rows = []
    for r in candidates:
        score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
        risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
        target_str = f"{r['target_price']:,.1f}" if r.get("target_price") is not None else "N/A"
        reasons = "<br>".join(r.get("reasons") or []) or "N/A"
        rows.append(
            f"| {r.get('conviction_stars') or 'N/A'} | {r['code']} | {r['name']} | {r['price']:,.1f} | "
            f"{score_str} | {risk_str} | {target_str} | {reasons} |"
        )
    return header + "\n".join(rows)


def _candidate_watchlist_section(candidates: list[dict]) -> list[str]:
    """目前沒有持有、評分較高的候選新標的（跟既有持股分開，回答「還有沒有值得考慮加入的新標的」，
    不是「該不該對目前持股採取行動」）。"""
    if not candidates:
        return ["目前抓不到候選新標的資料，或候選池股票都已在你的持股中。"]

    lines = []
    for tier, tier_label in (("high", "高價股"), ("low", "低價股")):
        group = [r for r in candidates if r.get("price_tier") == tier]
        if not group:
            continue
        lines.append(f"**{tier_label}**\n")
        lines.append(_candidate_table(group))
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


def _market_intel_table(holdings, market_intel: dict) -> str:
    """依需求 7 精簡成「重點摘要」表格：代號/名稱/重點摘要（只挑一項最值得注意的）+新聞連結。"""
    header = "| 代號 | 名稱 | 重點摘要 | 相關新聞 |\n"
    header += "|---|---|---|---|\n"
    rows = []
    for h in holdings:
        info = market_intel.get(h.code)
        highlight = market_intel_highlight(info)
        news = (info.get("general_news") or [])[:3] if info else []
        news_str = "<br>".join(f"[{n['title']}]({n['link']})" for n in news) if news else "N/A"
        rows.append(f"| {h.code} | {h.name} | {highlight} | {news_str} |")
    if not rows:
        rows.append("| N/A | N/A | 暫無資料。 | N/A |")
    return header + "\n".join(rows)


def _monthly_priority_table(priority_list: list[dict]) -> str:
    header = "| 順位 | 代號 | 名稱 | Investment Score | 長期信心 |\n"
    header += "|---:|---|---|---:|---|\n"
    rows = []
    for p in priority_list:
        inv_str = f"{p['investment_score']:.0f}" if p.get("investment_score") is not None else "N/A"
        rows.append(f"| {p['rank']} | {p['code']} | {p['name']} | {inv_str} | {p.get('conviction_stars', 'N/A')} |")
    return header + "\n".join(rows)


def _monthly_allocation_table(allocations: list[dict]) -> str:
    header = "| 代號 | 名稱 | 投入金額 | 買進階段 | 本輪比例 | 約可買股數 | 備註 |\n"
    header += "|---|---|---:|---|---:|---:|---|\n"
    rows = []
    for a in allocations:
        rows.append(
            f"| {a['code']} | {a['name']} | {a['amount']:,.0f} | {a['tier_label']} | {a['tier_pct']:.0%} | "
            f"{a['shares']:,.1f} | {a.get('note') or ''} |"
        )
    return header + "\n".join(rows)


def _monthly_allocation_section(data: dict) -> list[str]:
    """需求 6：優先購買清單＋資金分配改成表格，總預算說明／尚未分配結轉／排除加碼說明維持文字，
    分別放在表格前後（總預算是前情提要、結轉與排除說明是表格結果的附註）。"""
    if data.get("no_value_note"):
        return [data["no_value_note"]]

    amount = data["amount"]
    carryover = data["carryover"]
    total_budget = data["total_budget"]
    lines = [
        f"本月可投資金額：新台幣 {total_budget:,.0f} 元"
        + (f"（月定期定額 {amount:,.0f} 元＋現金流結餘 {carryover:,.0f} 元，結轉上限 {data['carryover_cap']:,.0f} 元）" if carryover else f"（月定期定額 {amount:,.0f} 元）")
    ]
    lines.append("")

    if data.get("no_candidates_note"):
        lines.append(data["no_candidates_note"])
        for n in data.get("excluded_notes") or []:
            lines.append(f"- {n}")
        return lines

    lines.append("**優先購買清單（依 Investment Score／長期持股信心排序）**\n")
    lines.append(_monthly_priority_table(data["priority_list"]))
    lines.append("")
    lines.append("**本月資金分配（集中在優先順序最前面的標的，不是每檔都買一點；資金用完或達上限為止）**\n")
    lines.append(_monthly_allocation_table(data["allocations"]))
    lines.append("")

    if data.get("remaining") is not None:
        lines.append(f"尚未分配：{data['remaining']:,.0f} 元，將結轉至下月（結轉上限：{MAX_CARRYOVER_MONTHS} 個月投入金額 {data['carryover_cap']:,.0f} 元）。")
    if data.get("no_allocation_note"):
        lines.append(data["no_allocation_note"])
    for n in data.get("excluded_notes") or []:
        lines.append(f"- {n}")

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
    lines.append(_buy_points_table(ctx.get("buy_points_data", [])))
    lines.append("")

    lines.append("## 四、AI 綜合評分與行動建議\n")
    lines.append(
        "*AI 的目標不是預測股價，而是回答「該不該採取行動」：結合股票本身的六構面加權評分"
        "（基本面30%／成長性20%／籌碼面15%／技術面15%／估值10%／市場環境10%，缺資料的子項目"
        "會標註「資料覆蓋率低」而非硬湊分數）與目前的持股狀態，換算成 Investment Score(0-100)"
        "＋獨立的 Risk Score(0-100，越高風險越高)，最終只給四種結論：🟢加碼買進／🟡持有觀察／"
        "🟠分批獲利了結／🔴全數賣出。極端虧損部位（≤-40%）除非出現重大利多/利空新聞，"
        "不會每天重複提醒同一個「建議停損」。*\n"
    )
    cash = ctx.get("available_cash", 0)
    lines.append(
        f"- 個人化設定：可投入現金 新台幣 {cash:,.0f} 元／風險承受能力 {ctx.get('risk_tolerance', 'N/A')}"
        f"／投資期限 {ctx.get('investment_horizon', 'N/A')}\n"
    )
    lines.append(_ai_scoring_table(holdings, ctx.get("ai_scoring", {})))
    lines.append("")

    lines.append("## 五、產業配置建議\n")
    header = "| 產業別 | 佔投組市值比重 |\n|---|---:|\n"
    rows = [f"| {sector} | {w:.1%} |" for sector, w in ctx["sector_allocation"].items()]
    lines.append(header + "\n".join(rows))
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
    lines.extend(_monthly_allocation_section(ctx.get("monthly_allocation_data", {})))
    lines.append("")

    lines.append("## 八、後續追蹤重點\n")
    for f in ctx["monthly_focus"]:
        lines.append(f"- {f}")
    lines.append("")

    lines.append("## 九、市場情報：重點摘要\n")
    lines.append(
        "*依優先序（重大訊息 > 三大法人買賣超 > 月營收年增率 > 下一場法說會）只挑一項最值得注意的"
        "重點；月營收／財報資料來源：台灣證交所 OpenAPI（僅涵蓋上市公司）；新聞來源：Google 新聞；"
        "法說會來源：公開資訊觀測站；三大法人買賣超來源：證交所（上市，含細項）／櫃買中心（上櫃，僅合計）。*\n"
    )
    lines.append(_market_intel_table(holdings, ctx.get("market_intel", {})))
    lines.append("")

    lines.append("## 十、潛力新標的觀察\n")
    lines.append(
        "*人工整理的權值股／優質股／熱門ETF候選池，篩掉目前追高的標的，"
        "依 Investment Score 分「高價股」「低價股」各挑出評分最高的幾檔，僅供觀察參考，非買進建議。*\n"
    )
    lines.extend(_candidate_watchlist_section(ctx.get("candidate_watchlist", [])))
    lines.append("")

    lines.append("**潛力新標的觀察（ETF）**\n")
    lines.append(
        "*ETF 不套用個股的基本面/成長性/籌碼面評分（ETF 沒有這些資料），改用 ETF 專屬指標："
        "規模/費用率/配息政策50%＋技術面30%＋市場環境15%＋估值5%（法人目標價，ETF通常無資料，"
        "缺就跳過）。候選池已排除槓桿反向型（正2/反1）與期貨型，僅收長期持有導向的市值型／"
        "高股息型／產業主題型 ETF。*\n"
    )
    lines.extend(_candidate_watchlist_section(ctx.get("candidate_watchlist_etf", [])))
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
