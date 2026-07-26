"""潛力新標的觀察：從一份人工整理的優質股／ETF 候選池中，篩出目前沒有持有、
評分最高的幾檔，獨立列在每日報告——跟既有持股的「AI 綜合評分與行動建議」是兩件事：
那邊回答「該不該對目前持股採取行動」，這裡回答「還有沒有值得考慮加入的新標的」。

**候選池是人工整理的台股常見權值股／優質股代表 + 熱門 ETF**（比照太太
`sector_rotation.py` 的 `WATCHLIST` 做法），不是全市場掃描——上市櫃合計近 2000 檔，
用免費資料源逐檔套六構面評分成本太高（每檔都要抓財報/技術面/籌碼面），這裡先用一份
精簡但涵蓋多元產業的候選清單，能穩定在合理時間內跑完。

**依使用者要求分成「高價股」「低價股」各挑幾檔**：按候選清單當下的股價中位數切成兩組，
各組內再依 Investment Score 排序取前幾名，讓使用者在不同價位帶都有選項可看
（不是只推薦一堆買不起零股以外都很貴的權值股，也不是只推薦低價股缺乏多樣性）。
"""

from portfolio import Holding, fetch_market_data, total_market_value
from market_data import build_market_intel
from technicals import build_technicals_map
from scoring import evaluate_candidate, evaluate_etf_candidate
from etf_fund_data import fetch_fund_metrics, ETF_ISSUER_ID_MAP

CANDIDATE_POOL: dict[str, str] = {
    # 權值／龍頭股（涵蓋多元產業，盡量避開跟太太 sector_rotation.py 短線輪動池全部重疊）
    "2330": "台積電", "2454": "聯發科", "2317": "鴻海", "2308": "台達電",
    "3711": "日月光投控", "2412": "中華電", "4904": "遠傳",
    "2881": "富邦金", "2882": "國泰金", "2891": "中信金", "2886": "兆豐金",
    "1301": "台塑", "1303": "南亞", "6505": "台塑化", "2002": "中鋼",
    "1216": "統一", "9910": "豐泰", "2912": "統一超", "9904": "寶成",
    # 熱門 ETF
    "0050": "元大台灣50", "0056": "元大高股息", "006208": "富邦台50",
    "00878": "國泰永續高股息", "00919": "群益台灣精選高息", "00929": "復華台灣科技優息",
}

# ETF 專屬候選池：跟 CANDIDATE_POOL（個股＋少量熱門ETF共用個股六構面評分）分開，用
# `ETF_ISSUER_ID_MAP`（已逐一用 SITCA 官方全名核對過統編的 12 檔）擴大覆蓋市值型／高股息型／
# 半導體主題型，**刻意排除槓桿反向型（正2/反1）與期貨型**——這些是短線工具，跟使用者
# 「長期持有 5-20 年」的定位衝突。名稱已用 WebSearch 核對市場常用簡稱（非官方基金全名，
# 官方全名見 etf_fund_data.py 的統編對照表註解）。
ETF_CANDIDATE_POOL: dict[str, str] = {
    # 市值型
    "0050": "元大台灣50", "006208": "富邦台50", "009816": "凱基台灣TOP50",
    # 高股息型
    "0056": "元大高股息", "00878": "國泰永續高股息", "00919": "群益台灣精選高息",
    "00929": "復華台灣科技優息", "00940": "元大台灣價值高息", "00713": "元大台灣高息低波",
    # 半導體主題型
    "00830": "國泰費城半導體", "00891": "中信關鍵半導體", "00892": "富邦台灣半導體",
}
assert set(ETF_CANDIDATE_POOL) == set(ETF_ISSUER_ID_MAP), "ETF_CANDIDATE_POOL 應與 ETF_ISSUER_ID_MAP 代號一致"


def _fetch_candidates(existing_codes: set[str]) -> list[Holding]:
    to_check = {code: name for code, name in CANDIDATE_POOL.items() if code not in existing_codes}
    candidates = [Holding(code=code, name=name, shares=0, avg_cost=0) for code, name in to_check.items()]
    for h in candidates:
        fetch_market_data(h)
    return [h for h in candidates if h.price is not None]


