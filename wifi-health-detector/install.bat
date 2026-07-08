@echo off
setlocal enabledelayedexpansion

if "%WIFI_HEALTH_DETECTOR_REPO%"=="" (
  set "REPO_URL=https://github.com/robotneo/skills-labs.git"
) else (
  set "REPO_URL=%WIFI_HEALTH_DETECTOR_REPO%"
)

set "SKILL_NAME=wifi-health-detector"
if "%CODEX_HOME%"=="" (
  set "SKILL_DIR=%USERPROFILE%\.codex\skills\%SKILL_NAME%"
) else (
  set "SKILL_DIR=%CODEX_HOME%\skills\%SKILL_NAME%"
)

where git >nul 2>nul
if errorlevel 1 (
  echo 需要先安装 git
  exit /b 1
)

set "TMP_DIR=%TEMP%\skills-labs-%RANDOM%%RANDOM%"
git clone --depth 1 "%REPO_URL%" "%TMP_DIR%\repo"
if errorlevel 1 exit /b 1

if not exist "%TMP_DIR%\repo\%SKILL_NAME%" (
  echo 仓库中未找到 %SKILL_NAME% 目录
  rmdir /s /q "%TMP_DIR%"
  exit /b 1
)

mkdir "%USERPROFILE%\.codex\skills" 2>nul
if exist "%SKILL_DIR%" (
  set "BACKUP_DIR=%SKILL_DIR%.backup.%DATE:/=-%-%TIME::=-%"
  set "BACKUP_DIR=!BACKUP_DIR: =0!"
  move "%SKILL_DIR%" "!BACKUP_DIR!" >nul
  echo 已备份旧版本到: !BACKUP_DIR!
)

xcopy "%TMP_DIR%\repo\%SKILL_NAME%" "%SKILL_DIR%\" /E /I /Y >nul
rmdir /s /q "%TMP_DIR%"

echo 无线网络检测 Skill 安装成功: %SKILL_DIR%
echo 使用方式：对 AI 助手说 检测 WiFi 质量 或运行 python "%SKILL_DIR%\main.py"
pause
