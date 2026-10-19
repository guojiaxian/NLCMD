"""命令执行结果的 AI 分析：把「意图 + 命令 + 输出」交给模型做结构化解读。"""
from __future__ import annotations

from typing import List

ANALYZE_PROMPT = """你是资深 Linux 运维专家。用户刚通过 AI 助手执行了一条命令，\
请你分析命令输出并给出简明结论。

要求：
1. 用中文回答，直击要点，不要复述原始输出。
2. 结构固定为三段，用下面的标题（保留标题原文）：
   结果解读：
   - 用 1~5 个要点总结输出中的关键信息（涉及多项数据时优先用表格呈现）
   结论：
   - 一句话给出整体判断（如健康/异常/需要注意）
   建议：
   - 0~2 条后续可执行的命令或操作建议（如有命令直接写出）
3. 若输出是空或与意图无关，如实说明。
4. 只输出分析内容本身，不要输出 JSON、代码块标记或多余寒暄。"""


def build_analysis_messages(query: str, command: str, output: str) -> List[dict]:
    """构造结果分析的消息序列。输出超长时截断，控制 token。"""
    out = (output or "").strip()
    if len(out) > 3000:
        out = out[-3000:]
        out = "…（输出较长，已截取末尾部分）\n" + out
    if not out:
        out = "（命令没有产生任何输出）"
    user = (
        "用户意图：{q}\n"
        "已执行命令：{c}\n"
        "--- 命令输出 开始 ---\n{o}\n--- 命令输出 结束 ---"
    ).format(q=query, c=command, o=out)
    return [
        {"role": "system", "content": ANALYZE_PROMPT},
        {"role": "user", "content": user},
    ]
