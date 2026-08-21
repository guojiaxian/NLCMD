"""配置管理：加载/保存 TOML 配置、环境变量优先级、首次配置向导。"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import tomli_w

from .presets import PRESETS


def default_config_path() -> Path:
    """配置文件路径（可用环境变量 NLCMD_CONFIG 覆盖）。"""
    if os.environ.get("NLCMD_CONFIG"):
        return Path(os.environ["NLCMD_CONFIG"])
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "nlcmd" / "config.toml"


@dataclass
class ProviderConfig:
    api_base: str = ""
    api_key: str = ""
    model: str = ""


@dataclass
class Config:
    default_provider: str = ""
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
    timeout: float = 30.0        # LLM 请求超时（秒）
    exec_timeout: float = 600.0  # 命令执行超时（秒），0 表示不限
    history_size: int = 200

    @classmethod
    def load(cls, path: Path) -> Optional["Config"]:
        """加载配置；文件不存在或内容无效时返回 None（触发配置向导）。"""
        if not path.is_file():
            return None
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError, ValueError):
            return None
        general = data.get("general") or {}
        providers: Dict[str, ProviderConfig] = {}
        for key, val in (data.get("providers") or {}).items():
            if not isinstance(val, dict):
                continue
            providers[key] = ProviderConfig(
                api_base=str(val.get("api_base", "")),
                api_key=str(val.get("api_key", "")),
                model=str(val.get("model", "")),
            )
        if not providers:
            return None
        default = str(general.get("default_provider", "")) or next(iter(providers))
        return cls(
            default_provider=default,
            providers=providers,
            timeout=float(general.get("timeout", 30)),
            exec_timeout=float(general.get("exec_timeout", 600)),
            history_size=int(general.get("history_size", 200)),
        )

    def save(self, path: Path) -> None:
        """保存配置（权限 0600，避免泄露 API Key）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "general": {
                "default_provider": self.default_provider,
                "timeout": self.timeout,
                "exec_timeout": self.exec_timeout,
                "history_size": self.history_size,
            },
            "providers": {k: asdict(v) for k, v in self.providers.items()},
        }
        path.write_bytes(tomli_w.dumps(data).encode("utf-8"))
        try:
            path.chmod(0o600)
        except OSError:
            pass


def effective_api_key(provider_key: str, pc: ProviderConfig) -> str:
    """API Key 优先级：NLCMD_API_KEY > 服务商专属环境变量 > 配置文件。"""
    if os.environ.get("NLCMD_API_KEY"):
        return os.environ["NLCMD_API_KEY"]
    preset = PRESETS.get(provider_key)
    if preset and preset.key_env and os.environ.get(preset.key_env):
        return os.environ[preset.key_env]
    return pc.api_key


def run_wizard(console, config_path: Path) -> Optional[Config]:
    """交互式配置向导：选服务商 → 填参数 → 可选测试连接 → 保存。"""
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.text import Text

    from .llm import LLMClient

    console.print(
        Panel(
            Text.assemble(
                ("首次使用配置向导\n", "bold"),
                ("配置文件将保存到：", "dim"),
                (str(config_path), "cyan"),
            ),
            border_style="cyan",
        )
    )

    keys = list(PRESETS)
    try:
        return _wizard_loop(console, config_path, keys)
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]已取消配置。[/yellow]")
        return None


def _wizard_loop(console, config_path: Path, keys):
    from rich.prompt import Confirm, Prompt

    from .llm import LLMClient

    while True:
        console.print("\n[bold]选择 LLM 服务商：[/bold]")
        for i, k in enumerate(keys, 1):
            p = PRESETS[k]
            console.print(f"  {i}) [green]{p.name:<16}[/green] 默认模型：{p.model or '-'}")
        choice = Prompt.ask(
            "请选择",
            choices=[str(i) for i in range(1, len(keys) + 1)],
            default="1",
            console=console,
        )
        key = keys[int(choice) - 1]
        preset = PRESETS[key]

        if key == "custom":
            api_base = Prompt.ask(
                "API 地址（OpenAI 兼容，如 https://host/v1）", console=console
            ).strip()
            model = Prompt.ask("模型名称", console=console).strip()
            if not api_base or not model:
                console.print("[red]API 地址和模型名称不能为空[/red]")
                continue
        else:
            api_base = Prompt.ask("API 地址", default=preset.api_base, console=console).strip()
            model = Prompt.ask("模型", default=preset.model, console=console).strip()

        api_key = ""
        env_used = ""
        if os.environ.get("NLCMD_API_KEY"):
            api_key = os.environ["NLCMD_API_KEY"]
            env_used = "NLCMD_API_KEY"
        elif preset.key_env and os.environ.get(preset.key_env):
            api_key = os.environ[preset.key_env]
            env_used = preset.key_env
        if env_used:
            console.print(f"[green]✓ 已从环境变量 {env_used} 读取到 API Key[/green]")
        else:
            hint = f"（获取：{preset.key_hint}）" if preset.key_hint else ""
            api_key = Prompt.ask(f"API Key{hint}", password=True, console=console).strip()
            if not api_key and key != "custom":
                console.print("[red]API Key 不能为空[/red]")
                continue
            if not api_key and key == "custom":
                console.print("[yellow]未填写 API Key（适用于无鉴权的本地服务）[/yellow]")

        pc = ProviderConfig(api_base=api_base.rstrip("/"), api_key=api_key, model=model)

        if Confirm.ask("测试连接？", default=True, console=console):
            client = LLMClient(
                api_base=pc.api_base, api_key=pc.api_key, model=pc.model,
                timeout=30.0, name=key,
            )
            ok, msg = client.test_connection()
            if ok:
                console.print(f"[green]✓ {msg}[/green]")
            else:
                console.print(f"[red]✗ {msg}[/red]")
                if not Confirm.ask("连接失败，仍保存这份配置吗？", default=False, console=console):
                    if Confirm.ask("重新配置？", default=True, console=console):
                        continue
                    return None

        cfg = Config(default_provider=key, providers={key: pc})
        try:
            cfg.save(config_path)
        except OSError as e:
            console.print(f"[red]配置保存失败：{e}[/red]")
            return None
        console.print(f"\n[green]✓ 配置已保存：{config_path}[/green]\n")
        return cfg
