"""ETF 觀察名單「品質」的事後驗證追蹤（僅用於使用者本人的每日報告，不是太太的短線輪動信）。

跟 `rotation_tracking.py` 追蹤「3-7天股價預測」的短線邏輯不同：ETF 的「優不優質」
（規模／費用率／配息政策）是慢變數，不是短期價格預測，這裡改用 90 天（一季）觀察窗、
每月彙總一次寄給使用者自己，觸發日設在**每月 1 日**（比對年月而非年週，避免同月手動
重複執行時又寄一次）。

追蹤邏輯延續 `rotation_tracking.py` 已驗證過的設計原則：`_infer_change_reason()` 依序檢查
規模變化率／費用率變化／配息政策是否改變／同期大盤(^TWII)報酬對照（只作參考對照，
不是及格標準），能查到幾項變化就列幾項，查無明顯變化也要給「品質指標維持穩定」的
具體結論，不接受「原因不明」。
"""

import json
from datetime import date, timedelta
from pathlib import Path

import yfinance as yf

from portfolio import Holding, fetch_market_data
from etf_fund_data import fetch_fund_metrics
from scoring import score_fund_quality

LOG_PATH = Path(__file__).parent / "etf_recommendations.json"
META_KEY = "_meta"

VERIFY_WINDOW_DAYS = 90
SUMMARY_DAY_OF_MONTH = 1  # 使用者指定「每月1日」寄送彙總，每天都有 05:00 排程會跑到，1日一定會觸發

AUM_INSIGNIFICANT_THRESHOLD = 0.10       # 基金規模變化 ±10% 內視為合理波動，不特別歸因
EXPENSE_RATIO_INSIGNIFICANT_THRESHOLD = 0.0005  # 年化費用率變化 ±0.05 個百分點內視為合理波動


def _load() -> dict:
    if not LOG_PATH.exists():
        return {}
    return json.loads(LOG_PATH.read_text(encoding="utf-8"))


def _save(records: dict) -> None:
    LOG_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def log_recommendations(etf_candidates: list[dict]) -> None:
    """把今天的 ETF 觀察名單記錄下來供 90 天後驗證。同一天同一檔重複執行只覆蓋，不重複累積。

    `quality_score` 刻意只用 `score_fund_quality()`（規模/費用率/配息政策），**不用**
    `evaluate_etf_candidates()` 回傳的完整 `investment_score`——investment_score 還混了
    技術面/市場環境這些短期雜訊，季度追蹤的目標是「基金體質有沒有變差」這個慢變數，
    只看 score_fund_quality() 才是乾淨的比較基準。
    """
    records = _load()
    today = date.today().isoformat()

    for r in etf_candidates:
        if not r.get("price"):
            continue
        fm = fetch_fund_metrics(r["code"])
        quality_score, _cov, _reasons = score_fund_quality(fm)
        record_id = f"{today}_{r['code']}"
        due = (date.today() + timedelta(days=VERIFY_WINDOW_DAYS)).isoformat()
        records[record_id] = {
            "date": today,
            "code": r["code"],
            "name": r["name"],
            "price_at_recommendation": r["price"],
            "quality_score_at_recommendation": quality_score,
            "aum_at_recommendation": fm.get("aum"),
            "expense_ratio_at_recommendation": fm.get("expense_ratio"),
            "dividend_policy_at_recommendation": fm.get("dividend_policy"),
            "due_date": due,
            "verified": False,
            "actual_price": None,
            "quality_score_now": None,
            "aum_now": None,
            "expense_ratio_now": None,
            "dividend_policy_now": None,
            "price_diff_pct": None,
            "quality_score_diff": None,
            "change_reason": None,
            "verified_date": None,
            "summarized": False,
        }
    _save(records)


def _fetch_current_price(code: str, name: str) -> float | None:
    """複用 `portfolio.fetch_market_data()` 既有的 .TW／.TWO 判斷邏輯，不重寫一份。"""
    h = Holding(code=code, name=name, shares=0, avg_cost=0)
    fetch_market_data(h)
    return h.price


def _market_return_pct(start_date: str, end_date: str) -> float | None:
    """同期加權指數（^TWII）漲跌幅，僅作參考對照，不是判斷 ETF 品質好壞的及格標準。"""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date) + timedelta(days=1)
        hist = yf.Ticker("^TWII").history(start=start.isoformat(), end=end.isoformat())
    except Exception:
        return None
    if hist is None or len(hist) < 2:
        return None
    return float(hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1)


