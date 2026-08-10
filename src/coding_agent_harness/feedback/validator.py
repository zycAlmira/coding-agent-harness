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
# 注意 nodeid 用 `.*?` 而非 `\S+`:参数化用例名可含空格(如
# `test_echo[hello world]`),`\S+` 在空格处截断致整行不匹配、fail_index 为空。
_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) (?P<nodeid>.*?)(?: - (?P<diff>.*))?$")
# _________________________________ test_add ___________________________________
# _____________________________ ERROR at setup of test_x ________________________
_FAIL_HEADER = re.compile(r"^_+ (?P<middle>.+?) _+$")
# tests/test_calc.py:5: AssertionError   (--tb=line / 手工 fixture 的位置行,带 err 词)
_TB_LOC = re.compile(r"^(?P<file>[^\s]+):(?P<line>\d+): (?P<err>\w+Error)$")
# tests/test_calc.py:5: in test_add   (真实 `pytest --tb=short` 的位置行,无 err 词)
# 该格式位置行出现在 assert 行之前(与 _TB_LOC 顺序相反),需延迟 flush(见 parse)。
_TB_LOC_SHORT = re.compile(r"^(?P<file>[^\s]+):(?P<line>\d+): in \S+$")
# ================ FAILURES ================ / ============ short test summary info ============
# 分节分隔行,标志一个失败块结束。
_SECTION_SEP = re.compile(r"^=+ .+ =+$")
# E       assert 4 == 5 —— assertion_diff 的兜底来源;
# 兼容两种真实 pytest 格式:短路信息 `E   assert 6 == 5`
# 与完整异常 `E   AssertionError: assert 'hello world' == 'different'`
# (无短路信息时 E 行带 AssertionError 前缀)。
_ASSERT_LINE = re.compile(r"E\s+(?:AssertionError:\s*)?assert\s+(?P<diff>.+)")
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
        # Maven surefire 输出(Java 项目,run_tests 用 mvn test 产生)走独立解析
        if "Tests run:" in stdout and ("surefire" in stdout or "Results:" in stdout):
            return _parse_maven(run, max_excerpt_lines)
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

        # 扫 traceback 块(header _ name _)拿 file:line + err。
        # 兼容两种位置行顺序:
        #   ① 手工 fixture / --tb=line:位置行 `file:line: ErrorType` 在 assert 行之后;
        #   ② 真实 `pytest --tb=short`:位置行 `file:line: in test_name` 在 assert 行之前。
        # 故不再于见到位置行时立即 append,而是先收集整个失败块的 excerpt,
        # 在块结束(下一个 header / 分节分隔行 / 末尾)时统一 flush。
        cur_nodeid: str | None = None
        pending: tuple[str, str, str] | None = None   # (file, line, err)
        excerpt: list[str] = []
        for ln in lines:
            mh = _FAIL_HEADER.match(ln)
            if mh:
                # 进入新失败块前,flush 上一块(若有)。
                _flush_failed(failed, cur_nodeid, pending, excerpt, fail_index, max_excerpt_lines)
                pending = None
                # header 中段提取测试名;nodeid 在 FAIL_HEADER 捕获不到全路径,
                # 改从 fail_index 中按名匹配。
                cur_nodeid = _match_nodeid_by_name(fail_index, _extract_name(mh.group("middle")))
                excerpt = []
                continue
            if cur_nodeid is None:
                continue
            mt = _TB_LOC.match(ln)
            if mt:
                pending = (mt.group("file"), mt.group("line"), mt.group("err"))
                continue
            ms = _TB_LOC_SHORT.match(ln)
            if ms:
                # 真实 --tb=short 位置行无 err 词,留空串,分类交由 diff 兜底
                # (excerpt 内 `E  assert` 行 → AssertionFailure)。
                pending = (ms.group("file"), ms.group("line"), "")
                continue
            if _SECTION_SEP.match(ln):
                _flush_failed(failed, cur_nodeid, pending, excerpt, fail_index, max_excerpt_lines)
                pending = None
                cur_nodeid = None
                continue
            excerpt.append(ln)
        _flush_failed(failed, cur_nodeid, pending, excerpt, fail_index, max_excerpt_lines)

        status = "PASS" if run.exit_code == 0 and not failed else "FAIL"
        passed = 0
        for b in summary_bits:
            if b.endswith("passed"):
                passed = int(b.split()[0])
        summary = ", ".join(summary_bits) if summary_bits else stdout.strip().splitlines()[-1]
        return Feedback(status=status, failed_tests=failed, passed_count=passed, summary=summary)


