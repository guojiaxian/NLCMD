# nlcmd 设计文档

| 项目 | 内容 |
| --- | --- |
| 对应需求 | docs/requirements.md v1.0 |
| 技术路线 | Python 3.7+（已与用户确认） |
| 日期 | 2026-08-21 |

## 1. 总体架构

三层架构：交互层（终端 UI）→ 业务层（生成编排、执行、安全）→ 服务层（配置、LLM HTTP 客户端）。

```
┌─────────────────────────────────────────────────────┐
│                 交互层  cli.py / ui.py / editor.py    │
│     REPL 主循环 · 欢迎页 · 候选面板 · 选择 · 编辑行      │
└──────────────┬──────────────────────────┬────────────┘
               │                          │
┌──────────────▼───────────┐   ┌──────────▼─────────────┐
│ 业务层：命令生成编排         │   │ 业务层：命令执行          │
│  llm.py + parser.py      │   │  executor.py            │
│  (调用模型→解析候选)        │   │  security.py (风险校验)  │
└──────────────┬───────────┘   └──────────▲─────────────┘
               │                          │
┌──────────────▼──────────────────────────┴─────────────┐
│                 服务层                                  │
│   config.py / presets.py   配置管理与预设模板             │
│   llm.py                   OpenAI 兼容 HTTP 客户端       │
└───────────────────────────────────────────────────────┘
```

### 1.1 核心状态机

```
INPUT ──输入自然语言──▶ GENERATING(动画) ──解析成功──▶ SELECTING(候选列表)
  ▲                        │ 解析失败/为空              │ 回车/序号/多选/a
  │                        ▼                          ▼
  │                    ERROR 提示              EDITING(可编辑命令行)
  │                                                   │ 回车
  │                              dangerous ◀─风险评估──┤
  │                                │                   │ safe/medium
  │                                ▼                   ▼
  ◀──── Esc/q 取消 ◀──── RESULT(输出+退出码) ◀── EXECUTING(流式输出)
```

## 2. 技术选型（已确认）

| 领域 | 选型 | 理由 | 备选 |
| --- | --- | --- | --- |
| 语言 | Python 3.7+ | 生态成熟；prompt_toolkit 提供"预填充可编辑行"，完美匹配"指令可修改"需求；pip/pipx 部署简单（已与用户确认，备选 Go/Node.js） | Go（单二进制，但交互组件开发量大）、Node.js |
| 终端交互 | prompt_toolkit 3.x | 可编辑输入行、历史、按键绑定 | curses（太底层） |
| 终端渲染 | rich | 面板/颜色/表格/spinner | plain print |
| HTTP | httpx | 同步用法简洁、超时控制好 | requests |
| 配置 | TOML（tomli / tomli-w，Python 3.11+ 用内置 tomllib） | 可注释、可手工编辑 | JSON（无注释）、INI（嵌套弱） |
| 打包 | pyproject.toml + pip / pipx | 标准化 | setup.py |

依赖清单：`prompt_toolkit>=3.0,<4`、`rich>=12,<14`、`httpx>=0.23,<0.26`、`tomli>=1.1,<3; python_version<"3.11"`、`tomli-w>=1`。

## 3. 交互流程与界面原型

### 3.1 主循环（cli.py）

```text
启动 → 加载配置(无则进入向导) → 打印欢迎面板
loop:
  user_input = 编辑行提示 "nl> "
  空输入            → continue
  /xxx              → 分发内置命令
  !!xxx             → 直接作为 shell 命令进入编辑行（逃生舱）
  自然语言           → 调用 LLM → 展示候选 → 选择 → 编辑 → 风险校验 → 执行 → 回显结果
```

### 3.2 界面原型

```
╭──────────────────────────────────────────────────────╮
│  nlcmd v1.0.0  自然语言 → Shell 命令                   │
│  模型: deepseek-chat @ DeepSeek      /help 查看帮助    │
╰──────────────────────────────────────────────────────╯

nl> 查询根目录下名字中包含vscode的文件
⠋ 正在思考...

┃ 生成 2 个候选命令:
┃
┃  [1] 🟢 find / -iname "*vscode*" 2>/dev/null
┃      └─ 全盘查找文件名包含 vscode 的文件（忽略权限报错）
┃  [2] 🟢 find / -maxdepth 4 -iname "*vscode*" 2>/dev/null
┃      └─ 限定深度查找，速度更快
┃
┃ 回车=执行[1] │ 序号单选(2) │ 多选(1,2) │ a=全部 │ e=编辑 │ q=取消

执行> find / -iname "*vscode*" 2>/dev/null        ← 预填充，可直接修改
（回车执行，Esc 取消）

/usr/share/code/vscode
/usr/share/applications/code.desktop
...
✓ 完成 · 退出码 0 · 耗时 3.2s

nl>
```

