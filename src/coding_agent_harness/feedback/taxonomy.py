"""失败分类表 + 确定性建议策略。"""
from __future__ import annotations
from enum import Enum


class FailureCategory(str, Enum):
    AssertionFailure = "AssertionFailure"
    ImportError = "ImportError"
    AttributeError = "AttributeError"
    NameError = "NameError"
    TypeError = "TypeError"
    SyntaxError = "SyntaxError"
    CollectionError = "CollectionError"
    Timeout = "Timeout"
    Unknown = "Unknown"


# 每个分类对应一条确定性策略提示,反馈闭环会回灌给 agent
_HINTS: dict[FailureCategory, str] = {
    FailureCategory.AssertionFailure: "看断言两侧实际值,定位计算错误",
    FailureCategory.ImportError: "检查模块名拼写/路径或是否缺依赖",
    FailureCategory.AttributeError: "检查属性名拼写与对象类型",
    FailureCategory.NameError: "检查名字是否已定义/作用域",
    FailureCategory.TypeError: "检查参数类型与个数",
    FailureCategory.SyntaxError: "先让文件能被解析,再谈逻辑",
    FailureCategory.CollectionError: "导入阶段就报错,先修 import-time 错误",
    FailureCategory.Timeout: "测试卡住,检查是否有死循环或阻塞",
    FailureCategory.Unknown: "仔细阅读 traceback,定位报错来源",
}


def strategy_hint(category: FailureCategory) -> str:
    """返回某失败分类对应的确切策略提示。确定性:相同输入永远相同输出。"""
    return _HINTS[category]
