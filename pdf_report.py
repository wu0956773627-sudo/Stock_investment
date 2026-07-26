"""把投資報告轉成 PDF，取代 Email 附件原本直接寄送的 Markdown 檔（.md 在多數郵件用戶端／手機開啟時排版很醜）。

直接用 reportlab 排版產生 PDF，**不透過 xhtml2pdf 這類 HTML→PDF 轉換**：
實測發現 xhtml2pdf 處理中文字型時，中文字元會整段跑版成缺字方框（■），
即使已正確註冊 TrueType 中文字型也一樣；改用 reportlab 直接繪製（platypus flowables）
搭配 Windows 內建的標楷體（`C:\\Windows\\Fonts\\kaiu.ttf`）則完全正常。

使用者要求整體字體不小於 14pt（老花眼不好閱讀太小的字），本檔案的內文／條列字體
固定在 14pt，只有表格內容（欄位較多，14pt 會超版面）採 12pt 折衷。
"""

from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from portfolio import weight, cost_weight

PDF_REPORT_PATH = "投資報告.pdf"

FONT_NAME = "KaiU"
FONT_PATH = r"C:\Windows\Fonts\kaiu.ttf"
BASE_FONT_SIZE = 14  # 使用者要求：整體字體 14pt 以上

if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
    pdfmetrics.registerFontFamily(FONT_NAME, normal=FONT_NAME, bold=FONT_NAME, italic=FONT_NAME, boldItalic=FONT_NAME)

STYLE_TITLE = ParagraphStyle("title", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE + 10, leading=BASE_FONT_SIZE + 14, spaceAfter=6)
STYLE_SUBTITLE = ParagraphStyle("subtitle", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE - 2, leading=BASE_FONT_SIZE + 2, textColor=colors.grey, spaceAfter=14)
STYLE_H2 = ParagraphStyle("h2", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE + 4, leading=BASE_FONT_SIZE + 8, spaceBefore=18, spaceAfter=8, textColor=colors.HexColor("#1a3d6d"))
STYLE_BODY = ParagraphStyle("body", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE, leading=BASE_FONT_SIZE + 6, spaceAfter=6)
STYLE_BULLET = ParagraphStyle("bullet", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE, leading=BASE_FONT_SIZE + 6, leftIndent=14, spaceAfter=5)
STYLE_SUB_BULLET = ParagraphStyle("sub_bullet", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE - 2, leading=BASE_FONT_SIZE + 2, leftIndent=28, textColor=colors.HexColor("#1a5fb4"), spaceAfter=4)
STYLE_TABLE_HEAD = ParagraphStyle("table_head", fontName=FONT_NAME, fontSize=12, leading=15, textColor=colors.white)
STYLE_TABLE_CELL = ParagraphStyle("table_cell", fontName=FONT_NAME, fontSize=12, leading=15)
STYLE_SMALL = ParagraphStyle("small", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE - 3, leading=BASE_FONT_SIZE + 1, textColor=colors.grey, spaceAfter=10)

TABLE_HEAD_BG = colors.HexColor("#1a3d6d")
TABLE_GRID = colors.HexColor("#bbbbbb")


# 標楷體（KaiU）沒有 emoji／特殊符號字符集，reportlab 遇到不支援的字符會直接跳過、不是顯示缺字方框，
# 很容易漏看（例如 "‣" 項目符號整個消失、"🔴" 訊號整個消失但周圍文字看起來還是通順的）。
# 這裡把已知會用到、但 KaiU 不支援的符號統一轉成「有顏色的中文方框標籤」或安全替代字元。
_SIGNAL_COLORS = {"🟢": "#2e7d32", "🟡": "#b8860b", "🟠": "#d2691e", "🔴": "#c62828"}
_SIGNAL_LABELS = {"🟢": "【加碼買進】", "🟡": "【持有觀察】", "🟠": "【分批獲利了結】", "🔴": "【全數賣出】"}
_TEXT_REPLACEMENTS = {
    "‣": "・",
    "⭐": "【重點】",
    "⚠️": "【注意】",
    "⚠": "【注意】",
    "❌": "【不建議】",
    "✅": "【符合】",
}


def _pdf_safe(text: str) -> str:
    for old, new in _TEXT_REPLACEMENTS.items():
        text = text.replace(old, new)
    for emoji in _SIGNAL_COLORS:
        text = text.replace(emoji, "")  # 訊號 emoji 若混在文字中間，交給 _signal_marker() 另外處理，這裡先清掉
    return text


def _signal_marker(signal: str) -> str:
    color = _SIGNAL_COLORS.get(signal, "#333333")
    label = _SIGNAL_LABELS.get(signal, "【評估中】")
    return f'<font color="{color}"><b>{label}</b></font>'


