"""凱基證券 SUPER PY API 連線包裝（僅報價與庫存查詢，不含下單功能）。

憑證與帳密一律從本機 .env 讀取，絕不寫死在程式碼或提交進版本控制。
"""

import os

from dotenv import load_dotenv

load_dotenv()

KGI_PERSON_ID = os.getenv("KGI_PERSON_ID")
KGI_PERSON_PWD = os.getenv("KGI_PERSON_PWD")
KGI_TRADE_ACCOUNT = os.getenv("KGI_TRADE_ACCOUNT") or None
KGI_SIMULATION = os.getenv("KGI_SIMULATION", "true").strip().lower() != "false"


def connect(simulation: bool | None = None):
    """登入凱基 SUPER PY API。憑證需已預先安裝在本機。"""
    import kgisuperpy as kgi

    if not KGI_PERSON_ID or not KGI_PERSON_PWD:
        raise RuntimeError("尚未設定 KGI_PERSON_ID / KGI_PERSON_PWD，請先複製 .env.example 為 .env 並填入帳密。")

    sim = KGI_SIMULATION if simulation is None else simulation
    api = kgi.login(KGI_PERSON_ID, KGI_PERSON_PWD, simulation=sim)

    if not hasattr(api, "show_account"):
        raise RuntimeError(
            "登入未完成（憑證檢查失敗，尚未取得帳務/下單功能）。"
            "若 log 出現 CoCreateInstance() fail，代表 KGICGCAPIATL2x64.dll 尚未註冊"
            "（解法見 README「疑難排解」段落）。"
            "若 log 出現「請重新安裝 CGEnvDetectATL、KGICGCAPIATL2 元件」但 CheckCAComponent 已顯示 ok，"
            "代表卡在 CGEnvDetectATL 元件缺失，這是未公開文件的凱基內部元件，"
            "請洽凱基 API 客服 (02)2389-0088 / 0800-085-005 詢問下載方式。"
        )
    return api


def list_accounts(api) -> None:
    """印出目前身分證字號底下可用的交易帳號。"""
    api.show_account()


def use_account(api, account: str | None = None):
    """設定要操作的交易帳號，預設使用 .env 的 KGI_TRADE_ACCOUNT。"""
    account = account or KGI_TRADE_ACCOUNT
    if not account:
        raise RuntimeError("尚未指定交易帳號，請先呼叫 list_accounts(api) 查詢，並填入 .env 的 KGI_TRADE_ACCOUNT。")
    api.set_Account(account)
    return api


def get_snapshot(api, codes: str | list[str]) -> dict:
    """取得即時報價快照（取代 yfinance 的股價來源）。"""
    return api.Data.get_snapshots(codes)


def get_holdings(api) -> object:
    """查詢目前庫存／持股部位。需先呼叫 use_account()。"""
    if not hasattr(api, "Order"):
        raise RuntimeError("尚未設定交易帳號，請先呼叫 use_account(api)。")
    return api.Order.get_position()


def logout(api) -> None:
    api.logout()
