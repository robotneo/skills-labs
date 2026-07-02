#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${WIFI_HEALTH_DETECTOR_REPO:-https://github.com/robotneo/skills-labs.git}"
SKILL_NAME="wifi_health_detector"
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/$SKILL_NAME"

if ! command -v git >/dev/null 2>&1; then
  echo "需要先安装 git"
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

git clone --depth 1 "$REPO_URL" "$TMP_DIR/repo"

if [ ! -d "$TMP_DIR/repo/$SKILL_NAME" ]; then
  echo "仓库中未找到 $SKILL_NAME 目录"
  exit 1
fi

mkdir -p "$(dirname "$SKILL_DIR")"
if [ -e "$SKILL_DIR" ]; then
  BACKUP_DIR="$SKILL_DIR.backup.$(date +%Y%m%d%H%M%S)"
  mv "$SKILL_DIR" "$BACKUP_DIR"
  echo "已备份旧版本到: $BACKUP_DIR"
fi

cp -R "$TMP_DIR/repo/$SKILL_NAME" "$SKILL_DIR"
echo "无线网络检测 Skill 安装成功: $SKILL_DIR"
echo "使用方式：对 AI 助手说『检测 WiFi 质量』或运行 python3 $SKILL_DIR/main.py"
