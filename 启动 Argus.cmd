@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 首次使用请先运行「安装依赖.cmd」。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "%~dp0start.py"
pause
