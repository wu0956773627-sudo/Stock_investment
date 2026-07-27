"""把投資報告轉成 PDF，取代 Email 附件原本直接寄送的 Markdown 檔（.md 在多數郵件用戶端／手機開啟時排版很醜）。

直接用 reportlab 排版產生 PDF，**不透過 xhtml2pdf 這類 HTML→PDF 轉換**：
實測發現 xhtml2pdf 處理中文字型時，中文字元會整段跑版成缺字方框（■），
即使已正確註冊 TrueType 中文字型也一樣；改用 reportlab 直接繪製（platypus flowables）
搭配 Windows 內建的標楷體（`C:\\Windows\\Fonts\\kaiu.ttf`）則完全正常。

使用者要求整體字體不小於 14pt（老花眼不好閱讀太小的字），本檔案的內文／條列字體
固定在 14pt，只有表格內容（欄位較多，14pt 會超版面）採 12pt 折衷。
"""

from datetime import datetime
import xml.sax.saxutils as saxutils

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from portfolio import (
    weight,
    cost_weight,
    current_price_display,
    industry_or_sector_label_zh,
    market_intel_highlight,
    MAX_CARRYOVER_MONTHS,
)

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
        if h.pnl is not None and h.pnl_pct is not None:
            pnl_color = "#c62828" if h.pnl >= 0 else "#2e7d32"  # 台股慣例：紅漲綠跌
            pnl = f'<font color="{pnl_color}">{h.pnl:,.0f}({h.pnl_pct:+.1%})</font>'
        else:
            pnl = "N/A"
        w = weight(h, total_value)
        w_str = f"{w:.1%}" if w is not None else "N/A"
        rows.append([h.code, h.name, price, mv, pnl, w_str])
    return _make_table(headers, rows, [2 * cm, 3.6 * cm, 2.6 * cm, 3 * cm, 3.6 * cm, 2.4 * cm])


def _fundamentals_table(holdings) -> Table:
    headers = ["代號", "名稱", "產業", "本益比(TTM)", "目前股價", "法人目標價"]
    rows = []
    for h in holdings:
        pe = f"{h.trailing_pe:.1f}" if h.trailing_pe else "N/A"
        target = f"{h.target_mean_price:,.1f}" if h.target_mean_price else "N/A"
        rows.append([h.code, h.name, industry_or_sector_label_zh(h), pe, current_price_display(h), target])
    return _make_table(headers, rows, [2 * cm, 3.6 * cm, 5 * cm, 3 * cm, 3.6 * cm, 3.4 * cm])


def _buy_points_table(buy_points_data: list[dict]) -> Table:
    headers = ["代號", "名稱", "近一年區間", "建議承接區間", "現價位置", "法人目標價", "上漲空間"]
    rows = []
    for bp in buy_points_data:
        week52 = bp.get("week52_range") or "N/A"
        zone = bp.get("suggested_zone") or "N/A"
        pos = bp.get("price_position") or "N/A"
        target = f"{bp['target_price']:,.1f}" if bp.get("target_price") is not None else "N/A"
        upside = f"{bp['upside_pct']:+.1%}" if bp.get("upside_pct") is not None else "N/A"
        rows.append([bp["code"], bp["name"], week52, zone, pos, target, upside])
    if not rows:
        rows.append(["N/A", "N/A", "N/A", "N/A", "暫無資料。", "N/A", "N/A"])
    return _make_table(headers, rows, [1.8 * cm, 3 * cm, 3.4 * cm, 3.4 * cm, 5.4 * cm, 2.8 * cm, 2.4 * cm])


def _ai_scoring_table(holdings, ai_scoring: dict) -> Table:
    headers = ["訊號", "代號", "名稱", "說明", "Investment Score", "Risk Score", "法人目標價", "關鍵理由"]
    rows = []
    for h in holdings:
        r = ai_scoring.get(h.code)
        if not r:
            rows.append(["N/A", h.code, h.name, "尚無評分資料。", "N/A", "N/A", "N/A", "N/A"])
            continue

        star_marker = '<font color="#6a1b9a"><b>【重點】</b></font>' if r.get("star") else ""
        signal_cell = f"{star_marker}{_signal_marker(r['signal'])}"
        score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
        risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
        target_str = f"{r['target_price']:,.1f}" if r.get("target_price") is not None else "N/A"
        reasons = "<br/>".join(r.get("reasons") or []) or "N/A"
        rows.append([signal_cell, h.code, h.name, r["label"], score_str, risk_str, target_str, reasons])
    if not rows:
        rows.append(["N/A", "N/A", "N/A", "暫無資料。", "N/A", "N/A", "N/A", "N/A"])
    return _make_table(headers, rows, [2.4 * cm, 1.8 * cm, 3 * cm, 5 * cm, 2.4 * cm, 2 * cm, 2.4 * cm, 6.5 * cm])


