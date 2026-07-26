# 專案層級規範

## Claude Code 技能（`.claude/skills/`）model 分級

新增本專案的技能時，一律依複雜度在 SKILL.md frontmatter 指定 `model`，不要留預設（會吃掉當前對話的模型，浪費 token）：

- **`haiku`**：機械式操作、不太會出錯的簡單任務（例如：跑一支既定腳本、回報成功/失敗、單純轉發終端機輸出）。
- **`sonnet`**：需要判斷、摘要、從資料中挑重點的中等複雜度任務。
- **`opus`**：複雜、需要診斷推理的任務（例如：判讀原生層級錯誤訊息、比對是否為已知問題還是全新狀況），誤判成本高的情境。

範例可參考現有 7 個技能（`investment-report`＝sonnet、`daily-report`／`spouse-report`／`spouse-intraday-check`／`sector-rotation-preview`／`investment-dashboard`＝haiku、`kgi-connection-test`＝opus），技能清單與觸發詞整理在 `技能清單.docx`。

## AI Agent 架構參考（`AI_Agent_架構規格_v2.0.md`）

使用者提供的 `AI_Agent_架構規格_v2.0.md` 描述了一套理想化的 21 個 Multi-Agent 架構（Data Collector／Financial
Analyst／Valuation Agent／...／Investment Chief AI 統籌決策）。**這份文件只當架構參考與角色對照表，不會照字面
拆成 21 個獨立呼叫的 LLM subagent**，原因：文件裡大部分「Agent」的工作（技術指標、財務比率、法人買賣超、
估值換算）本質上是確定性的數學計算，現有 `scoring.py` 用 Python 公式一次算完，比逐一呼叫 LLM 更快、更便宜、
結果也更穩定（同樣輸入一定得到同樣輸出，不會有 LLM 的隨機性）；真正需要「判斷/推理」的部分（新聞利多利空
判讀、診斷推理）才有必要交給 LLM，這也是 6 個 Claude Code 技能已經在做的事。

**角色 → 現有實作對照**（供未來擴充功能時參考，不代表要重構成分散的 agent）：

| v2.0 文件角色 | 現有對應實作 |
|---|---|
| Data Collector／Data Cleaner | `market_data.py`／`technicals.py`／`market_environment.py`（抓取＋正規化） |
| Financial Analyst | `market_data.normalize_income_statement()`／`normalize_financial_ratios()`／`normalize_profitability()` |
| Valuation Agent | `scoring.score_valuation()`／`estimate_fair_value()` |
| Technical Analyst | `technicals.py` |
| Institution Agent | `market_data.fetch_institutional_flow_map()`／`fetch_margin_trading_map()`／董監持股相關函式 |
| News Analyst | `market_data.fetch_news()`＋`scoring.scan_catalyst()`（關鍵字判讀利多/利空） |
| Industry Analyst | `scoring.score_growth()` 的產業關鍵字弱代理＋`market_environment.py` |
| Risk Manager | `scoring.score_risk()` |
| Portfolio Manager | `portfolio.py`（持股比例、再平衡、月度資金分配） |
| Strategy Agent／Investment Chief AI | `scoring.decide_signal()`（四色訊號最終決策） |
| Behavior Guardian | `scoring.decide_signal()` 的禁止追高／加碼六條件邏輯 |
| Recommendation Agent | `portfolio.monthly_allocation_suggestion()` 的優先購買清單 |
| Report Generator／Notification Agent | `report.py`／`excel_report.py`／`pdf_report.py`／`app.py`／`notify.py` |
| Memory Agent | `alert_state.json`（節流狀態記憶） |
| Scheduler Agent | Windows 工作排程器（`daily_report.py`／`spouse_report.py`） |
| Backtest Agent／Learning Agent／Quality Auditor | **尚未實作**，屬於未來可能擴充的方向，目前沒有真實資料源或需求驅動，不要主動開工 |

**v2.0 文件的「Agent 權重表」（財報25%／估值20%／投資組合15%／風險控制15%／法人10%／技術5%／新聞5%／情境5%）
與現有 `scoring.py` 的六構面權重（基本面30%／成長性20%／籌碼面15%／技術面15%／估值10%／市場環境10%）分類方式
不同，兩者不是同一套系統，不要混用或誤以為要對齊——除非使用者明確要求把 `scoring.py` 改成 v2.0 這套分類，
否則維持現有六構面（已用真實持股資料驗證過，不要無故重構）。
