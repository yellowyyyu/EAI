@echo off
schtasks /Delete /TN "EAI-DailyConsolidate" /F
if %errorlevel%==0 (echo OK: daily task removed) else (echo Task not found or access denied)
pause
