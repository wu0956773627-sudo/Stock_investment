---
name: daily-report
description: 當使用者說「補寄每日報告」「手動寄每日報告」「今天的排程沒跑幫我寄」「重新寄一次通知」時，執行 daily_report.py 產生報告並寄送 Email／LINE。
model: haiku
---

# 每日報告 (Daily Report)

用於手動觸發原本應由 Windows 工作排程器在每天 05:00 自動執行的每日通知（`daily_report.py`）。常見情境：排程漏跑、電腦當時沒開機、或使用者想立即收到最新通知。

## 執行前提

1. 確認 `.env` 內已有 `EMAIL_ADDRESS`／`EMAIL_APP_PASSWORD`／`EMAIL_TO` 等寄信設定；`LINE_CHANNEL_ACCESS_TOKEN` 有設定才會一併發送 LINE，沒有就自動略過，不算錯誤。若使用者從未設定過，先提醒需要哪些變數，不要盲目執行後才發現失敗。

## 執行步驟

2. 寄送本身是使用者觸發這個技能時已經同意的操作，但等待寄信／LINE API 回應可能花一點時間。若使用者這回合還想在前台繼續做其他事，**用 Agent 工具背景執行**（`subagent_type: general-purpose`，`run_in_background: true`），派工內容為「在專案目錄執行 `uv run python daily_report.py`，回報完整終端機輸出」；若使用者明確想要「馬上等結果」，直接用 Bash 前台執行 `uv run python daily_report.py` 即可，不強制背景化。
3. 背景任務回報完成後（或前台執行完成後），依終端機輸出回報：Email 是否寄出（寄到哪個信箱）、LINE 是否有發送（若沒設定 token，說明是正常略過，不是失敗）。
4. 若失敗，把錯誤訊息原文回報給使用者，不要猜測原因亂改程式碼；常見原因是 Gmail 應用程式密碼失效（需重新產生）或網路問題。

## 注意事項

- 這個技能一觸發就會**實際寄出信件／LINE 通知**給使用者本人。如果使用者只是想「看看報告內容」而不是「要收到通知」，改用 `/investment-report`，不要多此一舉寄信。
- 若同一天內已經執行過（不論是排程自動跑還是手動跑過），除非使用者明確要求，不要主動再次觸發，避免使用者收到重複通知。
- 這個技能**只寄給使用者本人**，跟太太的短線報告是完全獨立的技能（`/spouse-report`），不要混用。
