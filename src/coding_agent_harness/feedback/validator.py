"""解析 pytest 输出为结构化 Feedback。纯函数,确定性,可单测。

输入:PytestRun(stdout 为 `pytest --tb=short` 的输出)
产出:Feedback(含失败用例 nodeid、分类、文件:行号、traceback 摘录、断言差异)
设计要点:
- 不改测试断言(fixture 是契约);若正则与 fixture 不匹配,调正则不调断言。
- assertion_diff 优先取自 FAILED 行的 `- <diff>` 残段,缺省时回退到 traceback 内
  `E  assert ...` 行(`_ASSERT_LINE` 兜底),确保任何格式都能拿到断言差异。
"""
from __future__ import annotations
import re
from coding_agent_harness.models import PytestRun, Feedback, FailedTest
from coding_agent_harness.feedback.taxonomy import FailureCategory


# FAILED tests/test_calc.py::test_add - assert 4 == 5
# ERROR tests/test_x.py::test_x(无 diff 段)
_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) (?P<nodeid>\S+)(?: - (?P<diff>.*))?$")
# _________________________________ test_add ___________________________________
# _____________________________ ERROR at setup of test_x ________________________
# 取中段最后一个 token 作为测试名(test_add / test_x)
_FAIL_HEADER = re.compile(r"^_+ (?P<middle>.+?) _+$")
# tests/test_calc.py:5: AssertionError
_TB_LOC = re.compile(r"^(?P<file>[^\s]+):(?P<line>\d+): (?P<err>\w+Error)$")
# E       assert 4 == 5 —— assertion_diff 的兜底来源
_ASSERT_LINE = re.compile(r"E\s+assert\s+(?P<diff>.+)")
# 1 failed, 1 passed in 0.05s / = 1 error in 0.04s =
_SUMMARY = re.compile(r"(\d+) (failed|passed|error)")


def _classify(err_word: str, diff: str | None) -> FailureCategory:
    """根据 err 单词与 diff 文本推断失败分类。确定性:相同输入永远相同输出。"""
    w = err_word.lower()
    if "assert" in w or (diff and "assert" in diff):
        return FailureCategory.AssertionFailure
    if "importerror" in w or "modulenotfound" in w:
        return FailureCategory.ImportError
    if "attributeerror" in w:
        return FailureCategory.AttributeError
    if "nameerror" in w:
        return FailureCategory.NameError
    if "typeerror" in w:
        return FailureCategory.TypeError
    if "syntaxerror" in w:
        return FailureCategory.SyntaxError
    if "collection" in w:
        return FailureCategory.CollectionError
    return FailureCategory.Unknown


class Validator:
    @staticmethod
    def parse(run: PytestRun, max_excerpt_lines: int = 8) -> Feedback:
        stdout = run.stdout.replace("\r\n", "\n").replace("\r", "\n")
        lines = stdout.splitlines()
        failed: list[FailedTest] = []
        summary_bits: list[str] = []
        for ln in lines:
            # 一行可能含多个摘要段(如 `1 failed, 1 passed`),用 finditer 全取
            for m in _SUMMARY.finditer(ln):
                summary_bits.append(f"{m.group(1)} {m.group(2)}")

        # 扫 FAILED 行拿 nodeid + diff(若 fixture 含该段)
        fail_index: dict[str, str | None] = {}
        for ln in lines:
            m = _FAILED_LINE.match(ln)
            if m:
                fail_index[m.group("nodeid")] = m.group("diff")

        # 扫 traceback 块(header _ name _)拿 file:line + err
        cur_nodeid: str | None = None
        excerpt: list[str] = []
        for ln in lines:
            mh = _FAIL_HEADER.match(ln)
            if mh:
                # header 中段取最后一个 token 作为测试名(test_add / test_x);
                # nodeid 已在 FAIL_HEADER 捕获不到全路径,改从 fail_index 中按名匹配
                name = mh.group("middle").split()[-1]
                cur_nodeid = _match_nodeid_by_name(fail_index, name)
                excerpt = []
                continue
            if cur_nodeid:
                mt = _TB_LOC.match(ln)
                if mt:
                    diff = fail_index.get(cur_nodeid)
                    # 兜底:FAILED 行无 diff 时,从 traceback 内 `E  assert` 行抽
                    if diff is None:
                        for e in excerpt:
                            am = _ASSERT_LINE.search(e)
                            if am:
                                diff = "assert " + am.group("diff")
                                break
                    failed.append(FailedTest(
                        nodeid=cur_nodeid,
                        category=_classify(mt.group("err"), diff),
                        file=mt.group("file"),
                        line=int(mt.group("line")),
                        traceback_excerpt="\n".join(excerpt[-max_excerpt_lines:]),
                        assertion_diff=diff,
                    ))
                    cur_nodeid = None
                else:
                    excerpt.append(ln)

        status = "PASS" if run.exit_code == 0 and not failed else "FAIL"
        passed = 0
        for b in summary_bits:
            if b.endswith("passed"):
                passed = int(b.split()[0])
        summary = ", ".join(summary_bits) if summary_bits else stdout.strip().splitlines()[-1]
        return Feedback(status=status, failed_tests=failed, passed_count=passed, summary=summary)


def _match_nodeid_by_name(index: dict[str, str | None], name: str) -> str | None:
    """从 fail_index 中找到 `::` 后名字匹配的 nodeid;找不到回退到第一个。"""
    for nid in index:
        if nid.split("::")[-1] == name:
            return nid
    return next(iter(index), None)