def _parse_maven(run: PytestRun, max_excerpt_lines: int) -> Feedback:
    """解析 Maven surefire 测试输出(Java 项目,test_command='mvn test')。

    格式:
      [ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0 ... <<< FAILURE!
      [ERROR] testShift  Time elapsed: 0.02 s  <<< FAILURE!
      KWICTest.java:45: expected:<[2, 1]> but was:<[1, 2]>
      [INFO] Results:
      [INFO] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0
    确定性纯函数,与 pytest 解析同一 Feedback 结构。
    """
    stdout = run.stdout.replace("\r\n", "\n").replace("\r", "\n")
    lines = stdout.splitlines()
    # 汇总:Results: 下的 "Tests run: N, Failures: F, Errors: E, Skipped: S"
    total = failures = errors = skipped = 0
    in_results = False
    for ln in lines:
        if "Results:" in ln:
            in_results = True
            continue
        if in_results and "Tests run:" in ln:
            m = re.search(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)", ln)
            if m:
                total, failures, errors, skipped = map(int, m.groups())
                break
    failed: list[FailedTest] = []
    for i, ln in enumerate(lines):
        # 失败块:[ERROR] testXxx  Time elapsed: ... <<< FAILURE!
        m = re.search(r"\[ERROR\]\s+(\w+)\s+Time elapsed:.*<<< FAILURE!", ln)
        if not m:
            continue
        name = m.group(1)
        # 后续行找 file:line 与 expected/assert 差异
        file, line, diff = "", 0, None
        for j in range(i + 1, min(i + 5, len(lines))):
            fl = re.match(r"^([\w./-]+\.java):(\d+):\s*(.*)$", lines[j].strip())
            if fl:
                file, line = fl.group(1), int(fl.group(2))
                if fl.group(3):
                    diff = fl.group(3)
                break
            if diff is None and ("expected" in lines[j].lower() or "assert" in lines[j].lower()):
                diff = lines[j].strip()
        failed.append(FailedTest(
            nodeid=name, category=FailureCategory.AssertionFailure if (diff and "assert" in diff.lower() or "expected" in diff.lower()) else FailureCategory.Unknown,
            file=file, line=line, traceback_excerpt="\n".join(lines[i:i + max_excerpt_lines]),
            assertion_diff=diff,
        ))
    passed = max(0, total - failures - errors - skipped)
    summary = f"{failures + errors} failed, {passed} passed, {skipped} skipped"
    status = "PASS" if run.exit_code == 0 and not failed else "FAIL"
    return Feedback(status=status, failed_tests=failed, passed_count=passed, summary=summary)


def _extract_name(middle: str) -> str:
    """从失败块 header 中段提取测试名。

    兼容三种形态:
    - 非参数化 `test_add` → 取最后一个 token;
    - 参数化含空格 `test_echo[hello world]` → 取含 `[` 的 token 起 join 到末尾
      (末 token 是 `world]`,`split()[-1]` 会取错);
    - 说明词前缀 `ERROR at setup of test_x[param]` → 跳过说明词取含 `[` 的 token。
    """
    tokens = middle.split()
    for i, t in enumerate(tokens):
        if "[" in t:
            return " ".join(tokens[i:])
    return tokens[-1]


def _match_nodeid_by_name(index: dict[str, str | None], name: str) -> str | None:
    """从 fail_index 中找到 `::` 后名字匹配的 nodeid;找不到回退到第一个。"""
    for nid in index:
        if nid.split("::")[-1] == name:
            return nid
    return next(iter(index), None)


def _flush_failed(failed, nodeid, pending, excerpt, fail_index, max_excerpt_lines):
    """把一个已收集完的失败块落成 FailedTest。

    纯函数式:只读入参,向 failed 列表 append。在失败块结束(下一个 header /
    分节行 / 输入末尾)时由 parse 调用。延迟 flush 使其兼容 `--tb=short`
    (位置行在 assert 行前)与手工 fixture(位置行在 assert 行后)两种顺序。
    """
    if nodeid is None or pending is None:
        return
    file, line, err = pending
    diff = fail_index.get(nodeid)
    # 兜底:FAILED 行无 diff 或 diff 是 pytest 截断形式(`a...`,超长短路信息
    # 被截断,无分类价值)时,从 traceback 内 `E  assert` 行抽完整 diff。
    if diff is None or (diff.endswith("...") and len(diff) <= 50):
        for e in excerpt:
            am = _ASSERT_LINE.search(e)
            if am:
                diff = "assert " + am.group("diff")
                break
    failed.append(FailedTest(
        nodeid=nodeid,
        category=_classify(err, diff),
        file=file,
        line=int(line),
        traceback_excerpt="\n".join(excerpt[-max_excerpt_lines:]),
        assertion_diff=diff,
    ))
