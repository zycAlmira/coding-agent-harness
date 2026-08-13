from coding_agent_harness.models import ReadFile, WriteFile, DeleteFile, ListDir
from coding_agent_harness.tools.files import read_file, write_file, delete_file, list_dir


def test_write_then_read(tmp_path):
    w = write_file(WriteFile("a.txt", "hello"), tmp_path)
    assert w.ok
    r = read_file(ReadFile("a.txt"), tmp_path)
    assert r.ok and "hello" in r.output  # 整读回灌带行数前缀(共 1 行)


def test_read_missing_file_fails(tmp_path):
    r = read_file(ReadFile("nope.txt"), tmp_path)
    assert not r.ok
    assert r.error


def test_delete_removes_file(tmp_path):
    write_file(WriteFile("x.txt", "y"), tmp_path)
    d = delete_file(DeleteFile("x.txt"), tmp_path)
    assert d.ok
    assert not (tmp_path / "x.txt").exists()


def test_list_dir_returns_names(tmp_path):
    write_file(WriteFile("a.txt", "1"), tmp_path)
    write_file(WriteFile("b.txt", "2"), tmp_path)
    r = list_dir(ListDir("."), tmp_path)
    assert r.ok and "a.txt" in r.output and "b.txt" in r.output


def test_long_output_truncated(tmp_path):
    write_file(WriteFile("big.txt", "x" * 20000), tmp_path)
    r = read_file(ReadFile("big.txt"), tmp_path)
    assert len(r.output) < 20000
    assert "已截断" in r.output  # 截断必须明确告知,防 agent 误以为读错反复重读


def test_read_file_offset_lines(tmp_path):
    """read_file 支持 offset/lines:按行切片读取文件中间部分(offset 1-based)。"""
    from coding_agent_harness.models import ReadFile
    from coding_agent_harness.tools.files import read_file
    p = tmp_path / "big.txt"
    p.write_text("\n".join(f"line {i}" for i in range(100)))
    # offset=50 表示第 50 行(1-based)起读 3 行 → line 49/50/51;回灌带进度前缀
    r = read_file(ReadFile("big.txt", offset=50, lines=3), tmp_path)
    assert r.ok
    assert "line 49\nline 50\nline 51" in r.output
    assert "已读第 50-52 行" in r.output
    assert "offset=53" in r.output
    # 缺省 offset/lines:读全文
    r = read_file(ReadFile("big.txt"), tmp_path)
    assert r.ok and "line 0" in r.output and "line 99" in r.output
    # offset 越界 → 错误
    r = read_file(ReadFile("big.txt", offset=200), tmp_path)
    assert not r.ok


def test_read_file_truncated_tells_agent(tmp_path):
    """超长输出截断时,回灌应明确告知「已截断」——防止 agent 以为读错反复重读。"""
    from coding_agent_harness.models import ReadFile
    from coding_agent_harness.tools.files import read_file
    p = tmp_path / "huge.txt"
    p.write_text("x" * 20000)
    r = read_file(ReadFile("huge.txt"), tmp_path)
    assert r.ok
    assert "截断" in r.output, "截断时应明确告知,否则 agent 会反复重读想要完整内容"


def test_list_dir_recursive(tmp_path):
    """list_dir 支持 recursive:一次列出整个目录树,替代多次逐层 ListDir。"""
    from coding_agent_harness.models import ListDir
    from coding_agent_harness.tools.files import list_dir
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "src" / "main").mkdir(parents=True)
    (tmp_path / "src" / "main" / "K.java").write_text("x")
    (tmp_path / "src" / "test").mkdir(parents=True)
    (tmp_path / "src" / "test" / "KTest.java").write_text("x")
    r = list_dir(ListDir(".", recursive=True), tmp_path)
    assert r.ok
    assert "a.txt" in r.output
    assert "src/main/K.java" in r.output
    assert "src/test/KTest.java" in r.output
    # 缺省 recursive:只列一层(原行为)
    r = list_dir(ListDir("."), tmp_path)
    assert r.ok and "a.txt" in r.output and "src" in r.output
    assert "K.java" not in r.output


def test_read_file_offset_reports_progress(tmp_path):
    """分段读取应回灌行区间进度(已读/总行数+建议下次 offset),否则 agent
    反复读开头拼凑,永远得不到"完整内容"(真实历史 45+ 次重读同一文件)。"""
    from coding_agent_harness.models import ReadFile
    from coding_agent_harness.tools.files import read_file
    p = tmp_path / "kwic.txt"
    p.write_text("\n".join(f"line {i}" for i in range(100)))
    r = read_file(ReadFile("kwic.txt", offset=1, lines=40), tmp_path)
    assert r.ok
    assert "line 0" in r.output and "line 39" in r.output
    # 回灌告知进度:已读行区间 + 总行数 + 剩余 + 建议下次 offset
    assert "行 1-40" in r.output or "1-40" in r.output
    assert "100 行" in r.output
    assert "offset=41" in r.output, "应建议下次从 offset=41 继续读"


def test_read_file_full_reports_total(tmp_path):
    """整读(无 offset)也应回灌总行数,方便 agent 判断是否需分段。"""
    from coding_agent_harness.models import ReadFile
    from coding_agent_harness.tools.files import read_file
    p = tmp_path / "small.txt"
    p.write_text("a\nb\nc")
    r = read_file(ReadFile("small.txt"), tmp_path)
    assert r.ok
    assert "3 行" in r.output


def test_search_file_finds_matches(tmp_path):
    """search_file:按内容搜索文件,返回匹配行+行号(agent 定位 TODO/方法,
    不再逐段读全文)。"""
    from coding_agent_harness.models import SearchFile
    from coding_agent_harness.tools.files import search_file
    (tmp_path / "kwic.java").write_text(
        "public class KWIC {\n    // TODO 填空1\n    void process() {\n    }\n    // TODO 填空2\n}")
    r = search_file(SearchFile("kwic.java", "TODO"), tmp_path)
    assert r.ok
    assert "2" in r.output and "TODO 填空1" in r.output   # 行2
    assert "5" in r.output and "TODO 填空2" in r.output   # 行5
    assert "行" in r.output and "kwic.java" in r.output


def test_search_file_no_match(tmp_path):
    from coding_agent_harness.models import SearchFile
    from coding_agent_harness.tools.files import search_file
    (tmp_path / "a.txt").write_text("hello")
    r = search_file(SearchFile("a.txt", "nonexistent"), tmp_path)
    assert r.ok
    assert "无匹配" in r.output