def _infer_change_reason(rec: dict) -> str:
    """依序檢查規模變化率／費用率變化／配息政策是否改變／同期大盤(^TWII)報酬對照，
    能查到幾項變化就列幾項；查無明顯變化時，也要給「品質指標維持穩定」的具體結論，
    比照 `rotation_tracking._infer_diff_reason()` 已驗證過的設計原則，不接受「原因不明」。
    """
    reasons: list[str] = []

    aum_before, aum_after = rec.get("aum_at_recommendation"), rec.get("aum_now")
    if aum_before and aum_after is not None:
        change = aum_after / aum_before - 1
        if abs(change) >= AUM_INSIGNIFICANT_THRESHOLD:
            trend = "成長" if change > 0 else "縮水"
            reasons.append(
                f"基金規模{trend} {change:+.1%}（{aum_before / 1e8:,.0f}億→{aum_after / 1e8:,.0f}億元）"
            )

    fee_before, fee_after = rec.get("expense_ratio_at_recommendation"), rec.get("expense_ratio_now")
    if fee_before is not None and fee_after is not None:
        fee_diff = fee_after - fee_before
        if abs(fee_diff) >= EXPENSE_RATIO_INSIGNIFICANT_THRESHOLD:
            trend = "調升" if fee_diff > 0 else "調降"
            reasons.append(f"年化費用率{trend}（{fee_before:.2%}→{fee_after:.2%}）")

    policy_before, policy_after = rec.get("dividend_policy_at_recommendation"), rec.get("dividend_policy_now")
    if policy_before and policy_after and policy_before != policy_after:
        reasons.append(f"配息政策由「{policy_before}」變更為「{policy_after}」")

    market_ret = _market_return_pct(rec["date"], rec["verified_date"])
    price_diff = rec.get("price_diff_pct")
    if market_ret is not None and price_diff is not None:
        reasons.append(
            f"同期大盤(^TWII)報酬 {market_ret:+.1%}，同期該ETF價格變化 {price_diff:+.1%}"
            "（僅供參考對照，非品質評估的及格標準）"
        )

    if not reasons:
        return (
            "規模／費用率／配息政策查無明顯變化（變化幅度在合理範圍內），"
            "品質指標維持穩定，符合推薦當下的判斷"
        )
    return "；".join(reasons)


def verify_due_recommendations() -> list[dict]:
    """把 90 天到期、還沒驗證過的紀錄拿現在的規模/費用率/配息政策/股價重新比對，
    推斷變化原因，回傳這次新驗證的清單。結果只寫進 JSON，不會出現在當天的每日報告裡。
    """
    records = _load()
    today = date.today().isoformat()
    newly_verified = []

    for record_id, rec in records.items():
        if record_id == META_KEY or rec["verified"] or rec["due_date"] > today:
            continue
        price = _fetch_current_price(rec["code"], rec["name"])
        fm = fetch_fund_metrics(rec["code"])
        quality_score_now, _cov, _reasons = score_fund_quality(fm)
        if price is None and quality_score_now is None:
            continue  # 這次完全抓不到任何資料，暫緩驗證，下次執行再重試

        rec["verified"] = True
        rec["actual_price"] = price
        rec["quality_score_now"] = quality_score_now
        rec["aum_now"] = fm.get("aum")
        rec["expense_ratio_now"] = fm.get("expense_ratio")
        rec["dividend_policy_now"] = fm.get("dividend_policy")
        rec["price_diff_pct"] = (
            price / rec["price_at_recommendation"] - 1
            if price is not None and rec.get("price_at_recommendation")
            else None
        )
        rec["quality_score_diff"] = (
            quality_score_now - rec["quality_score_at_recommendation"]
            if quality_score_now is not None and rec.get("quality_score_at_recommendation") is not None
            else None
        )
        rec["verified_date"] = today
        rec["change_reason"] = _infer_change_reason(rec)
        newly_verified.append(rec)

    if newly_verified:
        _save(records)
    return newly_verified


def _due_for_summary(records: dict) -> bool:
    """使用者指定每月1日寄送。用 last_summary_date 的年月跟今天比對（不是年週，比照
    `rotation_tracking._due_for_summary()` 的週比對邏輯改成月比對），避免同月1日手動
    重複執行時又寄一次。"""
    if date.today().day != SUMMARY_DAY_OF_MONTH:
        return False
    last = records.get(META_KEY, {}).get("last_summary_date")
    if last is None:
        return True
    last_date = date.fromisoformat(last)
    today = date.today()
    return (last_date.year, last_date.month) != (today.year, today.month)


