"""凱基 API 連線測試腳本。

使用前請先：
  1. 複製 .env.example 為 .env，填入您的身分證字號與密碼
  2. 確認本機已完成凱基電子憑證安裝（登入憑證與這台電腦綁定）

執行：
  uv run python test_kgi_connection.py
"""

import kgi_client as kc


def main():
    print("正在連線凱基 SUPER PY API ...")
    api = kc.connect()

    print("\n可用交易帳號：")
    kc.list_accounts(api)

    if kc.KGI_TRADE_ACCOUNT:
        print(f"\n設定交易帳號：{kc.KGI_TRADE_ACCOUNT}")
        kc.use_account(api)

        print("\n查詢庫存：")
        print(kc.get_holdings(api))
    else:
        print("\n尚未在 .env 設定 KGI_TRADE_ACCOUNT，略過庫存查詢。"
              "請從上方帳號列表選一個填入 .env 後重新執行。")

    print("\n查詢台積電(2330)即時報價：")
    print(kc.get_snapshot(api, "2330"))

    kc.logout(api)
    print("\n連線測試完成，已登出。")


if __name__ == "__main__":
    main()
