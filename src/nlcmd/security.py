"""本地风险评估：独立于大模型输出的安全网。

风险分级：
- safe      只读查询，无副作用
- medium    会修改文件/进程/配置，但影响可控
- dangerous 不可逆、破坏性或影响系统运行
"""
from __future__ import annotations

import os
import re
import shlex
from typing import List, Optional

RISK_ORDER = {"safe": 0, "medium": 1, "dangerous": 2}


def combine_risk(a: str, b: str) -> str:
    """取两者中更高的风险等级。"""
    return a if RISK_ORDER.get(a, 1) >= RISK_ORDER.get(b, 1) else b


_DANGEROUS_PATTERNS = [
    r"\bmkfs(\.\w+)?\b",                                          # 格式化磁盘
    r"\bdd\b[^|;&]*\bof=/dev/",                                   # dd 写块设备
    r":\(\)\s*\{[^}]*\}\s*;\s*:",                                 # fork 炸弹
    r">\s*/dev/(sd[a-z]|nvme\d+n\d+|vd[a-z])",                    # 覆盖磁盘设备
    r"\b(shutdown|reboot|halt|poweroff)\b",                       # 电源操作
    r"\binit\s+[06]\b",                                           # 切运行级别
    r"\bchmod\s+(-\w+\s+)*[0-7]*7[0-7]{2}\s+/(etc|usr|var|boot|bin|sbin|lib|root|home)(/|\s|$)",
    r"(curl|wget)[^|;&]*\|\s*(ba|z|fi|da)?sh\b",                  # 远程脚本直接执行
    r">\s*/etc/(passwd|shadow|sudoers|fstab|hosts|profile|bashrc)\b",
    r"\bkill\s+(-\d+\s+)?1\b",                                    # 杀 init
    r"\bfind\b[^|;&]*\s-(delete|exec\s+rm)\b",                    # find 批量删除
    r"\bcrontab\s+(-\w*r|--remove)\b",                            # 删除 crontab
]

_MEDIUM_PATTERNS = [
    r"\brm\b",
    r"\b(systemctl|service)\s+(restart|stop|disable|mask|kill)\b",
    r"\b(pkill|killall|kill)\b",
    r"\b(apt|apt-get|yum|dnf|pacman|zypper)\s+(install|remove|erase|purge|autoremove|update|upgrade)\b",
    r"\bpip3?\s+(install|uninstall)\b",
    r"\bnpm\s+(install|uninstall|rm)\b",
    r"\bchmod\b|\bchown\b|\bchgrp\b",
    r"\bmv\b",
    r"\bcrontab\b",
    r"\bgit\s+(reset\s+--hard|clean\s+-\w*f|push\b[^\n]*--force)\b",
    r"\bswapoff\b",
    r"(?:^|\s|\d)>{1,2}\s*(?!/dev/null\b|&)\S",                   # 重定向覆盖文件
]

_DANGEROUS_COMPILED = [re.compile(p) for p in _DANGEROUS_PATTERNS]
_MEDIUM_COMPILED = [re.compile(p) for p in _MEDIUM_PATTERNS]

# rm 的精确分析（tokens[0] 为 rm 时）
_TMP_PREFIXES = ("/tmp", "/var/tmp", "/dev/shm")


def _tokenize(s: str) -> List[str]:
    try:
        return shlex.split(s)
    except ValueError:
        return s.split()


def _rm_risk(segment: str) -> Optional[str]:
    """对以 rm 开头的命令段做精确风险评估。"""
    tokens = _tokenize(segment)
    if not tokens or os.path.basename(tokens[0]) != "rm":
        return None
    rest = tokens[1:]
    has_recursive = any(t.startswith("-") and "r" in t.lower() for t in rest)
    targets = [t for t in rest if not t.startswith("-")]
    if not targets or not has_recursive:
        return "medium"
    home = os.path.expanduser("~")
    for t in targets:
        t2 = os.path.expandvars(os.path.expanduser(t))
        if t2 in ("/", "/*", "/.*"):
            return "dangerous"
        if t2.rstrip("/") == home:
            return "dangerous"
        if t2.startswith(home + os.sep):
            continue  # 家目录子路径 → medium
        if t2.startswith("/"):
            if not any(t2 == p or t2.startswith(p + "/") for p in _TMP_PREFIXES):
                return "dangerous"
    return "medium"


# 嵌入式 rm（如 xargs rm -rf、bash -c 'rm -rf ~'）的粗粒度检测
_RM_WORD_RE = re.compile(r"\brm\b")
_RFLAG_RE = re.compile(r"-{1,2}[a-zA-Z]*[rR]")
_BARE_ROOT_RE = re.compile(r"(^|[\s\"'])/(\s|/|\*|$|[\"'])")
_HOME_RE = re.compile(r"(^|[\s\"'])(~|\$HOME)([\s\"']|$)")


def _embedded_rm_dangerous(seg: str) -> bool:
    if not _RM_WORD_RE.search(seg):
        return False
    if not _RFLAG_RE.search(seg):
        return False
    return bool(_BARE_ROOT_RE.search(seg) or _HOME_RE.search(seg))


def assess_risk(cmd: str) -> str:
    """评估命令风险：dangerous > medium > safe。"""
    for pat in _DANGEROUS_COMPILED:
        if pat.search(cmd):
            return "dangerous"
    for seg in re.split(r"[;|&\n]", cmd):
        seg = seg.strip()
        if not seg:
            continue
        if _rm_risk(seg) == "dangerous" or _embedded_rm_dangerous(seg):
            return "dangerous"
    for pat in _MEDIUM_COMPILED:
        if pat.search(cmd):
            return "medium"
    return "safe"
