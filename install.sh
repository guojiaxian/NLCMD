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

# 5. PATH 处理：自动写入 ~/.bashrc，并确保登录 shell 能加载（无需用户手动操作）
BASHRC="${HOME}/.bashrc"
touch "$BASHRC"

ensure_bashrc_source() {
    # 保证登录 shell（读取 .bash_profile / .profile）最终会加载 .bashrc
    local pf
    for pf in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
        if [ -f "$pf" ]; then
            if grep -qE '(^|[^a-zA-Z_.])\. ?~/\.bashrc|source ?~/\.bashrc|\$HOME/\.bashrc' "$pf"; then
                return 0  # 已有加载逻辑
            fi
            printf '\n# added by nlcmd install: 加载 .bashrc（含 PATH 与 nlcmd 钩子）\n[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"\n' >> "$pf"
            info "已在 $pf 中追加 .bashrc 加载（登录 shell 生效）"
            return 0
        fi
    done
    # 三个文件都不存在时，创建 .bash_profile
    printf '# added by nlcmd install\n[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"\n' > "$HOME/.bash_profile"
    info "已创建 ~/.bash_profile（登录 shell 加载 .bashrc）"
}

case ":$PATH:" in
    *":$BIN_DIR:"*) : ;;  # 当前会话已包含
    *)
        if ! grep -q 'added by nlcmd install' "$BASHRC" 2>/dev/null; then
            printf '\n# added by nlcmd install: nlcmd 命令所在目录\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$BASHRC"
            info "已将 ~/.local/bin 写入 PATH（~/.bashrc）"
        fi
        ensure_bashrc_source
        ;;
esac

# 6. 注入 bash 钩子：在任意 shell 提示符下直接输入自然语言即可调用 nlcmd，
#    并把 nlcmd 执行过的命令导入 bash 历史（上键可随时查看）
#    （原理：输入的中文不是有效命令时，bash 会调用 command_not_found_handle；
#     PROMPT_COMMAND 在每次出提示符前把 shell_history 新增内容 history -s 进当前会话）
HOOK_START="# >>> NLCMD_HOOK >>>"
HOOK_END="# <<< NLCMD_HOOK <<<"
if [ -f "$BASHRC" ]; then
    # 先移除旧版本钩子块，保证升级到最新注入内容
    sed -i '/>>> NLCMD_HOOK >>>/,/<<< NLCMD_HOOK <<</d' "$BASHRC" 2>/dev/null
fi
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
# 将 nlcmd 执行过的命令导入 bash 历史（按上键可随时查看）
_nlc_history_import() {
    local f="\$HOME/.local/state/nlcmd/shell_history"
    local o="\$HOME/.local/state/nlcmd/.history_offset"
    [ -f "\$f" ] || return 0
    local sz cur line
    sz=\$(stat -c %s "\$f" 2>/dev/null) || return 0
    cur=0; [ -f "\$o" ] && cur=\$(cat "\$o" 2>/dev/null)
    if [ "\$sz" -gt "\$cur" ]; then
        while IFS= read -r line; do
            [ -n "\$line" ] && history -s "\$line"
        done < <(tail -c +"\$((cur + 1))" "\$f")
        echo "\$sz" > "\$o"
    elif [ "\$sz" -lt "\$cur" ]; then
        echo "\$sz" > "\$o"
    fi
}
case ":\$PROMPT_COMMAND:" in
    *"_nlc_history_import"*) : ;;
    *) PROMPT_COMMAND="_nlc_history_import\${PROMPT_COMMAND:+;\$PROMPT_COMMAND}" ;;
esac
$HOOK_END
HOOK
    info "已注入 bash 钩子到 ~/.bashrc：新终端里可直接输入中文调用（当前终端执行：source ~/.bashrc）"

# 7. 自检（模拟新终端环境验证）
if PATH="$BIN_DIR:$PATH" "$BIN_DIR/$APP_NAME" --version >/dev/null 2>&1; then
    info "安装成功！重新登录或执行 source ~/.bashrc 后即可使用："
    echo "    1) 输入 $APP_NAME 进入交互模式（别名 nlc）"
    echo "    2) 任意提示符下直接输入自然语言"
    if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
        echo "    （当前终端 PATH 尚未刷新，请先执行：source ~/.bashrc）"
    fi
else
    error "安装自检失败，请检查上方输出"
    exit 1
fi
