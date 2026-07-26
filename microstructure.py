"""盤中開盤強弱判斷（Market Microstructure Agent）。

**只用於太太的短線輪動觀察，不影響使用者本人長期持股的月度配置決策**（使用者明確要求的範圍）。

使用者原本提出「開盤溢價率>5%且不跌破3%＝連番漲停」之類的硬性規則，經使用者自己審查後
明確否定（「沒有任何學術研究支持」「很多股票開+6%收+2%隔天-4%太常見了」），改為量能確認的
加減分規則。**這裡只做到這裡：回傳 0-100 的粗略評分＋文字說明，不會單獨用這個分數決定買賣**，
必須跟 `sector_rotation.py` 既有的動能排名一起看。

這些資料（開盤溢價率、委買委賣量、盤中K棒）只有在盤中（09:00-13:30）才有意義，
跟專案其他「一天跑一次」的模組不同，見 `spouse_intraday_check.py`。
"""

from datetime import datetime, time as dt_time

import requests
import yfinance as yf

MARKET_OPEN = dt_time(9, 0)
MARKET_CLOSE = dt_time(13, 30)

MIS_QUOTE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
MIS_MARKET_PREFIX = {"sii": "tse", "otc": "otc"}

STRONG_OPEN_PREMIUM = 0.05      # 開盤溢價率門檻
HOLD_ABOVE_PCT = 0.03           # 30 分鐘內不能跌破的漲幅
VOLUME_CONFIRM_RATIO = 1.5      # 量能達 20 日均量的倍數才算「確認」
HIGH_OPEN_LOW_CLOSE_HIGH = 0.07 # 盤中最高衝上此漲幅
HIGH_OPEN_LOW_CLOSE_NOW = 0.04  # 但現在剩不到這個漲幅 → 疑似倒貨
BLOWOUT_VOLUME_RATIO = 2.0      # 爆量門檻（均量倍數）


