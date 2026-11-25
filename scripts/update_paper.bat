@echo off
rem Hourly update from the bot machine: paper replay + read-only snapshot of the real account, both encrypted with the
rem owner's password (private\password.txt, never committed) into docs\data\vault.json, which is the only data pushed.
rem Log: scripts\update_paper.log
cd /d "%~dp0.."
echo ===== %date% %time% >> scripts\update_paper.log
git pull --rebase -q >> scripts\update_paper.log 2>&1
"C:\Users\AI_TOP_100\AppData\Local\Programs\Python\Python310\python.exe" engine\donchian_paper.py >> scripts\update_paper.log 2>&1
if errorlevel 1 goto end
"C:\CLAUDE\_BOT_TRADE\MEKVRO_bOT\.venv\Scripts\python.exe" "C:\CLAUDE\_BOT_TRADE\MEKVRO_bOT\scripts\export_live.py" > private\live.tmp 2>> scripts\update_paper.log
if not errorlevel 1 move /y private\live.tmp private\live.json >nul
"C:\Users\AI_TOP_100\AppData\Local\Programs\Python\Python310\python.exe" engine\seal.py >> scripts\update_paper.log 2>&1
if errorlevel 1 goto end
git add docs\data\vault.json
git diff --cached --quiet && goto end
git commit -q -m "chore: update encrypted dashboard" >> scripts\update_paper.log 2>&1
git push -q >> scripts\update_paper.log 2>&1
:end
