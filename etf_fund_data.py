"""ETF 基金層級資料（規模／費用率／配息政策）：投信投顧公會（SITCA）開放資料，經 data.gov.tw 轉發。

跟 `market_data.py` 的證交所 OpenAPI（上市公司層級資料）是不同資料網域——ETF 的規模/費用率/配息
這些「基金本身」的資料，官方來源是投信投顧公會，不是證交所。三份 CSV 用「統一編號」互相 join：
- 境內基金基本資料（data.gov.tw/dataset/43476）：基金規模、基金類型別、配息規定
- 境內基金各項費用資料（data.gov.tw/dataset/46443）：月費用各項金額，用「合計金額／基金規模金額×12」
  自算年化費用率（**不用**資料集裡的「合計_比率」欄位，其分母定義不夠明確，實測用原始金額自算出的
  0050 費用率約 0.2%，量級跟公開已知數字吻合，比直接信任「合計_比率」欄位更可靠、可驗證）

**配息資料集（dataset/160547）刻意不用來算「近12個月配息穩定度」**：實測發現這份資料集每次抓到的
只有最新一個月的配息快照（例如某次抓到的紀錄全部落在同一個月內），不是真正的12個月歷史，沒辦法
回推變異係數。改用基金基本資料 CSV 裡本來就有的「基金配息規定」欄位做「配息型／累積不配息型」的
簡單分類（純文字描述，不是量化穩定度分數），延續專案一貫「寧可缺資料也不亂估」的原則。

這些 CSV 都沒有股票代號欄位（沒有「0050」這種欄位），只能用統一編號互相對照，因此
`ETF_ISSUER_ID_MAP` 是人工整理的「代號→統編」對照表——已逐一用 SITCA 基金基本資料 CSV 核對官方
完整基金全名（例如 0050 官方全名是「元大台灣卓越50基金」，不是市場慣稱的「元大台灣50」）取得，
不是憑印象猜測。
"""

import csv
import io

import requests
import truststore

# SITCA（投信投顧公會）網站的憑證鏈缺少 Subject Key Identifier 擴充欄位，瀏覽器／curl（走系統
# 憑證庫）都能正常連線，但 Python `requests`（走 `cryptography` 套件的嚴格 x509 驗證）會直接判定
# 憑證鏈不合法而連線失敗（實測錯誤：SSLCertVerificationError: Missing Subject Key Identifier）。
# 改用 `truststore` 讓 Python 的 SSL 驗證走作業系統原生信任庫（Windows CryptoAPI，跟 curl 同一套），
# **不是**停用憑證驗證（不是 verify=False），連線安全性不變，只是換一套鏈建構演算法。
truststore.inject_into_ssl()

FUND_BASIC_CSV_URL = "https://www.sitca.org.tw/MemberK0000/F/03/43476投信投顧公會境內基金基本資料.csv"
FUND_FEE_CSV_URL = "https://www.sitca.org.tw/MemberK0000/F/03/46443投信投顧公會境內基金各項費用資料.csv"

# 代號 -> 統一編號，已用 SITCA 基金基本資料 CSV 逐一核對官方全名確認（見專案進度.md）。
ETF_ISSUER_ID_MAP: dict[str, str] = {
    "0050": "98764389",      # 元大台灣卓越50基金
    "006208": "31840182",    # 富邦台灣釆吉50基金
    "009816": "00655756",    # 凱基台灣TOP 50 ETF基金
    "0056": "48966213",      # 元大台灣高股息基金
    "00878": "88090913",     # 國泰台灣高股息傘型基金之台灣ESG永續高股息ETF基金
    "00919": "88330879",     # 群益台灣精選高息ETF基金
    "00929": "88399314",     # 復華台灣科技優息ETF基金
    "00940": "93176257",     # 元大臺灣價值高息ETF基金
    "00713": "42540916",     # 元大台灣高股息低波動ETF基金
    "00830": "75968002",     # 國泰美國費城半導體基金
    "00891": "88182265",     # 中國信託臺灣ESG永續關鍵半導體ETF基金
    "00892": "88183736",     # 富邦台灣核心半導體ETF基金
}

_csv_cache: dict[str, list[dict]] = {}


def _fetch_csv(url: str) -> list[dict]:
    """下載並解析 SITCA CSV（UTF-8 BOM），同一次執行內快取，避免同一份被下載三次
    （一次執行要查全部候選 ETF，三份 CSV 各自只需要下載一次）。
    """
    if url in _csv_cache:
        return _csv_cache[url]
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        text = r.content.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
    except Exception:
        rows = []
    _csv_cache[url] = rows
    return rows


def _to_number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_row(rows: list[dict]) -> dict | None:
    return max(rows, key=lambda r: r.get("年月") or "") if rows else None


def fetch_fund_size(issuer_id: str) -> float | None:
    """該統編最新一筆「基金規模(依基金別)_金額」（新台幣元）。"""
    rows = [r for r in _fetch_csv(FUND_BASIC_CSV_URL) if r.get("統編") == issuer_id]
    latest = _latest_row(rows)
    return _to_number(latest.get("基金規模(依基金別)_金額")) if latest else None


def fetch_dividend_policy(issuer_id: str) -> str | None:
    """依「基金配息規定」欄位粗略分類：'distributing'（有明訂配息）／'accumulating'（收益併入淨值不
    分配，例如 009816）。文字描述複雜、含糊的情況（例如僅寫「詳公開說明書」）一律視為 'distributing'
    （沒有明確寫「不予分配」就不假設它是累積型），資料完全缺失回傳 None。
    """
    rows = [r for r in _fetch_csv(FUND_BASIC_CSV_URL) if r.get("統編") == issuer_id]
    latest = _latest_row(rows)
    if not latest:
        return None
    rule = latest.get("基金配息規定(基金收益分配規定)") or ""
    if not rule:
        return None
    return "accumulating" if "不予分配" in rule else "distributing"


def fetch_expense_ratio(issuer_id: str) -> float | None:
    """該統編最新一筆年化費用率（合計金額／基金規模金額 × 12）。"""
    fee_rows = [r for r in _fetch_csv(FUND_FEE_CSV_URL) if r.get("基金統編") == issuer_id]
    latest = _latest_row(fee_rows)
    if not latest:
        return None
    total_fee = _to_number(latest.get("合計"))
    fund_size = fetch_fund_size(issuer_id)
    if total_fee is None or not fund_size:
        return None
    return total_fee / fund_size * 12


def fetch_fund_metrics(code: str) -> dict:
    """代號 -> {"aum", "expense_ratio", "dividend_policy"}。不在 `ETF_ISSUER_ID_MAP` 裡的代號，
    或抓不到資料的欄位，一律回傳 None（缺資料不亂估，延續專案既有原則）。
    """
    issuer_id = ETF_ISSUER_ID_MAP.get(code)
    if not issuer_id:
        return {"aum": None, "expense_ratio": None, "dividend_policy": None}
    return {
        "aum": fetch_fund_size(issuer_id),
        "expense_ratio": fetch_expense_ratio(issuer_id),
        "dividend_policy": fetch_dividend_policy(issuer_id),
    }
