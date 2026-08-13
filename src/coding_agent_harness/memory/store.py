"""分类索引记忆 store。自实现,不接框架 memory。检索是纯函数,确定。"""
from __future__ import annotations
import json
from pathlib import Path
from coding_agent_harness.models import Fix
from coding_agent_harness.feedback.taxonomy import FailureCategory


class Memory:
    def __init__(self, fixes_path: Path | str, conventions_path: Path | str, top_k: int = 3):
        self.fixes_path = Path(fixes_path)
        self.conventions_path = Path(conventions_path)
        self.top_k = top_k

    def _load_fixes(self) -> list[Fix]:
        # 不存在视为空库;读取用 UTF-8 以正确处理中文 symptom/fix。
        if not self.fixes_path.exists():
            return []
        data = json.loads(self.fixes_path.read_text(encoding="utf-8"))
        return [Fix(**d) for d in data]

    def retrieve(self, category: FailureCategory) -> list[Fix]:
        # 纯函数检索:按分类精确匹配,取最近 top_k 条(尾部切片)。
        all_fixes = self._load_fixes()
        matched = [f for f in all_fixes if f.category == category.value]
        return matched[-self.top_k :] if self.top_k else matched

    def record_fix(self, fix: Fix) -> None:
        # 仅在任务结束时调用(循环内不写),追加后整体落盘。
        all_fixes = self._load_fixes()
        all_fixes.append(fix)
        self.fixes_path.parent.mkdir(parents=True, exist_ok=True)
        self.fixes_path.write_text(
            json.dumps([f.__dict__ for f in all_fixes], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_conventions(self) -> list[str]:
        # 约定为 key/value 项列表,拼成可读字符串回灌给 agent。
        if not self.conventions_path.exists():
            return []
        data = json.loads(self.conventions_path.read_text(encoding="utf-8"))
        return [f"{d.get('key','')}: {d.get('value','')}" for d in data]
