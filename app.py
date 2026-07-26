"""AI 投資顧問 v1.0 - 網頁儀表板（FastAPI）。啟動：uv run uvicorn app:app --reload"""

import html

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from portfolio import (
    load_portfolio,
    enrich_with_market_data,
    build_report_context,
    weight,
    cost_weight,
    current_price_display,
    industry_or_sector_label_zh,
    market_intel_highlight,
    MAX_CARRYOVER_MONTHS,
)
from report import DISCLAIMER
from sector_rotation import HTML_NAME_COLOR, HTML_CODE_COLOR

app = FastAPI(title="AI 投資顧問 v1.0")


def _name_code_html(code: str, name: str) -> str:
    """股票/ETF 名稱／代號配色，套用跟太太短線輪動信（sector_rotation.py）一致的規格：
    名稱玫瑰紅、代號寶藍，都是粗體，方便在一堆數字中快速抓到重點標的。"""
    return (
        f'<span style="color:{HTML_NAME_COLOR};font-weight:700;">{html.escape(name)}</span>'
        f'（<span style="color:{HTML_CODE_COLOR};font-weight:700;">{html.escape(code)}</span>）'
    )


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
        current_price = html.escape(current_price_display(h))
        target = f"{h.target_mean_price:,.1f}" if h.target_mean_price else "N/A"
        fundamentals_rows += f"""
        <tr>
          <td>{h.code}</td><td>{h.name}</td><td>{html.escape(industry_or_sector_label_zh(h))}</td>
          <td>{pe}</td><td>{eps}</td><td>{current_price}</td><td>{target}</td><td>{h.recommendation or 'N/A'}</td>
        </tr>"""

    buy_points_rows = ""
    for bp in ctx.get("buy_points_data", []):
        week52 = html.escape(bp.get("week52_range") or "N/A")
        zone = html.escape(bp.get("suggested_zone") or "N/A")
        pos = html.escape(bp.get("price_position") or "N/A")
        target = f"{bp['target_price']:,.1f}" if bp.get("target_price") is not None else "N/A"
        upside = f"{bp['upside_pct']:+.1%}" if bp.get("upside_pct") is not None else "N/A"
        buy_points_rows += f"""
        <tr>
          <td>{bp['code']}</td><td>{bp['name']}</td><td>{week52}</td><td>{zone}</td>
          <td>{pos}</td><td>{target}</td><td>{upside}</td>
        </tr>"""

    sector_advice_items = "".join(f"<li>{html.escape(a)}</li>" for a in ctx["sector_advice"])
    risk_items = "".join(f"<li>{html.escape(r)}</li>" for r in ctx["risk"])
    rebalance_items = "".join(f"<li>{html.escape(r)}</li>" for r in ctx["rebalance"])
    focus_items = "".join(f"<li>{html.escape(f)}</li>" for f in ctx["monthly_focus"])

    ai_scoring = ctx.get("ai_scoring", {})
    ai_scoring_rows = ""
    for h in holdings:
        r = ai_scoring.get(h.code)
        if not r:
            ai_scoring_rows += f"""
        <tr><td>N/A</td><td>{h.code}</td><td>{h.name}</td><td>尚無評分資料。</td>
        <td>N/A</td><td>N/A</td><td>N/A</td><td>N/A</td></tr>"""
            continue
        score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
        risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
        target_str = f"{r['target_price']:,.1f}" if r.get("target_price") is not None else "N/A"
        star = "⭐ " if r.get("star") else ""
        reasons_html = "<br>".join(html.escape(x) for x in (r.get("reasons") or [])) or "N/A"
        ai_scoring_rows += f"""
        <tr>
          <td>{star}{r['signal']}</td>
          <td style="color:{HTML_CODE_COLOR};font-weight:700;">{h.code}</td>
          <td style="color:{HTML_NAME_COLOR};font-weight:700;">{html.escape(h.name)}</td>
          <td>{html.escape(r['label'])}</td><td>{score_str}</td><td>{risk_str}</td>
          <td>{target_str}</td><td>{reasons_html}</td>
        </tr>"""

    market_intel = ctx.get("market_intel", {})
    market_intel_rows = ""
    for h in holdings:
        info = market_intel.get(h.code)
        highlight = html.escape(market_intel_highlight(info))
        news = (info.get("general_news") or [])[:3] if info else []
        news_html = "<br>".join(
            f'<a href="{html.escape(n["link"])}" target="_blank">{html.escape(n["title"])}</a>' for n in news
        ) or "N/A"
        market_intel_rows += f"""
        <tr>
          <td>{h.code}</td><td>{h.name}</td><td>{highlight}</td><td>{news_html}</td>
        </tr>"""

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

    tier_label = {"high": "高價股", "low": "低價股"}

    def _render_candidate_blocks(candidates: list[dict]) -> str:
        if not candidates:
            return "<p>目前抓不到候選新標的資料，或候選池股票都已在你的持股中。</p>"
        blocks = ""
        for tier in ("high", "low"):
            group = [r for r in candidates if r.get("price_tier") == tier]
            if not group:
                continue
            rows = ""
            for r in group:
                score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
                risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
                target_str = f"{r['target_price']:,.1f}" if r.get("target_price") is not None else "N/A"
                reasons_html = "<br>".join(html.escape(x) for x in (r.get("reasons") or [])) or "N/A"
                rows += f"""
                <tr>
                  <td>{html.escape(r.get('conviction_stars') or 'N/A')}</td>
                  <td style="color:{HTML_CODE_COLOR};font-weight:700;">{r['code']}</td>
                  <td style="color:{HTML_NAME_COLOR};font-weight:700;">{html.escape(r['name'])}</td>
                  <td>{r['price']:,.1f}</td><td>{score_str}</td><td>{risk_str}</td>
                  <td>{target_str}</td><td>{reasons_html}</td>
                </tr>"""
            blocks += f"""
            <p><strong>{tier_label[tier]}</strong></p>
            <table>
              <tr><th>星等</th><th>代號</th><th>名稱</th><th>股價</th><th>Investment Score</th>
              <th>Risk Score</th><th>法人目標價</th><th>關鍵理由</th></tr>
              {rows}
            </table>"""
        return blocks

    candidate_blocks = _render_candidate_blocks(ctx.get("candidate_watchlist", []))
    candidate_blocks_etf = _render_candidate_blocks(ctx.get("candidate_watchlist_etf", []))

    mad = ctx.get("monthly_allocation_data") or {}
    monthly_alloc_html = ""
    if mad.get("no_value_note"):
        monthly_alloc_html = f"<p>{html.escape(mad['no_value_note'])}</p>"
    else:
        amount = mad.get("amount", 0)
        carryover = mad.get("carryover") or 0
        total_budget = mad.get("total_budget") or 0
        budget_line = (
            f"本月可投資金額：新台幣 {total_budget:,.0f} 元"
            + (f"（月定期定額 {amount:,.0f} 元＋現金流結餘 {carryover:,.0f} 元，結轉上限 {mad.get('carryover_cap', 0):,.0f} 元）" if carryover else f"（月定期定額 {amount:,.0f} 元）")
        )
        monthly_alloc_html = f"<p>{budget_line}</p>"

        if mad.get("no_candidates_note"):
            monthly_alloc_html += f"<p>{html.escape(mad['no_candidates_note'])}</p>"
            monthly_alloc_html += "".join(f"<p>{html.escape(n)}</p>" for n in mad.get("excluded_notes") or [])
        else:
            priority_rows = ""
            for p in mad.get("priority_list") or []:
                inv_str = f"{p['investment_score']:.0f}" if p.get("investment_score") is not None else "N/A"
                priority_rows += f"""
                <tr>
                  <td>{p['rank']}</td>
                  <td style="color:{HTML_CODE_COLOR};font-weight:700;">{p['code']}</td>
                  <td style="color:{HTML_NAME_COLOR};font-weight:700;">{html.escape(p['name'])}</td>
                  <td>{inv_str}</td><td>{html.escape(p.get('conviction_stars', 'N/A'))}</td>
                </tr>"""
            monthly_alloc_html += f"""
            <p><strong>優先購買清單（依 Investment Score／長期持股信心排序）</strong></p>
            <table>
              <tr><th>順位</th><th>代號</th><th>名稱</th><th>Investment Score</th><th>長期信心</th></tr>
              {priority_rows}
            </table>"""

            alloc_rows = ""
            for a in mad.get("allocations") or []:
                alloc_rows += f"""
                <tr>
                  <td style="color:{HTML_CODE_COLOR};font-weight:700;">{a['code']}</td>
                  <td style="color:{HTML_NAME_COLOR};font-weight:700;">{html.escape(a['name'])}</td>
                  <td>{a['amount']:,.0f}</td><td>{html.escape(a['tier_label'])}</td>
                  <td>{a['tier_pct']:.0%}</td><td>{a['shares']:,.1f}</td>
                  <td>{html.escape(a.get('note') or '')}</td>
                </tr>"""
            monthly_alloc_html += f"""
            <p><strong>本月資金分配（集中在優先順序最前面的標的，不是每檔都買一點；資金用完或達上限為止）</strong></p>
            <table>
              <tr><th>代號</th><th>名稱</th><th>投入金額</th><th>買進階段</th><th>本輪比例</th><th>約可買股數</th><th>備註</th></tr>
              {alloc_rows}
            </table>"""

            if mad.get("remaining") is not None:
                monthly_alloc_html += (
                    f"<p>尚未分配：{mad['remaining']:,.0f} 元，將結轉至下月"
                    f"（結轉上限：{MAX_CARRYOVER_MONTHS} 個月投入金額 {mad.get('carryover_cap', 0):,.0f} 元）。</p>"
                )
            if mad.get("no_allocation_note"):
                monthly_alloc_html += f"<p>{html.escape(mad['no_allocation_note'])}</p>"
            monthly_alloc_html += "".join(f"<p>{html.escape(n)}</p>" for n in mad.get("excluded_notes") or [])

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
        <tr><th>代號</th><th>名稱</th><th>產業</th><th>本益比(TTM/預估)</th><th>EPS(TTM/預估)</th><th>目前股價</th><th>法人目標價</th><th>法人評等</th></tr>
        {fundamentals_rows}
      </table>

      <h2>三、合理買點</h2>
      <table>
        <tr><th>代號</th><th>名稱</th><th>近一年區間</th><th>建議承接區間</th><th>現價位置</th><th>法人目標價</th><th>上漲空間</th></tr>
        {buy_points_rows}
      </table>

      <h2>四、AI 綜合評分與行動建議</h2>
      <p style="color:#888;font-size:0.85rem;">
        六構面加權評分（基本面30%／成長性20%／籌碼面15%／技術面15%／估值10%／市場環境10%）算出 Investment Score(0-100)，
        另外算獨立的 Risk Score(0-100，越高風險越高)，只給四種結論：🟢加碼買進／🟡持有觀察／🟠分批獲利了結／🔴全數賣出。
        極端虧損部位（≤-40%）除非出現重大利多/利空新聞，不會每天重複提醒同一個「建議停損」。<br>
        個人化設定：可投入現金 新台幣 {ctx.get('available_cash', 0):,.0f} 元／風險承受能力 {ctx.get('risk_tolerance', 'N/A')}／投資期限 {ctx.get('investment_horizon', 'N/A')}
      </p>
      <table>
        <tr><th>訊號</th><th>代號</th><th>名稱</th><th>說明</th><th>Investment Score</th><th>Risk Score</th><th>法人目標價</th><th>關鍵理由</th></tr>
        {ai_scoring_rows}
      </table>

      <h2>五、產業配置建議</h2>
      <table>
        <tr><th>產業別</th><th>佔投組市值比重</th></tr>
        {"".join(f'<tr><td>{html.escape(sector)}</td><td>{w:.1%}</td></tr>' for sector, w in ctx["sector_allocation"].items())}
      </table>
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

      <h2>九、市場情報：重點摘要</h2>
      <p style="color:#888;font-size:0.85rem;">
        依優先序（重大訊息 > 三大法人買賣超 > 月營收年增率 > 下一場法說會）只挑一項最值得注意的重點；
        月營收／財報資料來源：台灣證交所 OpenAPI（僅涵蓋上市公司）；新聞來源：Google 新聞；
        法說會來源：公開資訊觀測站；三大法人買賣超來源：證交所（上市，含細項）／櫃買中心（上櫃，僅合計）。
      </p>
      <table>
        <tr><th>代號</th><th>名稱</th><th>重點摘要</th><th>相關新聞</th></tr>
        {market_intel_rows}
      </table>

      <h2>十、潛力新標的觀察</h2>
      <p style="color:#888;font-size:0.85rem;">
        人工整理的權值股／優質股／熱門ETF候選池，篩掉目前追高的標的，
        依 Investment Score 分「高價股」「低價股」各挑出評分最高的幾檔，僅供觀察參考，非買進建議。
      </p>
      {candidate_blocks}

      <p><strong>潛力新標的觀察（ETF）</strong></p>
      <p style="color:#888;font-size:0.85rem;">
        ETF 不套用個股的基本面/成長性/籌碼面評分，改用規模/費用率/配息政策50%＋技術面30%＋市場環境15%＋估值5%，
        候選池已排除槓桿反向型（正2/反1）與期貨型，僅收長期持有導向的市值型／高股息型／產業主題型 ETF。
      </p>
      {candidate_blocks_etf}

      <footer>{DISCLAIMER}</footer>
    </body>
    </html>
    """


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return render_report_html()