def _market_intel_table(holdings, market_intel: dict) -> Table:
    """需求 7：精簡成「重點摘要」表格（代號/名稱/重點摘要 + 相關新聞連結）。"""
    headers = ["代號", "名稱", "重點摘要", "相關新聞"]
    rows = []
    for h in holdings:
        info = market_intel.get(h.code)
        highlight = market_intel_highlight(info)
        news = (info.get("general_news") or [])[:3] if info else []
        if news:
            news_cell = "<br/>".join(
                f'<a href={saxutils.quoteattr(n["link"])} color="#1a5fb4">{saxutils.escape(n["title"])}</a>'
                for n in news
            )
        else:
            news_cell = "N/A"
        rows.append([h.code, h.name, highlight, news_cell])
    if not rows:
        rows.append(["N/A", "N/A", "暫無資料。", "N/A"])
    return _make_table(headers, rows, [1.8 * cm, 3.2 * cm, 8 * cm, 10 * cm])


def _candidate_table(candidates: list[dict]) -> Table:
    headers = ["星等", "代號", "名稱", "股價", "Investment Score", "Risk Score", "法人目標價", "關鍵理由"]
    rows = []
    for r in candidates:
        score_str = f"{r['investment_score']:.0f}" if r.get("investment_score") is not None else "N/A"
        risk_str = f"{r['risk_score']:.0f}" if r.get("risk_score") is not None else "N/A"
        target_str = f"{r['target_price']:,.1f}" if r.get("target_price") is not None else "N/A"
        reasons = "<br/>".join(r.get("reasons") or []) or "N/A"
        rows.append(
            [r.get("conviction_stars") or "N/A", r["code"], r["name"], f"{r['price']:,.1f}", score_str, risk_str, target_str, reasons]
        )
    return _make_table(headers, rows, [2.2 * cm, 1.8 * cm, 3 * cm, 2.2 * cm, 2.4 * cm, 2 * cm, 2.4 * cm, 6.5 * cm])


def _candidate_watchlist_flowables(candidates: list[dict]) -> list:
    """目前沒有持有、評分較高的候選新標的（跟既有持股分開，回答「還有沒有值得考慮加入的新標的」）。
    個股一張表、ETF 一張表（呼叫端各自傳入自己的 candidates），維持既有「高價股/低價股」分組。
    """
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
        flowables.append(_candidate_table(group))
        flowables.append(Spacer(1, 6))
    return flowables


def _monthly_priority_table(priority_list: list[dict]) -> Table:
    headers = ["順位", "代號", "名稱", "Investment Score", "長期信心"]
    rows = []
    for p in priority_list:
        inv_str = f"{p['investment_score']:.0f}" if p.get("investment_score") is not None else "N/A"
        rows.append([str(p["rank"]), p["code"], p["name"], inv_str, p.get("conviction_stars", "N/A")])
    return _make_table(headers, rows, [1.6 * cm, 1.8 * cm, 3.6 * cm, 3.2 * cm, 2.6 * cm])


def _monthly_allocation_table(allocations: list[dict]) -> Table:
    headers = ["代號", "名稱", "投入金額", "買進階段", "本輪比例", "約可買股數", "備註"]
    rows = []
    for a in allocations:
        rows.append(
            [
                a["code"],
                a["name"],
                f"{a['amount']:,.0f}",
                a["tier_label"],
                f"{a['tier_pct']:.0%}",
                f"{a['shares']:,.1f}",
                a.get("note") or "",
            ]
        )
    return _make_table(headers, rows, [1.8 * cm, 3 * cm, 2.6 * cm, 4 * cm, 2 * cm, 2.6 * cm, 6 * cm])


