@echo off
rem Hourly paper update from this machine (GitHub's hourly schedule proved unreliable):
rem pull, replay the paper engine on Binance futures data, commit dashboard.json, push. Log: scripts\update_paper.log
cd /d "%~dp0.."
echo ===== %date% %time% >> scripts\update_paper.log
git pull --rebase -q >> scripts\update_paper.log 2>&1
"C:\Users\AI_TOP_100\AppData\Local\Programs\Python\Python310\python.exe" engine\donchian_paper.py >> scripts\update_paper.log 2>&1
if errorlevel 1 goto end
git add docs\data\dashboard.json
git diff --cached --quiet && goto end
git commit -q -m "chore(paper): update dashboard.json (local)" >> scripts\update_paper.log 2>&1
git push -q >> scripts\update_paper.log 2>&1
:end
