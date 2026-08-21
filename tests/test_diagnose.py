import pytest

from nlcmd.diagnose import is_failure, match_error
from nlcmd.prompts import build_fix_prompt


@pytest.mark.parametrize("output,keyword", [
    ("sudo: ufw：找不到命令\n", "未安装"),
    ("bash: ls: command not found\n", "未安装"),
    ("/bin/sh: foo: not found\n", "未安装"),
    ("cat: /no/such: No such file or directory\n", "路径不存在"),
    ("Permission denied\n", "权限"),
    ("Connection refused\n", "连接被拒绝"),
    ("Could not resolve host: example.com\n", "域名解析"),
    ("mkdir: cannot create directory 'x': File exists\n", "已存在"),
    ("unrecognized option '--foo'\n", "参数有误"),
])
def test_match_error_known(output, keyword):
    assert keyword in (match_error(output) or "")


def test_match_error_unknown():
    assert match_error("") is None
    assert match_error("hello world\nrandom output\n") is None


@pytest.mark.parametrize("code,output", [
    # 真正的失败：错误输出 + 非零退出码
    (1, "sudo: ufw：找不到命令\n"),
    (1, "cat: /x: No such file or directory\n"),
    (1, "Permission denied\n"),
    # 致命码：无论输出如何都算失败
    (127, "hello world"),
    (126, ""),
])
def test_is_failure_true(code, output):
    assert is_failure(code, output)


@pytest.mark.parametrize("code,output", [
    # systemctl status firewalld（服务未运行，退出码 3）→ 不是失败
    (3, "● firewalld.service - firewalld - dynamic firewall daemon\n"
        "   Loaded: loaded (...; disabled; vendor preset: enabled)\n"
        "   Active: inactive (dead)\n"),
    # grep 无匹配（退出码 1）→ 业务结果，不是失败
    (1, ""),
    (1, None),
    # 退出码 0 永远不是失败
    (0, "Permission denied\nagain"),  # 输出含错误词但退出码 0，可能是软错误
    (0, "error happened but exit 0"),
    # 非零退出码但无错误特征 → 不是失败
    (2, "=2\nsome normal output\n"),
    (5, "normal status text\n"),
])
def test_is_failure_false(code, output):
    assert not is_failure(code, output)


def test_build_fix_prompt_matches_command():
    prompt = build_fix_prompt("sudo ufw status", 1, "sudo: ufw：找不到命令\n")
    assert "sudo ufw status" in prompt
    assert "sudo: ufw" in prompt
    assert "1" in prompt


def test_build_fix_prompt_truncates_long_output():
    long = "x" * 5000
    prompt = build_fix_prompt("echo", 1, long)
    assert "x" * 3000 not in prompt  # 已截断