def _monthly_allocation_flowables(data: dict) -> list:
    """需求 6：優先購買清單＋資金分配改成表格，總預算說明／尚未分配結轉／排除加碼說明維持文字。"""
    if data.get("no_value_note"):
        return [_p(data["no_value_note"], STYLE_BODY)]

    amount = data["amount"]
    carryover = data["carryover"]
    total_budget = data["total_budget"]
    flowables = [
        _p(
            f"本月可投資金額：新台幣 {total_budget:,.0f} 元"
            + (f"（月定期定額 {amount:,.0f} 元＋現金流結餘 {carryover:,.0f} 元，結轉上限 {data['carryover_cap']:,.0f} 元）" if carryover else f"（月定期定額 {amount:,.0f} 元）"),
            STYLE_BODY,
        )
    ]

    if data.get("no_candidates_note"):
        flowables.append(_p(data["no_candidates_note"], STYLE_BODY))
        flowables.extend(_bullets(data.get("excluded_notes") or []))
        return flowables

    flowables.append(_p("優先購買清單（依 Investment Score／長期持股信心排序）", STYLE_BODY))
    flowables.append(_monthly_priority_table(data["priority_list"]))
    flowables.append(Spacer(1, 8))
    flowables.append(_p("本月資金分配（集中在優先順序最前面的標的，不是每檔都買一點；資金用完或達上限為止）", STYLE_BODY))
    flowables.append(_monthly_allocation_table(data["allocations"]))
    flowables.append(Spacer(1, 8))

    if data.get("remaining") is not None:
        flowables.append(
            _p(
                f"尚未分配：{data['remaining']:,.0f} 元，將結轉至下月（結轉上限：{MAX_CARRYOVER_MONTHS} 個月投入金額 {data['carryover_cap']:,.0f} 元）。",
                STYLE_BODY,
            )
        )
    if data.get("no_allocation_note"):
        flowables.append(_p(data["no_allocation_note"], STYLE_BODY))
    flowables.extend(_bullets(data.get("excluded_notes") or []))

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
    total_pnl_color = "#c62828" if (ctx["total_pnl"] or 0) >= 0 else "#2e7d32"  # 台股慣例：紅漲綠跌
    flow.append(_p(f'總報酬：新台幣 <font color="{total_pnl_color}">{ctx["total_pnl"]:,.0f} 元（{total_pnl_pct_str}）</font>', STYLE_BODY))
    idx = ctx.get("market_index")
    if idx and idx.get("close") is not None:
        change_str = f"{idx['change_points']:+,.2f}（{idx['change_pct']:+.2f}%）" if idx.get("change_points") is not None else "N/A"
        flow.append(_p(f"大盤{idx['name']}：{idx['close']:,.2f} 點，漲跌 {change_str}", STYLE_BODY))
    flow.append(Spacer(1, 8))
    flow.append(_holdings_table(holdings, ctx["total_value"], ctx["total_cost"]))

    flow.append(_p("二、個股分析", STYLE_H2))
    flow.append(_fundamentals_table(holdings))

    flow.append(_p("三、合理買點", STYLE_H2))
    flow.append(_buy_points_table(ctx.get("buy_points_data", [])))

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
    flow.append(_ai_scoring_table(holdings, ctx.get("ai_scoring", {})))

    flow.append(_p("五、產業配置建議", STYLE_H2))
    sector_headers = ["產業別", "佔投組市值比重"]
    sector_rows = [[sector, f"{w:.1%}"] for sector, w in ctx["sector_allocation"].items()]
    if sector_rows:
        flow.append(_make_table(sector_headers, sector_rows, [8 * cm, 5 * cm]))
        flow.append(Spacer(1, 8))
    flow.extend(_bullets(ctx["sector_advice"]))

    flow.append(_p("六、風險評估與再平衡", STYLE_H2))
    flow.append(_p("風險評估：", STYLE_BODY))
    flow.extend(_bullets(ctx["risk"]))
    flow.append(_p("再平衡建議：", STYLE_BODY))
    flow.extend(_bullets(ctx["rebalance"]))

    flow.append(_p("七、每月投資建議", STYLE_H2))
    flow.extend(_monthly_allocation_flowables(ctx.get("monthly_allocation_data", {})))

    flow.append(_p("八、後續追蹤重點", STYLE_H2))
    flow.extend(_bullets(ctx["monthly_focus"]))

    flow.append(_p("九、市場情報：重點摘要", STYLE_H2))
    flow.append(
        _p(
            "依優先序（重大訊息 > 三大法人買賣超 > 月營收年增率 > 下一場法說會）只挑一項最值得注意的重點；"
            "月營收／財報來源：證交所 OpenAPI（僅上市）；新聞：Google 新聞；"
            "法說會：公開資訊觀測站；三大法人買賣超：證交所（上市，含細項）／櫃買中心（上櫃，僅合計）。",
            STYLE_SMALL,
        )
    )
    flow.append(_market_intel_table(holdings, ctx.get("market_intel", {})))

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
