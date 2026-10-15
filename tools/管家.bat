@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONPATH=%~dp0..\src;%PYTHONPATH%
python -m eai menu
