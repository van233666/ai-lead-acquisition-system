@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "ua_mini.db.bak" copy "ua_mini.db" "ua_mini.db.bak" >nul
echo 正在清理重复线索...
".venv\Scripts\python.exe" clean_duplicates.py
echo.
pause
