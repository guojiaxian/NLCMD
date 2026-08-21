"""REPL 全链路冒烟测试：真实 nlcmd 进程 + mock LLM 服务器 + 管道输入。"""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

CANDIDATES = json.dumps({"commands": [
    {"command": "echo pipeline-ok", "description": "打印验证信息", "risk": "safe"},
    {"command": "echo second", "description": "第二个候选", "risk": "safe"},
]}, ensure_ascii=False)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        msgs = body.get("messages", [])
        # 第二次调用（纠错重试）不应发生；验证用户输入被携带
        assert any("查询" in str(m.get("content", "")) for m in msgs), msgs
        resp = {"choices": [{"message": {"role": "assistant", "content": CANDIDATES}}]}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def log_message(self, *args):
        pass


httpd = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

with tempfile.TemporaryDirectory() as td:
    cfg_path = os.path.join(td, "config.toml")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(
            "[general]\ndefault_provider = \"custom\"\n\n"
            "[providers.custom]\napi_base = \"http://127.0.0.1:{p}\"\n"
            "api_key = \"\"\nmodel = \"mock-model\"\n".format(p=httpd.server_port)
        )
    env = dict(os.environ, NLCMD_STATE_DIR=os.path.join(td, "state"))
    # 输入序列：自然语言 → 选择 1 → 编辑行回车（接受预填命令）→ 退出
    proc = subprocess.run(
        [sys.executable, "-m", "nlcmd", "-c", cfg_path],
        input="查询一下测试\n1\n\n/exit\n",
        capture_output=True, text=True, env=env, timeout=60,
    )
    out = proc.stdout
    print(out)
    assert "生成 2 个候选命令" in out, "候选未渲染"
    assert "echo pipeline-ok" in out, "候选命令未展示"
    assert "执行>" in out, "编辑行未出现"
    assert "pipeline-ok" in out, "命令未执行"
    assert "✓ 完成" in out, "结果未渲染"
    assert proc.returncode == 0, proc.returncode

httpd.shutdown()
print("REPL SMOKE TEST PASSED")
