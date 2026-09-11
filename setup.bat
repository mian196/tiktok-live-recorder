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
echo [INFO] Syncing dependencies into local virtual environment (.venv)...
uv sync --all-extras
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
    if exist configs\config.example.json (
        copy configs\config.example.json configs\config.json >nul
        echo [SUCCESS] Created configs/config.json from template.
    )
) else (
    echo [INFO] Config file already exists in configs/config.json.
)

:: Create configs/cookies.json template if not exists
if not exist configs\cookies.json (
    if exist configs\cookies.example.json (
        copy configs\cookies.example.json configs\cookies.json >nul
        echo [SUCCESS] Created configs/cookies.json from template.
    ) else (
        echo {} > configs\cookies.json
        echo [SUCCESS] Created template in configs/cookies.json.
    )
) else (
    echo [INFO] Cookies file already exists in configs/cookies.json.
)

:: Create configs/telegram.json template if not exists
if not exist configs\telegram.json (
    if exist configs\telegram.example.json (
        copy configs\telegram.example.json configs\telegram.json >nul
        echo [SUCCESS] Created configs/telegram.json from template.
    )
) else (
    echo [INFO] Telegram config already exists in configs/telegram.json.
)
echo.

:: 4. Register Startup trigger (Task Scheduler, fallback to Startup Folder)
echo [INFO] Registering startup trigger in Windows Task Scheduler...
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

powershell -ExecutionPolicy Bypass -Command "$scriptDir = '%SCRIPT_DIR%'; $action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('\"' + $scriptDir + '\silent_start.vbs\"') -WorkingDirectory $scriptDir; $trigger = New-ScheduledTaskTrigger -AtLogOn; $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -Compatibility Win8; $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings; Register-ScheduledTask -TaskName 'TikTok_Live_Recorder' -InputObject $task -Force" >nul 2>&1
if %errorlevel% EQU 0 goto TASK_SUCCESS

echo [INFO] Task Scheduler registration requires Administrator privileges.
echo [INFO] Falling back to Windows Startup Folder (user-level startup, no admin needed)...

set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not exist "%STARTUP_DIR%" goto STARTUP_FAILED

echo @echo off> "%STARTUP_DIR%\TikTok_Live_Recorder.bat"
echo cd /d "%~dp0">> "%STARTUP_DIR%\TikTok_Live_Recorder.bat"
echo wscript.exe "%~dp0silent_start.vbs">> "%STARTUP_DIR%\TikTok_Live_Recorder.bat"
echo [SUCCESS] Created startup shortcut in Windows Startup Folder!
echo [SUCCESS] The script will run silently in background every time you log into Windows.
goto REGISTRATION_END

:TASK_SUCCESS
echo [SUCCESS] Windows Task Scheduler task 'TikTok_Live_Recorder' registered successfully!
echo [SUCCESS] Visible in Task Scheduler Library and set to run automatically on logon.
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
