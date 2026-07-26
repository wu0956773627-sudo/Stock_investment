"""v4.0：月營收、財報重點、重大訊息、新聞、法說會排程、大盤指數、三大法人買賣超、即時報價。

全部使用免費公開資料源，不需申請、不需金鑰：
- 台灣證交所 OpenAPI（openapi.twse.com.tw）：月營收、損益表、每日重大訊息、大盤指數（僅涵蓋上市公司）
- Google 新聞 RSS：中文財經新聞（不限個股類型，ETF／上櫃股也適用）
- 公開資訊觀測站（mopsov.twse.com.tw）「法人說明會一覽表」：上市／上櫃／興櫃法說會排程
- 證交所官方三大法人買賣超日報（www.twse.com.tw/rwd）：上市個股外資／投信／自營商買賣超細項
- 櫃買中心三大法人買賣明細（www.tpex.org.tw）：上櫃個股三大法人買賣超合計（欄位無法拆分細項）
- 證交所看盤資訊 API（mis.twse.com.tw）：近即時成交價（比 yfinance 更即時，但仍非逐筆委託資料）

上櫃股（如 6550 北極星藥業-KY）不在 TWSE OpenAPI 涵蓋範圍內，會回傳 None，
呼叫端需自行處理缺值。
"""

import html
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import quote

import requests

TWSE_OPENAPI = "https://openapi.twse.com.tw/v1/opendata"


