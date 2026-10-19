"""nlcmd 入口：参数解析、REPL 主循环、内置命令。"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Deque, List, Optional, Tuple

from prompt_toolkit import PromptSession, prompt as pt_prompt
from prompt_toolkit.history import FileHistory
from rich import box
from rich.console import Console
from rich.table import Table

from . import __version__
from .analyze import build_analysis_messages
from .config import (
    Config,
    ProviderConfig,
    create_template,
    default_config_path,
    effective_api_key,
    run_wizard,
)
from .presets import PRESETS
from .diagnose import is_failure, match_error
from .editor import edit_command
from .executor import run_command
from .llm import LLMClient, LLMError
from .memory import Memory, default_memory_path
from .parser import Candidate, ParseError, parse_candidates
from .presets import PRESETS
from .prompts import build_fix_prompt, build_system_prompt
from .security import assess_risk, combine_risk
from .ui import (
    Selection,
    confirm_dangerous,
    prompt_select,
    render_analysis,
    render_candidates,
    render_error,
    render_help,
    render_result,
    render_welcome,
)


def default_state_dir() -> Path:
    if os.environ.get("NLCMD_STATE_DIR"):
        return Path(os.environ["NLCMD_STATE_DIR"])
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "nlcmd"


SHELL_HISTORY_FILE = "shell_history"


def record_shell_history(cmd: str, state_dir: Optional[Path] = None) -> None:
    """把执行过的命令追加到历史文件，供 bash PROMPT_COMMAND 导入上键历史。

    多行命令（如 heredoc 脚本）中的换行转义为字面 \\n，保证一行一条；
    导入失败静默忽略，绝不能影响命令执行主流程。
    """
    try:
        d = state_dir or default_state_dir()
        d.mkdir(parents=True, exist_ok=True)
        line = (cmd or "").replace("\r", "").strip()
        if not line:
            return
        line = line.replace("\n", "\\n")  # 多行命令转义为字面 \n，一行一条
        with open(d / SHELL_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


@dataclass
class Runtime:
    console: Console
    cfg: Config
    config_path: Path
    provider: str
    model: str
    client: LLMClient
    session: PromptSession
    editor_session: PromptSession
    exec_history: Deque[Tuple[str, str, int]] = field(default_factory=deque)
    memory: Optional["Memory"] = None     # 跨会话记忆
    pending_query: Optional[str] = None   # 当前提问（供执行后记入记忆）
    pending_cmds: List[str] = field(default_factory=list)


def _build_client(cfg: Config, provider: str, model: Optional[str] = None) -> LLMClient:
    pc = cfg.providers[provider]
    return LLMClient(
        api_base=pc.api_base,
        api_key=effective_api_key(provider, pc),
        model=model or pc.model,
        timeout=cfg.timeout,
        name=provider,
        disable_thinking=pc.disable_thinking,
    )


def _provider_label(cfg: Config, provider: str, model: str) -> str:
    preset = PRESETS.get(provider)
    name = preset.name if preset else provider
    return "{} @ {}".format(model, name)


def _split_run_args(argv: List[str]) -> Optional[str]:
    """从 argv 中剥离一次性子命令 `run <查询>`，返回查询文本（无则 None）。

    `run` 必须是第一个非选项参数；其后所有参数（含 - 开头者）都视为查询文本，
    全局选项需写在 run 之前，如：nlcmd -p glm run 查看进程内存占用。
    """
    value_flags = {"-p", "--provider", "-m", "--model", "-c", "--config"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in value_flags:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        if a == "run":
            query = " ".join(argv[i + 1:]).strip()
            del argv[i:]
            return query or None
        break  # 其他位置参数交给 argparse 报错
    return None


CONFIG_USAGE = """[bold]nlcmd config[/bold] — 命令行快捷配置

用法：
  nlcmd config show                     查看当前配置（API Key 自动脱敏）
  nlcmd config set <键> <值>            设置配置项
  nlcmd config test [服务商]            测试连通（默认当前服务商）
  nlcmd config edit                     用系统编辑器打开配置文件（文件自带中文备注）
  nlcmd config wizard                   交互式配置向导

可设置的键：
  default_provider                      默认服务商（如 deepseek / glm / qwen / kimi）
  timeout / exec_timeout                LLM 超时 / 命令执行超时（秒）
  history_size                          历史记录条数
  auto_analyze                          是否自动 AI 分析结果（true/false）
  providers.<名称>.api_base             接口根路径（不带 /chat/completions）
  providers.<名称>.api_key              API Key
  providers.<名称>.model                模型名
  providers.<名称>.disable_thinking     关闭思考模式加速（true/false）

