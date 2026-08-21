from nlcmd.memory import Memory


def test_append_and_save_load_roundtrip(tmp_path):
    path = tmp_path / "session_memory.json"
    mem = Memory(path)
    mem.append("查询 python 文件", ["find / -iname '*.py'"])
    mem.append("按文件大小排序", ["find / -iname '*.py' -exec ls -lS {} \\;"])
    mem.save()

    loaded = Memory.load(path)
    assert len(loaded.entries) == 2
    assert loaded.entries[1]["query"] == "按文件大小排序"
    assert loaded.entries[0]["cmds"][0].startswith("find /")


def test_max_history_cap(tmp_path):
    path = tmp_path / "m.json"
    mem = Memory(path, max_history=3)
    for i in range(10):
        mem.append("q{}".format(i), ["echo {}".format(i)])
    assert len(mem.entries) == 3
    assert mem.entries[-1]["query"] == "q9"


def test_build_context_none_without_cmds(tmp_path):
    mem = Memory(tmp_path / "m.json")
    mem.append("打招呼", [])  # 未执行，不应进入上下文
    assert mem.build_context() is None


def test_build_context_contains_history(tmp_path):
    mem = Memory(tmp_path / "m.json")
    mem.append("查询包含vscode的文件", ["find / -iname '*vscode*'"])
    ctx = mem.build_context()
    assert ctx is not None
    assert "<nlcmd_history>" in ctx
    assert "vscode" in ctx
    assert "find / -iname" in ctx


def test_load_missing_file_returns_empty(tmp_path):
    mem = Memory.load(tmp_path / "nonexistent.json")
    assert mem.entries == []


def test_load_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    mem = Memory.load(path)
    assert mem.entries == []