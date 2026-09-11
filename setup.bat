@echo off
:: TikTok Live Recorder Local Setup Utility
cd /d "%~dp0"

:: Self-elevate the script to run as Administrator (needed for Task Scheduler registration)
fsutil dirty query %systemdrive% >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Requesting Administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ===================================================
echo   TikTok Live Recorder - Windows Local Setup
echo ===================================================
echo.

:: 1. Verify/Install uv
where uv >nul 2>&1
if %errorlevel% neq 0 (
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
)

where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] uv not found. Installing uv using PowerShell installer...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
    where uv >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install uv automatically. Please install uv from https://docs.astral.sh/uv/getting-started/installation/
        pause
        exit /b 1
    )
    echo [SUCCESS] uv installed successfully.
) else (
    echo [SUCCESS] uv is already installed.
    uv --version
)
echo.

:: 2. Setup virtual environment and sync dependencies
echo [INFO] Syncing dependencies using uv...
uv sync
if %errorlevel% neq 0 (
    echo [ERROR] Failed to sync dependencies.
    pause
    exit /b 1
)
echo [SUCCESS] Dependencies synchronized successfully.
echo.

:: 3. Create configs directory and template config files if not present
echo [INFO] Configuring local directories and template configuration files...
if not exist configs (
    mkdir configs
)

:: Create configs/config.json template if not exists
if not exist configs\config.json (
    (
        echo {
        echo   "user": "",
        echo   "url": "",
        echo   "room_id": "",
        echo   "mode": "manual",
        echo   "automatic_interval": 5,
        echo   "output": "output",
        echo   "duration": null,
        echo   "proxy": "",
        echo   "telegram": false,
        echo   "bitrate": "",
        echo   "quality": "best",
        echo   "retry_delay": 5,
        echo   "disk_space_alert_gb": 5,
        echo   "keep_flv": false,
        echo   "no_update_check": false,
        echo   "notifications": {
        echo     "enabled": false,
        echo     "discord_webhook_url": "",
        echo     "telegram": false,
        echo     "cooldown_seconds": 30,
        echo     "events": {
        echo       "live_detected": true,
        echo       "recording_started": true,
        echo       "recording_finished": true,
        echo       "recording_failed": true,
        echo       "user_offline": true,
        echo       "app_started": true,
        echo       "app_error": true,
        echo       "low_disk_space": true
        echo     }
        echo   }
        echo }
    ) > configs\config.json
    echo [SUCCESS] Created template in configs/config.json.
) else (
    echo [INFO] Config file already exists in configs/config.json.
)

:: Create configs/cookies.json template if not exists
if not exist configs\cookies.json (
    echo {} > configs\cookies.json
    echo [SUCCESS] Created template in configs/cookies.json.
) else (
    echo [INFO] Cookies file already exists in configs/cookies.json.
)

:: Create configs/telegram.json template if not exists
if not exist configs\telegram.json (
    (
        echo {
        echo   "api_id": "",
        echo   "api_hash": "",
        echo   "session": "",
        echo   "chat_id": ""
        echo }
    ) > configs\telegram.json
    echo [SUCCESS] Created template in configs/telegram.json.
) else (
    echo [INFO] Telegram config already exists in configs/telegram.json.
)
echo.

:: 4. Register Startup trigger (Task Scheduler, fallback to Startup Folder)
echo [INFO] Registering startup trigger...
powershell -Command "$action = New-ScheduledTaskAction -Execute ($pwd.Path + '\start.bat') -WorkingDirectory $pwd.Path; $trigger = New-ScheduledTaskTrigger -AtLogOn; $settings = New-ScheduledTaskSettingsSet -Compatibility Win8; $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings; $task.Settings.Hidden = $true; Register-ScheduledTask -TaskName 'TikTok_Live_Recorder' -InputObject $task -Force" >nul 2>&1
if %errorlevel% EQU 0 goto TASK_SUCCESS

echo [INFO] Task Scheduler registration failed (requires Administrator privileges).
echo [INFO] Falling back to Windows Startup Folder (user-level startup, no admin needed)...

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not exist "%STARTUP_DIR%" goto STARTUP_FAILED

echo @echo off> "%STARTUP_DIR%\TikTok_Live_Recorder.bat"
echo cd /d "%~dp0">> "%STARTUP_DIR%\TikTok_Live_Recorder.bat"
echo start "" /b "start.bat">> "%STARTUP_DIR%\TikTok_Live_Recorder.bat"
echo [SUCCESS] Created startup shortcut in Windows Startup Folder!
echo [SUCCESS] The script will run automatically every time you log into Windows.
goto REGISTRATION_END

:TASK_SUCCESS
echo [SUCCESS] Windows Task Scheduler task 'TikTok_Live_Recorder' registered successfully!
echo [SUCCESS] The script will run automatically every time you log into Windows.
goto REGISTRATION_END

:STARTUP_FAILED
echo [WARNING] Startup folder not found. Please launch the script manually using start.bat.

:REGISTRATION_END
echo.

echo ===================================================
echo   TikTok Live Recorder Setup Completed!
echo ===================================================
echo.
echo [Next Steps]:
echo 1. Edit configs/config.json with target usernames, mode, or Discord webhook.
echo 2. Run start.bat to test recording.
echo.
pause
exit /b 0
