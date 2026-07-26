"""市場環境（六構面評分的 F 類）：VIX、費半、那斯達克、美元指數、台幣匯率、台積電 ADR、NVDA/AMD/INTC。

全部用 yfinance 免費抓取（不需金鑰）。FOMC 會議時程／CPI／利率等官方數據沒有免費即時
API，依使用者指示不做成結構化欄位，改由既有 `market_data.fetch_news()` 的新聞機制帶過。

**這裡的「市場情緒分數」只是粗略的規則型加減分，不是精確的總體經濟模型**，
僅供六構面評分裡的一個參考子項，不能單獨當作進出場依據。
"""

import yfinance as yf

ENV_TICKERS = {
    "vix": "^VIX",
    "sox": "^SOX",
    "nasdaq": "^IXIC",
    "usd_index": "DX-Y.NYB",
    "usdtwd": "TWD=X",
    "tsm_adr": "TSM",
    "nvda": "NVDA",
    "amd": "AMD",
    "intc": "INTC",
}


def fetch_market_environment() -> dict[str, dict]:
    """回傳各指標的現價、1日／5日漲跌幅。抓不到的指標回傳全 None，不中斷其他指標。"""
    result: dict[str, dict] = {}
    for key, ticker in ENV_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="10d")
        except Exception:
            hist = None

        if hist is None or hist.empty:
            result[key] = {"price": None, "change_1d_pct": None, "change_5d_pct": None}
            continue

        close = hist["Close"]
        price = float(close.iloc[-1])
        change_1d = float(close.iloc[-1] / close.iloc[-2] - 1) if len(close) >= 2 else None
        change_5d = float(close.iloc[-1] / close.iloc[-6] - 1) if len(close) >= 6 else None
        result[key] = {"price": price, "change_1d_pct": change_1d, "change_5d_pct": change_5d}
    return result


def compute_environment_score(env: dict[str, dict]) -> float | None:
    """粗略市場情緒分數 0-100：VIX 越低越好、費半／那斯達克近5日走勢越強越好。"""
    scores = []

    vix = env.get("vix", {}).get("price")
    if vix is not None:
        scores.append(max(0.0, min(100.0, (40 - vix) / (40 - 10) * 100)))

    for key in ("sox", "nasdaq"):
        change_5d = env.get(key, {}).get("change_5d_pct")
        if change_5d is not None:
            scores.append(max(0.0, min(100.0, (change_5d + 0.10) / 0.20 * 100)))

    return sum(scores) / len(scores) if scores else None
