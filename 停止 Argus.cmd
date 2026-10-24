@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "data\server.pid" (
  echo 未找到运行记录。如果服务在命令窗口运行，请在对应窗口按 Ctrl+C。
  pause
  exit /b 0
)
powershell -NoProfile -Command "$argusRoot = (Get-Location).Path; $argusServerPid = [int](Get-Content -LiteralPath 'data/server.pid'); $argusProcess = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $argusServerPid); if ($argusProcess -and $argusProcess.CommandLine -match 'start.py' -and ($argusProcess.CommandLine.Contains($argusRoot) -or $argusProcess.ExecutablePath.StartsWith($argusRoot, [System.StringComparison]::OrdinalIgnoreCase))) { $argusChildren = Get-CimInstance Win32_Process -Filter ('ParentProcessId = ' + $argusServerPid); foreach ($argusChild in $argusChildren) { Get-CimInstance Win32_Process -Filter ('ParentProcessId = ' + $argusChild.ProcessId) | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }; Stop-Process -Id $argusChild.ProcessId -ErrorAction SilentlyContinue }; Stop-Process -Id $argusServerPid -ErrorAction SilentlyContinue; Write-Output 'Argus 已停止，未完成任务将在下次启动恢复。' } else { Write-Output '未发现匹配的 Argus 进程，未终止其他程序。' }"
pause
