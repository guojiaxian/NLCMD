"""冒烟测试：mock LLM 服务器 → chat → 解析 → 执行 全链路（不依赖真实 API）。"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from rich.console import Console

from nlcmd.config import Config, ProviderConfig
from nlcmd.executor import run_command
from nlcmd.llm import LLMClient
from nlcmd.parser import parse_candidates
from nlcmd.prompts import build_system_prompt
from nlcmd.security import assess_risk


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        # 回显系统提示词长度，验证请求格式正确
        assert "messages" in body and body["model"] == "deepseek-chat"
        resp = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"commands": [
                        {"command": "echo hello-nlcmd", "description": "打印测试信息", "risk": "safe"},
                        {"command": "echo second", "description": "第二个候选", "risk": "safe"},
                    ]}, ensure_ascii=False),
                }
            }]
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def log_message(self, *args):
        pass


httpd = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

cfg = Config(default_provider="deepseek",
             providers={"deepseek": ProviderConfig(
                 api_base="http://127.0.0.1:{}".format(httpd.server_port),
                 api_key="sk-test", model="deepseek-chat")})
client = LLMClient(api_base=cfg.providers["deepseek"].api_base,
                   api_key="sk-test", model="deepseek-chat", timeout=5)

# 1. LLM 调用
raw = client.chat([
    {"role": "system", "content": build_system_prompt()},
    {"role": "user", "content": "打印 hello-nlcmd"},
])
assert "commands" in raw

# 2. 解析
cands = parse_candidates(raw)
assert len(cands) == 2, cands
assert cands[0].command == "echo hello-nlcmd"
assert cands[0].risk == "safe"
print("[1/4] LLM 调用与解析 OK:", cands[0].command)

# 3. 风险评估
assert assess_risk(cands[0].command) == "safe"
print("[2/4] 风险评估 OK")

# 4. 执行器（流式输出）
console = Console()
res = run_command(cands[0].command, console)
assert res.exit_code == 0, res
print("[3/4] 执行器 OK: exit_code={}, duration={:.2f}s".format(res.exit_code, res.duration))

# 5. 执行失败场景
res2 = run_command("ls /definitely/not/exist", console)
assert res2.exit_code != 0
print("[4/4] 失败退出码 OK:", res2.exit_code)

httpd.shutdown()
print("SMOKE TEST PASSED")
