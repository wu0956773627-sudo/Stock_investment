# 二十一、AI Agent（代理人）架構

> **架構名稱：Multi-Agent AI Investment Advisor**
>
> **架構模式：Master + Worker Agents**
>
> **設計理念：單一代理人只負責一項專業工作，由投資長 AI 統整所有分析結果，避免單一模型產生偏誤，提高分析品質、可維護性與可擴充性。**

## 一、設計原則

本專案採用 **Multi-Agent（多代理人）架構**。

- 每位 Agent 僅負責單一職責（Single Responsibility）。
- 所有 Agent 可獨立維護、獨立測試、獨立更新。
- 最終分析皆交由 **Investment Chief AI（投資長 AI）** 做唯一正式決策。

## 二、代理人架構

### Agent 01：Data Collector（資料收集）
- 股價、成交量、法人、夜盤、ADR、月營收、財報、公告、新聞
- 建議模型：基礎模型

### Agent 02：Data Cleaner（資料清洗）
- 股票名稱、代號、缺值、格式、重複資料
- 建議模型：基礎模型

### Agent 03：Financial Analyst（財報分析）
- 四大報表、EPS、ROE、ROA、毛利率、營益率、淨利率、現金流、負債比
- 建議模型：高階模型

### Agent 04：Valuation Agent（估值分析）
- PER、PEG、PB、EV/EBITDA、DCF、法人目標價、合理價、最佳買點
- 建議模型：高階模型

### Agent 05：Technical Analyst（技術分析）
- MA、KD、RSI、MACD、ATR、VWAP、布林通道、支撐壓力
- 建議模型：基礎模型

### Agent 06：Institution Agent（法人分析）
- 外資、投信、自營商、借券、籌碼集中度
- 建議模型：基礎模型

### Agent 07：News Analyst（新聞分析）
- 公司新聞、法說會、重大事件、利多利空判讀
- 建議模型：高階模型

### Agent 08：Industry Analyst（產業分析）
- AI、半導體、電子、金融、ETF、全球趨勢
- 建議模型：高階模型

### Agent 09：Risk Manager（風險控制）
- Beta、VaR、波動率、最大回撤、集中度
- 建議模型：高階模型

### Agent 10：Portfolio Manager（投資組合）
- 持股比例、報酬率、再平衡、現金比例
- 建議模型：高階模型

### Agent 11：Strategy Agent（交易策略）
- 買進、加碼、持有、減碼、賣出
- 建議模型：高階模型

### Agent 12：Scenario Agent（情境推演）
- 樂觀／中性／悲觀劇本、目標價、機率
- 建議模型：高階模型

### Agent 13：Behavior Guardian（衝動交易防護）
- 防止 FOMO、追高、恐慌停損、過度交易
- 建議模型：基礎模型

### Agent 14：Recommendation Agent（選股推薦）
- 每日最多推薦 3 檔，Investment Score ≥ 80
- 建議模型：高階模型

### Agent 15：Report Generator（報告產生）
- Markdown、PDF、HTML、Email
- 建議模型：基礎模型

### Agent 16：Notification Agent（通知）
- LINE、Email、Discord、Telegram
- 建議模型：基礎模型

### Agent 17：Memory Agent（記憶）
- 保存交易、AI建議、績效
- 建議模型：基礎模型

### Agent 18：Backtest Agent（策略回測）
- 5／10／20 年回測、CAGR、Sharpe、最大回撤
- 建議模型：高階模型

### Agent 19：Quality Auditor（品質稽核）
- 檢查各 Agent 是否互相衝突
- 建議模型：基礎模型

### Agent 20：Scheduler Agent（排程）
- 每日、每週、每月、每季工作排程
- 建議模型：基礎模型

### Agent 21：Learning Agent（學習）
- 比較 AI 建議與實際績效，自動調整權重
- 建議模型：高階模型

## 三、Investment Chief AI

唯一具有最終決策權。

最終只能輸出：

- 🟢 強烈買進
- 🟢 分批布局
- 🟡 持有
- 🟠 減碼
- 🔴 賣出

## 四、Agent 權重

| Agent | 權重 |
|------|----:|
| 財報分析 | 25% |
| 估值分析 | 20% |
| 投資組合 | 15% |
| 風險控制 | 15% |
| 法人分析 | 10% |
| 技術分析 | 5% |
| 新聞分析 | 5% |
| 情境推演 | 5% |

## 五、Model Routing

### 基礎模型
- 查詢
- 整理
- 排程
- 通知
- 報表

### 高階模型
- 推論
- 財報
- 估值
- 策略
- 多因子分析
- AI 決策

## 六、Cache

資料未更新不得重複分析。

重新分析條件：
- 股價更新
- 財報更新
- 月營收更新
- 法人更新
- 持股更新
- 規則更新

## 七、永久規範

所有未來新增 Agent、API、MCP、自動化流程皆須遵循：

1. Multi-Agent
2. Model Routing
3. Cache
4. Investment Chief AI 最終決策
5. 單一職責
6. 可擴充
7. 可維護
8. 可回測
9. 可稽核
