"""技術面指標：月/季/年線、RSI、KD、MACD、布林通道、ATR、支撐壓力、量能。

資料源與 sector_rotation.py 相同（yfinance 歷史股價），全部用 pandas 手算，不需額外套件。

**已知限制**：yfinance 提供的是日線收盤資料，沒有逐筆委託／盤中資料，因此
VWAP 這裡用「近 20 日成交量加權平均價」近似，不是真正的當日盤中 VWAP。
"""

import pandas as pd
import yfinance as yf

HISTORY_PERIOD = "2y"  # 需要至少 240 個交易日（年線）+ 緩衝


def fetch_history(code: str, market: str | None = None) -> pd.DataFrame | None:
    """依市場別（sii→.TW／otc→.TWO）抓歷史股價；market 未知時依序嘗試兩種後綴。"""
    suffixes = {"sii": [".TW"], "otc": [".TWO"]}.get(market, [".TW", ".TWO"])
    for suffix in suffixes:
        try:
            hist = yf.Ticker(f"{code}{suffix}").history(period=HISTORY_PERIOD)
        except Exception:
            continue
        if not hist.empty:
            return hist
    return None


def _last(series: pd.Series) -> float | None:
    series = series.dropna()
    return float(series.iloc[-1]) if not series.empty else None


def compute_technicals(hist: pd.DataFrame) -> dict:
    """回傳單一持股的技術面快照（缺資料的指標回傳 None，不硬湊）。"""
    close, high, low, volume = hist["Close"], hist["High"], hist["Low"], hist["Volume"]

    ma20 = _last(close.rolling(20).mean())
    ma60 = _last(close.rolling(60).mean())
    ma240 = _last(close.rolling(240).mean())

    delta = close.diff()
    avg_gain = delta.clip(lower=0).rolling(14).mean()
    avg_loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi14 = _last(100 - (100 / (1 + rs)))

    low9, high9 = low.rolling(9).min(), high.rolling(9).max()
    rsv = (close - low9) / (high9 - low9).replace(0, float("nan")) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    kd_k, kd_d = _last(k), _last(d)

    ema12, ema26 = close.ewm(span=12, adjust=False).mean(), close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    macd_signal = dif.ewm(span=9, adjust=False).mean()
    macd_hist = dif - macd_signal

    boll_mid = close.rolling(20).mean()
    boll_std = close.rolling(20).std()
    boll_upper = _last(boll_mid + 2 * boll_std)
    boll_lower = _last(boll_mid - 2 * boll_std)

    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr14 = _last(true_range.rolling(14).mean())

    vol_ma20 = volume.rolling(20).mean()
    last_volume, last_vol_ma20 = _last(volume), _last(vol_ma20)
    volume_ratio = (last_volume / last_vol_ma20) if last_volume is not None and last_vol_ma20 else None

    typical_price = (high + low + close) / 3
    vol_sum_20 = volume.tail(20).sum()
    vwap20 = float((typical_price.tail(20) * volume.tail(20)).sum() / vol_sum_20) if vol_sum_20 else None

    support_60 = float(low.tail(60).min()) if len(low) else None
    resistance_60 = float(high.tail(60).max()) if len(high) else None

    price = _last(close)
    bullish_alignment = (
        price is not None
        and ma20 is not None
        and ma60 is not None
        and ma240 is not None
        and price > ma20 > ma60 > ma240
    )

    return {
        "price": price,
        "ma20": ma20,
        "ma60": ma60,
        "ma240": ma240,
        "bullish_ma_alignment": bullish_alignment,
        "rsi14": rsi14,
        "kd_k": kd_k,
        "kd_d": kd_d,
        "macd_dif": _last(dif),
        "macd_signal": _last(macd_signal),
        "macd_hist": _last(macd_hist),
        "boll_upper": boll_upper,
        "boll_mid": _last(boll_mid),
        "boll_lower": boll_lower,
        "atr14": atr14,
        "volume_ratio": volume_ratio,
        "vwap20": vwap20,
        "support_60": support_60,
        "resistance_60": resistance_60,
    }


def build_technicals_map(holdings: list) -> dict[str, dict]:
    """代號 -> 技術面快照。抓不到歷史資料（如剛上市、代號異動）的持股回傳空字典。"""
    result: dict[str, dict] = {}
    for h in holdings:
        hist = fetch_history(h.code, getattr(h, "market", None))
        result[h.code] = compute_technicals(hist) if hist is not None and len(hist) >= 20 else {}
    return result
