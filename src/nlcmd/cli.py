"""nlcmd 入口：参数解析、REPL 主循环、内置命令。"""
from __future__ import annotations

import argparse
import os
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
from .config import Config, default_config_path, effective_api_key, run_wizard
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


def main(argv: Optional[List[str]] = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
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
