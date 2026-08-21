"""预设 LLM 服务商模板（均为 OpenAI 兼容接口）。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    key: str
    name: str
    api_base: str
    model: str
    key_env: str = ""      # 服务商专属 API Key 环境变量
    key_hint: str = ""     # Key 获取地址提示


PRESETS = {
    "deepseek": ProviderPreset(
        key="deepseek",
        name="DeepSeek",
        api_base="https://api.deepseek.com",
        model="deepseek-chat",
        key_env="DEEPSEEK_API_KEY",
        key_hint="https://platform.deepseek.com",
    ),
    "glm": ProviderPreset(
        key="glm",
        name="GLM（智谱）",
        api_base="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
        key_env="ZHIPU_API_KEY",
        key_hint="https://open.bigmodel.cn",
    ),
    "qwen": ProviderPreset(
        key="qwen",
        name="通义千问",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        key_env="DASHSCOPE_API_KEY",
        key_hint="https://bailian.console.aliyun.com",
    ),
    "kimi": ProviderPreset(
        key="kimi",
        name="Kimi（月之暗面）",
        api_base="https://api.moonshot.cn/v1",
        model="moonshot-v1-8k",
        key_env="MOONSHOT_API_KEY",
        key_hint="https://platform.moonshot.cn",
    ),
    "custom": ProviderPreset(
        key="custom",
        name="自定义（OpenAI 兼容）",
        api_base="",
        model="",
    ),
}
