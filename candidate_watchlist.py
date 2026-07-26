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
from scoring import evaluate_candidate

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
