"""命令执行器：子进程、流式输出、超时与信号处理。"""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from rich.console import Console


@dataclass
class ExecResult:
    exit_code: int
    duration: float
    interrupted: bool
    timed_out: bool = False
    output_tail: str = ""   # 最近 N 行输出，用于失败诊断


def run_command(cmd: str, console: Console, timeout: float = 600.0) -> ExecResult:
    """通过 bash -c 执行命令，实时流式回显输出。

    - timeout > 0 时超时自动 SIGKILL 整个进程组；0 表示不限时
    - 执行中 Ctrl+C 向进程组转发 SIGINT
    - 同时截留最近 N 行输出，供失败后诊断
    """
    start = time.monotonic()
    state = {"timed_out": False}
    tail: "deque[str]" = deque(maxlen=40)

    proc = subprocess.Popen(
        ["bash", "-c", cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        start_new_session=True,
    )

    def _kill_group(sig: int) -> None:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(proc.pid), sig)

    timer = None  # type: Optional[threading.Timer]
    if timeout and timeout > 0:
        def _on_timeout() -> None:
            state["timed_out"] = True
            _kill_group(signal.SIGKILL)

        timer = threading.Timer(timeout, _on_timeout)
        timer.daemon = True
        timer.start()

    interrupted = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            console.print(line, end="", markup=False, highlight=False, soft_wrap=True)
            tail.append(line)
        proc.wait()
    except KeyboardInterrupt:
        interrupted = True
        _kill_group(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_group(signal.SIGKILL)
            proc.wait()
    finally:
        if timer is not None:
            timer.cancel()

    duration = time.monotonic() - start
    exit_code = proc.returncode if proc.returncode is not None else -1
    return ExecResult(
        exit_code=exit_code,
        duration=duration,
        interrupted=interrupted or state["timed_out"],
        timed_out=state["timed_out"],
        output_tail="".join(tail).rstrip(),
    )