多选（`1,2` 或 `a`）时：候选按序进入编辑行逐条确认执行；也可在编辑行内用换行合并为一段脚本一次执行（v1 采用**逐条确认**，更安全）。

### 3.3 危险命令警示原型

```
╭─ ⚠ 危险操作 ─────────────────────────────────────────╮
│  rm -rf /var/log                                     │
│  该命令不可逆，可能删除重要数据！                         │
│  确认执行请输入 yes，其他任意键取消:                     │
╰──────────────────────────────────────────────────────╯
```

## 4. 模块设计

### 4.1 cli.py — 入口与主循环

- `main()`：解析命令行参数（`-p/--provider`、`-m/--model`、`-c/--config`、`--no-color`、`--version`）
- REPL 循环、内置命令分发（`/help` `/exit` `/config` `/model` `/provider` `/history`）、`!!` 逃生舱

### 4.2 ui.py — 渲染

| 函数 | 职责 |
| --- | --- |
| `render_welcome(cfg)` | 欢迎面板（版本、当前模型） |
| `render_candidates(cands)` | 候选编号面板（颜色随风险等级） |
| `prompt_select(n)` | 选择提示（回车/序号/多选/a/e/q），循环直到合法输入 |
| `confirm_dangerous(cmd)` | 危险命令二次确认（输入 yes） |
| `render_result(res)` | 执行结果（退出码、耗时、中断标记） |

### 4.3 editor.py — 可编辑命令行

基于 `prompt_toolkit.PromptSession`：

```python
def edit_command(default: str, session: PromptSession) -> str | None:
    """预填充 default 的可编辑行；回车返回编辑后内容，Esc 返回 None"""
```

- `session.prompt("执行> ", default=cmd)` 实现预填充编辑
- Esc 键绑定：返回 None（取消）

### 4.4 llm.py — OpenAI 兼容客户端

```python
class LLMClient:
    def __init__(self, cfg: ProviderConfig): ...      # api_base/api_key/model/timeout
    def chat(self, messages: list[dict], *, temperature: float = 0.2) -> str
    def test_connection(self) -> tuple[bool, str]      # 发送最小请求验证连通性与鉴权
```

- 统一走 `POST {api_base}/chat/completions`（OpenAI 兼容格式，DeepSeek/GLM/Qwen/Kimi 及自定义接口均兼容）
- 异常分类：超时 / 401 / 403 / 429 / 5xx / 其他，向上抛带建议文案的 `LLMError`

### 4.5 prompts.py — 系统提示词

```python
SYSTEM_PROMPT = """你是一名资深 Linux 系统工程师和 shell 专家。用户会用自然语言描述
想在 Linux 服务器上完成的操作，你的任务是生成对应的 bash 命令。

规则：
1. 返回 1~3 个候选命令，按推荐程度从高到低排列。
2. 命令必须准确、完整、可直接在 bash 中执行，注意转义。
3. description 用一句话中文解释命令作用。
4. risk 评估命令风险：safe=只读无副作用；medium=会修改文件/进程/配置但影响可控；
   dangerous=不可逆、破坏性或影响系统运行。
5. 对耗时操作（如全盘 find）尽量给出更快的替代候选。
6. 当前系统：{os_info}。优先使用普遍预装的工具。
7. 仅输出如下 JSON，不要输出任何其他内容（包括 markdown 代码块标记）：
{"commands":[{"command":"...","description":"...","risk":"safe"}]}
8. 若用户输入与"在 Linux 上执行操作"无关（如打招呼、闲聊），输出：
{"commands":[]}"""
```

`{os_info}` 启动时采集一次：`uname -a` + 发行版 + 默认 shell。

### 4.6 parser.py — 候选解析（含容错）

```python
@dataclass
class Candidate:
    command: str
    description: str
    risk: str          # safe | medium | dangerous

def parse_candidates(raw: str) -> list[Candidate]
```

解析策略（层层兜底）：

