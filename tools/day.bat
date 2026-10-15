@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONPATH=%~dp0..\src
cd /d %~dp0..
if not exist logs mkdir logs
echo START %date% %time% >> logs\daily.log
python -u -m eai day >> logs\daily.log 2>&1
echo DONE %date% %time% >> logs\daily.log
