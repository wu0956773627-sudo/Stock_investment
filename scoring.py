"""AI 綜合評分與行動建議引擎（六構面加權評分 + 獨立 Risk Score + 四色訊號決策）。

**設計原則**：AI 的目標不是預測股價，而是回答「該不該採取行動」，且一定要結合
「股票本身的評分」與「使用者目前的持股狀態」（成本、損益率、佔比），不能只看股票本身。

六構面權重：A基本面30% + B成長性20% + C籌碼面15% + D技術面15% + E估值10% + F市場環境10%。
每個子項目正規化到 0-100 分；缺資料的子項目**不計分、不當 0 分**，而是把該類別的權重
按比例分給該類別其餘可用子項（`_weighted_avg()`），避免「資料不全」被誤判成「基本面差」。

Risk Score（0-100，獨立於六構面之外，數字越高風險越高）：波動度／持股集中度／產業集中度／
負債比／自 52 週高點拉回幅度／估值乖離度／董監質押比例。

最終四色訊號（🟢加碼買進／🟡持有觀察／🟠分批獲利了結／🔴全數賣出）決策順序見
`decide_signal()`，結合：巨額虧損降低提醒頻率（`alert_state.json` 狀態記憶）、
禁止追高、獲利但法人持續看好續抱、虧損但未到硬停損續抱觀察、加碼六條件檢查。

DCF、FOMC／CPI／利率、台指夜盤等無免費即時資料源的項目依使用者指示不建模，
相關新聞仍會透過既有 `market_data.fetch_news()` 機制間接呈現。
"""

import json
import math
from datetime import date

from portfolio import (
    Holding,
    is_market_bullish,
    weight,
    total_market_value,
    STOP_LOSS_THRESHOLD,
    STOP_LOSS_HARD_THRESHOLD,
    TAKE_PROFIT_THRESHOLD,
    CONCENTRATION_WARNING,
)

ALERT_STATE_PATH = "alert_state.json"
QUIET_PERIOD_DAYS = 7
EXTREME_LOSS_THRESHOLD = -0.70
CHASE_HIGH_THRESHOLD = 0.20  # 現價距合理價 ≥20% 視為追高
OVERVALUED_THRESHOLD = 0.20  # 獲利部位現價超過合理價 20% 視為高估

POSITIVE_CATALYST_KEYWORDS = [
    "三期成功", "三期臨床", "FDA核准", "FDA批准", "授權合作", "增資完成", "增資案",
    "轉虧為盈", "被收購", "併購", "重大合約", "大單", "財務改善", "調高財測", "調升目標價",
]
NEGATIVE_CATALYST_KEYWORDS = [
    "下市", "停止交易", "全額交割", "財報無法出具", "無法表示意見", "現金不足", "減資",
    "重大訴訟", "董事長辭職", "總經理辭職", "查核意見", "繼續經營假設", "跳票", "違約交割", "掏空",
]


# ── 狀態記憶（極端虧損股節流用） ─────────────────────────────