1. 去除首尾空白与 ```json ... ``` 围栏
2. 截取首个 `{` 到末个 `}` 的子串，`json.loads`
3. 校验结构（commands 数组、字段类型、risk 枚举非法值归一为 medium）
4. 失败 → 追加一条纠错消息让模型重新只输出 JSON，**重试 1 次**
5. 仍失败 → 正则提取 `"command"\s*:\s*"(...)"` 兜底；再失败则抛 `ParseError`

### 4.7 executor.py — 命令执行

```python
@dataclass
class ExecResult:
    exit_code: int
    duration: float
    interrupted: bool   # 被 Ctrl+C 或超时终止

def run_command(cmd: str, *, timeout: float, console) -> ExecResult
```

- `subprocess.Popen(["bash", "-c", cmd], stdout=PIPE, stderr=STDOUT, text=True, start_new_session=True)`
- 逐行读取并实时 `console.print`（流式回显）
- 超时：`os.killpg(SIGKILL)` 整个进程组
- Ctrl+C：捕获 KeyboardInterrupt → `killpg(SIGINT)` → 标记 interrupted
- 多条命令：顺序执行；非 0 退出码时询问 `继续执行下一条? [y/N]`

### 4.8 security.py — 本地风险评估（独立于模型）

```python
DANGEROUS_PATTERNS = [
    r"\brm\s+[^|;&]*\s-r[a-zA-Z]*f?[a-zA-Z]*\s+(/|~|\$HOME)\b",   # rm -rf / ~
    r"\bmkfs(\.\w+)?\b",                                            # 格式化
    r"\bdd\b[^|]*\bof=/dev/",                                       # dd 写设备
    r":\(\)\s*\{.*\};\s*:",                                         # fork 炸弹
    r">\s*/dev/sd[a-z]",                                            # 覆盖磁盘设备
    r"\b(shutdown|reboot|halt|poweroff)\b|\binit\s+[06]\b",
    r"\bchmod\s+-R\s+[0-7]*7[0-7]*\s+/(etc|usr|var|boot)?\s*$",     # chmod -R 777 /
    r"(curl|wget)[^|]*\|\s*(ba)?sh\b",                              # 远程脚本直执行
    r">\s*/etc/(passwd|shadow|sudoers|fstab)\b",                    # 覆盖系统文件
]
MEDIUM_PATTERNS = [...]   # rm(非根)、mv 覆盖、systemctl restart/stop、pkill、包管理器 install 等

def assess_risk(cmd: str) -> str   # dangerous > medium > safe；与模型标注取更高级别
```

### 4.9 presets.py — 预设模板

| key | 名称 | api_base | 默认模型 | 说明 |
| --- | --- | --- | --- | --- |
| deepseek | DeepSeek | `https://api.deepseek.com` | `deepseek-chat` | 推荐默认 |
| glm | GLM（智谱） | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | flash 免费额度 |
| qwen | 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | |
| kimi | Kimi（月之暗面） | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | |
| custom | 自定义 | 用户填写 | 用户填写 | 任意 OpenAI 兼容接口 |

> 注：OpenAI / Ollama 模板未纳入 v1 预设（已与用户确认：国内四家 + 自定义），如需接入可经 custom 模板配置。

### 4.10 config.py — 配置管理与向导

```python
class Config:
    @staticmethod load(path) -> Config          # 不存在返回 None
    def save(path)                              # 写 TOML，chmod 0600
    def run_wizard(console) -> Config           # 首次配置向导
```

配置文件：`~/.config/nlcmd/config.toml`（可用 `NLCMD_CONFIG` 或 `-c` 覆盖）。

```toml
[general]
default_provider = "deepseek"
timeout = 30          # LLM 请求超时(秒)
exec_timeout = 600    # 命令执行超时(秒)，0=不限
history_size = 200

[providers.deepseek]
api_base = "https://api.deepseek.com"
api_key  = "sk-xxxx"          # 环境变量 NLCMD_API_KEY / DEEPSEEK_API_KEY 优先
model    = "deepseek-chat"
```

**优先级**：命令行参数 > 环境变量（`NLCMD_API_KEY`、`DEEPSEEK_API_KEY` 等）> 配置文件 > 预设默认值。

向导流程：选服务商（编号列表）→ 显示该模板默认 api_base/model（可回车跳过/输入覆盖）→ 输入 API Key（检测到环境变量时自动复用；custom 允许为空）→ 询问是否测试连接（发送"回复 ok"最小请求）→ 成功写入配置。

