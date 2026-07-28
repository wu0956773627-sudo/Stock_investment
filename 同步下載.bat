@echo off
chcp 65001 >nul
cd /d %~dp0

echo ===== 同步下載 =====

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 goto :notgit

set DIRTY=
for /f "delims=" %%x in ('git status --porcelain') do set DIRTY=1
if defined DIRTY goto :dirty

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%b

echo 正在檢查遠端最新狀態...
git fetch

git rev-parse --abbrev-ref --symbolic-full-name @{u} >nul 2>&1
if errorlevel 1 goto :noupstream

git pull
if errorlevel 1 goto :pullfail

echo.
echo 下載完成！最近的變更：
git log --oneline -n 5
goto :end

:pullfail
echo.
echo 下載失敗或發生合併衝突，請手動處理，不會自動選邊解決衝突。
goto :end

:noupstream
echo 分支尚未設定追蹤的遠端分支，無法自動比對，請手動處理。
goto :end

:dirty
echo 本機有尚未提交的變更，為避免覆蓋，已中止同步下載。
echo 請先手動處理下列異動（commit 或還原）後再重新執行：
echo.
git status --short
goto :end

:notgit
echo 目前資料夾不是 Git 儲存庫。
goto :end

:end
pause
