"""预填充可编辑命令行：用户可修改后回车执行，Esc 取消。"""
from __future__ import annotations

from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings


def edit_command(session: PromptSession, default: str) -> Optional[str]:
    """打开预填充 default 的可编辑输入行。

    返回编辑后的命令；Esc / Ctrl+C / Ctrl+D 或清空内容时返回 None（取消）。
    """
    state = {"cancelled": False}
    kb = KeyBindings()

    @kb.add("escape", eager=True)
    def _cancel(event):
        state["cancelled"] = True
        event.app.exit(result="")

    try:
        text = session.prompt("执行> ", default=default, key_bindings=kb)
    except (KeyboardInterrupt, EOFError):
        return None
    if state["cancelled"]:
        return None
    text = text.strip()
    return text if text else None
