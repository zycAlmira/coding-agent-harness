# Subagent-Driven Development 进度账本

> 恢复地图:compaction 后据此 + `git log` 判断进度,勿重复派发已完成 task。
> 基线 commit(主干):`f07f8cd docs: 项目文档与 SPEC/PLAN 初始提交`。
> 实现分支:`feature/coding-agent-harness`。

## 已完成

- [x] 冷启动验证(§4.5):general-purpose subagent 跑 Task 1-2,6 项 spec/plan 缺陷已修订。commit 已 reset 回 `f07f8cd` 丢弃,过程证据见 `SPEC_PROCESS.md`。冷启动不占用 Task 1/2 的正式执行——正式实现从干净 Task 1 重跑。

## 待执行(Task 列表)

- [ ] Task 1: 项目脚手架与依赖
- [ ] Task 2: 值类型与数据模型 models.py
- [ ] Task 3: 配置 config.py
- [ ] Task 4: 失败分类 taxonomy
- [ ] Task 5: 反馈校验器 Validator.parse
- [ ] Task 6: 工具 文件操作
- [ ] Task 7: 工具 跨平台 shell
- [ ] Task 8: 工具 pytest 运行器
- [ ] Task 9: 工具分发 dispatch
- [ ] Task 10: 记忆 store
- [ ] Task 11: 治理护栏 guardrail
- [ ] Task 12: LLM 抽象层 base
- [ ] Task 13: MockLLMClient
- [ ] Task 14: 循环状态与停机判断 state
- [ ] Task 15: AgentLoop 主循环
- [ ] Task 15b: HITL 完整化(补)
- [ ] Task 16: 凭据管理 keychain
- [ ] Task 17: 真实 LLM 客户端 openai_compat
- [ ] Task 18: §A.6 三个机制演示
- [ ] Task 19: FastAPI WebUI 后端
- [ ] Task 20: 单页前端
- [ ] Task 21: CLI 入口 main
- [ ] Task 22: CI 配置
- [ ] Task 23: Dockerfile 与云部署
- [ ] Task 24: README 与安全边界

## 模型选择策略

- 机械实现(1-2 文件、PLAN 给完整代码):cheap(haiku)
- 多文件集成/judgment:standard(sonnet)
- 架构/最终审查:most capable(opus)
- 审查者:按 diff 复杂度,默认 standard

## 偏离记录

- §4.6 worktree:EnterWorktree 工具因会话缓存状态拒绝,回退特性分支(见 AGENT_LOG)。
- §4.5 类型不同:仅 Claude 系列可用,用 general-purpose(类型不同但模型同源),部分满足。
- 冷启动样本仅 Task 1/2(信号量偏低,见 SPEC_PROCESS §5.5)。
