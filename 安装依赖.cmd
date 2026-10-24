@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo 安装失败，请检查网络和 Python 版本。
  pause
  exit /b 1
)
echo 安装完成。双击「启动 Argus.cmd」开始使用。
pause