def _p(text: str, style=STYLE_BODY) -> Paragraph:
    return Paragraph(_pdf_safe(text), style)


def _bullets(items: list[str], style=STYLE_BULLET) -> list[Paragraph]:
    return [_p(f"・{item}", style) for item in items]


def _plain_lines(items: list[str], style=STYLE_BULLET) -> list:
    """給已經自帶格式（標題／編號／「- 」開頭）的多行內容用，不額外加項目符號；空行轉成小間距。"""
    flowables = []
    for item in items:
        if item == "":
            flowables.append(Spacer(1, 4))
        else:
            flowables.append(_p(item, style))
    return flowables


def _make_table(headers: list[str], rows: list[list[str]], col_widths: list[float]) -> Table:
    data = [[Paragraph(_pdf_safe(h), STYLE_TABLE_HEAD) for h in headers]]
    for row in rows:
        data.append([Paragraph(_pdf_safe(str(cell)), STYLE_TABLE_CELL) for cell in row])

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD_BG),
                ("GRID", (0, 0), (-1, -1), 0.5, TABLE_GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5f9")]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _holdings_table(holdings, total_value, total_cost) -> Table:
    headers = ["代號", "名稱", "現價", "市值", "損益(率)", "市值佔比"]
    rows = []
    for h in holdings:
        price = f"{h.price:,.2f}" if h.price is not None else "N/A"
        mv = f"{h.market_value:,.0f}" if h.market_value is not None else "N/A"
        pnl = f"{h.pnl:,.0f}({h.pnl_pct:+.1%})" if h.pnl is not None and h.pnl_pct is not None else "N/A"
        w = weight(h, total_value)
        w_str = f"{w:.1%}" if w is not None else "N/A"
        rows.append([h.code, h.name, price, mv, pnl, w_str])
    return _make_table(headers, rows, [2 * cm, 3.6 * cm, 2.6 * cm, 3 * cm, 3.6 * cm, 2.4 * cm])


def _fundamentals_table(holdings) -> Table:
    headers = ["代號", "名稱", "產業", "本益比(TTM)", "法人目標價"]
    rows = []
    for h in holdings:
        pe = f"{h.trailing_pe:.1f}" if h.trailing_pe else "N/A"
        target = f"{h.target_mean_price:,.1f}" if h.target_mean_price else "N/A"
        rows.append([h.code, h.name, h.industry or h.sector or "N/A", pe, target])
    return _make_table(headers, rows, [2 * cm, 3.6 * cm, 6 * cm, 3.2 * cm, 3.4 * cm])


def _ai_scoring_flowables(holdings, ai_scoring: dict) -> list:
    flowables = []
    for h in holdings:
        r = ai_scoring.get(h.code)
        if not r:
            flowables.append(_p(f"・{h.code} {h.name}：尚無評分資料。", STYLE_BULLET))
            continue

        score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
        risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
        target_str = f"／法人目標價 {r['target_price']:,.1f}" if r.get("target_price") is not None else ""
        star_marker = '<font color="#6a1b9a"><b>【重點追蹤】</b></font> ' if r.get("star") else ""
        marker = _signal_marker(r["signal"])

        flowables.append(
            _p(
                f"・{star_marker}{marker} <b>{h.code} {h.name}</b>：{r['label']}"
                f"（Investment Score {score_str}／Risk Score {risk_str}{target_str}）",
                STYLE_BULLET,
            )
        )
        if r.get("reasons"):
            flowables.append(_p(f"・關鍵理由：{'；'.join(r['reasons'])}", STYLE_SUB_BULLET))
    if not flowables:
        flowables.append(_p("・暫無資料。", STYLE_BULLET))
    return flowables


def _market_intel_flowables(holdings, market_intel: dict) -> list:
    flowables = []
    has_any = False
    for h in holdings:
        info = market_intel.get(h.code)
        if not info:
            continue

        parts = []
        rev = info.get("monthly_revenue")
        if rev:
            yoy = rev.get("營業收入-去年同月增減(%)")
            month = rev.get("資料年月")
            if yoy not in (None, ""):
                parts.append(f"月營收({month})年增率 {float(yoy):+.1f}%")

        inc = info.get("income_statement") or {}
        if inc.get("revenue") is not None:
            eps_str = f"／EPS {inc['eps']}元" if inc.get("eps") else ""
            parts.append(f"{inc.get('quarter', '最新季')}營收 {float(inc['revenue']):,.0f}仟元{eps_str}")

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

        if not parts:
            continue
        has_any = True
        flowables.append(_p(f"・<b>{h.code} {h.name}</b>　" + "，".join(parts), STYLE_BULLET))
        for n in (info.get("general_news") or [])[:2]:
            flowables.append(_p(f"‣ {n['title']}", STYLE_SUB_BULLET))

    if not has_any:
        flowables.append(_p("・暫無資料。", STYLE_BULLET))
    return flowables


def _candidate_watchlist_flowables(candidates: list[dict]) -> list:
    """目前沒有持有、評分較高的候選新標的（跟既有持股分開，回答「還有沒有值得考慮加入的新標的」）。"""
    flowables = []
    if not candidates:
        flowables.append(_p("・目前抓不到候選新標的資料，或候選池股票都已在你的持股中。", STYLE_BULLET))
        return flowables

    tier_label = {"high": "高價股", "low": "低價股"}
    for tier in ("high", "low"):
        group = [r for r in candidates if r.get("price_tier") == tier]
        if not group:
            continue
        flowables.append(_p(f"<b>{tier_label[tier]}</b>", STYLE_BODY))
        for r in group:
            score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
            risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
            target_str = f"／法人目標價 {r['target_price']:,.1f}" if r.get("target_price") is not None else ""
            stars = _pdf_safe(r.get("conviction_stars") or "")
            flowables.append(
                _p(
                    f"・{stars} <b>{r['code']} {r['name']}</b>　股價 {r['price']:,.1f}"
                    f"（Investment Score {score_str}／Risk Score {risk_str}{target_str}）",
                    STYLE_BULLET,
                )
            )
            if r.get("reasons"):
                flowables.append(_p(f"・關鍵理由：{'；'.join(r['reasons'])}", STYLE_SUB_BULLET))
    return flowables


def build_pdf_flowables(holdings, ctx: dict) -> list:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    flow = []

    flow.append(_p("投資報告", STYLE_TITLE))
    flow.append(_p(f"更新時間：{now}", STYLE_SUBTITLE))

    flow.append(_p("個人短期目標追蹤", STYLE_H2))
    goal = ctx.get("goal") or {}
    if goal:
        progress_str = f"{goal['profit_progress_pct']:+.1%}" if goal.get("profit_progress_pct") is not None else "N/A"
        pace_str = _pdf_safe("✅ 進度符合預期" if goal.get("on_pace") else "⚠️ 進度落後預期")
        floor_str = _pdf_safe("⚠️ 已跌破基準總市值下限！" if goal.get("floor_breached") else "✅ 總市值仍在基準之上")
        flow.append(_p(f"目標期間：{goal['baseline_date']} ~ {goal['target_date']}（剩餘 {goal['days_remaining']} 天）", STYLE_BODY))
        flow.append(_p(f"基準總市值：新台幣 {goal['baseline_value']:,.0f} 元", STYLE_BODY))
        flow.append(
            _p(
                f"獲利目標：累積獲利達新台幣 {goal['profit_target']:,.0f} 元"
                f"（目前累積獲利 {goal['current_pnl']:,.0f} 元，達成率 {progress_str}）",
                STYLE_BODY,
            )
        )
        flow.append(_p(f"進度評估：{pace_str}", STYLE_BODY))
        flow.append(_p(f"下限檢查：{floor_str}（目前總市值 {goal['current_value']:,.0f} 元）", STYLE_BODY))

    flow.append(_p("一、投資組合總覽", STYLE_H2))
    total_pnl_pct_str = f"{ctx['total_pnl_pct']:+.1%}" if ctx["total_pnl_pct"] is not None else "N/A"
    flow.append(_p(f"總成本：新台幣 {ctx['total_cost']:,.0f} 元", STYLE_BODY))
    flow.append(_p(f"總市值：新台幣 {ctx['total_value']:,.0f} 元", STYLE_BODY))
    flow.append(_p(f"總報酬：新台幣 {ctx['total_pnl']:,.0f} 元（{total_pnl_pct_str}）", STYLE_BODY))
    idx = ctx.get("market_index")
    if idx and idx.get("close") is not None:
        change_str = f"{idx['change_points']:+,.2f}（{idx['change_pct']:+.2f}%）" if idx.get("change_points") is not None else "N/A"
        flow.append(_p(f"大盤{idx['name']}：{idx['close']:,.2f} 點，漲跌 {change_str}", STYLE_BODY))
    flow.append(Spacer(1, 8))
    flow.append(_holdings_table(holdings, ctx["total_value"], ctx["total_cost"]))

    flow.append(_p("二、個股分析", STYLE_H2))
    flow.append(_fundamentals_table(holdings))

    flow.append(_p("三、合理買點", STYLE_H2))
    flow.extend(_bullets(ctx["buy_points"]))

    flow.append(_p("四、AI 綜合評分與行動建議", STYLE_H2))
    flow.append(
        _p(
            "AI 的目標不是預測股價，而是回答「該不該採取行動」：結合六構面加權評分"
            "（基本面30%／成長性20%／籌碼面15%／技術面15%／估值10%／市場環境10%）與目前持股狀態，"
            "算出 Investment Score(0-100)＋獨立 Risk Score(0-100)，只給四種結論："
            "🟢加碼買進／🟡持有觀察／🟠分批獲利了結／🔴全數賣出。",
            STYLE_SMALL,
        )
    )
    cash = ctx.get("available_cash", 0)
    flow.append(
        _p(
            f"個人化設定：可投入現金 新台幣 {cash:,.0f} 元／風險承受能力 {ctx.get('risk_tolerance', 'N/A')}"
            f"／投資期限 {ctx.get('investment_horizon', 'N/A')}",
            STYLE_SMALL,
        )
    )
    flow.extend(_ai_scoring_flowables(holdings, ctx.get("ai_scoring", {})))

    flow.append(_p("五、產業配置建議", STYLE_H2))
    flow.extend(_bullets([f"{sector}：{w:.1%}" for sector, w in ctx["sector_allocation"].items()]))
    flow.extend(_bullets(ctx["sector_advice"]))

    flow.append(_p("六、風險評估與再平衡", STYLE_H2))
    flow.append(_p("風險評估：", STYLE_BODY))
    flow.extend(_bullets(ctx["risk"]))
    flow.append(_p("再平衡建議：", STYLE_BODY))
    flow.extend(_bullets(ctx["rebalance"]))

    flow.append(_p("七、每月投資建議", STYLE_H2))
    flow.extend(_plain_lines(ctx["monthly_allocation"]))

    flow.append(_p("八、後續追蹤重點", STYLE_H2))
    flow.extend(_bullets(ctx["monthly_focus"]))

    flow.append(_p("九、市場情報：月營收、財報、新聞、法說會、三大法人買賣超", STYLE_H2))
    flow.append(
        _p(
            "月營收／財報來源：證交所 OpenAPI（僅上市）；新聞：Google 新聞；"
            "法說會：公開資訊觀測站；三大法人買賣超：證交所（上市，含細項）／櫃買中心（上櫃，僅合計）。",
            STYLE_SMALL,
        )
    )
    flow.extend(_market_intel_flowables(holdings, ctx.get("market_intel", {})))

    flow.append(_p("十、潛力新標的觀察", STYLE_H2))
    flow.append(
        _p(
            "人工整理的權值股／優質股／熱門ETF候選池，篩掉目前追高的標的，"
            "依 Investment Score 分「高價股」「低價股」各挑出評分最高的幾檔，僅供觀察參考，非買進建議。",
            STYLE_SMALL,
        )
    )
    flow.extend(_candidate_watchlist_flowables(ctx.get("candidate_watchlist", [])))

    flow.append(_p("潛力新標的觀察（ETF）", STYLE_H2))
    flow.append(
        _p(
            "ETF 不套用個股的基本面/成長性/籌碼面評分，改用規模/費用率/配息政策50%＋技術面30%"
            "＋市場環境15%＋估值5%。候選池已排除槓桿反向型（正2/反1）與期貨型，僅收長期持有"
            "導向的市值型／高股息型／產業主題型 ETF，僅供觀察參考，非買進建議。",
            STYLE_SMALL,
        )
    )
    flow.extend(_candidate_watchlist_flowables(ctx.get("candidate_watchlist_etf", [])))

    flow.append(Spacer(1, 16))
    flow.append(
        _p(
            "本報告依公開市場資料與規則化邏輯自動產生，僅供個人投資參考，"
            "不構成任何形式的投資建議或保證，投資決策與風險請自行評估承擔。",
            STYLE_SMALL,
        )
    )
    return flow


def generate_pdf_report(holdings, ctx: dict, path: str = PDF_REPORT_PATH) -> str:
    doc = SimpleDocTemplate(
        path,
        pagesize=landscape(A4),
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        title="投資報告",
    )
    doc.build(build_pdf_flowables(holdings, ctx))
    return path


if __name__ == "__main__":
    from portfolio import load_portfolio, enrich_with_market_data, build_report_context

    _holdings = load_portfolio()
    enrich_with_market_data(_holdings)
    _ctx = build_report_context(_holdings)
    saved_path = generate_pdf_report(_holdings, _ctx)
    print(f"投資報告 PDF 已產生：{saved_path}")
