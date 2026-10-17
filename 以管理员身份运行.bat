@echo off
cd /d "%~dp0"
for %%f in ("%~dp0*.exe") do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -LiteralPath '%%~ff' -ErrorAction SilentlyContinue; Start-Process -FilePath '%%~ff' -Verb RunAs"
)