def load_alert_state(path: str = ALERT_STATE_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_alert_state(state: dict, path: str = ALERT_STATE_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def scan_catalyst(news_items: list[dict], title_key: str = "title") -> str | None:
    """依新聞標題關鍵字命中判斷 'positive'/'negative'/None。粗略字串比對，非語意分析。"""
    titles = " ".join((n.get(title_key) or "") for n in news_items)
    if any(k in titles for k in NEGATIVE_CATALYST_KEYWORDS):
        return "negative"
    if any(k in titles for k in POSITIVE_CATALYST_KEYWORDS):
        return "positive"
    return None


# ── 子項目正規化到 0-100 分 ─────────────────────────────


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _linear(value: float | None, low: float, high: float) -> float | None:
    """把 value 從 [low, high] 線性映射到 [0, 100]（high 可以小於 low，代表反向映射）。"""
    if value is None:
        return None
    span = high - low
    if span == 0:
        return None
    return _clamp((value - low) / span * 100)


def _weighted_avg(items: list[tuple[float | None, float]]) -> tuple[float | None, float]:
    """items: [(0-100分或None, 子權重), ...]。缺資料的子項目跳過，權重按比例分給其餘可用子項。
    回傳 (加權平均分數, 該類別實際可用的權重覆蓋率 0~1)。
    """
    available = [(s, w) for s, w in items if s is not None and w > 0]
    total_declared = sum(w for _, w in items)
    if not available or total_declared == 0:
        return None, 0.0
    total_available = sum(w for _, w in available)
    score = sum(s * w for s, w in available) / total_available
    return score, total_available / total_declared


# ── A. 基本面 30% ─────────────────────────────


def score_fundamentals(h: Holding, intel: dict) -> tuple[float | None, float, list[str]]:
    ratios = intel.get("financial_ratios") or {}
    profit = intel.get("profitability") or {}

    roe_annual = ratios.get("roe") * 4 if ratios.get("roe") is not None else None
    roa_annual = ratios.get("roa") * 4 if ratios.get("roa") is not None else None

    items = [
        (_linear(roe_annual, -0.10, 0.30), 1.0),
        (_linear(roa_annual, -0.05, 0.15), 1.0),
        (_linear(profit.get("gross_margin"), 0.0, 0.60), 1.0),
        (_linear(profit.get("operating_margin"), -0.10, 0.40), 1.0),
        (_linear(profit.get("net_margin"), -0.10, 0.30), 1.0),
        (_linear(ratios.get("debt_ratio"), 0.80, 0.20), 1.0),
        (_linear(ratios.get("current_ratio"), 0.5, 2.5), 1.0),
        (_linear(h.dividend_yield / 100 if h.dividend_yield else None, 0.0, 0.08), 1.0),
    ]
    score, coverage = _weighted_avg(items)

    reasons = []
    if profit.get("net_margin") is not None:
        reasons.append(f"淨利率 {profit['net_margin']:.1%}")
    if roe_annual is not None:
        reasons.append(f"ROE(季×4概算) {roe_annual:.1%}")
    if ratios.get("debt_ratio") is not None:
        reasons.append(f"負債比 {ratios['debt_ratio']:.1%}")
    return score, coverage, reasons


# ── Conviction Score（長期持股信心分數，1-5 星）─────────────────────────────
# 這不是「今天該不該買」的評分（那是 Investment Score 的工作），而是「這家公司體質好不好、
# 值得長期一直買」的評分，理想上應該評估產業地位／競爭優勢／管理能力，但這些沒有免費、
# 結構化的資料源可以量化。這裡改用可取得的量化代理指標組成：ROE 水準、毛利率
# （定價能力的粗略訊號）、負債比（財務體質）、市值規模（產業地位的粗略代理）、是否穩定配息。
# **這不是真正的護城河或管理品質評估，只是財務體質的量化近似，僅供參考**。


def score_conviction(h: Holding, intel: dict) -> tuple[float | None, float, list[str]]:
    ratios = intel.get("financial_ratios") or {}
    profit = intel.get("profitability") or {}
    dividend = intel.get("dividend_policy") or {}

    roe_annual = ratios.get("roe") * 4 if ratios.get("roe") is not None else None
    market_cap_log = math.log10(h.market_cap) if h.market_cap and h.market_cap > 0 else None
    cash_dividend = dividend.get("cash_dividend")
    dividend_score = 100.0 if cash_dividend else (0.0 if cash_dividend == 0 else None)

    items = [
        (_linear(roe_annual, 0.0, 0.25), 1.5),
        (_linear(profit.get("gross_margin"), 0.10, 0.55), 1.5),
        (_linear(ratios.get("debt_ratio"), 0.70, 0.20), 1.0),
        (_linear(market_cap_log, 9.0, 12.5), 1.0),  # 約 10 億～3 千億元以上市值
        (dividend_score, 0.5),
    ]
    score, coverage = _weighted_avg(items)

    reasons = []
    if roe_annual is not None:
        reasons.append(f"ROE(季×4概算) {roe_annual:.1%}")
    if profit.get("gross_margin") is not None:
        reasons.append(f"毛利率 {profit['gross_margin']:.1%}")
    if h.market_cap:
        reasons.append(f"市值約 {h.market_cap / 1e8:,.0f} 億元")

    return score, coverage, reasons


def conviction_stars(score: float | None) -> str:
    """把 0-100 分轉成 1-5 星文字（例如 ★★★★☆）。"""
    if score is None:
        return "N/A"
    stars = max(1, min(5, math.ceil(score / 20)))
    return "★" * stars + "☆" * (5 - stars)


# ── B. 成長性 20% ─────────────────────────────

_GROWTH_KEYWORDS = ["AI", "成長", "擴產", "大單", "合作", "新產品", "接單", "產能", "轉型", "獲利創新高"]


def score_growth(h: Holding, intel: dict) -> tuple[float | None, float, list[str]]:
    revenue = intel.get("monthly_revenue") or {}
    yoy_raw = revenue.get("營業收入-去年同月增減(%)")
    yoy = float(yoy_raw) / 100 if yoy_raw not in (None, "") else None

    eps_growth = None
    if h.trailing_eps and h.forward_eps and h.trailing_eps > 0:
        eps_growth = h.forward_eps / h.trailing_eps - 1

    news_titles = [n.get("title", "") for n in (intel.get("general_news") or [])]
    hits = sum(1 for title in news_titles for kw in _GROWTH_KEYWORDS if kw in title)
    news_score = min(hits * 25, 100) if news_titles else None

    items = [
        (_linear(yoy, -0.20, 0.40), 1.5),
        (_linear(eps_growth, -0.20, 0.30), 1.5),
        (news_score, 0.5),  # 新聞關鍵字屬弱代理指標，權重刻意壓低
    ]
    score, coverage = _weighted_avg(items)

    reasons = []
    if yoy is not None:
        reasons.append(f"月營收年增率 {yoy:+.1%}")
    if eps_growth is not None:
        reasons.append(f"法人預估EPS成長 {eps_growth:+.1%}")
    return score, coverage, reasons


# ── C. 籌碼面 15% ─────────────────────────────


def score_chips(h: Holding, intel: dict) -> tuple[float | None, float, list[str]]:
    flow = intel.get("institutional_flow") or {}
    margin = intel.get("margin_trading") or {}
    director = intel.get("director_holdings") or {}

    flow_score = None
    total_net = flow.get("total_net")
    if total_net is not None:
        flow_score = _clamp(50 + total_net / 200_000 * 50)

    margin_score = None
    try:
        today_balance = float(margin.get("融資今日餘額") or "")
        prev_balance = float(margin.get("融資前日餘額") or "")
        limit = float(margin.get("融資限額") or "")
        if limit:
            change_ratio = (today_balance - prev_balance) / limit
            margin_score = _clamp(50 - change_ratio * 5000)
    except (ValueError, TypeError):
        pass

    pledge_score = None
    if director.get("max_pledge_ratio") is not None:
        pledge_score = _clamp(100 - director["max_pledge_ratio"] * 2)

    items = [(flow_score, 1.0), (margin_score, 1.0), (pledge_score, 1.0)]
    score, coverage = _weighted_avg(items)

    reasons = []
    if total_net is not None:
        reasons.append(f"今日三大法人買賣超 {total_net:+,.0f} 股")
    if director.get("max_pledge_ratio"):
        reasons.append(f"董監最高質押比例 {director['max_pledge_ratio']:.1f}%")
    return score, coverage, reasons


# ── D. 技術面 15% ─────────────────────────────


def score_technicals(tech: dict) -> tuple[float | None, float, list[str]]:
    if not tech:
        return None, 0.0, []

    ma_score = 100.0 if tech.get("bullish_ma_alignment") else 40.0
    rsi = tech.get("rsi14")
    rsi_score = _clamp(100 - abs(rsi - 55) * 2) if rsi is not None else None

    kd_score = None
    if tech.get("kd_k") is not None and tech.get("kd_d") is not None:
        kd_score = _clamp(50 + (tech["kd_k"] - tech["kd_d"]) * 2)

    macd_score = None
    if tech.get("macd_hist") is not None and tech.get("price"):
        macd_score = _clamp(50 + (tech["macd_hist"] / tech["price"]) * 1000)

    boll_score = None
    price, upper, lower = tech.get("price"), tech.get("boll_upper"), tech.get("boll_lower")
    if price is not None and upper is not None and lower is not None and upper != lower:
        position = (price - lower) / (upper - lower)
        boll_score = _clamp(100 - position * 60, 20, 100)

    vol_score = None
    if tech.get("volume_ratio") is not None:
        vol_score = _clamp(50 + (tech["volume_ratio"] - 1) * 30)

    items = [(ma_score, 1.0), (rsi_score, 1.0), (kd_score, 1.0), (macd_score, 1.0), (boll_score, 1.0), (vol_score, 0.5)]
    score, coverage = _weighted_avg(items)

    reasons = []
    if tech.get("bullish_ma_alignment"):
        reasons.append("均線多頭排列（現價>月線>季線>年線）")
    if rsi is not None:
        reasons.append(f"RSI14 {rsi:.0f}")
    return score, coverage, reasons


# ── E. 估值 10% ─────────────────────────────


def score_valuation(h: Holding, all_holdings: list[Holding]) -> tuple[float | None, float, list[str]]:
    pe_score = _linear(h.trailing_pe, 40, 10) if h.trailing_pe and h.trailing_pe > 0 else None
    upside_score = _linear(h.upside_to_target, -0.20, 0.40)

    peers = [p.trailing_pe for p in all_holdings if p.industry == h.industry and p.code != h.code and p.trailing_pe]
    peer_score = None
    if peers and h.trailing_pe:
        peer_avg = sum(peers) / len(peers)
        if peer_avg:
            peer_score = _clamp(50 + (peer_avg - h.trailing_pe) / peer_avg * 100)

    peg_score = None
    if h.trailing_pe and h.trailing_eps and h.forward_eps and h.trailing_eps > 0:
        eps_growth_pct = (h.forward_eps / h.trailing_eps - 1) * 100
        if eps_growth_pct > 0:
            peg = h.trailing_pe / eps_growth_pct
            peg_score = _linear(peg, 3.0, 0.5)

    items = [(pe_score, 1.0), (upside_score, 1.5), (peer_score, 0.5), (peg_score, 1.0)]
    score, coverage = _weighted_avg(items)

    reasons = []
    if h.trailing_pe:
        reasons.append(f"本益比(TTM) {h.trailing_pe:.1f}")
    if h.upside_to_target is not None:
        reasons.append(f"法人目標價上漲空間 {h.upside_to_target:+.1%}")
    return score, coverage, reasons


# ── 合理價估算（供追高／高估判斷用） ─────────────────────────────


def estimate_fair_value(h: Holding) -> float | None:
    """合理價僅用法人目標價；沒有法人目標價（多半是 ETF，沒有分析師覆蓋）就回傳 None。
    **刻意不用「52週區間中位數」之類的替代估算**：實測發現這類 ETF／正2 商品的 52 週低點
    常被單一次系統性下跌拖低，中位數會嚴重低估「合理價」，導致誤判成追高，
    寧可缺資料時不做這項判斷，也不要用不可靠的估算誤導使用者。
    """
    return h.target_mean_price


# ── Risk Score（獨立 0-100，越高風險越高） ─────────────────────────────


def score_risk(h: Holding, intel: dict, tech: dict, total_value: float, sector_weight: float) -> float | None:
    ratios = intel.get("financial_ratios") or {}
    director = intel.get("director_holdings") or {}
    fair_value = estimate_fair_value(h)

    volatility_risk = None
    if tech.get("atr14") is not None and tech.get("price"):
        volatility_risk = _clamp(tech["atr14"] / tech["price"] / 0.08 * 100)

    position_weight = weight(h, total_value)
    concentration_risk = _clamp(position_weight / CONCENTRATION_WARNING * 100) if position_weight is not None else None
    sector_risk = _clamp(sector_weight / CONCENTRATION_WARNING * 100) if sector_weight is not None else None
    debt_risk = _clamp(ratios["debt_ratio"] / 0.80 * 100) if ratios.get("debt_ratio") is not None else None

    drawdown_risk = None
    if h.week52_high and h.price is not None:
        drawdown_risk = _clamp((1 - h.price / h.week52_high) / 0.50 * 100)

    stretch_risk = None
    if fair_value and h.price is not None:
        overshoot = max(h.price / fair_value - 1, 0.0)
        stretch_risk = _clamp(overshoot / 0.30 * 100)

    pledge_risk = _clamp(director["max_pledge_ratio"]) if director.get("max_pledge_ratio") is not None else None

    items = [(volatility_risk, 1.0), (concentration_risk, 1.0), (sector_risk, 1.0),
             (debt_risk, 1.0), (drawdown_risk, 1.0), (stretch_risk, 1.0), (pledge_risk, 0.5)]
    score, _coverage = _weighted_avg(items)
    return score


# ── 加碼六條件（第四節） ─────────────────────────────


def add_on_conditions_met(h: Holding, intel: dict, tech: dict, fundamentals_score: float | None) -> bool:
    """基本面未變／長期趨勢向上／法人未大幅調降目標價／EPS未惡化／籌碼未崩壞／技術面接近支撐，六項全符合才算。"""
    if fundamentals_score is None or fundamentals_score < 50:
        return False
    if not tech.get("bullish_ma_alignment") and not (tech.get("ma20") and tech.get("ma60") and tech["ma20"] >= tech["ma60"]):
        return False
    if h.upside_to_target is None or h.upside_to_target < 0:
        return False
    if h.trailing_eps is not None and h.forward_eps is not None and h.forward_eps < h.trailing_eps * 0.8:
        return False
    flow = intel.get("institutional_flow") or {}
    if flow.get("total_net") is not None and flow["total_net"] < -1_000_000:
        return False
    support = tech.get("support_60")
    if support and h.price is not None and h.price > support * 1.15:
        return False
    return True


# ── ETF 專屬品質評分（規模／費用率／配息政策 45%） ─────────────────────────────
# ETF 完全沒有 ROE、月營收年增率、三大法人買賣超這些個股才有的資料，套用個股的六構面評分
# （score_fundamentals/score_growth/score_chips）只會讓基本面/成長性/籌碼面三個構面幾乎全是
# None，最後分數幾乎只剩技術面在撐，不是真正反映「這檔 ETF 體質好不好」。改用 ETF 自己的
# 公開可靠指標：基金規模（越大越具規模經濟、流動性越好）、年化費用率（越低對長期持有人越有利）、
# 配息政策（'distributing'／'accumulating'／None，純文字分類，不是量化穩定度分數——實測發現
# 官方配息資料集每次只能抓到最新一個月的快照，沒辦法回推變異係數算穩定度，見 etf_fund_data.py）。


def score_fund_quality(fund_metrics: dict) -> tuple[float | None, float, list[str]]:
    aum = fund_metrics.get("aum")
    expense_ratio = fund_metrics.get("expense_ratio")
    policy = fund_metrics.get("dividend_policy")

    # 規模差異量級很大（小型 ETF 約幾億元 vs 0050 約 2.2 兆元），比照 score_conviction 對市值的
    # 處理方式，取 log10 後再線性映射，避免大規模 ETF 全部被硬壓在同一個滿分區間看不出差異。
    aum_log = math.log10(aum) if aum and aum > 0 else None
    # 使用者是「薪資現金流投資人」，配息型 ETF 較貼合其現金流需求，給予比累積型略高的分數；
    # 累積型不是「品質差」，只是投資風格不同，兩者都給及格以上分數，差距刻意不拉大。
    policy_score = {"distributing": 70.0, "accumulating": 50.0}.get(policy)

    items = [
        (_linear(aum_log, 8.5, 12.0), 1.5),          # 約 3億～1兆元
        (_linear(expense_ratio, 0.012, 0.0015), 1.5),  # 年化費用率 1.2%(差)～0.15%(優)，反向映射
        (policy_score, 1.0),
    ]
    score, coverage = _weighted_avg(items)

    reasons = []
    if aum is not None:
        reasons.append(f"基金規模約 {aum / 1e8:,.0f} 億元")
    if expense_ratio is not None:
        reasons.append(f"年化費用率約 {expense_ratio:.2%}")
    if policy == "distributing":
        reasons.append("配息政策：定期配息")
    elif policy == "accumulating":
        reasons.append("配息政策：收益併入淨值，不配息")
    return score, coverage, reasons


def evaluate_etf_candidate(
    h: Holding,
    fund_metrics: dict,
    tech: dict,
    all_candidates: list[Holding],
    total_value: float,
    sector_weight: float,
) -> dict:
    """評估「目前沒有持有」的 ETF 候選新標的。跟個股版 `evaluate_candidate()` 走同樣的流程與
    回傳 dict key（code/name/price/investment_score/risk_score/data_coverage/fair_value/
    target_price/chase_high_distance/conviction_score/conviction_stars/conviction_reasons/
    reasons），讓 report.py／pdf_report.py／excel_report.py／app.py 不需要為了欄位差異
    另外改渲染邏輯，但六構面組成換成 ETF 適用的版本：
    規模/費用率/配息政策 50% + 技術面 30% + 市場環境 15% + 估值 5%
    （估值只用法人目標價，ETF 通常無分析師覆蓋，缺資料就自動跳過，不強行估算）。
    這組權重方向沿用 plan 給的「45/25/10/5」，因為 45+25+10+5=85 並非剛好等於 100，
    這裡依實際四項的相對比重等比例縮放到合計 100%。

    ETF 沒有個股式「長期持股信心」的獨立資料來源（ROE／毛利率／負債比這些個股財報項目），
    這裡直接沿用 `score_fund_quality()` 的分數與理由當作 conviction_score——對 ETF 而言，
    「基金體質好不好（規模/費用率/配息）」本來就等同於「值不值得長期持有」，沒有必要另外
    發明一套指標。
    """
    fund_score, fund_cov, fund_reasons = score_fund_quality(fund_metrics)
    tech_score, tech_cov, tech_reasons = score_technicals(tech)
    env_score = fund_metrics.get("environment_score")
    val_score = _linear(h.upside_to_target, -0.20, 0.40)
    val_cov = 1.0 if val_score is not None else 0.0

    category_items = [
        (fund_score, 0.50), (tech_score, 0.30), (env_score, 0.15), (val_score, 0.05),
    ]
    investment_score, _present = _weighted_avg(category_items)
    coverage_items = [
        (fund_cov, 0.50), (tech_cov, 0.30), (1.0 if env_score is not None else 0.0, 0.15), (val_cov, 0.05),
    ]
    data_coverage = sum(cov * w for cov, w in coverage_items)
    risk_score = score_risk(h, {}, tech, total_value, sector_weight)

    fair_value = estimate_fair_value(h)
    chase_high_distance = None
    if fair_value and h.price is not None:
        distance = h.price / fair_value - 1
        if distance >= CHASE_HIGH_THRESHOLD:
            chase_high_distance = distance

    return {
        "code": h.code,
        "name": h.name,
        "price": h.price,
        "investment_score": investment_score,
        "risk_score": risk_score,
        "data_coverage": data_coverage,
        "fair_value": fair_value,
        "target_price": h.target_mean_price,
        "chase_high_distance": chase_high_distance,
        "conviction_score": fund_score,
        "conviction_stars": conviction_stars(fund_score),
        "conviction_reasons": fund_reasons,
        "reasons": (fund_reasons + tech_reasons)[:4],
    }


# ── 候選新標的評估（目前沒有持有，不套用 decide_signal 的持倉判斷） ─────────────────────────────


def evaluate_candidate(
    h: Holding,
    intel: dict,
    tech: dict,
    all_candidates: list[Holding],
    total_value: float,
    sector_weight: float,
) -> dict:
    """評估「目前沒有持有」的候選新標的，只回答「值不值得列入觀察」，不回答「該不該賣」。

    跟 `decide_signal()` 共用同一套六構面評分／Risk Score／信心分數計算，但**不套用
    decide_signal() 的持倉判斷邏輯**——那一套從 `h.pnl_pct` 開始分支，候選股沒有成本、
    `pnl_pct` 必為 None，套用 decide_signal 只會一律落到「🟡 尚無市價資料」，沒有意義。
    """
    fund_score, fund_cov, fund_reasons = score_fundamentals(h, intel)
    growth_score, growth_cov, growth_reasons = score_growth(h, intel)
    chip_score, chip_cov, chip_reasons = score_chips(h, intel)
    tech_score, tech_cov, tech_reasons = score_technicals(tech)
    val_score, val_cov, val_reasons = score_valuation(h, all_candidates)
    env_score = intel.get("environment_score")
    conviction_score, _conviction_cov, conviction_reasons = score_conviction(h, intel)

    category_items = [
        (fund_score, 0.30), (growth_score, 0.20), (chip_score, 0.15),
        (tech_score, 0.15), (val_score, 0.10), (env_score, 0.10),
    ]
    investment_score, _present = _weighted_avg(category_items)
    coverage_items = [
        (fund_cov, 0.30), (growth_cov, 0.20), (chip_cov, 0.15),
        (tech_cov, 0.15), (val_cov, 0.10), (1.0 if env_score is not None else 0.0, 0.10),
    ]
    data_coverage = sum(cov * w for cov, w in coverage_items)
    risk_score = score_risk(h, intel, tech, total_value, sector_weight)

    fair_value = estimate_fair_value(h)
    chase_high_distance = None
    if fair_value and h.price is not None:
        distance = h.price / fair_value - 1
        if distance >= CHASE_HIGH_THRESHOLD:
            chase_high_distance = distance

    return {
        "code": h.code,
        "name": h.name,
        "price": h.price,
        "investment_score": investment_score,
        "risk_score": risk_score,
        "data_coverage": data_coverage,
        "fair_value": fair_value,
        "target_price": h.target_mean_price,
        "chase_high_distance": chase_high_distance,
        "conviction_score": conviction_score,
        "conviction_stars": conviction_stars(conviction_score),
        "conviction_reasons": conviction_reasons,
        "reasons": (fund_reasons + growth_reasons + chip_reasons + tech_reasons + val_reasons)[:4],
    }


# ── 最終四色訊號決策 ─────────────────────────────

INVESTMENT_SCORE_BANDS = [
    (85, "🟢", "強烈買進"),
    (70, "🟢", "分批布局"),
    (55, "🟡", "持有觀察"),
    (40, "🟠", "減碼"),
    (0, "🔴", "建議賣出"),
]


def _band_for_score(score: float) -> tuple[str, str]:
    for threshold, emoji, label in INVESTMENT_SCORE_BANDS:
        if score >= threshold:
            return emoji, label
    return "🔴", "建議賣出"


def decide_signal(
    h: Holding,
    intel: dict,
    tech: dict,
    total_value: float,
    sector_weight: float,
    all_holdings: list[Holding],
    alert_state: dict,
    today: date | None = None,
) -> dict:
    """回傳單一持股的完整決策結果：signal、investment_score、risk_score、fair_value、reasons、quiet。"""
    today = today or date.today()

    fund_score, fund_cov, fund_reasons = score_fundamentals(h, intel)
    growth_score, growth_cov, growth_reasons = score_growth(h, intel)
    chip_score, chip_cov, chip_reasons = score_chips(h, intel)
    tech_score, tech_cov, tech_reasons = score_technicals(tech)
    val_score, val_cov, val_reasons = score_valuation(h, all_holdings)
    env_score = intel.get("environment_score")
    conviction_score, _conviction_cov, conviction_reasons = score_conviction(h, intel)

    category_items = [
        (fund_score, 0.30), (growth_score, 0.20), (chip_score, 0.15),
        (tech_score, 0.15), (val_score, 0.10), (env_score, 0.10),
    ]
    investment_score, _present = _weighted_avg(category_items)
    # 「有沒有分數」跟「這個分數是不是靠豐富資料算出來的」是兩回事：ETF 常常光靠殖利率/技術面
    # 就能讓每個類別「有分數」，但基本面/成長性/籌碼面其實幾乎全是缺資料。data_coverage 用
    # 每個類別內部子項目的實際覆蓋率（各 score_* 回傳的第二個值）加權平均，才是誠實的信心指標。
    coverage_items = [
        (fund_cov, 0.30), (growth_cov, 0.20), (chip_cov, 0.15),
        (tech_cov, 0.15), (val_cov, 0.10), (1.0 if env_score is not None else 0.0, 0.10),
    ]
    data_coverage = sum(cov * w for cov, w in coverage_items)
    risk_score = score_risk(h, intel, tech, total_value, sector_weight)

    all_reasons = fund_reasons + growth_reasons + chip_reasons + tech_reasons + val_reasons
    fair_value = estimate_fair_value(h)
    bullish = is_market_bullish(h)
    pnl_pct = h.pnl_pct

    signal, label, quiet, star = None, None, False, False

    if pnl_pct is None:
        signal, label = "🟡", "尚無市價資料"
    elif pnl_pct <= EXTREME_LOSS_THRESHOLD:
        catalyst = scan_catalyst((intel.get("material_news") or []) + (intel.get("general_news") or []), "title") \
            or scan_catalyst(intel.get("material_news") or [], "主旨")
        if catalyst == "negative":
            signal, label = "🔴", "重大利空，建議停損"
        elif catalyst == "positive":
            signal, label = _band_for_score(investment_score) if investment_score is not None else ("🟡", "持有觀察")
            label = f"出現利多訊號，重新評估：{label}"
        else:
            code_state = alert_state.get(h.code, {})
            last_date_str = code_state.get("last_alert_date")
            days_since = (today - date.fromisoformat(last_date_str)).days if last_date_str else 999
            quiet = days_since < QUIET_PERIOD_DAYS and code_state.get("last_signal") in ("🔴", None)
            if investment_score is not None and investment_score >= 40:
                star = True
                signal, label = "🔴", "⭐重點追蹤：巨額虧損但評分顯示有回升機會，非每日提醒"
            else:
                signal, label = "🔴", "已知巨額虧損部位，除非重大變化不再頻繁提醒"
    elif fair_value and h.price is not None and (h.price / fair_value - 1) >= CHASE_HIGH_THRESHOLD:
        distance = h.price / fair_value - 1
        signal, label = "🔴", f"❌不建議追價，現價已超合理價 {distance:+.1%}"
    elif pnl_pct >= TAKE_PROFIT_THRESHOLD:
        if bullish and h.upside_to_target is not None and h.upside_to_target >= 0.20:
            signal, label = "🟢", "獲利豐厚但法人／市場持續看好，建議續抱，不建議賣"
        elif fair_value and h.price is not None and (h.price / fair_value - 1) >= OVERVALUED_THRESHOLD:
            signal, label = "🟠", "獲利且現價已高估，建議分批獲利了結"
        else:
            signal, label = "🟠", "獲利達門檻，可考慮分批獲利了結"
    elif pnl_pct <= STOP_LOSS_HARD_THRESHOLD:
        signal, label = "🔴", "虧損擴大，不論法人看法，建議停損"
    elif pnl_pct <= STOP_LOSS_THRESHOLD:
        if bullish:
            signal, label = "🟡", "虧損但法人／市場持續看好，建議續抱觀察"
        elif add_on_conditions_met(h, intel, tech, fund_score):
            signal, label = "🟢", "符合加碼六條件，可考慮逢低加碼"
        else:
            emoji, band_label = _band_for_score(investment_score) if investment_score is not None else ("🟠", "減碼")
            signal, label = emoji, band_label
    else:
        signal, label = _band_for_score(investment_score) if investment_score is not None else ("🟡", "資料不足")

    if risk_score is not None and risk_score >= 80:
        label = f"{label}（⚠️高波動）"
    if data_coverage < 0.5:
        label = f"{label}（資料覆蓋率低，訊號僅供參考，常見於 ETF 缺乏基本面/籌碼面資料）"

    return {
        "signal": signal,
        "label": label,
        "investment_score": investment_score,
        "risk_score": risk_score,
        "data_coverage": data_coverage,
        "fair_value": fair_value,
        "target_price": h.target_mean_price,
        "reasons": all_reasons[:4],
        "quiet": quiet,
        "star": star,
        "conviction_score": conviction_score,
        "conviction_stars": conviction_stars(conviction_score),
        "conviction_reasons": conviction_reasons,
    }


def build_scoring_context(
    holdings: list[Holding],
    market_intel: dict[str, dict],
    technicals_map: dict[str, dict],
    environment_score: float | None,
) -> dict[str, dict]:
    """整合所有持股的評分與四色訊號決策，並更新（讀寫）alert_state.json。"""
    total_value = total_market_value(holdings)
    alert_state = load_alert_state()
    today = date.today()

    sector_totals: dict[str, float] = {}
    for h in holdings:
        if h.sector and h.market_value is not None and total_value:
            sector_totals[h.sector] = sector_totals.get(h.sector, 0) + h.market_value / total_value

    results: dict[str, dict] = {}
    for h in holdings:
        intel = dict(market_intel.get(h.code) or {})
        intel["environment_score"] = environment_score
        tech = technicals_map.get(h.code) or {}
        sector_weight = sector_totals.get(h.sector, 0.0) if h.sector else 0.0

        decision = decide_signal(h, intel, tech, total_value, sector_weight, holdings, alert_state, today)
        results[h.code] = decision

        if decision["signal"] is not None:
            entry = alert_state.setdefault(h.code, {})
            entry["last_signal"] = decision["signal"]
            entry["last_alert_date"] = today.isoformat()

    save_alert_state(alert_state)
    return results
