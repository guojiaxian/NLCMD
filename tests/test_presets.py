from nlcmd.presets import PRESETS


def test_expected_keys():
    assert set(PRESETS) == {"deepseek", "glm", "qwen", "kimi", "custom"}


def test_preset_fields_complete():
    for key, p in PRESETS.items():
        assert p.key == key
        assert p.name
        if key != "custom":
            assert p.api_base.startswith("https://")
            assert p.model
            assert p.key_env


def test_preset_urls():
    assert "deepseek" in PRESETS["deepseek"].api_base
    assert "bigmodel" in PRESETS["glm"].api_base
    assert "dashscope" in PRESETS["qwen"].api_base
    assert "moonshot" in PRESETS["kimi"].api_base
