"""短線類股輪動掃描（延伸功能，非本專案主要的長期持股分析）。

直接執行本檔案（`uv run python sector_rotation.py`）可在終端機預覽今天的輪動排名，
不會寄送任何 Email／LINE（寄送邏輯獨立在 `spouse_report.py`）。

依「3-7天平均漲跌幅」（3日與7日報酬率取平均，視為短期動能）排名族群與個股，
找出目前資金正在輪動進去的最強勢族群（強弱名次 1~3），
再從族群內挑出動能領先的個股，搭配 5日/10日均線給出參考買賣區間。

**較嚴謹的篩選條件**（比照主要持股分析的「禁止追高」精神）：RSI14 超過 80（嚴重過熱）
直接排除、依動能改往下一檔找，不會硬推已經噴出的高點；RSI14 落在 70~80 或成交量不足以
確認動能時，仍列入但附加「⚠」提醒。RSI／量能取自 `technicals.py`，重複利用同一份歷史股價。

**重要限制**：
- 這是短線技術面規則型參考（均線 + 近期高低點），不是基本面分析，
  也不是價格預測，短線進出風險遠高於本專案其他長期持股建議。
- WATCHLIST 是人工整理的常見台股熱門族群代表股，非全市場掃描，
  可能遺漏其他正在輪動的族群或個股。
"""

import sys
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import yfinance as yf

from technicals import compute_technicals

if hasattr(sys.stdout, "reconfigure"):
    # 輸出含 ⚠ 等符號，非 UTF-8 主控台（如 Windows cp950）印出時會 UnicodeEncodeError。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 篩選門檻（比照主要持股分析用的「禁止追高」精神，避免太太被建議追進已經過熱的標的）：
RSI_OVERBOUGHT_EXCLUDE = 80    # RSI14 超過此值直接排除，不列入建議（追高風險過高）
RSI_CAUTION_THRESHOLD = 70     # RSI14 超過此值仍列入，但附加「偏熱」提醒
MIN_VOLUME_RATIO = 0.8         # 成交量低於近20日均量的 80%，視為量能不足以確認動能，附加提醒

DISCLAIMER = (
    "本報告為短線技術面規則型參考（依5日/10日均線與近期高低點計算買賣區間），"
    "非長期基本面分析，短線進出風險較高，不保證獲利，請自行評估風險。"
)

# 太太的 Email 較常在手機上瞄一眼，字體特別加大（14.5~16px 以上）、股票名稱/代號分別用
# 醒目對比色標示，方便快速抓到重點，不用逐字看內文。
HTML_BASE_FONT_PX = 15
HTML_HEADER_FONT_PX = 17
HTML_STOCK_FONT_PX = 16
HTML_NAME_COLOR = "#c2255c"   # 股票名稱：醒目玫瑰紅
HTML_CODE_COLOR = "#1864ab"   # 股票代號：醒目寶藍
HTML_SELL_ZONE_COLOR = "#e03131"  # 獲利了結區間價位：醒目紅（避免用綠色——台股慣例綠色代表下跌，語意會反過來）

WATCHLIST: dict[str, list[str]] = {
    "記憶體": ["2344", "2408", "3260", "8299", "2337"],
    "半導體/IC設計": ["2330", "2454", "3034", "2379"],
    "AI伺服器/散熱": ["3017", "2382", "2376", "6669"],
    "航運": ["2603", "2609", "2615"],
    "金融": ["2886", "2891", "2892"],
    "生技製藥": ["4174", "6547", "1795"],
    "網通": ["2345", "4938"],
    "面板": ["3481", "2409"],
    "綠能/太陽能": ["6244", "3691"],
    "重電": ["1513", "1519", "1503", "1504", "1514"],
    "軍工": ["2634", "8033", "6753", "5371"],
}

