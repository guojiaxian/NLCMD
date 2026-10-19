"""终端渲染：欢迎页、候选面板、选择、危险确认与结果。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from prompt_toolkit import prompt as pt_prompt
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

RISK_STYLE = {
    "safe": ("green", "🟢"),
    "medium": ("yellow", "🟡"),
    "dangerous": ("red", "🔴"),
}


def render_welcome(console: Console, provider_label: str, version: str) -> None:
    console.print()
    console.print(
        Panel(
            Text.assemble(
                ("nlcmd ", "bold cyan"),
                ("v" + version + "  ", "dim"),
                ("自然语言 → Shell 命令\n", ""),
                ("模型：", "dim"),
                (provider_label, "bold green"),
                ("\n输入 /help 查看帮助，/exit 退出", "dim"),
            ),
            box=box.ROUNDED,
            border_style="cyan",
        )
    )


def render_candidates(console: Console, cands: List) -> None:
    body = Text()
    for i, c in enumerate(cands, 1):
        style, icon = RISK_STYLE.get(c.risk, RISK_STYLE["medium"])
        body.append("\n  [{}] ".format(i), style="bold")
        body.append(icon + " ", style=style)
        body.append(c.command + "\n", style=style)
        if c.description:
            body.append("      └─ " + c.description + "\n", style="dim")
    console.print()
    console.print(
        Panel(
            body,
            title="生成 {} 个候选命令".format(len(cands)),
            border_style="cyan",
            box=box.ROUNDED,
        )
    )


@dataclass
class Selection:
    action: str  # "run" | "edit" | "cancel"
    indices: List[int] = field(default_factory=list)


def prompt_select(count: int) -> Selection:
    """候选选择：回车=第1条；序号单选；逗号分隔多选；a=全部；e=编辑第1条；q=取消。"""
    print("回车=执行[1] │ 序号单选(2) │ 多选(1,2) │ a=全部 │ e=编辑 │ q=取消")
    while True:
        try:
            raw = pt_prompt("选择: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return Selection("cancel")
        if raw == "q":
            return Selection("cancel")
        if raw == "":
            return Selection("run", [0])
        if raw == "a":
            return Selection("run", list(range(count)))
        if raw == "e":
            return Selection("edit", [0])
        if re.fullmatch(r"[0-9][0-9,\s]*", raw):
            nums = [int(x) for x in re.split(r"[,\s]+", raw) if x]
            if nums and all(1 <= n <= count for n in nums):
                return Selection("run", sorted(set(n - 1 for n in nums)))
        print("输入无效，请重试（示例：1、1,3、a、q）")


def confirm_dangerous(console: Console, cmd: str) -> bool:
    """危险命令二次确认：需手动输入 yes。"""
    console.print()
    console.print(
        Panel(
            Text.assemble(
                ("⚠ 危险操作\n\n", "bold red"),
                (cmd + "\n\n", "red"),
                ("该命令不可逆或具有破坏性，请确认你了解其后果！", "bold"),
            ),
            border_style="red",
            box=box.HEAVY,
        )
    )
    try:
        ans = pt_prompt("确认执行请输入 yes（其他任意输入取消）: ").strip()
    except (KeyboardInterrupt, EOFError):
        return False
    return ans.lower() == "yes"


def render_result(console: Console, res) -> None:
    from .diagnose import is_failure

    console.print()
    if res.timed_out:
        console.print("[bold yellow]⚠ 命令执行超时，已被终止[/bold yellow]")
    elif res.interrupted:
        console.print("[bold yellow]⚠ 命令已被中断[/bold yellow]")
    elif res.exit_code == 0:
        console.print("[green]✓ 完成[/green] · 退出码 0 · 耗时 {:.1f}s".format(res.duration))
    elif is_failure(res.exit_code, res.output_tail):
        console.print(
            "[red]✗ 失败[/red] · 退出码 {} · 耗时 {:.1f}s".format(res.exit_code, res.duration)
        )
        if res.exit_code == 127:
            console.print("[dim]提示：命令未安装或不在 PATH 中[/dim]")
    else:
        # 非失败的非零退出码（如 systemctl status=3、grep=1）属于业务结果
        console.print(
            "[yellow]✓ 已执行（退出码 {}）[/yellow] · 耗时 {:.1f}s".format(
                res.exit_code, res.duration
            )
        )


def render_error(console: Console, title: str, suggestion: str = "") -> None:
    console.print("[bold red]✗ {}[/bold red]".format(title))
    if suggestion:
        console.print("[dim]{}[/dim]".format(suggestion))


def render_help(console: Console) -> None:
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("命令")
    table.add_column("说明")
    table.add_row("/help", "显示本帮助")
    table.add_row("/exit、/quit", "退出 nlcmd")
    table.add_row("/config", "重新运行配置向导（切换服务商 / 修改 Key）")
    table.add_row("/model [名称]", "查看或切换当前模型")
    table.add_row("/provider [名称]", "查看或切换当前服务商")
    table.add_row("/history", "查看本次会话已执行的命令")
    table.add_row("!!<命令>", "直接进入编辑行执行 shell 命令（逃生舱）")
    table.add_row("（自然语言）", "描述你想完成的操作，由大模型生成候选命令")
    console.print(table)


def render_analysis(console: Console, text: str) -> None:
    """渲染 AI 结果分析面板（支持表格等 Markdown 元素）。"""
    from rich.markdown import Markdown

    console.print()
    console.print(
        Panel(
            Markdown(text.strip()),
            title="AI 结果分析",
            title_align="left",
            border_style="cyan",
            padding=(0, 1),
        )
    )
