<div align="center">

# NLCMD

**自然语言 → Shell 命令的终端助手**

在 Linux 终端里用自然语言描述你想做的操作，大模型生成候选 shell 命令，**经你确认或修改后**才执行。

[![Python](https://img.shields.io/badge/Python-3.7%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux_Debian%20%7C%20Ubuntu%20%7C%20CentOS%20%7C%20Rocky-blue)](https://github.com)
[![License](https://img.shields.io/github/license/your-org/nlcmd)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com)

</div>

```

nl> 查询根目录下名字中包含vscode的文件

╭───────────────────────────────────────────────── 生成 2 个候选命令 ─────────────────────────────────────────────────╮
│                                                                                                             │
│   [1] 🟢 find / -iname "*vscode*" 2>/dev/null                                                               │
│       └─ 全盘查找文件名包含 vscode 的文件（忽略权限报错）                                                     │
│   [2] 🟢 find / -maxdepth 4 -iname "*vscode*" 2>/dev/null                                                   │
│       └─ 限定深度查找，速度更快                                                                               │
│                                                                                                             │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
回车=执行[1] │ 序号单选(2) │ 多选(1,2) │ a=全部 │ e=编辑 │ q=取消

执行> find / -iname "*vscode*" 2>/dev/null    ← 预填充，可直接修改，回车执行

✓ 完成 · 退出码 0 · 耗时 3.2s
```

## 目录

- [特性](#特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [使用](#使用)
- [命令行快捷配置](#命令行快捷配置)
- [配置](#配置)
- [安全说明](#安全说明)
- [开发](#开发)
- [文档](#文档)
- [许可证](#许可证)

## 特性

- 🗣️ **自然语言生成命令**：中/英文描述意图，生成 1~3 个候选命令（含说明与风险标记）
- ✅ **人工确认可控**：命令先进入可编辑行（预填充），可修改后回车执行，Esc 取消
- 🔢 **多候选多选**：`1`、`1,3` 多选、`a` 全部，按顺序逐条确认执行
- 🛡️ **安全防护**：本地规则独立二次评估风险；`rm -rf /` 等危险命令需输入 `yes` 二次确认
- ⏩ **流式输出**：命令输出实时回显，支持超时（默认 600s）与 `Ctrl+C` 中断
- 🔧 **失败诊断与自动修复**：命令失败后离线给出原因建议，可一键交给模型生成修正命令
- 🧠 **跨会话记忆**：记住上次会话的意图与执行结果，可直接接续（如"再按文件大小排序"）
- 📊 **AI 结果分析**：命令执行成功后自动分析输出，给出"结果解读 / 结论 / 建议"结构化总结
- 💬 **免启动调用**：安装时注入 bash 钩子，在任意 shell 提示符下直接输入中文即可（无需先打开程序）
- 📜 **脚本编写**：一句"写一个 xx 脚本"，自动在当前目录创建对应文件
- 🏢 **预设模型模板**：DeepSeek、GLM（智谱）、通义千问、Kimi，以及任意自定义 OpenAI 兼容接口
- 🚀 **一键部署**：`bash install.sh` 即可，仅依赖 Python 3.7+

## 环境要求

- Linux（Debian / Ubuntu / CentOS / Rocky / openEuler / 麒麟等）
- Python ≥ 3.7（无系统级编译依赖）
- 纯 SSH 终端可用，无需 GUI

## 安装

新服务器从零开始，三步完成：**传代码 → 跑安装脚本 → 配置 Key**。

### 第 1 步：把项目传到服务器

```bash
git clone https://github.com/guojiaxian/NLCMD.git
cd nlcmd
```

### 第 2 步：执行安装脚本

```bash
bash install.sh
```

脚本自动完成：创建独立 venv（`~/.local/share/nlcmd`）→ 安装依赖 → 软链接 `nlcmd`/`nlc` 到 `~/.local/bin` → 注入 bash 钩子到 `~/.bashrc` → 自检，不污染系统 Python。

**唯一前置要求**：Python 3.7+。极简系统镜像可能缺组件，缺什么装什么：

```bash
# CentOS / Rocky / 麒麟（一般已自带）
dnf install -y python3 python3-pip

# Debian / Ubuntu 最小镜像
apt install -y python3 python3-pip python3-venv
```

### 第 3 步：生效并配置

```bash
source ~/.bashrc          # 让钩子和 PATH 立即生效（或直接开新终端）
nlcmd                     # 首次运行进入配置向导
```

向导里选服务商（如 DeepSeek）→ 粘贴 API Key → 回车测试连通 → 完成。

### 卸载

```bash
bash uninstall.sh                # 卸载程序（保留配置）
bash uninstall.sh --purge        # 卸载程序 + 配置 + 历史
```

### 常见问题

- **提示 `nlcmd: 未找到命令`**：PATH 未包含 `~/.local/bin`，执行
  `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc`
- **直接输入中文没有反应**：钩子未生效，执行 `source ~/.bashrc` 或重开终端；确认 `~/.bashrc` 中有 `NLCMD_HOOK` 标记
- **按 ↑ 看不到 nlcmd 执行过的命令**：旧版钩子不含历史导入，重新执行 `bash install.sh`（会自动替换旧钩子）后 `source ~/.bashrc`；历史文件在 `~/.local/state/nlcmd/shell_history`
- **API 返回 404**：检查 `api_base` 是否只填了根路径（如 `https://api.deepseek.com`），不要带 `/chat/completions` 后缀

## 快速开始

**方式一：免启动直输（推荐，仿 AI Shell 体验）**

安装后 bash 钩子自动注入 `~/.bashrc`（新终端生效），在任意提示符下直接输入：

```bash
[root@server ~]# 查看当前所有进程占用内存的情况
# → AI 生成候选 → 选择/编辑 → 执行 → 自动输出 AI 结果分析
# 执行过的命令会自动进入 bash 历史，按 ↑ 键可随时调出
```

**方式二：交互模式**

```bash
nlc                       # 启动（或使用 nlcmd）
> 查询根目录下名字中包含vscode的文件
> 1                        # 选择 [1] 号候选
> （编辑命令后回车执行，随后自动展示 AI 结果分析）
```

**方式三：一次性子命令**

```bash
nlcmd run 查看当前所有进程占用内存的情况
```

首次运行会进入**配置向导**：选择服务商 → 填写 API Key → 一键测试连通。

## 使用

```bash
nlcmd                # 启动（自动进入配置向导）
nlcmd -p glm         # 指定服务商启动
nlcmd -m glm-4.5     # 指定模型启动
nlcmd run <自然语言>  # 一次性模式：生成 → 执行 → 分析后退出
nlc --version
```

| 输入 | 作用 |
| --- | --- |
| （自然语言） | 生成候选命令 |
| `回车` / `1` / `1,2` / `a` | 选择候选（默认第 1 条 / 单选 / 多选 / 全部） |
| `q`、`Esc` | 取消 |
| `!!<命令>` | 跳过生成，直接编辑执行 shell 命令 |
| `/help` | 显示帮助 |
| `/model`、`/provider` | 查看/切换模型、服务商 |
| `/config` | 重新运行配置向导 |
| `/history` | 查看本次会话已执行的命令 |
| `/exit`、Ctrl+D | 退出 |

## 命令行快捷配置

不进入交互模式，直接用 `nlcmd config` 子命令完成常用设置（改完立即生效，下次启动即用新配置）：

```bash
nlcmd config show                              # 查看当前配置（API Key 自动脱敏）
nlcmd config set auto_analyze false            # 关闭 AI 自动分析执行结果
nlcmd config set auto_analyze true             # 重新开启
nlcmd config set providers.deepseek.api_key sk-xxxx   # 设置/更换 API Key
nlcmd config set providers.deepseek.model deepseek-flash
nlcmd config set default_provider glm          # 切换默认服务商（预设字段自动初始化）
nlcmd config set timeout 60                    # LLM 请求超时（秒）
nlcmd config set exec_timeout 300              # 命令执行超时（秒）
nlcmd config set providers.myproxy.api_base https://proxy.example.com/v4   # 自定义服务商
nlcmd config test                              # 一键测试当前服务商连通性
nlcmd config test glm                          # 测试指定服务商
nlcmd config edit                              # 用系统编辑器打开配置文件（自带中文备注）
nlcmd config wizard                            # 改用交互式向导
nlcmd config --help                            # 查看全部可配置项
```

布尔值支持 `true/false`、`on/off`、`1/0`、`开/关`。

> `config edit` 按 `$EDITOR`/`$VISUAL` 选择编辑器（缺省依次尝试 vi/vim/nano）；
> 配置文件不存在时会先生成一份带中文备注的默认模板。所有配置文件均自带逐项中文注释。

## 配置

配置文件：`~/.config/nlcmd/config.toml`（权限 0600，自带逐项中文备注；推荐用上面的 [命令行快捷配置](#命令行快捷配置) 修改，也可 `nlcmd config edit` 直接编辑）：

```toml
[general]
default_provider = "deepseek"
timeout = 30          # LLM 请求超时(秒)
exec_timeout = 600    # 命令执行超时(秒)，0 = 不限
history_size = 200
auto_analyze = true   # 命令执行成功后自动 AI 分析输出

[providers.deepseek]
api_base = "https://api.deepseek.com"
api_key  = "sk-xxxx"
model    = "deepseek-flash"
disable_thinking = true   # 关闭思考模式以加速（DeepSeek V4+）
```

**API Key 优先级**：环境变量 `NLCMD_API_KEY` > 服务商专属变量（`DEEPSEEK_API_KEY` / `ZHIPU_API_KEY` / `DASHSCOPE_API_KEY` / `MOONSHOT_API_KEY`）> 配置文件。

### 预设服务商

| Key | 名称 | 默认模型 |
| --- | --- | --- |
| `deepseek` | DeepSeek | `deepseek-flash`（默认关闭思考模式加速） |
| `glm` | GLM（智谱） | `glm-4-flash` |
| `qwen` | 通义千问 | `qwen-plus` |
| `kimi` | Kimi（月之暗面） | `moonshot-v1-8k` |
| `custom` | 自定义（任意 OpenAI 兼容接口） | 用户填写 |

## 安全说明

- 所有命令必须经过编辑行**人工确认**，绝不自动执行
- 危险命令（`rm -rf /`、`mkfs`、`dd of=/dev/*`、远程脚本直执行等）由本地规则**二次拦截**，需输入 `yes` 才能执行
- 命令以当前用户权限在 `bash -c` 中运行，超时自动终止进程组
- API Key 只会写入权限为 0600 的配置文件，绝不写入日志

## 开发

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e . pytest
pytest tests/ -q
```

项目结构：

```
nlcmd/
├── src/nlcmd/        # 源码
│   ├── cli.py        # 入口与 REPL 主循环
│   ├── analyze.py    # AI 结果分析
│   ├── memory.py     # 跨会话记忆
│   ├── security.py   # 本地风险检测
│   ├── diagnose.py   # 失败诊断
│   └── ...
├── docs/             # 需求与设计文档
├── tests/            # 单元测试
├── install.sh        # 一键安装（含 bash 钩子注入）
└── uninstall.sh      # 卸载（含钩子清理）
```

## 文档

- [需求文档](docs/requirements.md)
- [设计文档](docs/design.md)

## 许可证

[MIT](LICENSE) © nlcmd contributors

---

<div align="center">如果本项目对你有帮助，欢迎 ⭐ Star 或提交 PR。</div>