STOCK_NAMES: dict[str, str] = {
    "2344": "華邦電", "2408": "南亞科", "3260": "威剛", "8299": "群聯", "2337": "旺宏",
    "2330": "台積電", "2454": "聯發科", "3034": "聯詠", "2379": "瑞昱",
    "3017": "奇鋐", "2382": "廣達", "2376": "技嘉", "6669": "緯穎",
    "2603": "長榮", "2609": "陽明", "2615": "萬海",
    "2886": "兆豐金", "2891": "中信金", "2892": "第一金",
    "4174": "浩鼎", "6547": "高端疫苗", "1795": "美時",
    "2345": "智邦", "4938": "和碩",
    "3481": "群創", "2409": "友達",
    "6244": "茂迪", "3691": "碩禾",
    "1513": "中興電", "1519": "華城", "1503": "士電", "1504": "東元", "1514": "亞力",
    "2634": "漢翔", "8033": "雷虎", "6753": "龍德造船", "5371": "中光電",
}

CODE_TO_GROUP: dict[str, str] = {code: group for group, codes in WATCHLIST.items() for code in codes}


@dataclass
class StockMetrics:
    code: str
    price: float
    ma5: float
    ma10: float | None
    ret_3d: float | None
    ret_7d: float | None
    recent_low: float
    recent_high: float
    rsi14: float | None = None
    volume_ratio: float | None = None

    @property
    def momentum(self) -> float | None:
        """3-7天動能：ret_3d 與 ret_7d 都有時取平均，只有一個時就用那一個。"""
        vals = [v for v in (self.ret_3d, self.ret_7d) if v is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def is_overbought(self) -> bool:
        """RSI14 過熱，視為追高風險過高，不應再列入建議。"""
        return self.rsi14 is not None and self.rsi14 > RSI_OVERBOUGHT_EXCLUDE

    @property
    def caution_note(self) -> str:
        """較嚴謹的篩選提醒：RSI 偏熱或量能不足以確認動能時附加說明，不是硬性排除。"""
        notes = []
        if self.rsi14 is not None and RSI_CAUTION_THRESHOLD < self.rsi14 <= RSI_OVERBOUGHT_EXCLUDE:
            notes.append(f"RSI14 已達 {self.rsi14:.0f}，短線偏熱")
        if self.volume_ratio is not None and self.volume_ratio < MIN_VOLUME_RATIO:
            notes.append("最近買賣的人不多，這波上漲買氣不夠熱絡，訊號較不可靠")
        return "；".join(notes)


def _fetch_history(code: str) -> pd.DataFrame | None:
    for suffix in (".TW", ".TWO"):
        try:
            hist = yf.Ticker(f"{code}{suffix}").history(period="1mo")
        except Exception:
            continue
        if not hist.empty:
            return hist
    return None


def compute_stock_metrics(code: str) -> StockMetrics | None:
    hist = _fetch_history(code)
    if hist is None or len(hist) < 6:
        return None

    close = hist["Close"]
    ret_3d = (close.iloc[-1] / close.iloc[-4] - 1) if len(close) >= 4 else None
    ret_7d = (close.iloc[-1] / close.iloc[-8] - 1) if len(close) >= 8 else None
    tech = compute_technicals(hist)

    return StockMetrics(
        code=code,
        price=float(close.iloc[-1]),
        ma5=float(close.tail(5).mean()),
        ma10=float(close.tail(10).mean()) if len(close) >= 10 else None,
        ret_3d=float(ret_3d) if ret_3d is not None else None,
        ret_7d=float(ret_7d) if ret_7d is not None else None,
        recent_low=float(close.tail(10).min()),
        recent_high=float(close.tail(10).max()),
        rsi14=tech.get("rsi14"),
        volume_ratio=tech.get("volume_ratio"),
    )


def scan_sector_rotation() -> dict:
    """回傳各族群依「3-7天平均漲跌幅（動能）」排名，以及每檔個股的均線/區間資料。"""
    group_avg_momentum: dict[str, float] = {}
    stock_cache: dict[str, StockMetrics] = {}

    for group, codes in WATCHLIST.items():
        momentums = []
        for code in codes:
            m = compute_stock_metrics(code)
            if m is None:
                continue
            stock_cache[code] = m
            if m.momentum is not None:
                momentums.append(m.momentum)
        if momentums:
            group_avg_momentum[group] = sum(momentums) / len(momentums)

    ranked_groups = sorted(group_avg_momentum.items(), key=lambda x: x[1], reverse=True)
    return {"ranked_groups": ranked_groups, "stock_metrics": stock_cache}


def estimate_holding_days(price: float, sell_zone: float, ret_3d: float | None) -> int:
    """用近3日日均漲幅推估到達獲利了結區間大約要幾個交易日，限制在 2~10 天區間。"""
    daily_rate = (ret_3d / 3) if ret_3d and ret_3d > 0 else 0.01
    distance = max(sell_zone / price - 1, 0.0)
    days = round(distance / daily_rate) if daily_rate > 0 else 5
    return min(max(days, 2), 10)


def _build_stock_entry(m: StockMetrics, group: str | None = None, group_momentum: float | None = None, rank: int | None = None) -> dict:
    ma_low, ma_high = sorted([m.ma5, m.ma10 if m.ma10 is not None else m.ma5])
    buy_mid = (ma_low + ma_high) / 2
    potential_return_pct = (m.recent_high / buy_mid - 1) if buy_mid else None
    return {
        "rank": rank,
        "group": group,
        "group_momentum": group_momentum,
        "code": m.code,
        "name": STOCK_NAMES.get(m.code, m.code),
        "price": m.price,
        "caution_note": m.caution_note,
        "momentum": m.momentum,
        "estimated_days": estimate_holding_days(m.price, m.recent_high, m.ret_3d),
        "buy_zone": (ma_low, ma_high),
        "sell_zone": m.recent_high,
        "potential_return_pct": potential_return_pct,
    }


def build_recommendations(scan_result: dict, top_n_groups: int = 5, top_n_stocks: int = 5) -> list[dict]:
    """從最強勢的前 N 個族群中，依同樣的 3-7天動能挑出領先個股，並用均線/近期區間算出買賣參考價位。
    每個族群會標上強弱名次（1=最強）。
    """
    recommendations = []

    for rank, (group, group_momentum) in enumerate(scan_result["ranked_groups"][:top_n_groups], start=1):
        codes = WATCHLIST[group]
        stocks = [scan_result["stock_metrics"][c] for c in codes if c in scan_result["stock_metrics"]]
        stocks.sort(key=lambda m: m.momentum or float("-inf"), reverse=True)

        # 較嚴謹的篩選：RSI14 過熱（追高風險過高）直接跳過，依動能排序往下找下一檔，
        # 不是機械式取前 N 檔——寧可這個族群少推薦一檔，也不要把太太推進已經噴出的高點。
        selected = [m for m in stocks if not m.is_overbought][:top_n_stocks]

        for m in selected:
            recommendations.append(_build_stock_entry(m, group=group, group_momentum=group_momentum, rank=rank))

    return recommendations


def build_top_stocks_by_price(scan_result: dict, top_n: int = 5) -> list[dict]:
    """跨所有族群（不限於前幾強），依3-7天動能取前N檔個股（同樣排除RSI過熱的追高風險），
    再依「股價單價」由低到高排序——方便太太快速比較，優先看得懂便宜好入手的標的。
    """
    stocks = [m for m in scan_result["stock_metrics"].values() if not m.is_overbought]
    stocks.sort(key=lambda m: m.momentum or float("-inf"), reverse=True)
    top = stocks[:top_n]
    top.sort(key=lambda m: m.price)
    return [_build_stock_entry(m, group=CODE_TO_GROUP.get(m.code)) for m in top]


def _format_stock_line(r: dict) -> str:
    return_str = f"約+{r['potential_return_pct']:.1%}" if r["potential_return_pct"] is not None else "N/A"
    caution = f"　⚠{r['caution_note']}" if r.get("caution_note") else ""
    return (
        f"- {r['name']}（{r['code']}）　股價：{r['price']:.1f}　"
        f"買入區間：{r['buy_zone'][0]:.1f}~{r['buy_zone'][1]:.1f}　"
        f"獲利了結區間：約{r['sell_zone']:.1f}　"
        f"潛在損益率：{return_str}　"
        f"預估天數：約{r['estimated_days']}天{caution}"
    )


def build_report_text(recommendations: list[dict], top_stocks_by_price: list[dict] | None = None) -> str:
    lines = [f"短線類股輪動觀察（{datetime.now().strftime('%Y-%m-%d')}）", ""]

    if not recommendations:
        lines.append("目前watchlist資料不足或無明顯輪動族群，暫無建議標的。")
    else:
        current_rank = None
        for r in recommendations:
            if r["rank"] != current_rank:
                current_rank = r["rank"]
                lines.append(f"■ 輪動排名{r['rank']}：{r['group']}")
            lines.append(_format_stock_line(r))
        lines.append("")

    if top_stocks_by_price:
        lines.append("■ 個股動能 Top5（依股價單價由低到高排序，方便比較好入手的標的）")
        for r in top_stocks_by_price:
            group_note = f"　所屬族群：{r['group']}" if r.get("group") else ""
            lines.append(_format_stock_line(r) + group_note)
        lines.append("")

    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _stock_name_code_html(name: str, code: str) -> str:
    return (
        f'<span style="color:{HTML_NAME_COLOR};font-weight:700;font-size:{HTML_STOCK_FONT_PX}px;">{name}</span>'
        f'（<span style="color:{HTML_CODE_COLOR};font-weight:700;font-size:{HTML_STOCK_FONT_PX}px;">{code}</span>）'
    )


def _format_stock_html(r: dict) -> str:
    return_str = f"約+{r['potential_return_pct']:.1%}" if r["potential_return_pct"] is not None else "N/A"
    caution = f'　<span style="color:#e8590c;">⚠{r["caution_note"]}</span>' if r.get("caution_note") else ""
    return (
        f'<div style="margin:6px 0;font-size:{HTML_BASE_FONT_PX}px;line-height:1.7;">'
        f'{_stock_name_code_html(r["name"], r["code"])}　股價：{r["price"]:.1f}　'
        f'買入區間：{r["buy_zone"][0]:.1f}~{r["buy_zone"][1]:.1f}　'
        f'獲利了結區間：'
        f'<span style="color:{HTML_SELL_ZONE_COLOR};font-weight:900;font-size:{HTML_STOCK_FONT_PX}px;">約{r["sell_zone"]:.1f}</span>　'
        f'潛在損益率：{return_str}　'
        f'預估天數：約{r["estimated_days"]}天{caution}'
        f'</div>'
    )


# ── 表格化呈現（HTML Email 版用，取代原本一行一筆的條列格式） ─────────────────────────────
HTML_TABLE_HEAD_BG = "#1a3d6d"
HTML_TABLE_GRID = "#d0d7e2"
HTML_PNL_GREEN = "#2f9e44"  # 損益為負：綠（台股慣例紅漲綠跌，紅=正向已用 HTML_SELL_ZONE_COLOR）

_TABLE_COLUMNS = ["輪動排名", "輪動類別", "股票名稱", "股票代號", "股價", "買入區間", "獲利了結區間", "損益", "預估天數", "備註"]


def _table_row_html(r: dict) -> str:
    rank_str = str(r["rank"]) if r.get("rank") is not None else "－"
    group_str = r.get("group") or "－"
    return_str = f"約+{r['potential_return_pct']:.1%}" if r["potential_return_pct"] is not None else "N/A"
    return_color = HTML_SELL_ZONE_COLOR if (r["potential_return_pct"] or 0) >= 0 else HTML_PNL_GREEN
    caution = r.get("caution_note") or ""

    cells = [
        rank_str,
        group_str,
        f'<span style="color:{HTML_NAME_COLOR};font-weight:700;">{r["name"]}</span>',
        f'<span style="color:{HTML_CODE_COLOR};font-weight:700;">{r["code"]}</span>',
        f'{r["price"]:.1f}',
        f'{r["buy_zone"][0]:.1f}~{r["buy_zone"][1]:.1f}',
        f'<span style="color:{HTML_SELL_ZONE_COLOR};font-weight:900;">約{r["sell_zone"]:.1f}</span>',
        f'<span style="color:{return_color};font-weight:900;">{return_str}</span>',
        f'約{r["estimated_days"]}天',
        f'<span style="color:#e8590c;">⚠{caution}</span>' if caution else "－",
    ]
    tds = "".join(
        f'<td style="padding:6px 8px;border:1px solid {HTML_TABLE_GRID};'
        f'font-size:{HTML_BASE_FONT_PX}px;white-space:nowrap;">{c}</td>'
        for c in cells
    )
    return f"<tr>{tds}</tr>"


def _rotation_table_html(rows: list[dict]) -> str:
    header = "".join(
        f'<th style="padding:6px 8px;border:1px solid {HTML_TABLE_GRID};'
        f'background:{HTML_TABLE_HEAD_BG};color:#ffffff;font-size:{HTML_BASE_FONT_PX}px;'
        f'white-space:nowrap;">{c}</th>'
        for c in _TABLE_COLUMNS
    )
    body = "".join(_table_row_html(r) for r in rows)
    return (
        '<table style="border-collapse:collapse;margin:8px 0;">'
        f'<tr>{header}</tr>{body}</table>'
    )


def build_report_html(recommendations: list[dict], top_stocks_by_price: list[dict] | None = None) -> str:
    """跟 build_report_text() 內容相同，改用實際 HTML `<table>` 表格化呈現（取代逐行條列），
    欄位：輪動排名／輪動類別／股票名稱／股票代號／股價／買入區間／獲利了結區間／損益／
    預估天數／備註（RSI偏熱或量能不足的提醒，沒有就顯示「－」）。股票名稱／代號沿用醒目對比色，
    字體全面加大（14.5~16px 以上），供 Email HTML 版使用（純文字版 `build_report_text()` 仍
    保留條列格式當備援，收信端不支援 HTML 時顯示）。
    """
    parts = [
        '<div style="font-family:\'Microsoft JhengHei\',Arial,sans-serif;'
        f'font-size:{HTML_BASE_FONT_PX}px;color:#212529;line-height:1.7;">',
        f'<div style="font-size:{HTML_HEADER_FONT_PX}px;font-weight:700;margin-bottom:10px;">'
        f'短線類股輪動觀察（{datetime.now().strftime("%Y-%m-%d")}）</div>',
    ]

    if not recommendations:
        parts.append(f'<div style="font-size:{HTML_BASE_FONT_PX}px;">目前watchlist資料不足或無明顯輪動族群，暫無建議標的。</div>')
    else:
        parts.append(f'<div style="overflow-x:auto;">{_rotation_table_html(recommendations)}</div>')

    if top_stocks_by_price:
        parts.append(
            f'<div style="font-size:{HTML_HEADER_FONT_PX}px;font-weight:700;margin:18px 0 4px;">'
            '■ 個股動能 Top5（依股價單價由低到高排序，方便比較好入手的標的）</div>'
        )
        parts.append(f'<div style="overflow-x:auto;">{_rotation_table_html(top_stocks_by_price)}</div>')

    parts.append(
        f'<div style="font-size:14.5px;color:#495057;margin-top:16px;">{DISCLAIMER}</div>'
    )
    parts.append("</div>")
    return "".join(parts)


if __name__ == "__main__":
    _scan = scan_sector_rotation()
    print(build_report_text(build_recommendations(_scan), build_top_stocks_by_price(_scan)))
