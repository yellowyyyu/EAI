@echo off
schtasks /Create /TN "EAI-DailyConsolidate" /TR "\"%~dp0day.bat\"" /SC DAILY /ST 21:30 /F
if %errorlevel%==0 (echo OK: daily task EAI-DailyConsolidate registered at 21:30) else (echo FAILED - run this file as Administrator)
pause
