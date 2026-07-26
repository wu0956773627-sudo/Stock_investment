"""短線輪動預測的事後驗證追蹤（僅用於 `spouse_report.py` 的每日完整輪動報告）。

每次寄出推薦清單時，把「當下股價／預估報酬率／預估天數」記錄到 `rotation_predictions.json`；
等預估天數過了之後（用日曆天數概算，不是精確的交易日，跟專案其他地方一樣沒有另外維護
台股假日表），下次執行時會自動拿實際股價回頭比對，算出預測 vs 實際的落差，並嘗試推斷落差
原因（同期大盤同步／新聞關鍵字偏多偏空／預測當下已有警訊…）。

**這只是「蒐集真實落差資料＋粗略歸因」的基礎建設，不是自動修正引擎**：一筆落差可能是很多
原因造成的，看到一筆落差就自動改 `sector_rotation.py` 的公式或門檻容易 overfitting 到雜訊。
驗證結果不會混進太太每天收到的輪動報告，而是每週五整理成一份彙總，單獨寄給使用者本人
自行判斷（見 `spouse_report.py` 的 `maybe_send_summary()` 呼叫），要不要調整規則由人決定。
"""

import json
from datetime import date, timedelta
from pathlib import Path

import yfinance as yf

from sector_rotation import compute_stock_metrics, MIN_VOLUME_RATIO
from market_data import fetch_news

LOG_PATH = Path(__file__).parent / "rotation_predictions.json"
META_KEY = "_meta"

SUMMARY_WEEKDAY = 4  # 使用者指定「每週五」寄送彙總報告；Python weekday()：週一=0...週五=4
DIFF_INSIGNIFICANT_THRESHOLD = 0.03  # 落差在 ±3% 內視為合理誤差，不特別歸因

NEWS_POSITIVE_KEYWORDS = ["調升目標價", "上修", "大單", "轉單效應", "法說樂觀", "利多", "強勁"]
NEWS_NEGATIVE_KEYWORDS = ["調降目標價", "下修", "財報不如預期", "利空", "違約交割", "出貨轉弱", "重挫"]


def _load() -> dict:
    if not LOG_PATH.exists():
        return {}
    return json.loads(LOG_PATH.read_text(encoding="utf-8"))


def _save(records: dict) -> None:
    LOG_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def log_predictions(*recommendation_lists: list[dict]) -> None:
    """把今天的推薦清單記錄下來供之後驗證。同一天同一檔股票重複執行只會覆蓋，不會重複累積。"""
    records = _load()
    today = date.today().isoformat()

    combined: dict[str, dict] = {}
    for lst in recommendation_lists:
        for r in lst:
            combined[r["code"]] = r

    for code, r in combined.items():
        if r.get("potential_return_pct") is None or not r.get("price"):
            continue
        record_id = f"{today}_{code}"
        due = (date.today() + timedelta(days=r["estimated_days"])).isoformat()
        records[record_id] = {
            "date": today,
            "code": code,
            "name": r["name"],
            "group": r.get("group"),
            "price_at_prediction": r["price"],
            "predicted_return_pct": r["potential_return_pct"],
            "estimated_days": r["estimated_days"],
            "caution_note": r.get("caution_note") or None,
            "due_date": due,
            "verified": False,
            "actual_price": None,
            "actual_return_pct": None,
            "diff_pct": None,
            "diff_reason": None,
            "verified_date": None,
            "summarized": False,
        }
    _save(records)


def _market_return_pct(start_date: str, end_date: str) -> float | None:
    """同期加權指數（^TWII）漲跌幅，用來判斷落差是不是「大盤系統性同步」而非個股特有。"""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date) + timedelta(days=1)
        hist = yf.Ticker("^TWII").history(start=start.isoformat(), end=end.isoformat())
    except Exception:
        return None
    if hist is None or len(hist) < 2:
        return None
    return float(hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1)


def _scan_news_direction(code: str, name: str) -> str | None:
    """粗略關鍵字比對新聞標題判斷偏多/偏空，不是語意分析，僅供參考。"""
    try:
        items = fetch_news(f"{name} {code}", limit=5)
    except Exception:
        return None
    titles = " ".join((it.get("title") or "") for it in items)
    if any(k in titles for k in NEWS_NEGATIVE_KEYWORDS):
        return "negative"
    if any(k in titles for k in NEWS_POSITIVE_KEYWORDS):
        return "positive"
    return None


