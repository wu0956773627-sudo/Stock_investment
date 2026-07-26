"""AI 投資顧問 v1.0 - 產生並印出固定格式的投資報告（Markdown + Excel）。"""

import sys

from portfolio import load_portfolio, enrich_with_market_data
from report import generate_investment_report, REPORT_PATH
from excel_report import generate_excel_report, EXCEL_REPORT_PATH

if hasattr(sys.stdout, "reconfigure"):
    # 報告內容含 AI 評分訊號 emoji（🟢🟡🟠🔴），非 UTF-8 主控台（如 Windows cp950）印出時
    # 會 UnicodeEncodeError 而中止程式；報告檔案其實已經正確寫入，只是收尾的 print() 崩潰。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    holdings = load_portfolio()
    enrich_with_market_data(holdings)

    content = generate_investment_report(holdings)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    generate_excel_report(EXCEL_REPORT_PATH, holdings)

    print(content)
    print(f"\n（報告已同步儲存至 {REPORT_PATH} 與 {EXCEL_REPORT_PATH}）")


if __name__ == "__main__":
    main()
