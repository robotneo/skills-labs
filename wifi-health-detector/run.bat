@echo off
setlocal
set "WIFI_LAUNCH_ENGINE=%WIFI_HEALTH_ENGINE%"
:scan_engine
if "%~1"=="" goto launch
if /I "%~1"=="--engine" set "WIFI_LAUNCH_ENGINE=%~2"
shift
goto scan_engine
:launch
powershell.exe -NoProfile -File "%~dp0run.ps1" %*
if not errorlevel 9009 exit /b %ERRORLEVEL%
if /I "%WIFI_LAUNCH_ENGINE%"=="python" goto unavailable
if /I "%WIFI_LAUNCH_ENGINE%"=="native" goto unavailable
rem PowerShell executable absent: only the explicit Node fallback is possible.
if defined WIFI_HEALTH_NODE (
  "%WIFI_HEALTH_NODE%" "%~dp0portable\node.cjs" %*
) else (
  node "%~dp0portable\node.cjs" %*
)
exit /b %ERRORLEVEL%
:unavailable
echo Requested engine cannot start because PowerShell is unavailable. 1>&2
exit /b 3
