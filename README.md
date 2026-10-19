<div align="center">

# nlcmd

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

- Linux（Debian / Ubuntu / CentOS / Rocky / openEuler 等）
- Python ≥ 3.7（无系统级编译依赖）
- 纯 SSH 终端可用，无需 GUI

## 安装

### 方式一：一键脚本（推荐）

```bash
bash install.sh          # 源码安装（在本仓库目录内）
nlc                      # 启动，首次运行进入配置向导
```

脚本会自动创建独立虚拟环境，并把 `nlcmd`（及别名 `nlc`）软链接到 `~/.local/bin`，不污染系统 Python。

> 若提示 `~/.local/bin` 不在 PATH，请执行：
> ```bash
> echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
> ```

### 方式二：pipx

```bash
pipx install nlcmd       # 发布到 PyPI 后可用
```

### 卸载

```bash
bash uninstall.sh                # 卸载程序（保留配置）
bash uninstall.sh --purge        # 卸载程序 + 配置 + 历史
```

## 快速开始

**方式一：免启动直输（推荐，仿 AI Shell 体验）**

安装后 bash 钩子自动注入 `~/.bashrc`（新终端生效），在任意提示符下直接输入：

```bash
[root@server ~]# 查看当前所有进程占用内存的情况
# → AI 生成候选 → 选择/编辑 → 执行 → 自动输出 AI 结果分析
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

## 配置

配置文件：`~/.config/nlcmd/config.toml`（权限 0600）

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
│   ├── memory.py     # 跨会话记忆
│   ├── security.py   # 本地风险检测
│   ├── diagnose.py   # 失败诊断
│   └── ...
├── docs/             # 需求与设计文档
├── tests/            # 单元测试
├── install.sh        # 一键安装
└── uninstall.sh      # 卸载
```

## 文档

- [需求文档](docs/requirements.md)
- [设计文档](docs/design.md)

## 许可证

[MIT](LICENSE) © nlcmd contributors

---

<div align="center">如果本项目对你有帮助，欢迎 ⭐ Star 或提交 PR。</div>