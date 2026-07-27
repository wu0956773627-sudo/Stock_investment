---
name: investment-dashboard
description: 當使用者說「打開投資儀表板」「啟動網頁報告」「看網頁版報告」時，啟動 app.py 的 FastAPI 網頁儀表板。
model: haiku
---

# 投資儀表板 (Investment Dashboard)

啟動網頁版的投資報告（FastAPI + uvicorn），讓使用者在瀏覽器查看即時報告。

## 執行步驟

1. 確認 8000 port 沒有被佔用（Windows 可用 `netstat -ano | findstr :8000` 檢查），若被佔用，告知使用者並詢問要不要改用其他 port（例如 `--port 8001`）。
2. 在背景執行 `uv run uvicorn app:app --reload`，啟動後告知使用者網址 `http://127.0.0.1:8000`（或替代 port）。
3. 提醒使用者這個網頁儀表板**沒有身分驗證**，只在本機瀏覽器開啟即可，不要把這個網址對外公開、部署到公網或分享給他人，因為內容包含使用者的個人持股與金額。

## 注意事項

- `--reload` 模式下，之後若修改了 `portfolio.py`／`report.py`／`app.py` 等程式碼，網頁會自動重新載入，不需要重啟服務。
- 若使用者說「看完了、關掉」，停止該背景 uvicorn 程序，不要遺留在背景一直佔用 port。
