#!/usr/bin/env bash
# nlcmd 卸载脚本
# 用法：bash uninstall.sh            # 卸载程序（保留配置）
#       bash uninstall.sh --purge   # 卸载程序 + 配置 + 历史
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
APP_DIR="$HOME/.local/share/nlcmd"
BIN="$HOME/.local/bin/nlcmd"
CFG_DIR="$HOME/.config/nlcmd"
STATE_DIR="$HOME/.local/state/nlcmd"

rm -rf "$APP_DIR"
rm -f "$BIN"
rm -f "$HOME/.local/bin/nlc"
# 移除注入到 ~/.bashrc 的 command_not_found_handle 钩子
if [ -f "$HOME/.bashrc" ] && grep -q "NLCMD_HOOK" "$HOME/.bashrc"; then
    sed -i '/>>> NLCMD_HOOK >>>/,/<<< NLCMD_HOOK <<</d' "$HOME/.bashrc"
    echo -e "${GREEN}[✓]${NC} 已移除 ~/.bashrc 中的 nlcmd 钩子"
fi
echo -e "${GREEN}[✓]${NC} 已删除程序：$APP_DIR"

if [ "${1:-}" = "--purge" ]; then
    rm -rf "$CFG_DIR" "$STATE_DIR"
    echo -e "${GREEN}[✓]${NC} 已删除配置与历史：$CFG_DIR $STATE_DIR"
else
    if [ -d "$CFG_DIR" ]; then
        echo -e "${YELLOW}[!]${NC} 保留了配置文件 $CFG_DIR（如需彻底删除：bash uninstall.sh --purge）"
    fi
fi
echo "卸载完成。"
