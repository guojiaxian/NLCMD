"""LLM 输出解析：JSON 严格解析 → 正则兜底。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional

VALID_RISKS = ("safe", "medium", "dangerous")


@dataclass
class Candidate:
    command: str
    description: str = ""
    risk: str = "medium"


class ParseError(Exception):
    """模型输出无法解析为候选命令。"""


_CMD_RE = re.compile(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"')


def parse_candidates(raw: str) -> List[Candidate]:
    """解析模型输出，容错顺序：去围栏 → JSON 截取 → 正则兜底 → 抛 ParseError。"""
    text = _strip_fences(raw)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            data = None
        if data is not None:
            cands = _from_data(data)
            if cands is not None:
                return cands
    fallback = _regex_fallback(text)
    if fallback:
        return fallback
    raise ParseError("无法从模型输出中解析出命令")


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _from_data(data) -> Optional[List[Candidate]]:
    """校验 JSON 结构；结构不符返回 None（交给兜底），空 commands 返回 []。"""
    if not isinstance(data, dict):
        return None
    cmds = data.get("commands")
    if not isinstance(cmds, list):
        return None
    out = []
    for item in cmds:
        if not isinstance(item, dict):
            return None
        command = item.get("command")
        if not isinstance(command, str) or not command.strip():
            return None
        description = item.get("description")
        if not isinstance(description, str):
            description = ""
        risk = item.get("risk")
        risk = risk.lower().strip() if isinstance(risk, str) else ""
        if risk not in VALID_RISKS:
            risk = "medium"
        out.append(Candidate(
            command=command.strip(),
            description=description.strip(),
            risk=risk,
        ))
    return out


def _regex_fallback(text: str) -> List[Candidate]:
    """JSON 整体解析失败时，正则提取 "command":"..." 字段兜底。"""
    out = []
    for m in _CMD_RE.findall(text):
        try:
            cmd = json.loads('"' + m + '"')
        except ValueError:
            cmd = m
        if isinstance(cmd, str) and cmd.strip():
            out.append(Candidate(command=cmd.strip(), risk="medium"))
    return out
