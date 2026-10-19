#!/usr/bin/env bash
# nlcmd 一键安装脚本（Linux）
# 用法：bash install.sh          # 从本仓库源码安装（推荐）
#       bash install.sh --pypi   # 从 PyPI 安装（发布后可用）
set -euo pipefail

APP_NAME="nlcmd"
APP_DIR="$HOME/.local/share/nlcmd"
VENV_DIR="$APP_DIR/venv"
BIN_DIR="$HOME/.local/bin"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. 检查 python3
if ! command -v python3 >/dev/null 2>&1; then
    error "未找到 python3，请先安装："
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv"
    echo "  CentOS/RHEL:    sudo yum install python3"
    exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)'; then
    error "需要 Python >= 3.7，当前版本：$(python3 -V 2>&1)"
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv"
    echo "  CentOS/RHEL 8:  sudo dnf install python3"
    exit 1
fi
info "Python 版本满足要求：$(python3 -V 2>&1)"

# 2. 创建独立虚拟环境（不污染系统 Python）
info "创建虚拟环境：$VENV_DIR"
rm -rf "$VENV_DIR"
python3 -m venv "$VENV_DIR"
PIP="$VENV_DIR/bin/pip"
"$PIP" install --disable-pip-version-check -q --upgrade "pip<24.1" 2>/dev/null || true

# 3. 安装（默认从本地源码；--pypi 从 PyPI）
if [ "${1:-}" = "--pypi" ]; then
    info "从 PyPI 安装 $APP_NAME"
    "$PIP" install --disable-pip-version-check "$APP_NAME"
elif [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    info "从本地源码安装：$SCRIPT_DIR"
    "$PIP" install --disable-pip-version-check "$SCRIPT_DIR"
else
    info "从 PyPI 安装 $APP_NAME"
    "$PIP" install --disable-pip-version-check "$APP_NAME"
fi

# 4. 链接到 PATH（nlcmd 主命令 + nlc 简写别名）
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/$APP_NAME" "$BIN_DIR/$APP_NAME"
ln -sf "$VENV_DIR/bin/$APP_NAME" "$BIN_DIR/nlc"
info "已链接可执行文件：$BIN_DIR/$APP_NAME（以及别名 nlc）"

# 5. PATH 检查
case ":$PATH:" in
    *":$BIN_DIR:"*) : ;;
    *)
        warn "检测到 $BIN_DIR 不在 PATH 中，请执行以下命令后重开终端："
        echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
        ;;
esac

# 6. 注入 bash 钩子：在任意 shell 提示符下直接输入自然语言即可调用 nlcmd
#    （原理：输入的中文不是有效命令时，bash 会调用 command_not_found_handle）
BASHRC="${HOME}/.bashrc"
HOOK_START="# >>> NLCMD_HOOK >>>"
HOOK_END="# <<< NLCMD_HOOK <<<"
if [ -f "$BASHRC" ] && grep -q "NLCMD_HOOK" "$BASHRC"; then
    info "bash 钩子已存在，跳过注入"
else
    cat >> "$BASHRC" <<HOOK

$HOOK_START 在提示符下直接输入自然语言，自动交给 nlcmd 生成并执行命令
command_not_found_handle() {
    if command -v nlcmd >/dev/null 2>&1; then
        nlcmd run "\$@"
        return \$?
    fi
    echo "bash: \$1：未找到命令" >&2
    return 127
}
$HOOK_END
HOOK
    info "已注入 bash 钩子到 ~/.bashrc：新终端里可直接输入中文调用（当前终端执行：source ~/.bashrc）"
fi

# 7. 自检
if "$BIN_DIR/$APP_NAME" --version >/dev/null 2>&1; then
    info "安装成功！两种用法："
    echo "    1) 输入 $APP_NAME 进入交互模式"
    echo "    2) 任意提示符下直接输入自然语言（需 source ~/.bashrc 生效钩子）"
else
    error "安装自检失败，请检查上方输出"
    exit 1
fi
