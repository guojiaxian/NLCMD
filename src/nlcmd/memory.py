"""跨进程会话记忆：持久化用户意图与已执行命令，用于多轮上下文。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

MAX_HISTORY = 10      # 最多保留的会话条目数
CONTEXT_LIMIT = 800   # 历史上下文拼入提示词的最大字符数


class Memory:
    """以 JSON 持久化的会话记忆。

    每条记录：{time, query, cmds:[已执行的命令]}。
    跨进程重启仍保留，使新会话可接着上一次会话继续（如"再按文件大小排序"）。
    """

    def __init__(self, path: Path, max_history: int = MAX_HISTORY):
        self.path = path
        self.max_history = max_history
        self.entries: List[dict] = []

    @classmethod
    def load(cls, path: Path) -> "Memory":
        mem = cls(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                mem.entries = [e for e in data if isinstance(e, dict)][-mem.max_history:]
        except (OSError, ValueError):
            pass
        return mem

    def append(self, query: str, cmds: List[str]) -> None:
        import time as _t

        entry = {
            "time": _t.strftime("%H:%M:%S"),
            "query": query,
            "cmds": list(cmds)[-5:],
        }
        self.entries.append(entry)
        self.entries = self.entries[-self.max_history:]

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self.entries, ensure_ascii=False, indent=0),
                encoding="utf-8",
            )
        except OSError:
            pass

    def build_context(self) -> Optional[str]:
        """把近期历史拼成提示词中的上下文块；无历史时返回 None。"""
        recents = [e for e in self.entries if e.get("cmds")]
        if not recents:
            return None
        lines = ["以下为本会话此前的操作历史（用户意图 + 已执行命令），新输入可能引用它们："]
        for i, e in enumerate(recents[-5:], 1):
            cmds = " ; ".join(e.get("cmds") or [])
            query = (e.get("query") or "").strip()
            lines.append("{}) 意图：「{}」 已执行: {}".format(i, query, cmds))
        text = "\n".join(lines)
        if len(text) > CONTEXT_LIMIT:
            text = "…（历史较长，截取最近部分）\n" + text[-CONTEXT_LIMIT:]
        return "<nlcmd_history>\n" + text + "\n</nlcmd_history>"


def default_memory_path(state_dir: Path) -> Path:
    if os.environ.get("NLCMD_MEMORY_FILE"):
        return Path(os.environ["NLCMD_MEMORY_FILE"])
    return state_dir / "session_memory.json"