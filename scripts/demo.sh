#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
echo "== 演示 ① 护栏拦截 =="
uv run pytest tests/demo/test_demo_1_guardrail.py -v
echo "== 演示 ② 反馈闭环改变下一步 =="
uv run pytest tests/demo/test_demo_2_feedback_loop.py -v
echo "== 演示 ③ 策略切换与停机 =="
uv run pytest tests/demo/test_demo_3_strategy_and_stop.py -v
echo "== 全部演示通过 =="
