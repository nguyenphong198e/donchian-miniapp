' Runs update_paper.bat with no window (used by the hourly scheduled task).
CreateObject("WScript.Shell").Run "cmd /c ""C:\CLAUDE\_BOT_TRADE\donchian_miniapp\scripts\update_paper.bat""", 0, True