示例：
  nlcmd config set auto_analyze false
  nlcmd config set providers.deepseek.api_key sk-xxxx
  nlcmd config set default_provider glm
  nlcmd -c /path/config.toml config show
"""


def _split_config_args(argv: List[str]) -> Optional[List[str]]:
    """识别首位置参数 `config`，返回其后的子命令参数（无则 None）。全局选项需写在 config 之前。"""
    i = 0
    value_flags = {"-p", "--provider", "-m", "--model", "-c", "--config"}
    while i < len(argv):
        a = argv[i]
        if a in value_flags:
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        if a == "config":
            rest = argv[i + 1:]
            del argv[i:]
            return rest
        break
    return None


def _coerce_bool(val: str) -> Optional[bool]:
    v = val.strip().lower()
    if v in ("1", "true", "yes", "on", "y", "开", "开启"):
        return True
    if v in ("0", "false", "no", "off", "n", "关", "关闭"):
        return False
    return None


def _mask_key(key: str) -> str:
    if not key:
        return "（未设置）"
    if len(key) <= 10:
        return "****"
    return key[:6] + "****" + key[-4:]


def _new_provider(name: str) -> tuple:
    """按预设创建服务商配置；未知名称则新建空的自定义服务商。"""
    preset = PRESETS.get(name)
    if preset:
        return ProviderConfig(
            api_base=preset.api_base, model=preset.model,
            disable_thinking=preset.disable_thinking,
        ), "（已按 {} 预设模板初始化）".format(preset.name)
    return ProviderConfig(), "（新建自定义服务商）"


def _config_edit(console: Console, config_path: Path) -> int:
    """用系统编辑器打开配置文件；文件不存在时先生成带备注的模板。"""
    if not config_path.is_file():
        create_template(config_path)
        console.print("[green]已生成默认配置模板：[/green]{}".format(config_path))

    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        for cand in ("vi", "vim", "nano"):
            if shutil.which(cand):
                editor = cand
                break
    if not editor:
        console.print("[red]未找到可用编辑器。[/red]请手动编辑：{}".format(config_path))
        console.print("或设置环境变量，如：[bold]export EDITOR=vim[/bold]")
        return 1

    console.print("[dim]正在打开 {}（编辑器：{}）...[/dim]".format(config_path, editor))
    rc = subprocess.call(shlex.split(editor) + [str(config_path)])
    if rc == 0:
        console.print("[green]✓ 编辑完成[/green]，配置将在下次启动 nlcmd 时生效。")
        console.print("可执行 [bold]nlcmd config test[/bold] 验证连通性。")
    else:
        console.print("[yellow]编辑器退出码 {}，配置未确认保存。[/yellow]".format(rc))
    return rc


def _handle_config(rest: List[str], console: Console, config_path: Path) -> int:
    """处理 `nlcmd config ...` 子命令，无需进入交互模式即可完成配置。"""
    action = rest[0] if rest else "show"

    if action in ("-h", "--help", "help"):
        console.print(CONFIG_USAGE)
        return 0

    if action == "wizard":
        cfg = run_wizard(console, config_path)
        return 0 if cfg else 1

    if action == "edit":
        return _config_edit(console, config_path)

    cfg = Config.load(config_path)

    if action == "show":
        if cfg is None:
            console.print("[yellow]尚未配置。[/yellow]运行 [bold]nlcmd config wizard[/bold] 开始配置，"
                          "或用 [bold]nlcmd config set providers.<名称>.api_key <key>[/bold] 快速设置。")
            return 1
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        table.add_column("配置项")
        table.add_column("值")
        table.add_row("default_provider", cfg.default_provider)
        table.add_row("timeout", "{}s".format(cfg.timeout))
        table.add_row("exec_timeout", "{}s".format(cfg.exec_timeout))
        table.add_row("history_size", str(cfg.history_size))
        table.add_row("auto_analyze", "开启" if cfg.auto_analyze else "关闭")
        for name, pc in cfg.providers.items():
            preset = PRESETS.get(name)
            label = "{}（{}）".format(name, preset.name) if preset else name
            table.add_row("", "")
            table.add_row("providers.{}".format(label), "")
            table.add_row("  api_base", pc.api_base or "（未设置）")
            table.add_row("  api_key", _mask_key(effective_api_key(name, pc)))
            table.add_row("  model", pc.model or "（未设置）")
            table.add_row("  disable_thinking", str(pc.disable_thinking))
        console.print(table)
        return 0

    if action == "test":
        if cfg is None:
            console.print("[red]尚未配置，无法测试。[/red]先运行 [bold]nlcmd config wizard[/bold]")
            return 1
        name = rest[1] if len(rest) > 1 else cfg.default_provider
        if name not in cfg.providers:
            console.print("[red]未知服务商：{}[/red]（已配置：{}）".format(
                name, ", ".join(cfg.providers)))
            return 1
        pc = cfg.providers[name]
        client = LLMClient(
            api_base=pc.api_base, api_key=effective_api_key(name, pc),
            model=pc.model, timeout=cfg.timeout, name=name,
            disable_thinking=pc.disable_thinking,
        )
        console.print("正在测试 [bold]{}[/bold]（{} / {}）...".format(name, pc.api_base, pc.model))
        ok, msg = client.test_connection()
        if ok:
            console.print("[green]✓ {}[/green]".format(msg or "连接成功"))
            return 0
        console.print("[red]✗ 连接失败[/red] · " + msg)
        return 1

    if action == "set":
        if len(rest) != 3:
            console.print(CONFIG_USAGE)
            return 1
        key, value = rest[1].strip(), rest[2].strip()
        if cfg is None:
            cfg = Config()

        if key.startswith("providers."):
            parts = key.split(".")
            valid_fields = ("api_base", "api_key", "model", "disable_thinking")
            if len(parts) != 3 or parts[2] not in valid_fields:
                console.print("[red]无效的键：{}[/red]".format(key))
                console.print("格式：providers.<名称>.<{}>".format("|".join(valid_fields)))
                return 1
            name, field = parts[1], parts[2]
            if name in cfg.providers:
                pc, note = cfg.providers[name], ""
            else:
                pc, note = _new_provider(name)
            if field == "disable_thinking":
                b = _coerce_bool(value)
                if b is None:
                    console.print("[red]布尔值应为 true/false（或 on/off/1/0）[/red]")
                    return 1
                pc.disable_thinking = b
                shown = str(b)
            else:
                setattr(pc, field, value)
                shown = _mask_key(value) if field == "api_key" else value
            cfg.providers[name] = pc
            cfg.save(config_path)
            console.print("[green]✓ 已保存[/green] {} = {} {}".format(key, shown, note))
            return 0

        if key == "auto_analyze":
            b = _coerce_bool(value)
            if b is None:
                console.print("[red]布尔值应为 true/false（或 on/off/1/0）[/red]")
                return 1
            cfg.auto_analyze = b
            shown = "开启" if b else "关闭"
        elif key in ("timeout", "exec_timeout"):
            try:
                num = float(value)
                assert num >= 0
            except (ValueError, AssertionError):
                console.print("[red]{} 应为非负数字（秒）[/red]".format(key))
                return 1
            setattr(cfg, key, num)
            shown = "{}s".format(num)
        elif key == "history_size":
            try:
                cfg.history_size = int(value)
            except ValueError:
                console.print("[red]history_size 应为整数[/red]")
                return 1
            shown = value
        elif key == "default_provider":
            name = value
            if name not in cfg.providers and name not in PRESETS:
                console.print("[red]未知服务商：{}[/red]（可选：{}）".format(
                    name, ", ".join(PRESETS)))
                return 1
            if name not in cfg.providers:
                pc, note = _new_provider(name)
                cfg.providers[name] = pc
                shown = name + " " + note
            else:
                shown = name
            cfg.default_provider = name
        else:
            console.print("[red]未知的配置键：{}[/red]".format(key))
            console.print(CONFIG_USAGE)
            return 1

        cfg.save(config_path)
        console.print("[green]✓ 已保存[/green] {} = {}".format(key, shown))
        return 0

    console.print(CONFIG_USAGE)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    config_args = _split_config_args(raw_argv)
    one_shot_query = _split_run_args(raw_argv)
    parser = argparse.ArgumentParser(
        prog="nlcmd", description="自然语言 → Shell 命令的终端助手"
    )
    parser.add_argument("-p", "--provider", help="指定服务商（覆盖配置文件）")
    parser.add_argument("-m", "--model", help="指定模型（覆盖配置文件）")
    parser.add_argument("-c", "--config", type=Path, help="指定配置文件路径")
    parser.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args = parser.parse_args(raw_argv)

    console = Console(no_color=args.no_color)
    config_path = args.config if args.config else default_config_path()

    if config_args is not None:
        # 命令行快捷配置：无需进入交互模式，空配置也可直接设置
        return _handle_config(config_args, console, config_path)

    cfg = Config.load(config_path)
    if cfg is None:
        console.print("[yellow]检测到尚未配置，进入首次配置向导[/yellow]\n")
        cfg = run_wizard(console, config_path)
        if cfg is None:
            console.print("[yellow]已取消配置，退出。[/yellow]")
            return 1

    provider = args.provider or cfg.default_provider
    if provider not in cfg.providers:
        console.print(
            "[red]未知的 provider：{}[/red]（已配置：{}）".format(
                provider, ", ".join(cfg.providers) or "无"
            )
        )
        return 1
    model = args.model or cfg.providers[provider].model

    state_dir = default_state_dir()
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    rt = Runtime(
        console=console,
        cfg=cfg,
        config_path=config_path,
        provider=provider,
        model=model,
        client=_build_client(cfg, provider, model),
        session=PromptSession(history=FileHistory(str(state_dir / "input_history"))),
        editor_session=PromptSession(),
        exec_history=deque(maxlen=cfg.history_size),
        memory=Memory.load(default_memory_path(state_dir)),
    )

    if one_shot_query is not None:
        # 一次性模式（供 bash 钩子调用）：处理一条自然语言后退出，不显示欢迎横幅
        _pipeline(rt, one_shot_query)
        return 0

    render_welcome(console, _provider_label(cfg, provider, model), __version__)

    while True:
        try:
            user = rt.session.prompt("nl> ").strip()
        except KeyboardInterrupt:
            console.print("[dim]（Ctrl+C 清空当前输入；Ctrl+D 或 /exit 退出）[/dim]")
            continue
        except EOFError:
            break

        if not user:
            continue
        if user.startswith("/"):
            if _dispatch_builtin(rt, user) == "exit":
                break
            continue
        if user.startswith("!!"):
            _run_direct(rt, user[2:].strip())
            continue
        _pipeline(rt, user)

    console.print("[dim]再见！[/dim]")
    return 0


# ---------------------------------------------------------------- 内置命令


def _dispatch_builtin(rt: Runtime, user: str) -> Optional[str]:
    parts = user.split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if name in ("/exit", "/quit"):
        return "exit"
    if name == "/help":
        render_help(rt.console)
    elif name == "/config":
        _cmd_config(rt)
    elif name == "/model":
        _cmd_model(rt, arg)
    elif name == "/provider":
        _cmd_provider(rt, arg)
    elif name == "/history":
        _cmd_history(rt)
    else:
        rt.console.print(
            "[red]未知命令：{}[/red]，输入 /help 查看可用命令".format(name)
        )
    return None


def _cmd_config(rt: Runtime) -> None:
    console = rt.console
    console.print("[yellow]重新运行配置向导（将生成新的配置文件）[/yellow]")
    cfg = run_wizard(console, rt.config_path)
    if cfg is None:
        console.print("[yellow]已取消，保留原配置[/yellow]")
        return
    rt.cfg = cfg
    rt.provider = cfg.default_provider
    rt.model = cfg.providers[cfg.default_provider].model
    rt.client = _build_client(cfg, rt.provider)
    rt.exec_history = deque(maxlen=cfg.history_size)
    render_welcome(console, _provider_label(cfg, rt.provider, rt.model), __version__)


def _cmd_model(rt: Runtime, arg: str) -> None:
    console = rt.console
    if not arg:
        table = Table(box=box.SIMPLE, header_style="bold")
        table.add_column("服务商")
        table.add_column("模型")
        table.add_column("状态")
        for key, pc in rt.cfg.providers.items():
            current = "→ 当前" if key == rt.provider else ""
            table.add_row(key, pc.model, current)
        console.print(table)
        console.print("[dim]用法：/model <模型名> 切换模型（写入配置文件）[/dim]")
        return
    rt.cfg.providers[rt.provider].model = arg
    rt.model = arg
    rt.client = _build_client(rt.cfg, rt.provider, arg)
    try:
        rt.cfg.save(rt.config_path)
        console.print("[green]✓ 模型已切换为 {}[/green]".format(arg))
    except OSError as e:
        console.print(
            "[green]✓ 模型已切换为 {}[/green] [dim]（配置保存失败：{}）[/dim]".format(arg, e)
        )


def _cmd_provider(rt: Runtime, arg: str) -> None:
    console = rt.console
    if not arg:
        console.print("当前服务商：[green]{}[/green]（模型：{}）".format(rt.provider, rt.model))
        console.print("已配置的服务商：" + ", ".join(rt.cfg.providers))
        console.print(
            "预设模板：" + ", ".join(PRESETS)
            + " [dim]（未配置的可经 /config 添加）[/dim]"
        )
        return
    if arg not in rt.cfg.providers:
        console.print(
            "[red]未配置的服务商：{}[/red]，已配置：{}；可用 /config 添加".format(
                arg, ", ".join(rt.cfg.providers)
            )
        )
        return
    rt.provider = arg
    rt.cfg.default_provider = arg
    rt.model = rt.cfg.providers[arg].model
    rt.client = _build_client(rt.cfg, arg)
    try:
        rt.cfg.save(rt.config_path)
    except OSError:
        pass
    render_welcome(console, _provider_label(rt.cfg, arg, rt.model), __version__)


def _cmd_history(rt: Runtime) -> None:
    if not rt.exec_history:
        rt.console.print("[dim]本次会话还没有执行过命令[/dim]")
        return
    console = rt.console
    console.print("[bold]本次会话已执行的命令：[/bold]")
    for ts, cmd, code in list(rt.exec_history)[-20:]:
        mark = "[green]✓[/green]" if code == 0 else "[red]✗({})[/red]".format(code)
        console.print("  {}  {}  {}".format(ts, mark, cmd))


# ---------------------------------------------------------------- 核心流程


def _run_direct(rt: Runtime, cmd: str) -> None:
    """!! 逃生舱：跳过生成，直接编辑执行。"""
    if not cmd:
        rt.console.print("[yellow]用法：!!<shell 命令>[/yellow]")
        return
    _execute(rt, [Candidate(command=cmd, description="", risk=assess_risk(cmd))],
             from_ai=False)


def _pipeline(rt: Runtime, text: str) -> None:
    """自然语言 → 生成候选 → 选择 → 编辑 → 执行 → 记入记忆。"""
    console = rt.console
    rt.pending_query = text
    rt.pending_cmds = []
    context = rt.memory.build_context() if rt.memory else None
    messages = [{"role": "system", "content": build_system_prompt()}]
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": text})
    raw = ""
    try:
        try:
            with console.status("[bold cyan]正在思考...[/bold cyan]", spinner="dots"):
                raw = rt.client.chat(messages)
            cands = parse_candidates(raw)
        except ParseError:
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": "你的输出不是合法 JSON。请重新生成，仅输出符合格式要求的 JSON，"
                           "不要包含 markdown 代码块标记或任何其他文字。",
            })
            with console.status("[bold cyan]正在重试...[/bold cyan]", spinner="dots"):
                raw = rt.client.chat(messages)
            cands = parse_candidates(raw)
    except LLMError as e:
        render_error(console, e.message, e.suggestion)
        return
    except ParseError:
        render_error(console, "模型输出无法解析为命令",
                     "请尝试换个说法，或用 /model 换个模型")
        return
    except KeyboardInterrupt:
        console.print("[dim]已取消[/dim]")
        return

    if not cands:
        console.print(
            "[yellow]该输入似乎与执行 Linux 命令无关，"
            "请描述你想在服务器上完成的操作。[/yellow]"
        )
        return

    # 本地风险评估与模型标注取更高级别
    for c in cands:
        c.risk = combine_risk(c.risk, assess_risk(c.command))

    render_candidates(console, cands)
    sel = prompt_select(len(cands))
    if sel.action == "cancel":
        console.print("[dim]已取消[/dim]")
        return
    _execute(rt, [cands[i] for i in sel.indices])

    # 把本次提问与执行结果记入跨会话记忆
    if rt.memory and rt.pending_query:
        rt.memory.append(rt.pending_query, rt.pending_cmds)
        rt.memory.save()
        rt.pending_query = None
        rt.pending_cmds = []


def _execute(rt: Runtime, cands: List[Candidate], from_ai: bool = True) -> None:
    console = rt.console
    total = len(cands)
    for n, cand in enumerate(cands, 1):
        if total > 1:
            console.print("\n[bold]第 {}/{} 条[/bold]".format(n, total))
        cmd = edit_command(rt.editor_session, cand.command)
        if cmd is None:
            console.print("[dim]已取消（后续命令不再执行）[/dim]")
            return
        risk = combine_risk(cand.risk, assess_risk(cmd))
        if risk == "dangerous":
            if not confirm_dangerous(console, cmd):
                console.print("[dim]已跳过该命令[/dim]")
                continue
        res = run_command(cmd, console, timeout=rt.cfg.exec_timeout)
        render_result(console, res)
        rt.exec_history.append((datetime.now().strftime("%H:%M:%S"), cmd, res.exit_code))
        rt.pending_cmds.append(cmd)
        record_shell_history(cmd)  # 写入历史文件，bash 钩子导入后上键可查
        # 仅"真的失败"（退出码非零且输出含错误特征，或退出码为 126/127）才进入诊断修复
        if is_failure(res.exit_code, res.output_tail) and not res.interrupted:
            if _recover_from_failure(rt, cmd, res):
                continue  # 用户已通过修正命令重试，不再追问后续
        else:
            # 执行成功且产生输出时，自动让 AI 分析结果（!! 直执行的命令除外）
            if (from_ai and rt.cfg.auto_analyze and not res.interrupted
                    and not res.timed_out and res.output_tail.strip()):
                _analyze_result(rt, rt.pending_query or cmd, cmd, res.output_tail)
        if is_failure(res.exit_code, res.output_tail) and n < total:
            if not _ask_continue(console):
                console.print("[dim]已停止后续命令[/dim]")
                return


def _analyze_result(rt: Runtime, query: str, cmd: str, output: str) -> None:
    """把命令输出交给模型做结构化分析并渲染。失败时静默降级，不影响主流程。"""
    console = rt.console
    try:
        with console.status("[bold cyan]正在分析执行结果...[/bold cyan]", spinner="dots"):
            text = rt.client.chat(build_analysis_messages(query, cmd, output))
    except LLMError as e:
        console.print("[dim]结果分析不可用：{}[/dim]".format(e.message))
        return
    except KeyboardInterrupt:
        console.print("[dim]已跳过结果分析[/dim]")
        return
    render_analysis(console, text)


def _recover_from_failure(rt: Runtime, cmd: str, res) -> bool:
    """命令失败后：先本地诊断给出建议（离线、即时），再询问是否让模型修正重试。

    返回 True 表示用户已通过修正命令重试并回到主流程；False 表示结束本次失败处理。
    """
    console = rt.console
    console.print()
    hint = match_error(res.output_tail)
    if hint:
        console.print("[bold yellow]诊断：[/bold yellow]" + hint)

    if not res.output_tail:
        console.print("[dim]（命令无任何输出）[/dim]")

    try:
        ans = pt_prompt("让模型分析并给出修正命令？[Y/n] ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    if ans in ("n", "no", "0"):
        return False

    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": build_fix_prompt(cmd, res.exit_code, res.output_tail)},
    ]
    try:
        with console.status("[bold cyan]模型正在分析失败原因...[/bold cyan]", spinner="dots"):
            raw = rt.client.chat(messages)
        fixes = parse_candidates(raw)
    except LLMError as e:
        render_error(console, e.message, e.suggestion)
        return False
    except ParseError:
        render_error(console, "模型未能给出有效修正", "请稍后重试或换种说法")
        return False
    except KeyboardInterrupt:
        console.print("[dim]已取消[/dim]")
        return False

    if not fixes:
        render_error(console, "模型未能判断失败原因", "可跳过，手动检查命令")
        return False

    for c in fixes:
        c.risk = combine_risk(c.risk, assess_risk(c.command))

    console.print("[bold cyan]模型给出的修正方案：[/bold cyan]")
    render_candidates(console, fixes)
    sel = prompt_select(len(fixes))
    if sel.action == "cancel":
        return False
    _execute(rt, [fixes[i] for i in sel.indices])
    return True


def _ask_continue(console: Console) -> bool:
    try:
        ans = pt_prompt("前一条命令失败，继续执行下一条？[y/N] ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    return ans in ("y", "yes")


if __name__ == "__main__":
    raise SystemExit(main())
