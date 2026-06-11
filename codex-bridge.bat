@echo off
chcp 65001 >nul
title Codex CLI 연결 프로그램 (영상 편집기용)
node "%~dp0codex-bridge.js"
pause
