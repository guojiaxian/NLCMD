"""OpenAI 兼容的 LLM HTTP 客户端。"""
from __future__ import annotations

from typing import List, Tuple

import httpx


class LLMError(Exception):
    """带用户可读建议文案的 LLM 调用错误。"""

    def __init__(self, message: str, suggestion: str = ""):
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion


class LLMClient:
    """统一走 POST {api_base}/chat/completions（OpenAI 兼容格式）。"""

    def __init__(self, api_base: str, api_key: str, model: str,
                 timeout: float = 30.0, name: str = "",
                 disable_thinking: bool = False):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.name = name
        self.disable_thinking = disable_thinking

    @property
    def _url(self) -> str:
        return "{}/chat/completions".format(self.api_base)

    def chat(self, messages: List[dict], temperature: float = 0.2) -> str:
        if not self.api_base:
            raise LLMError("未配置 api_base", "请运行 /config 重新配置")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer {}".format(self.api_key)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if self.disable_thinking:
            # DeepSeek V4+：关闭思考模式以加速响应（其余服务商忽略该字段）
            payload["thinking"] = {"type": "disabled"}
        try:
            resp = httpx.post(self._url, json=payload, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException:
            raise LLMError(
                "请求超时（{:.0f}s）".format(self.timeout),
                "可在配置文件中调大 timeout，或检查网络",
            )
        except httpx.ConnectError:
            raise LLMError(
                "无法连接到 API 服务",
                "请检查网络与 api_base 是否正确：{}".format(self._url),
            )
        except httpx.HTTPError as e:
            raise LLMError("网络错误：{}".format(e))

        if resp.status_code in (401, 403):
            raise LLMError("API Key 无效或无权限（{}）".format(resp.status_code),
                           "请运行 /config 重新配置 API Key")
        if resp.status_code == 429:
            raise LLMError("触发服务限流（429）", "请稍后重试，或降低使用频率")
        if resp.status_code >= 500:
            raise LLMError("服务端错误（{}）".format(resp.status_code), "请稍后重试")
        if resp.status_code != 200:
            raise LLMError("API 返回异常状态码 {}".format(resp.status_code),
                           resp.text[:200])
        try:
            data = resp.json()
        except ValueError:
            raise LLMError("API 返回了非 JSON 内容", resp.text[:200])
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("API 响应格式异常", str(data)[:200])
        if not isinstance(content, str) or not content.strip():
            raise LLMError("模型返回了空内容", "请重试")
        return content

    def test_connection(self) -> Tuple[bool, str]:
        """发送最小请求验证连通性与鉴权。"""
        try:
            self.chat([{"role": "user", "content": "请只回复两个字符：ok"}], temperature=0.0)
        except LLMError as e:
            detail = "（{}）".format(e.suggestion) if e.suggestion else ""
            return False, "{}{}".format(e.message, detail)
        return True, "连接成功（模型 {} 已应答）".format(self.model)
