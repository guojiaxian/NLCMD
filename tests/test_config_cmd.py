import os
import subprocess
import sys
import tempfile

import tomli

from nlcmd.cli import _coerce_bool, _mask_key


# ---------------------------------------------------------------- 单元测试


def test_coerce_bool():
    assert _coerce_bool("true") is True
    assert _coerce_bool("ON") is True
    assert _coerce_bool("1") is True
    assert _coerce_bool("false") is False
    assert _coerce_bool("off") is False
    assert _coerce_bool("0") is False
    assert _coerce_bool("开启") is True
    assert _coerce_bool("关闭") is False
    assert _coerce_bool("abc") is None


def test_mask_key():
    assert _mask_key("") == "（未设置）"
    assert _mask_key("short") == "****"
    m = _mask_key("sk-abcdefghijklmnop")
    assert m.startswith("sk-abc")
    assert m.endswith("mnop")
    assert "****" in m


# ---------------------------------------------------------------- 集成测试


def _run_config(cfg_path, *args):
    return subprocess.run(
        [sys.executable, "-m", "nlcmd", "-c", str(cfg_path), "config"] + list(args),
        capture_output=True, text=True, timeout=60,
    )


def _read_toml(cfg_path):
    with open(cfg_path, "rb") as f:
        return tomli.load(f)


def test_config_set_auto_analyze():
    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "c.toml")
        # 空配置时也能直接设置
        p = _run_config(cfg, "set", "auto_analyze", "false")
        assert p.returncode == 0, p.stderr
        assert _read_toml(cfg)["general"]["auto_analyze"] is False
        # 再改回 true
        p = _run_config(cfg, "set", "auto_analyze", "true")
        assert _read_toml(cfg)["general"]["auto_analyze"] is True


def test_config_set_provider_key_and_show_masks():
    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "c.toml")
        p = _run_config(cfg, "set", "providers.deepseek.api_key", "sk-abcdefghijklmnopqrstuvwxyz")
        assert p.returncode == 0, p.stderr
        data = _read_toml(cfg)
        assert data["providers"]["deepseek"]["api_key"] == "sk-abcdefghijklmnopqrstuvwxyz"
        # 预设字段自动初始化
        assert data["providers"]["deepseek"]["api_base"] == "https://api.deepseek.com"
        assert data["providers"]["deepseek"]["model"] == "deepseek-flash"
        # show 输出脱敏，不泄露完整 Key
        p = _run_config(cfg, "show")
        assert p.returncode == 0
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in p.stdout
        assert "****" in p.stdout


def test_config_set_default_provider_creates_preset():
    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "c.toml")
        p = _run_config(cfg, "set", "default_provider", "glm")
        assert p.returncode == 0, p.stderr
        data = _read_toml(cfg)
        assert data["general"]["default_provider"] == "glm"
        assert data["providers"]["glm"]["api_base"].startswith("https://open.bigmodel")


def test_config_set_numeric_and_invalid():
    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "c.toml")
        p = _run_config(cfg, "set", "timeout", "45")
        assert p.returncode == 0
        assert _read_toml(cfg)["general"]["timeout"] == 45.0
        # 非法值报错退出码 1
        p = _run_config(cfg, "set", "timeout", "abc")
        assert p.returncode == 1
        p = _run_config(cfg, "set", "auto_analyze", "maybe")
        assert p.returncode == 1
        p = _run_config(cfg, "set", "no_such_key", "1")
        assert p.returncode == 1
        p = _run_config(cfg, "set", "default_provider", "not-exist")
        assert p.returncode == 1


def test_config_show_empty_hint():
    with tempfile.TemporaryDirectory() as td:
        p = _run_config(os.path.join(td, "none.toml"), "show")
        assert p.returncode == 1
        assert "尚未配置" in p.stdout


def test_config_custom_provider():
    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "c.toml")
        p = _run_config(cfg, "set", "providers.myproxy.api_base", "https://proxy.example.com/v4")
        assert p.returncode == 0, p.stderr
        p = _run_config(cfg, "set", "providers.myproxy.model", "glm-4.5")
        assert p.returncode == 0
        data = _read_toml(cfg)
        assert data["providers"]["myproxy"]["api_base"] == "https://proxy.example.com/v4"
        assert data["providers"]["myproxy"]["model"] == "glm-4.5"


def test_config_test_unknown_provider_no_network():
    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "c.toml")
        p = _run_config(cfg, "set", "providers.deepseek.api_key", "sk-x")
        assert p.returncode == 0
        # 未知服务商在联网前即报错返回
        p = _run_config(cfg, "test", "no-such")
        assert p.returncode == 1
        assert "未知服务商" in p.stdout


def test_save_writes_comments_and_roundtrip(tmp_path):
    from nlcmd.config import Config, ProviderConfig

    path = tmp_path / "c.toml"
    cfg = Config(
        default_provider="deepseek",
        providers={"deepseek": ProviderConfig(
            api_base="https://api.deepseek.com", api_key="sk-secret",
            model="deepseek-flash", disable_thinking=True,
        )},
        auto_analyze=False,
    )
    cfg.save(path)
    text = path.read_text(encoding="utf-8")
    assert "# 默认服务商" in text
    assert "# auto_analyze" in text or "自动让 AI 分析" in text
    assert "# API Key 申请地址" in text
    # 带注释的文件仍能被正常解析，且内容一致
    loaded = Config.load(path)
    assert loaded.auto_analyze is False
    assert loaded.providers["deepseek"].api_key == "sk-secret"
    assert loaded.providers["deepseek"].disable_thinking is True
    assert loaded.providers["deepseek"].model == "deepseek-flash"


def test_config_edit_creates_template():
    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "c.toml")
        env = dict(os.environ, EDITOR="true")  # no-op 编辑器，立即退出 0
        p = subprocess.run(
            [sys.executable, "-m", "nlcmd", "-c", cfg, "config", "edit"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert p.returncode == 0, p.stderr
        assert os.path.isfile(cfg)
        with open(cfg, "rb") as f:
            data = tomli.load(f)
        assert data["providers"]["deepseek"]["api_key"] == ""
        # 模板带中文备注
        text = open(cfg, encoding="utf-8").read()
        assert "申请地址" in text
