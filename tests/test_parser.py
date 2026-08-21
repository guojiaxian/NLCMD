import pytest

from nlcmd.parser import ParseError, parse_candidates


def test_parse_multiline_heredoc_script():
    # 脚本生成：命令内含换行（JSON 转义 \n）
    raw = (
        '{"commands":[{"command":"cat > check_python_env.sh <<\'EOF\'\\n'
        '#!/usr/bin/env bash\\n'
        'echo $PYTHON_VERSION\\n'
        'which python3 || python3 --version\\n'
        'EOF\\n'
        '","description":"生成查看 Python 环境的脚本","risk":"medium"}]}'
    )
    cands = parse_candidates(raw)
    assert len(cands) == 1
    cmd = cands[0].command
    assert cmd.startswith("cat > check_python_env.sh")
    assert "EOF" in cmd
    assert "\n" in cmd  # 多行已还原
    assert cands[0].risk == "medium"


def test_parse_plain_json():
    raw = '{"commands":[{"command":"ls -la","description":"列出文件","risk":"safe"}]}'
    cands = parse_candidates(raw)
    assert len(cands) == 1
    assert cands[0].command == "ls -la"
    assert cands[0].description == "列出文件"
    assert cands[0].risk == "safe"


def test_parse_fenced_json():
    raw = '```json\n{"commands":[{"command":"ls","description":"","risk":"safe"}]}\n```'
    cands = parse_candidates(raw)
    assert len(cands) == 1
    assert cands[0].command == "ls"


def test_parse_with_surrounding_text():
    raw = '好的，以下是命令：\n{"commands":[{"command":"pwd","risk":"safe"}]}\n希望有帮助'
    cands = parse_candidates(raw)
    assert cands[0].command == "pwd"


def test_parse_multiple():
    raw = (
        '{"commands":['
        '{"command":"find / -iname \\"*vscode*\\" 2>/dev/null","description":"全盘查找","risk":"safe"},'
        '{"command":"locate vscode","description":"索引查找","risk":"safe"}]}'
    )
    cands = parse_candidates(raw)
    assert len(cands) == 2
    assert "vscode" in cands[0].command


def test_parse_empty_commands():
    assert parse_candidates('{"commands":[]}') == []


def test_invalid_risk_normalized_to_medium():
    raw = '{"commands":[{"command":"ls","risk":"unknown"}]}'
    assert parse_candidates(raw)[0].risk == "medium"


def test_missing_description_ok():
    raw = '{"commands":[{"command":"ls","risk":"safe"}]}'
    assert parse_candidates(raw)[0].description == ""


def test_parse_invalid_raises():
    with pytest.raises(ParseError):
        parse_candidates("抱歉，我无法理解你的意思")


def test_regex_fallback_on_broken_json():
    # JSON 缺少闭合括号 → 正则兜底提取 command
    raw = '{"commands": [{"command": "find / -iname \\"*vscode*\\"", "description": "查找", "risk": "safe"'
    cands = parse_candidates(raw)
    assert len(cands) == 1
    assert cands[0].command == 'find / -iname "*vscode*"'
