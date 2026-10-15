@echo off
set PYTHONUTF8=1
"E:\Anaconda\python.exe" -X utf8 "%~dp0session_start_hook.py" 2>> "%~dp0..\logs\hook_err.log"
