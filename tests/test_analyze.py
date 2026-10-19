import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from nlcmd.analyze import ANALYZE_PROMPT, build_analysis_messages
from nlcmd.cli import record_shell_history


# ---------------------------------------------------------------- 单元测试


def test_record_shell_history_single_line(tmp_path):
    record_shell_history("ps aux | head -5", state_dir=tmp_path)
    assert (tmp_path / "shell_history").read_text() == "ps aux | head -5\n"


def test_record_shell_history_multiline_escaped(tmp_path):
    record_shell_history("cat > a.sh <<'EOF'\necho hi\nEOF", state_dir=tmp_path)
    content = (tmp_path / "shell_history").read_text()
    assert content == "cat > a.sh <<'EOF'\\necho hi\\nEOF\n"  # 换行转义，仍是一行


def test_record_shell_history_appends(tmp_path):
    record_shell_history("cmd1", state_dir=tmp_path)
    record_shell_history("cmd2", state_dir=tmp_path)
    assert (tmp_path / "shell_history").read_text().splitlines() == ["cmd1", "cmd2"]


def test_record_shell_history_skips_blank(tmp_path):
    record_shell_history("   \n  ", state_dir=tmp_path)
    assert not (tmp_path / "shell_history").exists()


def test_build_analysis_messages_basic():
    msgs = build_analysis_messages("查看进程", "ps aux", "user 1.5% python")
    assert msgs[0]["role"] == "system"
    assert "运维专家" in msgs[0]["content"]
    assert "查看进程" in msgs[1]["content"]
    assert "ps aux" in msgs[1]["content"]
    assert "python" in msgs[1]["content"]


def test_build_analysis_messages_empty_output():
    msgs = build_analysis_messages("q", "cmd", "")
    assert "没有产生任何输出" in msgs[1]["content"]


def test_build_analysis_messages_truncates_long_output():
    out = "x" * 8000
    msgs = build_analysis_messages("q", "cmd", out)
    user = msgs[1]["content"]
    assert len(user) < 4000
    assert "已截取末尾部分" in user


def test_analyze_prompt_structure():
    assert "结果解读" in ANALYZE_PROMPT
    assert "结论" in ANALYZE_PROMPT
    assert "建议" in ANALYZE_PROMPT


# ---------------------------------------------------------------- 集成测试
# 覆盖：nlcmd run 一次性模式 → 生成 → 执行 → 自动结果分析（模拟阿里云助手流程）


class _Handler(BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _Handler.calls.append(body)
        sys_msgs = [m for m in body.get("messages", []) if m["role"] == "system"]
        if any("运维专家" in m.get("content", "") for m in sys_msgs):
            # 结果分析请求
            content = "结果解读：\n- 分析标记 analyze-ok\n结论：\n一切正常\n建议：\n- 无"
        else:
            # 命令生成请求
            content = json.dumps({"commands": [
                {"command": "echo run-e2e-marker", "description": "验证", "risk": "safe"}
            ]})
        resp = {"choices": [{"message": {"role": "assistant", "content": content}}]}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def log_message(self, *a):
        pass


def test_run_one_shot_with_auto_analyze():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "c.toml")
            with open(cfg, "w") as f:
                f.write(
                    '[general]\ndefault_provider="custom"\n'
                    '[providers.custom]\napi_base="http://127.0.0.1:{}"\n'
                    'api_key=""\nmodel="m"\n'.format(httpd.server_port)
                )
            env = dict(os.environ, NLCMD_STATE_DIR=os.path.join(td, "state"))
            # 输入序列：选择候选[1] → 编辑行回车确认
            p = subprocess.run(
                [sys.executable, "-m", "nlcmd", "-c", cfg,
                 "run", "查看当前所有进程占用内存的情况"],
                input="1\n\n", capture_output=True, text=True,
                env=env, timeout=60,
            )
            assert p.returncode == 0, p.stderr
            assert "run-e2e-marker" in p.stdout, p.stdout
            assert "AI 结果分析" in p.stdout, p.stdout
            assert "analyze-ok" in p.stdout, p.stdout
            # 执行过的命令已写入 shell 历史文件（供 bash 上键导入）
            hist_file = os.path.join(td, "state", "shell_history")
            with open(hist_file) as f:
                hist = f.read()
            assert "echo run-e2e-marker" in hist, hist
            # 共两次 LLM 调用：生成 + 分析；分析请求带上了命令输出
            assert len(_Handler.calls) == 2
            analysis_req = _Handler.calls[1]
            joined = " ".join(m["content"] for m in analysis_req["messages"])
            assert "run-e2e-marker" in joined  # 输出内容已传给分析
    finally:
        httpd.shutdown()
        _Handler.calls.clear()