def _infer_diff_reason(rec: dict, m=None) -> str:
    """推斷落差原因——使用者要求「每個落差都要查出原因」，所以這裡不會停在「原因不明」就結束：
    依序檢查警訊／大盤同步程度／新聞關鍵字／驗證當下的技術面（RSI、量能），能查到幾項就列幾項；
    真的什麼訊號都沒有時，也要給一個具體結論（模型本身對這檔股票的預測力可能不足），
    而不是丟給使用者一句「不明」。每一項都刻意保留「疑似／可能」的不確定語氣，不是確定的因果分析。
    """
    diff = rec["diff_pct"]
    if abs(diff) < DIFF_INSIGNIFICANT_THRESHOLD:
        return "落差在合理誤差範圍內（±3%），暫不需特別歸因"

    reasons: list[str] = []

    if rec.get("caution_note") and diff < 0:
        reasons.append(f"預測當下已有警訊「{rec['caution_note']}」")

    market_ret = _market_return_pct(rec["date"], rec["verified_date"])
    if market_ret is not None:
        actual = rec["actual_return_pct"]
        same_direction = (market_ret >= 0) == (actual >= 0)
        magnitude_ratio = abs(market_ret) / abs(actual) if actual else None
        if same_direction and magnitude_ratio is not None and magnitude_ratio >= 0.5:
            trend = "走揚" if market_ret > 0 else "走弱"
            reasons.append(f"同期大盤同步{trend}約{market_ret:+.1%}，落差有相當比重可能是系統性因素")
        else:
            reasons.append(f"同期大盤約{market_ret:+.1%}，走勢跟個股背離，落差較可能是個股特有因素")

    news_dir = _scan_news_direction(rec["code"], rec["name"])
    if news_dir == "negative" and diff < 0:
        reasons.append("近期新聞標題偏空（關鍵字比對，非語意分析），疑似受個股利空消息影響")
    elif news_dir == "positive" and diff > 0:
        reasons.append("近期新聞標題偏多（關鍵字比對，非語意分析），疑似受個股利多消息影響")

    if m is not None and m.rsi14 is not None:
        if diff < 0 and m.rsi14 < 50:
            reasons.append(f"驗證當下 RSI14 已降到 {m.rsi14:.0f}，短線動能明顯轉弱")
        elif diff > 0 and m.rsi14 > 60:
            reasons.append(f"驗證當下 RSI14 達 {m.rsi14:.0f}，短線動能延續")
    if m is not None and m.volume_ratio is not None and m.volume_ratio < MIN_VOLUME_RATIO:
        reasons.append(f"驗證當下量能只有 20 日均量的 {m.volume_ratio:.0%}，明顯萎縮，追價意願下降")

    if not reasons:
        return (
            "查無明顯的外部消息、大盤同步或籌碼/技術面異常，落差可能反映短線動能規則"
            "（3-7天報酬率排名）對這檔股票的預測力本身不足，建議留意是否為個股特性"
            "（低流動性／籌碼結構特殊），可考慮列入後續觀察名單"
        )

    return "；".join(reasons)


def verify_due_predictions() -> list[dict]:
    """把預估天數到期、還沒驗證過的預測拿實際股價比對，算出落差並推斷原因，
    回傳這次新驗證的清單。結果只寫進 JSON，不會出現在太太當天收到的信裡。"""
    records = _load()
    today = date.today().isoformat()
    newly_verified = []

    for record_id, rec in records.items():
        if record_id == META_KEY or rec["verified"] or rec["due_date"] > today:
            continue
        m = compute_stock_metrics(rec["code"])
        if m is None:
            continue
        actual_return_pct = m.price / rec["price_at_prediction"] - 1
        rec["verified"] = True
        rec["actual_price"] = m.price
        rec["actual_return_pct"] = actual_return_pct
        rec["diff_pct"] = actual_return_pct - rec["predicted_return_pct"]
        rec["verified_date"] = today
        rec["diff_reason"] = _infer_diff_reason(rec, m)
        newly_verified.append(rec)

    if newly_verified:
        _save(records)
    return newly_verified


def pending_summary_records() -> list[dict]:
    records = _load()
    return [rec for k, rec in records.items() if k != META_KEY and rec.get("verified") and not rec.get("summarized")]