def _fetch_twse(dataset: str) -> list[dict]:
    try:
        r = requests.get(f"{TWSE_OPENAPI}/{dataset}", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def fetch_monthly_revenue_map() -> dict[str, dict]:
    """代號 -> 最新月營收資料（僅上市公司，t187ap05_L）。"""
    return {d["公司代號"]: d for d in _fetch_twse("t187ap05_L")}


INCOME_STATEMENT_DATASETS = [
    "t187ap06_L_ci",  # 一般業
    "t187ap06_L_fh",  # 金控業
    "t187ap06_L_bd",  # 證券期貨業
    "t187ap06_L_ins",  # 保險業
    "t187ap06_L_mim",  # 金融業
]


def fetch_income_statement_map() -> dict[str, dict]:
    """代號 -> 最新季損益表（合併一般業／金控／證券期貨／保險／金融業，僅上市公司）。"""
    result: dict[str, dict] = {}
    for dataset in INCOME_STATEMENT_DATASETS:
        for d in _fetch_twse(dataset):
            result[d["公司代號"]] = d
    return result


BALANCE_SHEET_DATASETS = [
    "t187ap07_L_ci",  # 一般業
    "t187ap07_L_fh",  # 金控業
    "t187ap07_L_bd",  # 證券期貨業
    "t187ap07_L_ins",  # 保險業
    "t187ap07_L_mim",  # 金融業
]


def fetch_balance_sheet_map() -> dict[str, dict]:
    """代號 -> 最新季資產負債表（合併各業別，僅上市公司）。"""
    result: dict[str, dict] = {}
    for dataset in BALANCE_SHEET_DATASETS:
        for d in _fetch_twse(dataset):
            result[d["公司代號"]] = d
    return result


def fetch_profitability_map() -> dict[str, dict]:
    """代號 -> 最新季營益分析（毛利率／營業利益率／稅前稅後純益率，t187ap17_L，僅上市公司）。"""
    return {d["公司代號"]: d for d in _fetch_twse("t187ap17_L")}


def fetch_dividend_policy_map() -> dict[str, dict]:
    """代號 -> 最新一次股利分派情形（t187ap45_L，僅上市公司）。"""
    result: dict[str, dict] = {}
    for d in _fetch_twse("t187ap45_L"):
        result[d["公司代號"]] = d  # 資料本身依出表日期排序，後面的會覆蓋成最新一筆
    return result


def fetch_margin_trading_map() -> dict[str, dict]:
    """代號 -> 當日融資融券餘額（exchangeReport/MI_MARGN，僅上市；上櫃無對應免費資料源）。"""
    result: dict[str, dict] = {}
    for d in _fetch_twse("exchangeReport/MI_MARGN"):
        result[d["股票代號"]] = d
    return result


def fetch_director_holdings_map() -> dict[str, dict]:
    """代號 -> 董監持股彙總（合計目前持股、最高單一設質比例，t187ap11_L，僅上市公司）。"""
    totals: dict[str, dict] = {}
    for d in _fetch_twse("t187ap11_L"):
        code = d["公司代號"]
        holding = _to_number(d.get("目前持股"))
        pledge_ratio = _to_number((d.get("設質股數佔持股比例") or "").rstrip("%"))
        entry = totals.setdefault(code, {"total_shares": 0.0, "max_pledge_ratio": 0.0})
        if holding is not None:
            entry["total_shares"] += holding
        if pledge_ratio is not None:
            entry["max_pledge_ratio"] = max(entry["max_pledge_ratio"], pledge_ratio)
    return totals


def fetch_major_shareholders_map() -> dict[str, list[str]]:
    """代號 -> 持股逾 10% 大股東名稱清單（t187ap02_L，僅上市公司；只有名單沒有持股比例數字）。"""
    result: dict[str, list[str]] = {}
    for d in _fetch_twse("t187ap02_L"):
        result.setdefault(d["公司代號"], []).append(d["大股東名稱"])
    return result


BOOK_VALUE_KEYS = ["每股參考淨值"]
TOTAL_EQUITY_KEYS = ["權益總額", "權益總計"]
TOTAL_ASSETS_KEYS = ["資產總額", "資產總計"]
TOTAL_LIABILITIES_KEYS = ["負債總額", "負債總計"]


def normalize_financial_ratios(balance_sheet: dict | None, net_income: float | None) -> dict:
    """從資產負債表＋損益表淨利，換算負債比／流動比率／每股淨值／概算 ROE／ROA。
    算不出來的欄位回傳 None，不硬湊假數字（例如缺存貨資料就不算速動比率）。
    """
    result = {
        "debt_ratio": None,
        "current_ratio": None,
        "book_value_per_share": None,
        "roe": None,
        "roa": None,
        "treasury_stock": None,
    }
    if not balance_sheet:
        return result

    def _first(record: dict, keys: list[str]) -> float | None:
        for k in keys:
            if k in record and record[k] not in ("", None):
                return _to_number(record[k])
        return None

    current_assets = _to_number(balance_sheet.get("流動資產"))
    current_liabilities = _to_number(balance_sheet.get("流動負債"))
    total_assets = _first(balance_sheet, TOTAL_ASSETS_KEYS)
    total_liabilities = _first(balance_sheet, TOTAL_LIABILITIES_KEYS)
    total_equity = _first(balance_sheet, TOTAL_EQUITY_KEYS)
    book_value = _first(balance_sheet, BOOK_VALUE_KEYS)
    treasury = balance_sheet.get("庫藏股票")

    if total_liabilities is not None and total_assets:
        result["debt_ratio"] = total_liabilities / total_assets
    if current_assets is not None and current_liabilities:
        result["current_ratio"] = current_assets / current_liabilities
    result["book_value_per_share"] = book_value
    result["treasury_stock"] = _to_number(treasury) if treasury not in (None, "") else None
    if net_income is not None and total_equity:
        result["roe"] = net_income / total_equity
    if net_income is not None and total_assets:
        result["roa"] = net_income / total_assets
    return result


def fetch_material_news_map() -> dict[str, list[dict]]:
    """代號 -> 今日重大訊息列表（僅上市公司，t187ap04_L）。"""
    result: dict[str, list[dict]] = {}
    for d in _fetch_twse("t187ap04_L"):
        result.setdefault(d["公司代號"], []).append(d)
    return result


TWSE_INDEX_NAME = "發行量加權股價指數"


def _to_number(text: str | None) -> float | None:
    if text is None:
        return None
    text = text.strip().replace(",", "")
    if text in ("", "--", "-", "X", "N/A"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_market_index() -> dict | None:
    """大盤（加權指數）收盤、漲跌點數／百分比。"""
    for row in _fetch_twse("exchangeReport/MI_INDEX"):
        if row.get("指數") != TWSE_INDEX_NAME:
            continue
        points = _to_number(row.get("漲跌點數"))
        pct = _to_number(row.get("漲跌百分比"))
        sign = -1 if row.get("漲跌") == "-" else 1
        return {
            "name": row.get("指數"),
            "date": row.get("日期"),
            "close": _to_number(row.get("收盤指數")),
            "change_points": points * sign if points is not None else None,
            "change_pct": pct * sign if pct is not None else None,
        }
    return None


TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_INSTI_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"


def fetch_institutional_flow_map(max_lookback_days: int = 5) -> dict[str, dict]:
    """代號 -> 當日三大法人買賣超股數。
    上市（TWSE T86）欄位有清楚標示，拆分外資／投信／自營商／合計；
    上櫃（TPEx）JSON 欄位重複無法明確拆分細項，僅取三大法人合計欄。
    找不到當天資料（如非交易日）時，往前最多找 max_lookback_days 天。
    """
    result: dict[str, dict] = {}

    day = datetime.now()
    for _ in range(max_lookback_days):
        try:
            r = requests.get(
                TWSE_T86_URL,
                params={"response": "json", "date": day.strftime("%Y%m%d"), "selectType": "ALL"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception:
            payload = {}
        rows = payload.get("data") if payload.get("stat") == "OK" else None
        if rows:
            for row in rows:
                code = row[0].strip()
                result[code] = {
                    "date": payload.get("date"),
                    "foreign_net": _to_number(row[4]),
                    "trust_net": _to_number(row[10]),
                    "dealer_net": _to_number(row[11]),
                    "total_net": _to_number(row[-1]),
                }
            break
        day -= timedelta(days=1)

    day = datetime.now()
    for _ in range(max_lookback_days):
        try:
            r = requests.get(
                TPEX_INSTI_URL,
                params={"type": "Daily", "sect": "EW", "date": day.strftime("%Y/%m/%d"), "id": "", "response": "json"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            r.raise_for_status()
            payload = r.json()
            table = (payload.get("tables") or [{}])[0]
            rows = table.get("data")
        except Exception:
            rows = None
        if rows:
            for row in rows:
                code = row[0].strip()
                if code in result:
                    continue  # 已有上市資料，避免代號衝突覆蓋
                result[code] = {
                    "date": table.get("date"),
                    "foreign_net": None,
                    "trust_net": None,
                    "dealer_net": None,
                    "total_net": _to_number(row[-1]),
                }
            break
        day -= timedelta(days=1)

    return result


MIS_QUOTE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
MIS_MARKET_PREFIX = {"sii": "tse", "otc": "otc"}


def fetch_realtime_quotes(codes_by_market: dict[str, str]) -> dict[str, dict]:
    """code -> {'sii','otc'} 對照表，回傳 code -> 近即時報價（成交價、時間、昨收）。
    來源為證交所公開看盤 API，比 yfinance 的延遲快照更即時，但仍非逐筆委託成交明細。
    """
    ex_ch_list = [
        f"{MIS_MARKET_PREFIX[m]}_{code}.tw" for code, m in codes_by_market.items() if m in MIS_MARKET_PREFIX
    ]
    if not ex_ch_list:
        return {}
    try:
        r = requests.get(
            MIS_QUOTE_URL,
            params={"ex_ch": "|".join(ex_ch_list), "json": "1", "delay": "0"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return {}

    result: dict[str, dict] = {}
    for item in payload.get("msgArray", []):
        code = item.get("c")
        price = _to_number(item.get("z"))
        if not code or price is None:
            continue
        result[code] = {
            "price": price,
            "prev_close": _to_number(item.get("y")),
            "date": item.get("d"),
            "time": item.get("t"),
        }
    return result


MOPS_CONFERENCE_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
MOPS_CONFERENCE_REFERER = "https://mopsov.twse.com.tw/mops/web/t100sb02_1"
MOPS_MARKETS = ("sii", "otc", "rotc")  # 上市／上櫃／興櫃

_ROW_RE = re.compile(r"<tr class='(?:even|odd)' data-type='body' >(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ROC_DATE_RE = re.compile(r"(\d{2,3})/(\d{2})/(\d{2})")


def _strip_html(cell: str) -> str:
    return html.unescape(_TAG_RE.sub("", cell)).strip()


def _parse_roc_date(text: str) -> date | None:
    """解析民國日期（如 115/07/16，或「115/03/03 至 115/03/06」取起始日）。"""
    m = _ROC_DATE_RE.search(text)
    if not m:
        return None
    year, month, day = (int(x) for x in m.groups())
    try:
        return date(year + 1911, month, day)
    except ValueError:
        return None


def fetch_investor_conferences(code: str, typek: str, roc_year: str | None = None) -> list[dict]:
    """查詢公開資訊觀測站「法人說明會一覽表」，回傳指定代號＋市場別在該民國年度的所有場次。"""
    if roc_year is None:
        roc_year = str(datetime.now().year - 1911)
    try:
        r = requests.post(
            MOPS_CONFERENCE_URL,
            headers={"Referer": MOPS_CONFERENCE_REFERER, "User-Agent": "Mozilla/5.0"},
            data={"step": "1", "firstin": "ture", "off": "1", "TYPEK": typek, "year": roc_year, "month": "", "co_id": code},
            timeout=15,
        )
        r.raise_for_status()
        r.encoding = "utf-8"
    except Exception:
        return []

    conferences = []
    for row in _ROW_RE.findall(r.text):
        cells = _CELL_RE.findall(row)
        if len(cells) < 6:
            continue
        date_text = _strip_html(cells[2])
        conferences.append(
            {
                "date": date_text,
                "date_obj": _parse_roc_date(date_text),
                "time": _strip_html(cells[3]),
                "location": _strip_html(cells[4]),
                "message": _strip_html(cells[5]),
            }
        )
    return conferences


def fetch_upcoming_investor_conference(code: str, market: str | None = None) -> dict | None:
    """回傳下一場（今天以後最近）的法說會；market 已知（sii/otc）時只查一次，否則依序嘗試上市／上櫃／興櫃。"""
    today = date.today()
    candidates = [market] if market in MOPS_MARKETS else list(MOPS_MARKETS)
    for typek in candidates:
        conferences = fetch_investor_conferences(code, typek)
        if not conferences:
            continue
        upcoming = sorted((c for c in conferences if c["date_obj"] and c["date_obj"] >= today), key=lambda c: c["date_obj"])
        return upcoming[0] if upcoming else None
    return None


_REVENUE_KEYS = ["營業收入", "收益", "收入", "淨收益"]
_PROFIT_KEYS = ["營業毛利", "營業利益", "營業利益（損失）", "利息淨收益"]
_EPS_KEYS = ["基本每股盈餘（元）"]
_NET_INCOME_KEYS = ["本期淨利（淨損）", "淨利（淨損）歸屬於母公司業主", "繼續營業單位本期淨利（淨損）"]


def normalize_income_statement(record: dict | None) -> dict:
    """不同業別（一般業／金控／證券期貨／保險／金融）欄位名稱不同，統一取出常用欄位。"""
    if not record:
        return {"revenue": None, "operating_profit": None, "eps": None, "net_income": None, "quarter": None}

    def _first(keys):
        for k in keys:
            if k in record and record[k] not in ("", None):
                return record[k]
        return None

    quarter = None
    if record.get("年度") and record.get("季別"):
        quarter = f"{record['年度']}年Q{record['季別']}"

    return {
        "revenue": _first(_REVENUE_KEYS),
        "operating_profit": _first(_PROFIT_KEYS),
        "eps": _first(_EPS_KEYS),
        "net_income": _to_number(_first(_NET_INCOME_KEYS)),
        "quarter": quarter,
    }


def fetch_news(query: str, limit: int = 3) -> list[dict]:
    """用 Google 新聞 RSS 抓中文財經新聞（免金鑰，適用所有股票／ETF名稱）。"""
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return []

    items = []
    for item in root.findall(".//item")[:limit]:
        items.append(
            {
                "title": item.findtext("title"),
                "link": item.findtext("link"),
                "pub_date": item.findtext("pubDate"),
            }
        )
    return items


_PROFITABILITY_KEYS = {
    "gross_margin": "毛利率(%)(營業毛利)/(營業收入)",
    "operating_margin": "營業利益率(%)(營業利益)/(營業收入)",
    "pretax_margin": "稅前純益率(%)(稅前純益)/(營業收入)",
    "net_margin": "稅後純益率(%)(稅後純益)/(營業收入)",
}


def normalize_profitability(record: dict | None) -> dict:
    """t187ap17_L 營益分析彙總表 -> 毛利率／營業利益率／稅前稅後純益率（回傳小數，例如 0.1872）。"""
    result = {k: None for k in _PROFITABILITY_KEYS}
    if not record:
        return result
    for key, field in _PROFITABILITY_KEYS.items():
        value = _to_number(record.get(field))
        result[key] = value / 100 if value is not None else None
    return result


_CASH_DIVIDEND_KEYS = [
    "股東配發-盈餘分配之現金股利(元/股)",
    "股東配發-法定盈餘公積發放之現金(元/股)",
    "股東配發-資本公積發放之現金(元/股)",
]
_STOCK_DIVIDEND_KEYS = [
    "股東配發-盈餘轉增資配股(元/股)",
    "股東配發-法定盈餘公積轉增資配股(元/股)",
    "股東配發-資本公積轉增資配股(元/股)",
]


def normalize_dividend_policy(record: dict | None) -> dict:
    """t187ap45_L 股利分派情形 -> 現金股利合計／股票股利合計（元/股）。"""
    if not record:
        return {"cash_dividend": None, "stock_dividend": None, "dividend_year": None}
    cash = sum(_to_number(record.get(k)) or 0 for k in _CASH_DIVIDEND_KEYS)
    stock = sum(_to_number(record.get(k)) or 0 for k in _STOCK_DIVIDEND_KEYS)
    return {
        "cash_dividend": cash,
        "stock_dividend": stock,
        "dividend_year": record.get("股利年度"),
    }


def build_market_intel(holdings: list) -> dict[str, dict]:
    """整合每檔持股的月營收、財報重點、重大訊息、新聞、法說會、三大法人買賣超、
    融資融券、董監／大股東持股、財務比率、股利政策。key 為股票代號。
    """
    revenue_map = fetch_monthly_revenue_map()
    income_map = fetch_income_statement_map()
    news_map = fetch_material_news_map()
    flow_map = fetch_institutional_flow_map()
    balance_sheet_map = fetch_balance_sheet_map()
    profitability_map = fetch_profitability_map()
    dividend_map = fetch_dividend_policy_map()
    margin_map = fetch_margin_trading_map()
    director_map = fetch_director_holdings_map()
    shareholder_map = fetch_major_shareholders_map()

    intel: dict[str, dict] = {}
    for h in holdings:
        revenue = revenue_map.get(h.code)
        income = income_map.get(h.code)
        material_news = news_map.get(h.code, [])
        general_news = fetch_news(h.name) if h.name else []
        investor_conference = fetch_upcoming_investor_conference(h.code, getattr(h, "market", None))
        institutional_flow = flow_map.get(h.code)
        income_normalized = normalize_income_statement(income)

        intel[h.code] = {
            "monthly_revenue": revenue,
            "income_statement": income_normalized,
            "material_news": material_news,
            "general_news": general_news,
            "investor_conference": investor_conference,
            "institutional_flow": institutional_flow,
            "financial_ratios": normalize_financial_ratios(
                balance_sheet_map.get(h.code), income_normalized.get("net_income")
            ),
            "profitability": normalize_profitability(profitability_map.get(h.code)),
            "dividend_policy": normalize_dividend_policy(dividend_map.get(h.code)),
            "margin_trading": margin_map.get(h.code),
            "director_holdings": director_map.get(h.code),
            "major_shareholders": shareholder_map.get(h.code, []),
        }
    return intel