def evaluate_candidates(
    existing_holdings: list[Holding], environment_score: float | None, top_n_each: int = 3
) -> list[dict]:
    """回傳「高價股」「低價股」各 top_n_each 檔的候選新標的評分結果（已排除追高、依 Investment
    Score 排序），每筆結果多一個 "price_tier": "high"/"low" 欄位。抓不到足夠候選資料就回傳空清單。
    """
    existing_codes = {h.code for h in existing_holdings}
    candidates = _fetch_candidates(existing_codes)
    if not candidates:
        return []

    market_intel = build_market_intel(candidates)
    technicals_map = build_technicals_map(candidates)

    total_value = total_market_value(existing_holdings)
    sector_totals: dict[str, float] = {}
    for h in existing_holdings:
        if h.sector and h.market_value is not None and total_value:
            sector_totals[h.sector] = sector_totals.get(h.sector, 0) + h.market_value / total_value

    scored: list[dict] = []
    for h in candidates:
        intel = dict(market_intel.get(h.code) or {})
        intel["environment_score"] = environment_score
        tech = technicals_map.get(h.code) or {}
        sector_weight = sector_totals.get(h.sector, 0.0) if h.sector else 0.0

        result = evaluate_candidate(h, intel, tech, candidates, total_value, sector_weight)
        if result["chase_high_distance"] is not None:
            continue  # 現在追高不建議進場的候選股先跳過
        if result["investment_score"] is None:
            continue
        scored.append(result)

    if not scored:
        return []

    scored.sort(key=lambda r: r["price"])
    mid = len(scored) // 2
    low_pool, high_pool = (scored[:mid], scored[mid:]) if mid else (scored, [])

    low_picks = sorted(low_pool, key=lambda r: r["investment_score"], reverse=True)[:top_n_each]
    high_picks = sorted(high_pool, key=lambda r: r["investment_score"], reverse=True)[:top_n_each]
    for r in low_picks:
        r["price_tier"] = "low"
    for r in high_picks:
        r["price_tier"] = "high"

    return low_picks + high_picks


def _fetch_etf_candidates(existing_codes: set[str]) -> list[Holding]:
    to_check = {code: name for code, name in ETF_CANDIDATE_POOL.items() if code not in existing_codes}
    candidates = [Holding(code=code, name=name, shares=0, avg_cost=0) for code, name in to_check.items()]
    for h in candidates:
        fetch_market_data(h)
    return [h for h in candidates if h.price is not None]


def evaluate_etf_candidates(
    existing_holdings: list[Holding], environment_score: float | None, top_n_each: int = 3
) -> list[dict]:
    """ETF 專屬候選觀察清單，跟 `evaluate_candidates()`（個股）**分開輸出、不混排**——兩者的
    Investment Score 子項目組成完全不同（個股：基本面/成長/籌碼/技術/估值/環境；ETF：
    規模/費用率/配息/技術/環境/估值），混在同一份排序裡比較「誰分數高」沒有意義。

    走同一套抓現價/技術面的 pipeline（`fetch_market_data`／`build_technicals_map`），但
    **不呼叫 `build_market_intel()`**——那是抓財報/籌碼面資料給個股用的，ETF 沒有這些資料，
    抓了也全是 None，白白浪費一輪網路請求；改呼叫 `etf_fund_data.fetch_fund_metrics()`
    取得規模/費用率/配息政策，交給 `scoring.evaluate_etf_candidate()` 評分。
    """
    existing_codes = {h.code for h in existing_holdings}
    candidates = _fetch_etf_candidates(existing_codes)
    if not candidates:
        return []

    technicals_map = build_technicals_map(candidates)

    total_value = total_market_value(existing_holdings)
    sector_totals: dict[str, float] = {}
    for h in existing_holdings:
        if h.sector and h.market_value is not None and total_value:
            sector_totals[h.sector] = sector_totals.get(h.sector, 0) + h.market_value / total_value

    scored: list[dict] = []
    for h in candidates:
        fund_metrics = dict(fetch_fund_metrics(h.code))
        fund_metrics["environment_score"] = environment_score
        tech = technicals_map.get(h.code) or {}
        sector_weight = sector_totals.get(h.sector, 0.0) if h.sector else 0.0

        result = evaluate_etf_candidate(h, fund_metrics, tech, candidates, total_value, sector_weight)
        if result["chase_high_distance"] is not None:
            continue  # 現在追高不建議進場的候選ETF先跳過
        if result["investment_score"] is None:
            continue
        scored.append(result)

    if not scored:
        return []

    scored.sort(key=lambda r: r["price"])
    mid = len(scored) // 2
    low_pool, high_pool = (scored[:mid], scored[mid:]) if mid else (scored, [])

    low_picks = sorted(low_pool, key=lambda r: r["investment_score"], reverse=True)[:top_n_each]
    high_picks = sorted(high_pool, key=lambda r: r["investment_score"], reverse=True)[:top_n_each]
    for r in low_picks:
        r["price_tier"] = "low"
    for r in high_picks:
        r["price_tier"] = "high"

    return low_picks + high_picks
