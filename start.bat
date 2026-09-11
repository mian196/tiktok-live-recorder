@echo off
:: TikTok Live Recorder Silent Runner
cd /d "%~dp0"

where uv >nul 2>&1
if %errorlevel% neq 0 (
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
)

if not exist .venv (
    echo [INFO] Setting up virtual environment...
    uv sync --all-extras
)

uv run python src/main.py
