@echo off
setlocal
title Codex Bridge
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js is not installed or not in PATH.
  echo         Install Node.js from https://nodejs.org and try again.
  pause
  exit /b 1
)

set "BRIDGE="
if exist "codex-bridge.js" set "BRIDGE=codex-bridge.js"
if not defined BRIDGE for %%f in (*codex-bridge*.js) do set "BRIDGE=%%f"

if not defined BRIDGE (
  echo [ERROR] codex-bridge.js not found in this folder:
  echo         %CD%
  echo         Put codex-bridge.js next to this .bat file and run again.
  pause
  exit /b 1
)

echo Starting bridge: %BRIDGE%
node "%BRIDGE%"
pause