## 5. 错误处理

| 场景 | 用户看到的提示 | 行为 |
| --- | --- | --- |
| 连接超时/网络错误 | 红色：连接失败，请检查网络或 api_base | 回到输入 |
| 401/403 | Key 无效或无权限，可用 /config 重新配置 | 回到输入 |
| 429 | 触发限流，请稍后重试 | 回到输入 |
| 5xx | 服务端错误 | 回到输入 |
| JSON 解析失败 | 自动重试 1 次；仍失败提示重述需求 | 回到输入 |
| commands 为空 | "该输入似乎与执行命令无关，请描述想在 Linux 上完成的操作" | 回到输入 |
| 执行超时 | 已超时终止（N 秒） | 回到输入 |
| 退出码 127 | 提示：命令未安装或不在 PATH | 正常回显 |

## 6. 部署设计

### 6.1 三种安装方式

```bash
# 方式一：一键脚本（推荐）
curl -fsSL https://<仓库地址>/install.sh | bash

# 方式二：pipx
pipx install nlcmd

# 方式三：源码
git clone <仓库地址> && cd nlcmd && bash install.sh
```

### 6.2 install.sh 流程

1. 检测 `python3` 存在且 ≥ 3.7（缺失时给出各发行版安装命令）
2. `python3 -m venv ~/.local/share/nlcmd/venv`
3. venv 内 `pip install .`（源码运行）或 `pip install nlcmd`（发布后）
4. `ln -sf ~/.local/share/nlcmd/venv/bin/nlcmd ~/.local/bin/nlcmd`
5. 检查 `~/.local/bin` 是否在 PATH，不在则提示向 `~/.bashrc` 追加一行
6. 执行 `nlcmd --version` 自检并输出成功提示

卸载：`rm -rf ~/.local/share/nlcmd ~/.local/bin/nlcmd ~/.config/nlcmd`（提供 uninstall.sh）。

## 7. 项目结构

```
nlcmd/
├── pyproject.toml
├── README.md
├── install.sh
├── uninstall.sh
├── docs/
│   ├── requirements.md
│   └── design.md
├── src/nlcmd/
│   ├── __init__.py      # __version__
│   ├── __main__.py      # python -m nlcmd
│   ├── cli.py           # 参数解析 + REPL + 内置命令
│   ├── ui.py            # 欢迎页/候选面板/选择/确认/结果渲染
│   ├── editor.py        # 预填充可编辑命令行
│   ├── llm.py           # OpenAI 兼容 HTTP 客户端
│   ├── prompts.py       # 系统提示词
│   ├── parser.py        # LLM 输出解析与校验
│   ├── executor.py      # 子进程执行/流式输出/超时/信号
│   ├── security.py      # 危险模式检测
│   ├── config.py        # 配置读写 + 向导
│   └── presets.py       # 预设模板定义
└── tests/
    ├── test_parser.py     # 正常/围栏/非法 JSON/空 commands
    ├── test_security.py   # 各危险/中险模式命中
    ├── test_config.py     # 读写 roundtrip、环境变量优先级
    └── test_presets.py    # 模板字段完整性
```

## 8. 测试计划

- **单元测试**（pytest，CI 本地跑）：parser 容错矩阵、security 模式命中、config roundtrip、presets 完整性
- **集成测试**：mock LLM 返回（正常 JSON / 围栏 JSON / 非法），驱动主流程状态机
- **手工验收**：按需求文档 §6 的 6 个端到端场景，用真实 API 各跑一遍

## 9. 里程碑

| 阶段 | 内容 | 交付物 |
| --- | --- | --- |
| M1 | 骨架 + 配置/向导 + LLM 客户端 + 预设 | 可配置、可测连通 |
| M2 | REPL + 生成/解析 + 选择/编辑/执行全链路 | 核心功能可用 |
| M3 | 安全拦截 + 内置命令 + 历史 + 错误处理 | 功能完整 |
| M4 | install.sh + README + 测试收尾 | 可交付 v1.0 |

## 10. v2 展望（非本期范围）

- `nlcmd -e "..."` 非交互模式（仅生成打印，不执行）
- `/explain` 命令逐段解释
- 命令补全与语法高亮
- 对话上下文（"再按时间排序"式追问）
- 插件机制、本地 man 手册检索增强