def maybe_send_summary(send_fn) -> bool:
    """檢查今天是不是每月1日、且有新驗證完成的紀錄；若是，呼叫 `send_fn(pending_records)`
    寄出，並把這批紀錄標記為已整理過。實際寄信邏輯（主旨/收件人）留給呼叫端
    （`daily_report.py`）決定，這裡只管「該不該寄、寄哪些」。回傳是否真的觸發了寄送。
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
    lines = [f"ETF觀察名單品質追蹤月報（{date.today().isoformat()}，共{len(records)}筆）", ""]
    for rec in records:
        price_diff = f"{rec['price_diff_pct']:+.1%}" if rec.get("price_diff_pct") is not None else "N/A"
        q_before = f"{rec['quality_score_at_recommendation']:.0f}" if rec.get("quality_score_at_recommendation") is not None else "N/A"
        q_after = f"{rec['quality_score_now']:.0f}" if rec.get("quality_score_now") is not None else "N/A"
        lines.append(
            f"- {rec['name']}（{rec['code']}）　{rec['date']}推薦時品質分數：{q_before}　"
            f"現在（{rec['verified_date']}）：{q_after}　同期股價變化：{price_diff}"
        )
        lines.append(f"　變化原因：{rec['change_reason']}")
    lines.append("")
    lines.append("以上為規則型粗略追蹤，非絕對正確，僅供你自行判斷是否調整 ETF_CANDIDATE_POOL 或評分規則。")
    return "\n".join(lines)


def build_summary_html(records: list[dict]) -> str:
    from sector_rotation import HTML_BASE_FONT_PX, HTML_HEADER_FONT_PX, HTML_STOCK_FONT_PX, HTML_NAME_COLOR, HTML_CODE_COLOR

    parts = [
        '<div style="font-family:\'Microsoft JhengHei\',Arial,sans-serif;'
        f'font-size:{HTML_BASE_FONT_PX}px;color:#212529;line-height:1.7;">',
        f'<div style="font-size:{HTML_HEADER_FONT_PX}px;font-weight:700;margin-bottom:10px;">'
        f'ETF觀察名單品質追蹤月報（{date.today().isoformat()}，共{len(records)}筆）</div>',
    ]
    for rec in records:
        price_diff = f"{rec['price_diff_pct']:+.1%}" if rec.get("price_diff_pct") is not None else "N/A"
        q_before = f"{rec['quality_score_at_recommendation']:.0f}" if rec.get("quality_score_at_recommendation") is not None else "N/A"
        q_after = f"{rec['quality_score_now']:.0f}" if rec.get("quality_score_now") is not None else "N/A"
        diff_val = rec.get("quality_score_diff")
        # 品質分數上升：紅（延續台股慣例「紅＝正向」）；下降：綠；缺資料：中性灰。
        if diff_val is None:
            diff_color = "#495057"
        else:
            diff_color = "#e03131" if diff_val >= 0 else "#2f9e44"
        name_code = (
            f'<span style="color:{HTML_NAME_COLOR};font-weight:700;font-size:{HTML_STOCK_FONT_PX}px;">{rec["name"]}</span>'
            f'（<span style="color:{HTML_CODE_COLOR};font-weight:700;font-size:{HTML_STOCK_FONT_PX}px;">{rec["code"]}</span>）'
        )
        parts.append(
            f'<div style="margin:10px 0 2px;font-size:{HTML_BASE_FONT_PX}px;">'
            f'{name_code}　{rec["date"]}推薦時品質分數：{q_before}　'
            f'現在（{rec["verified_date"]}）：<span style="color:{diff_color};font-weight:900;">{q_after}</span>　'
            f'同期股價變化：{price_diff}</div>'
        )
        parts.append(
            f'<div style="font-size:{HTML_BASE_FONT_PX}px;margin-left:12px;color:#495057;">變化原因：{rec["change_reason"]}</div>'
        )
    parts.append(
        f'<div style="font-size:14.5px;color:#495057;margin-top:16px;">'
        '以上為規則型粗略追蹤，非絕對正確，僅供你自行判斷是否調整 ETF_CANDIDATE_POOL 或評分規則。</div>'
    )
    parts.append("</div>")
    return "".join(parts)
