@echo off
chcp 65001 >nul
cd /d %~dp0

echo ===== 同步上傳 =====

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 goto :notgit

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%b

git add -A

git diff --cached --quiet
if errorlevel 1 goto :dodiff_hascommit
echo 沒有新的檔案變更，檢查是否有尚未推送的 commit...
goto :dopush

:dodiff_hascommit
echo 偵測到變更，建立 commit...
git commit -m "自動上傳備份 %date% %time%"
if errorlevel 1 goto :commitfail

:dopush
git rev-parse --abbrev-ref --symbolic-full-name @{u} >nul 2>&1
if errorlevel 1 goto :nopstream

git push
goto :checkresult

:nopstream
echo 分支尚未設定遠端追蹤，建立中...
git push -u origin %BRANCH%
goto :checkresult

:checkresult
if errorlevel 1 goto :pushfail
echo.
echo 上傳完成！分支：%BRANCH%
goto :end

:pushfail
echo.
echo 上傳失敗，請檢查上方錯誤訊息，可能是遠端有新的 commit，需要手動處理，這支批次檔不會自動 force push。
goto :end

:commitfail
echo.
echo Commit 失敗，請檢查上方錯誤訊息。
goto :end

:notgit
echo 目前資料夾不是 Git 儲存庫。
goto :end

:end
pause
