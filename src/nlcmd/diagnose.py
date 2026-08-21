"""命令失败后的本地诊断：离线识别常见报错原因并给出建议。

判断"是否真的失败"与"给出具体建议"是两件事：
- is_failure 判断一次执行是否真的出错了（供是否触发修复流程使用）。
  仅退出码非零 ≠ 失败：`systemctl status`(3=未运行)、`grep`(1=无匹配) 等
  退出码表示业务结果，并非错误，不应误判。
- match_error 在确实失败时，给出更具体的离线建议。
"""
from __future__ import annotations

import re
from typing import Optional

# 常见错误特征。与退出码非零同时出现才算"真的失败"。
_ERROR_PATTERNS = [
    # 命令/包不存在
    r"command not found", r"not found", r"no such file", r"no such directory",
    r"找不到命令", r"没有那个文件", r"不存在",
    # 权限
    r"permission denied", r"not permitted", r"operation not allowed",
    r"access denied", r"权限不足", r"被拒绝", r"拒绝访问", r"无权",
    # 无法/失败
    r"cannot\b", r"can'?t\b", r"unable to", r"could not", r"failed",
    r"failure", r"error", r"无法", r"失败", r"错误",
    # 参数/语法
    r"invalid option", r"unrecognized", r"unknown option", r"illegal option",
    r"syntax error", r"parse error", r"无效选项", r"语法错误",
    # 网络
    r"connection refused", r"connection timed out", r"could not resolve host",
    r"name resolution", r"temporary failure", r"连接被拒绝", r"访问超时",
    r"no space left", r"没有可用空间",
]
_ERROR_RE = re.compile("|".join(_ERROR_PATTERNS), re.IGNORECASE)

# 明确致命的 shell 级错误码（命令不存在/不可执行），与输出内容无关即为失败
_FATAL_CODES = (126, 127)


def is_failure(exit_code: int, output: str) -> bool:
    """判断一次命令执行是否真的失败。

    规则：退出码非零 且 （退出码为致命码 126/127，或 输出含错误特征）。
    `systemctl status`(3)、`grep`(1) 等业务状态码但无错误输出时不算失败。
    """
    if exit_code == 0:
        return False
    if exit_code in _FATAL_CODES:
        return True
    return bool(_ERROR_RE.search(output or ""))


def is_error_like(output: str) -> bool:
    """输出是否呈现错误特征（is_failure 的内部信号，也单测复用）。"""
    return bool(_ERROR_RE.search(output or ""))


def match_error(output: str) -> Optional[str]:
    """根据命令输出，返回命中错误时的用户可读诊断建议；不命中返回 None。"""
    low = output.lower()
    if not low:
        return None

    # 命令/包未安装
    if "command not found" in low or "找不到命令" in low or "not found" in low:
        if "sudo" in low:
            return (
                "命令未安装或不在 PATH 中。可先安装它，例如："
                "`sudo apt install <包名>`（Debian/Ubuntu）或 "
                "`sudo yum install <包名>`（CentOS/RHEL）。"
            )
        return "命令未安装或不在 PATH 中，请确认软件已安装。"

    if "no such file or directory" in low or "没有那个文件或目录" in low:
        return "路径不存在。请检查文件/目录路径是否拼写正确，或先用 ls 确认。"

    if "permission denied" in low or "权限不够" in low or "拒绝访问" in low:
        return "权限不足。可改用 sudo 运行，或检查文件/目录权限。"

    if "connection refused" in low or "连接被拒绝" in low:
        return "连接被拒绝。请确认目标服务已启动、端口号是否正确。"

    if "could not resolve host" in low or "无法解析主机" in low or "temporary failure in name resolution" in low:
        return "域名解析失败。请检查网络连接或 DNS 配置。"

    if "file exists" in low and ("mkdir" in low or "already exists" in low):
        return "目标已存在。可加 -p 忽略已存在，或改用其他路径。"

    if "too many arguments" in low or "参数太多" in low \
            or "invalid option" in low or "unrecognized option" in low \
            or "unknown option" in low or "illegal option" in low \
            or "无效选项" in low:
        return "命令参数有误。请检查选项写法或引号/转义是否正确。"

    return None