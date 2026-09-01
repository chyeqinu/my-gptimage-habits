#!/usr/bin/env sh
# my-gptimage-habits 安装脚本（macOS / Linux）
# 用法：在本仓库根目录执行  sh install/install.sh [目标技能目录]
# 默认目标：$HOME/.agents/skills/my-gptimage-habits
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TARGET_DIR="${1:-$HOME/.agents/skills/my-gptimage-habits}"

mkdir -p "$(dirname "$TARGET_DIR")"
if [ -d "$TARGET_DIR" ]; then
  rm -rf "$TARGET_DIR"
fi
mkdir -p "$TARGET_DIR"

# 复制技能文件（排除安装脚本以外的无关产物）
cp "$REPO_ROOT/SKILL.md" "$REPO_ROOT/README.md" "$REPO_ROOT/LICENSE" "$REPO_ROOT/VERSION" "$REPO_ROOT/CHANGELOG.md" "$REPO_ROOT/.env.example" "$TARGET_DIR/" 2>/dev/null || true
[ -f "$REPO_ROOT/.env.example" ] && cp "$REPO_ROOT/.env.example" "$TARGET_DIR/" || true
cp -R "$REPO_ROOT/scripts" "$TARGET_DIR/scripts"
cp -R "$REPO_ROOT/references" "$TARGET_DIR/references"

find "$TARGET_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "已安装到: $TARGET_DIR"
echo ""
echo "下一步（配置 API key，每台设备一次）："
echo "  python3 \"$TARGET_DIR/scripts/gimg.py\" --set-key <你的key>"
echo "  验证:   python3 \"$TARGET_DIR/scripts/gimg.py\" --show-config"
