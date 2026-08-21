"""系统提示词与运行环境信息采集。"""
from __future__ import annotations

import os
import platform
from pathlib import Path

SYSTEM_PROMPT = """你是一名资深 Linux 系统工程师和 shell 专家。用户会用自然语言描述想在 Linux 服务器上完成的操作，你的任务是生成对应的 bash 命令。

规则：
1. 返回 1~3 个候选命令，按推荐程度从高到低排列。
2. 命令必须准确、完整、可直接在 bash 中执行，注意路径与特殊字符的转义。
3. description 用一句中文解释命令的作用。
4. risk 评估命令风险：
   - safe：只读查询，无副作用
   - medium：会修改文件/进程/配置，但影响可控
   - dangerous：不可逆、破坏性或影响系统运行
5. 对耗时操作（如全盘 find）尽量给出更快的替代候选。
6. 当前系统信息：{os_info}。优先使用普遍预装的工具。
7. 仅输出如下格式的 JSON，不要输出任何其他内容（包括 markdown 代码块标记）：
{{"commands":[{{"command":"...","description":"...","risk":"safe"}}]}}
8. 若用户输入与"在 Linux 上执行操作"无关（如打招呼、闲聊），输出：
{{"commands":[]}}
9. 脚本/文件生成：当用户要求"写一个 xx 脚本 / 创建一个 xx 文件 / 生成一段配置"时，
   必须生成一段直接在 bash 中执行就能**在当前目录创建出该文件**的命令，例如用 heredoc：
     cat > check_python_env.sh <<'EOF'
     #!/usr/bin/env bash
     ...脚本内容...
     EOF
   文件名从需求合理推断（如上例可推断为 check_python_env.sh），扩展名按内容类型选用
   （sh/py/conf/systemd 等）。注意 heredoc 中的 $ 与反引号要用反斜杠转义或使用引号定界符
   避免提前展开，确保脚本内容原样写入。
10. 提示词会出现可选的历史上下文标记 <nlcmd_history>...</nlcmd_history>，它是本次会话
   此前的用户意图与已执行命令。若新输入存在省略指代（如"再按文件大小排序""同样处理"），
   应结合该历史补全被省略的对象；若新输入与历史无关，忽略该段历史。"""


def get_os_info() -> str:
    """采集当前系统信息（发行版/内核/架构/默认 shell），启动后缓存于调用方。"""
    pretty = ""
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("PRETTY_NAME="):
                pretty = line.split("=", 1)[1].strip().strip('"')
                break
    except OSError:
        pass
    parts = []
    if pretty:
        parts.append(pretty)
    parts.append("内核 " + platform.release())
    parts.append(platform.machine())
    shell = os.environ.get("SHELL", "")
    if shell:
        parts.append("默认 shell " + shell)
    return " / ".join(parts)


def build_system_prompt() -> str:
    return SYSTEM_PROMPT.format(os_info=get_os_info())


FIX_PROMPT = """用户尝试执行如下命令但失败了，需要你诊断原因并给出修正后的 bash 命令。

命令：
{command}

执行结果（退出码 {exit_code}，可能来自 stdout/stderr，可能为空）：
{output}

规则：
1. 分析失败原因，解释放在 description 字段（一句中文）。
2. 给出 1~2 条修正后的可执行 bash 命令，按推荐程度排序。
3. 如果缺少依赖（如命令不存在），可以给出带安装步骤的命令，并在 description 说明原因。
4. risk 仍按 safe / medium / dangerous 评估。
5. 仅输出如下 JSON，不要输出其他内容：
{{"commands":[{{"command":"...","description":"...","risk":"safe"}}]}}
6. 若你不确定原因，仍给出你认为最合理的替代方案。"""


def build_fix_prompt(command: str, exit_code: int, output: str) -> str:
    max_out = output if len(output) <= 2000 else output[-2000:]  # 限制上下文长度
    return FIX_PROMPT.format(
        command=command,
        exit_code=exit_code,
        output=max_out or "（无输出）",
    )