def _to_number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_snapshot(code: str, market: str | None) -> dict | None:
    """抓即時開盤價／昨收／今高／今低／現價／累積成交量（證交所 mis API，免費免金鑰）。
    market 未知時（例如 sector_rotation 的 WATCHLIST 沒有記錄市場別）依序嘗試上市／上櫃。
    """
    prefixes = [MIS_MARKET_PREFIX[market]] if market in MIS_MARKET_PREFIX else list(MIS_MARKET_PREFIX.values())
    for prefix in prefixes:
        try:
            r = requests.get(
                MIS_QUOTE_URL,
                params={"ex_ch": f"{prefix}_{code}.tw", "json": "1", "delay": "0"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            r.raise_for_status()
            items = r.json().get("msgArray") or []
        except Exception:
            continue
        if not items:
            continue
        item = items[0]
        return {
            "date": item.get("d"),  # 資料所屬日期（YYYYMMDD），用來判斷是不是「今天」的即時資料
            "open": _to_number(item.get("o")),
            "prev_close": _to_number(item.get("y")),
            "high": _to_number(item.get("h")),
            "low": _to_number(item.get("l")),
            "price": _to_number(item.get("z")) or _to_number(item.get("pz")),
            "volume": _to_number(item.get("v")),  # 累積成交量（張）
            "limit_up": _to_number(item.get("u")),
        }
    return None


def _suffixes_for(market: str | None) -> list[str]:
    if market == "sii":
        return [".TW"]
    if market == "otc":
        return [".TWO"]
    return [".TW", ".TWO"]


def fetch_opening_30min_low(code: str, market: str | None) -> float | None:
    """抓今天 09:00-09:30 的盤中最低價（5分K，yfinance），抓不到回傳 None。"""
    for suffix in _suffixes_for(market):
        try:
            hist = yf.Ticker(f"{code}{suffix}").history(period="1d", interval="5m")
        except Exception:
            continue
        if hist.empty:
            continue
        window = hist.between_time("09:00", "09:30")
        if not window.empty:
            return float(window["Low"].min())
    return None


def fetch_avg_daily_volume(code: str, market: str | None, days: int = 20) -> float | None:
    """近 N 日平均成交量（股數），做為今日累積成交量的比較基準（僅日線層級的粗略基準，
    不是「同一時段的歷史正常量」，量能比例僅供參考）。
    """
    for suffix in _suffixes_for(market):
        try:
            hist = yf.Ticker(f"{code}{suffix}").history(period="2mo")
        except Exception:
            continue
        if not hist.empty and len(hist) >= 5:
            return float(hist["Volume"].tail(days).mean())
    return None


def score_open_premium(snapshot: dict, opening_30min_low: float | None, avg_volume: float | None) -> tuple[float, list[str]]:
    """依開盤溢價率／30分鐘量能確認／盤中拉回幅度／爆量方向，給 0-100 分＋說明文字。
    這是規則型的粗略評分，**沒有經過統計驗證，不是必勝公式**，只當觀察因子。
    """
    o, y = snapshot.get("open"), snapshot.get("prev_close")
    if o is None or y is None or y == 0:
        return 50.0, []

    premium = (o - y) / y
    price, high, volume = snapshot.get("price"), snapshot.get("high"), snapshot.get("volume")
    volume_ratio = (volume / avg_volume) if volume is not None and avg_volume else None

    score = 50.0
    flags = []

    if premium > STRONG_OPEN_PREMIUM:
        held = opening_30min_low is not None and (opening_30min_low - y) / y >= HOLD_ABOVE_PCT
        if held and volume_ratio is not None and volume_ratio >= VOLUME_CONFIRM_RATIO:
            score += 15
            flags.append(f"開盤溢價 {premium:+.1%} 且 30 分鐘內未跌破 +{HOLD_ABOVE_PCT:.0%}，量能達 20 日均量 {volume_ratio:.0%}，強勢確認")
        elif held:
            score += 8
            flags.append(f"開盤溢價 {premium:+.1%} 且未跌破 +{HOLD_ABOVE_PCT:.0%}，但量能未達確認標準（僅供參考，非必然延續強勢）")

    if high is not None and price is not None:
        high_premium = (high - y) / y
        current_premium = (price - y) / y
        if high_premium >= HIGH_OPEN_LOW_CLOSE_HIGH and current_premium < HIGH_OPEN_LOW_CLOSE_NOW:
            score -= 20
            flags.append(f"盤中最高衝上 {high_premium:+.1%}，現在剩 {current_premium:+.1%}，疑似獲利了結賣壓，留意高檔震盪")

    if volume_ratio is not None and volume_ratio >= BLOWOUT_VOLUME_RATIO and price is not None:
        if price >= o:
            score += 10
            flags.append(f"爆量（{volume_ratio:.0%}均量）且站上開盤價，量增價漲")
        else:
            score -= 25
            flags.append(f"爆量（{volume_ratio:.0%}均量）但跌破開盤價，爆量黑K警訊")

    return max(0.0, min(100.0, score)), flags


def is_trading_session_now(reference_code: str = "2330", reference_market: str = "sii") -> bool:
    """粗略判斷「現在是不是台股交易時段」：週一~週五、09:00~13:30，且拿得到的即時報價
    確實是「今天」的資料。最後一項是關鍵：國定假日 MIS API 只會回傳最後一個交易日的舊資料，
    日期會對不上今天，用這個判斷可以順便排除假日，不用另外維護一份假日表。
    """
    now = datetime.now()
    if now.weekday() >= 5:  # 週六=5、週日=6
        return False
    if not (MARKET_OPEN <= now.time() <= MARKET_CLOSE):
        return False

    snapshot = fetch_snapshot(reference_code, reference_market)
    if not snapshot or not snapshot.get("date"):
        return False
    return snapshot["date"] == now.strftime("%Y%m%d")


def evaluate(code: str, market: str | None) -> dict:
    """整合抓資料＋評分，回傳單一持股的盤中強弱快照。抓不到資料則 score=None。"""
    snapshot = fetch_snapshot(code, market)
    if not snapshot or snapshot.get("open") is None or snapshot.get("prev_close") is None:
        return {"score": None, "flags": [], "premium": None}

    opening_low = fetch_opening_30min_low(code, market)
    avg_volume = fetch_avg_daily_volume(code, market)
    score, flags = score_open_premium(snapshot, opening_low, avg_volume)
    premium = (snapshot["open"] - snapshot["prev_close"]) / snapshot["prev_close"] if snapshot["prev_close"] else None

    return {"score": score, "flags": flags, "premium": premium, "snapshot": snapshot}
