"""AI 投資顧問 v1.0 - 網頁儀表板（FastAPI）。啟動：uv run uvicorn app:app --reload"""

import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from portfolio import load_portfolio, enrich_with_market_data, build_report_context, weight, cost_weight
from report import DISCLAIMER

app = FastAPI(title="AI 投資顧問 v1.0")


def render_report_html() -> str:
    holdings = load_portfolio()
    enrich_with_market_data(holdings)
    ctx = build_report_context(holdings)
    total_value, total_cost = ctx["total_value"], ctx["total_cost"]
    total_pnl_pct_str = f"{ctx['total_pnl_pct']:.1%}" if ctx["total_pnl_pct"] is not None else "N/A"

    idx = ctx.get("market_index")
    market_index_html = ""
    if idx and idx.get("close") is not None:
        change_color = "red" if (idx.get("change_points") or 0) >= 0 else "green"  # 台股慣例：紅漲綠跌
        change_str = f"{idx['change_points']:+,.2f}（{idx['change_pct']:+.2f}%）" if idx.get("change_points") is not None else "N/A"
        market_index_html = (
            f"<p>大盤{html.escape(idx['name'])}：{idx['close']:,.2f} 點，"
            f"<span style=\"color:{change_color}\">{change_str}</span>（{html.escape(idx.get('date') or '')}）</p>"
        )

    rows = ""
    for h in holdings:
        price_str = f"{h.price:,.2f}" if h.price is not None else "N/A"
        mv_str = f"{h.market_value:,.0f}" if h.market_value is not None else "N/A"
        pnl_str = f"{h.pnl:,.0f}" if h.pnl is not None else "N/A"
        pnl_pct_str = f"{h.pnl_pct:.1%}" if h.pnl_pct is not None else "N/A"
        w = weight(h, total_value)
        cw = cost_weight(h, total_cost)
        w_str = f"{w:.1%}" if w is not None else "N/A"
        cw_str = f"{cw:.1%}" if cw is not None else "N/A"
        pnl_color = "red" if (h.pnl or 0) >= 0 else "green"  # 台股慣例：紅漲綠跌
        rows += f"""
        <tr>
          <td>{h.code}</td><td>{h.name}</td><td>{h.shares:,.0f}</td>
          <td>{h.avg_cost:,.2f}</td><td>{price_str}</td><td>{mv_str}</td>
          <td style="color:{pnl_color}">{pnl_str} ({pnl_pct_str})</td><td>{w_str}</td><td>{cw_str}</td>
        </tr>"""

    fundamentals_rows = ""
    for h in holdings:
        pe = f"{h.trailing_pe:.1f} / {h.forward_pe:.1f}" if h.trailing_pe and h.forward_pe else "N/A"
        eps = f"{h.trailing_eps:.2f} / {h.forward_eps:.2f}" if h.trailing_eps and h.forward_eps else "N/A"
        target = f"{h.target_mean_price:,.1f}" if h.target_mean_price else "N/A"
        fundamentals_rows += f"""
        <tr>
          <td>{h.code}</td><td>{h.name}</td><td>{h.industry or h.sector or 'N/A'}</td>
          <td>{pe}</td><td>{eps}</td><td>{target}</td><td>{h.recommendation or 'N/A'}</td>
        </tr>"""

    buy_point_items = "".join(f"<li>{b}</li>" for b in ctx["buy_points"])
    sector_items = "".join(f"<li>{sector}：{w:.1%}</li>" for sector, w in ctx["sector_allocation"].items())
    sector_advice_items = "".join(f"<li>{a}</li>" for a in ctx["sector_advice"])
    risk_items = "".join(f"<li>{r}</li>" for r in ctx["risk"])
    rebalance_items = "".join(f"<li>{r}</li>" for r in ctx["rebalance"])
    monthly_alloc_html = "".join(f"<p>{html.escape(m)}</p>" if m else "<br>" for m in ctx["monthly_allocation"])
    focus_items = "".join(f"<li>{f}</li>" for f in ctx["monthly_focus"])

    ai_scoring = ctx.get("ai_scoring", {})
    ai_scoring_blocks = ""
    for h in holdings:
        r = ai_scoring.get(h.code)
        if not r:
            continue
        score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
        risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
        target_str = f"／法人目標價 {r['target_price']:,.1f}" if r.get("target_price") is not None else ""
        star = "⭐ " if r.get("star") else ""
        reasons_str = "；".join(r.get("reasons") or [])
        ai_scoring_blocks += f"""
        <div style="margin-bottom:0.8rem;">
          <strong>{star}{r['signal']} {h.code} {h.name}</strong>：{html.escape(r['label'])}
          <span style="color:#888;">（Investment Score {score_str}／Risk Score {risk_str}{target_str}）</span>
          {"<p style='color:#666;font-size:0.9rem;margin:2px 0 0 0;'>關鍵理由：" + html.escape(reasons_str) + "</p>" if reasons_str else ""}
        </div>"""

    market_intel = ctx.get("market_intel", {})
    market_intel_blocks = ""
    for h in holdings:
        info = market_intel.get(h.code)
        if not info:
            continue
        rev = info.get("monthly_revenue") or {}
        inc = info.get("income_statement") or {}
        material_news = info.get("material_news") or []
        news = info.get("general_news") or []

        summary_parts = []
        yoy = rev.get("營業收入-去年同月增減(%)")
        if yoy not in (None, ""):
            summary_parts.append(f"月營收年增率 {float(yoy):+.1f}%")
        if inc.get("revenue") is not None:
            eps_str = f"／EPS {inc['eps']}元" if inc.get("eps") else ""
            summary_parts.append(f"{inc.get('quarter', '最新季')}營收 {float(inc['revenue']):,.0f}仟元{eps_str}")
        if material_news:
            summary_parts.append(f"今日重大訊息 {len(material_news)} 則")
        conf = info.get("investor_conference")
        if conf:
            summary_parts.append(
                f"下一場法說會 {html.escape(conf['date'])} {html.escape(conf['time'])}，"
                f"地點：{html.escape(conf['location'])}"
            )
        flow = info.get("institutional_flow")
        if flow and flow.get("total_net") is not None:
            if flow.get("foreign_net") is not None:
                summary_parts.append(
                    f"三大法人買賣超 {flow['total_net']:+,.0f} 股"
                    f"（外資 {flow['foreign_net']:+,.0f}／投信 {flow['trust_net']:+,.0f}／自營商 {flow['dealer_net']:+,.0f}）"
                )
            else:
                summary_parts.append(f"三大法人買賣超合計 {flow['total_net']:+,.0f} 股")

        news_items = "".join(
            f'<li><a href="{html.escape(n["link"])}" target="_blank">{html.escape(n["title"])}</a></li>' for n in news
        )

        market_intel_blocks += f"""
        <div style="margin-bottom:1rem;">
          <strong>{h.code} {h.name}</strong>
          {"<p>" + "，".join(summary_parts) + "</p>" if summary_parts else ""}
          <ul>{news_items}</ul>
        </div>"""

    goal = ctx.get("goal") or {}
    goal_html = ""
    if goal:
        progress_str = f"{goal['profit_progress_pct']:+.1%}" if goal.get("profit_progress_pct") is not None else "N/A"
        pace_color = "red" if goal.get("on_pace") else "green"
        pace_str = "進度符合預期" if goal.get("on_pace") else "進度落後預期"
        floor_color = "green" if goal.get("floor_breached") else "red"
        floor_str = "已跌破基準總市值下限！" if goal.get("floor_breached") else "總市值仍在基準之上"
        goal_html = f"""
        <p>目標期間：{goal['baseline_date']} ~ {goal['target_date']}（剩餘 {goal['days_remaining']} 天）
        基準總市值：{goal['baseline_value']:,.0f}</p>
        <p>獲利目標：{goal['profit_target']:,.0f}　目前累積獲利：{goal['current_pnl']:,.0f}
        達成率：<span style="color:{pace_color}">{progress_str}</span>
        進度評估：<span style="color:{pace_color}">{pace_str}</span></p>
        <p>下限檢查：<span style="color:{floor_color}">{floor_str}</span>（目前總市值 {goal['current_value']:,.0f}）</p>"""

    candidate_watchlist = ctx.get("candidate_watchlist", [])
    tier_label = {"high": "高價股", "low": "低價股"}
    candidate_blocks = ""
    if not candidate_watchlist:
        candidate_blocks = "<p>目前抓不到候選新標的資料，或候選池股票都已在你的持股中。</p>"
    else:
        for tier in ("high", "low"):
            group = [r for r in candidate_watchlist if r.get("price_tier") == tier]
            if not group:
                continue
            candidate_blocks += f"<p><strong>{tier_label[tier]}</strong></p>"
            for r in group:
                score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
                risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
                target_str = f"／法人目標價 {r['target_price']:,.1f}" if r.get("target_price") is not None else ""
                reasons_str = "；".join(r.get("reasons") or [])
                candidate_blocks += f"""
                <div style="margin-bottom:0.8rem;">
                  <strong>{html.escape(r.get('conviction_stars') or '')} {r['code']} {r['name']}</strong>
                  股價 {r['price']:,.1f}
                  <span style="color:#888;">（Investment Score {score_str}／Risk Score {risk_str}{target_str}）</span>
                  {"<p style='color:#666;font-size:0.9rem;margin:2px 0 0 0;'>關鍵理由：" + html.escape(reasons_str) + "</p>" if reasons_str else ""}
                </div>"""

    return f"""
    <html>
    <head>
      <meta charset="utf-8">
      <title>AI 投資顧問 v1.0</title>
      <style>
        body {{ font-family: "Microsoft JhengHei", sans-serif; margin: 2rem; max-width: 1000px; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 1rem; }}
        th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: right; }}
        th:nth-child(1), td:nth-child(1), th:nth-child(2), td:nth-child(2),
        th:nth-child(3), td:nth-child(3) {{ text-align: left; }}
        h2 {{ margin-top: 2rem; border-bottom: 2px solid #eee; padding-bottom: 4px; }}
        footer {{ margin-top: 2rem; color: #888; font-size: 0.85rem; }}
      </style>
    </head>
    <body>
      <h1>AI 投資顧問 v1.0 - 投資報告</h1>

      <h2>個人短期目標追蹤</h2>
      {goal_html}

      <h2>一、投資組合總覽</h2>
      <p>總成本：{total_cost:,.0f}　總市值：{total_value:,.0f}
         總報酬：<span style="color:{'red' if ctx['total_pnl'] >= 0 else 'green'}">{ctx['total_pnl']:,.0f} ({total_pnl_pct_str})</span></p>
      {market_index_html}
      <table>
        <tr><th>代號</th><th>名稱</th><th>股數</th><th>平均成本</th><th>現價</th><th>市值</th><th>損益</th><th>市值佔比</th><th>成本佔比</th></tr>
        {rows}
      </table>

      <h2>二、個股分析</h2>
      <table>
        <tr><th>代號</th><th>名稱</th><th>產業</th><th>本益比(TTM/預估)</th><th>EPS(TTM/預估)</th><th>法人目標價</th><th>法人評等</th></tr>
        {fundamentals_rows}
      </table>

      <h2>三、合理買點</h2>
      <ul>{buy_point_items}</ul>

      <h2>四、AI 綜合評分與行動建議</h2>
      <p style="color:#888;font-size:0.85rem;">
        六構面加權評分（基本面30%／成長性20%／籌碼面15%／技術面15%／估值10%／市場環境10%）算出 Investment Score(0-100)，
        另外算獨立的 Risk Score(0-100，越高風險越高)，只給四種結論：🟢加碼買進／🟡持有觀察／🟠分批獲利了結／🔴全數賣出。
        極端虧損部位（≤-70%）除非出現重大利多/利空新聞，不會每天重複提醒同一個「建議停損」。<br>
        個人化設定：可投入現金 新台幣 {ctx.get('available_cash', 0):,.0f} 元／風險承受能力 {ctx.get('risk_tolerance', 'N/A')}／投資期限 {ctx.get('investment_horizon', 'N/A')}
      </p>
      {ai_scoring_blocks}

      <h2>五、產業配置建議</h2>
      <ul>{sector_items}</ul>
      <ul>{sector_advice_items}</ul>

      <h2>六、風險評估與再平衡</h2>
      <p><strong>風險評估</strong></p>
      <ul>{risk_items}</ul>
      <p><strong>再平衡建議</strong></p>
      <ul>{rebalance_items}</ul>

      <h2>七、每月投資建議</h2>
      {monthly_alloc_html}

      <h2>八、後續追蹤重點</h2>
      <ul>{focus_items}</ul>

      <h2>九、市場情報：月營收、財報、新聞、法說會、三大法人買賣超</h2>
      <p style="color:#888;font-size:0.85rem;">
        月營收／財報資料來源：台灣證交所 OpenAPI（僅涵蓋上市公司）；新聞來源：Google 新聞；
        法說會來源：公開資訊觀測站；三大法人買賣超來源：證交所（上市，含細項）／櫃買中心（上櫃，僅合計）。
      </p>
      {market_intel_blocks}

      <h2>十、潛力新標的觀察</h2>
      <p style="color:#888;font-size:0.85rem;">
        人工整理的權值股／優質股／熱門ETF候選池，篩掉目前追高的標的，
        依 Investment Score 分「高價股」「低價股」各挑出評分最高的幾檔，僅供觀察參考，非買進建議。
      </p>
      {candidate_blocks}

      <footer>{DISCLAIMER}</footer>
    </body>
    </html>
    """


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return render_report_html()