def _due_for_summary(records: dict) -> bool:
    """使用者指定每週五寄送。用 last_summary_date 的 ISO 年週跟今天比對，避免同一週五
    手動重複執行時又寄一次（例如測試時多跑了幾次）。"""
    if date.today().weekday() != SUMMARY_WEEKDAY:
        return False
    last = records.get(META_KEY, {}).get("last_summary_date")
    if last is None:
        return True
    return date.fromisoformat(last).isocalendar()[:2] != date.today().isocalendar()[:2]


def maybe_send_summary(send_fn) -> bool:
    """檢查今天是不是週五、且有新驗證完成的紀錄；若是，呼叫 send_fn(pending_records) 寄出，
    並把這批紀錄標記為已整理過。實際寄信邏輯（主旨/收件人）留給呼叫端（`spouse_report.py`）
    決定，這裡只管「該不該寄、寄哪些」。回傳是否真的觸發了寄送。
    """
    records = _load()
    pending = [rec for k, rec in records.items() if k != META_KEY and rec.get("verified") and not rec.get("summarized")]
    if not pending or not _due_for_summary(records):
        return False

    send_fn(pending)

    for rec in pending:
        rec["summarized"] = True
    records.setdefault(META_KEY, {})["last_summary_date"] = date.today().isoformat()
    _save(records)
    return True


def build_summary_text(records: list[dict]) -> str:
    lines = [f"短線輪動預測追蹤彙總（{date.today().isoformat()}，共{len(records)}筆）", ""]
    for rec in records:
        predicted = f"{rec['predicted_return_pct']:+.1%}"
        actual = f"{rec['actual_return_pct']:+.1%}"
        diff = f"{rec['diff_pct']:+.1%}"
        lines.append(
            f"- {rec['name']}（{rec['code']}）　{rec['date']}預估：{predicted}　"
            f"實際（{rec['verified_date']}）：{actual}　落差：{diff}"
        )
        lines.append(f"　推斷原因：{rec['diff_reason']}")
    lines.append("")
    lines.append("以上為規則型粗略推斷，非絕對正確，僅供你自行判斷要不要調整 sector_rotation.py 的規則或門檻。")
    return "\n".join(lines)


def build_summary_html(records: list[dict]) -> str:
    from sector_rotation import HTML_BASE_FONT_PX, HTML_HEADER_FONT_PX, HTML_STOCK_FONT_PX, HTML_NAME_COLOR, HTML_CODE_COLOR

    parts = [
        '<div style="font-family:\'Microsoft JhengHei\',Arial,sans-serif;'
        f'font-size:{HTML_BASE_FONT_PX}px;color:#212529;line-height:1.7;">',
        f'<div style="font-size:{HTML_HEADER_FONT_PX}px;font-weight:700;margin-bottom:10px;">'
        f'短線輪動預測追蹤彙總（{date.today().isoformat()}，共{len(records)}筆）</div>',
    ]
    for rec in records:
        predicted = f"{rec['predicted_return_pct']:+.1%}"
        actual = f"{rec['actual_return_pct']:+.1%}"
        # 落差優於預估：紅（台股慣例紅漲綠跌，避免用綠色造成語意相反）；落差劣於預估：沿用既有警示橘。
        diff_color = "#e03131" if rec["diff_pct"] >= 0 else "#e8590c"
        diff = f'<span style="color:{diff_color};font-weight:900;">{rec["diff_pct"]:+.1%}</span>'
        name_code = (
            f'<span style="color:{HTML_NAME_COLOR};font-weight:700;font-size:{HTML_STOCK_FONT_PX}px;">{rec["name"]}</span>'
            f'（<span style="color:{HTML_CODE_COLOR};font-weight:700;font-size:{HTML_STOCK_FONT_PX}px;">{rec["code"]}</span>）'
        )
        parts.append(
            f'<div style="margin:10px 0 2px;font-size:{HTML_BASE_FONT_PX}px;">'
            f'{name_code}　{rec["date"]}預估：{predicted}　實際（{rec["verified_date"]}）：{actual}　落差：{diff}</div>'
        )
        parts.append(
            f'<div style="font-size:{HTML_BASE_FONT_PX}px;margin-left:12px;color:#495057;">推斷原因：{rec["diff_reason"]}</div>'
        )
    parts.append(
        f'<div style="font-size:14.5px;color:#495057;margin-top:16px;">'
        '以上為規則型粗略推斷，非絕對正確，僅供你自行判斷要不要調整 sector_rotation.py 的規則或門檻。</div>'
    )
    parts.append("</div>")
    return "".join(parts)
