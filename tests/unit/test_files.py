from coding_agent_harness.models import ReadFile, WriteFile, DeleteFile, ListDir
from coding_agent_harness.tools.files import read_file, write_file, delete_file, list_dir


def test_write_then_read(tmp_path):
    w = write_file(WriteFile("a.txt", "hello"), tmp_path)
    assert w.ok
    r = read_file(ReadFile("a.txt"), tmp_path)
    assert r.ok and r.output == "hello"


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
    assert "..." in r.output
