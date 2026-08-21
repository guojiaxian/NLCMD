import os

from nlcmd.config import Config, ProviderConfig, effective_api_key


def test_load_missing_returns_none(tmp_path):
    assert Config.load(tmp_path / "none.toml") is None


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config(
        default_provider="deepseek",
        providers={
            "deepseek": ProviderConfig(
                api_base="https://api.deepseek.com",
                api_key="sk-test",
                model="deepseek-chat",
            )
        },
        timeout=45.0,
        exec_timeout=120.0,
    )
    cfg.save(path)
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    loaded = Config.load(path)
    assert loaded is not None
    assert loaded.default_provider == "deepseek"
    assert loaded.providers["deepseek"].api_key == "sk-test"
    assert loaded.timeout == 45.0
    assert loaded.exec_timeout == 120.0


def test_load_invalid_toml_returns_none(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("this is not toml {{{", encoding="utf-8")
    assert Config.load(path) is None


def test_load_without_providers_returns_none(tmp_path):
    path = tmp_path / "empty.toml"
    path.write_text('[general]\ndefault_provider = "x"\n', encoding="utf-8")
    assert Config.load(path) is None


def test_load_defaults_when_general_missing(tmp_path):
    path = tmp_path / "min.toml"
    path.write_text(
        '[providers.deepseek]\napi_base = "https://api.deepseek.com"\napi_key = "k"\nmodel = "deepseek-chat"\n',
        encoding="utf-8",
    )
    cfg = Config.load(path)
    assert cfg is not None
    assert cfg.default_provider == "deepseek"
    assert cfg.timeout == 30.0


def test_effective_api_key_priority(monkeypatch):
    pc = ProviderConfig(api_key="from-file")
    assert effective_api_key("deepseek", pc) == "from-file"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
    assert effective_api_key("deepseek", pc) == "from-env"
    monkeypatch.setenv("NLCMD_API_KEY", "from-generic")
    assert effective_api_key("deepseek", pc) == "from-generic"
    assert effective_api_key("glm", ProviderConfig(api_key="")) == "from-generic"
