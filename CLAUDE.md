# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目性质与当前状态

这是 **AI4SE 期末项目 · Project A · Coding Agent Harness**:一个**由学生自己编码实现**的 Coding Agent 内核,主贡献维度为**反馈闭环(feedback loop)**。**已实现完成**,全套 mock-LLM 确定性单测通过,CI 双平台通过。

完整要求 = `# AI4SE 期末项目 · 通用要求（所有项目必读）.md` + `AI4SE_Final_Project_A_Coding_Agent_Harness.md`。后者定义了 Coding Agent Harness 专属的硬性约束(§A.4 红线见下)。B 方向文件对本项目不适用。

- `SPEC.md`/`PLAN.md` 是指向 `docs/superpowers/` 下文档的软链接;实施进度以 PLAN 中 task 标记与 git 历史为准。
- 需求/架构/安全边界细节在 `README.md` 有完整叙述,本文件不再重复,只记录需要读多个文件才能理解的架构与纪律。

## 常用命令

需 Python >= 3.11,用 uv 管理依赖:

```bash
uv sync --extra dev        # 安装含 pytest/ruff 的开发依赖
make test                  # 等价 uv run pytest -q(全套件,不触网)
make lint                  # uv run ruff check src tests
make run                   # 等价 uv run harness serve(mock LLM WebUI)
uv run pytest tests/demo/ -v                    # 机制演示(§A.6 三个演示)
uv run pytest tests/unit/test_guardrail.py -q  # 单个测试文件
uv run harness serve [--real] [--project-root <path>]  # WebUI,默认 mock 模式
uv run harness creds {status|set|clear}        # keychain 凭据(不回显)
uv run harness run "<task>"                    # CLI 用真实 LLM 跑一次任务
```

所有测试零网络、零时钟、确定性(mock LLM 脚本化分支驱动),本地无需任何 API key。

## 架构:数据流与模块职责

**agent 主循环只有一条**(`core/loop.py::AgentLoop.run`),每轮:组织上下文 `_build_messages` → `llm.complete` → 解析出 `AssistantTurn(action, intent)` → `guardrail` 判定 → `dispatch` 执行 → 若是 RunTests 则 `Validator.parse` 校验 → `update_after_feedback`/`decide_stop` → 下一轮或停机;停机后 `_record_memory` 写记忆。

各模块(自实现,不寄生任何 agent 框架):

- `models.py` — 值类型中心:动作联合类型 `Action`(WriteFile/DeleteFile/RunShell/RunTests/ReadFile/ListDir/Stop/Respond,frozen dataclass 不可变)、护栏三分支 `Verdict`(Allow/Deny/NeedsApproval)、`AssistantTurn`/`ToolResult`/`Feedback`/`Fix`/`Step`/`RunResult`。**陷阱**:`FailedTest.category` 是 TYPE_CHECKING 下的字符串前向引用,由 `feedback/validator.py` 真正 import `FailureCategory` 后解析;新增直接构造 `FailedTest` 的代码需先 import 使注解可解析,或用 `typing.get_type_hints`。
- `core/state.py` — `LoopState` + `update_after_feedback`/`decide_stop`,全部纯函数。停机判定优先级:max_rounds > 连续同类失败(stuck)> 连续同一失败集合(stuck)。PASS 后不再自动判 success,留给 agent 一轮机会文字总结再 Stop。
- `llm/` — `base.py` 抽象 `LLMClient`(可注入 mock);`mock.py` 脚本化分支客户端;`openai_compat.py` 真实 OpenAI 兼容客户端(key 只进 Authorization header)。
- `tools/dispatch.py` — match-action 分发到 files/shell/tests_runner 三个工具模块;`RunTests` 的 `ToolResult.structured` 携带 `PytestRun` 供反馈校验器解析。
- `guardrails/guardrail.py` — 纯函数。删除文件一律 NeedsApproval;写文件按 `project_root` 路径围栏(`resolve()` 防 `../` 逃逸);shell 黑名单**子串匹配**优先 Deny、白名单**精确首词匹配**(shlex 取第一个 token)放行、其余 NeedsApproval;只读动作 Allow。
- `feedback/validator.py` — 纯函数解析 pytest stdout 为结构化 `Feedback`(失败分类 `FailureCategory` + nodeid/文件:行/traceback 摘录/断言差异),兼容 `--tb=short` 与手工 fixture 两种位置行顺序(延迟 flush);`taxonomy.py` 每分类对应一条确定性策略提示 `strategy_hint`。
- `memory/store.py` — JSON 分类索引,`retrieve` 按 `FailureCategory` 精确匹配取 top-k(纯函数)。
- `creds/keychain.py` — macOS Keychain 安全存储,`status` 不回显明文。
- `web/app.py` — FastAPI + SSE 事件流 + HITL 审批端点。**循环在后台线程跑**:`hitl_enabled=True` 时 `run()` 阻塞,必须由 WebUI/CLI 驱动方线程化。

## 确定性纪律(新代码必须遵守,§A.4 判定标准)

项目立身之本:**移除真实 LLM 后每个机制都要能确定性单测**。已有代码全部遵循,新增代码不得破坏:

1. **循环内不取系统时间**:`ts` 一律由调用方经 `ts_provider` 注入(mock 测试传固定字符串)。
2. **不用 uuid/随机**:HITL `approval_id` 用自增计数器,保证同脚本下可复现。
3. **记忆只在循环外写**:`_record_memory` 在 `run()` 返回前、循环结束后调用;循环中只读检索。
4. **纯函数边界**:guardrail / Validator.parse / state 更新 / memory 检索 / dispatch 分支均为无副作用纯函数,可独立单测。
5. **对话历史回灌统一用 "user" 角色**(含工具结果),不用 assistant/tool 角色——`Message` 抽象只有 role+content,表达不了 OpenAI function-calling 的 tool_calls 结构。
6. **连续 2 次纯文本 Respond(中间无工具调用)自动停机**,防止 LLM 只说不停;`_consecutive_responds` 计数在工具调用时清零。

## 测试与 mock LLM 模式

- `tests/unit/` — 机制单测(护栏/分发/校验器/状态/记忆/凭据/配置/CI 配置本身);`tests/integration/` — loop 全链路、HITL、WebUI;`tests/demo/` — §A.6 三个机制演示(护栏拦截、反馈闭环改变下一步、停机与策略切换)。
- `MockLLMClient` 注入**脚本**(有序 `{"when", "action", "intent"}` 条目),`complete` 据当前 LoopState 选**第一个匹配**分支;when 支持 `always` / `round N` / `feedback.category == X` / `feedback.status == X`。**无匹配分支抛 RuntimeError 而非静默兜底**——脚本写错会直接暴露。
- 写 loop 级测试的标准三段式:临时目录 + `shutil.copytree(fixtures/sample_pkg)` 拷贝故意失败的夹具 + 脚本化 mock;注意脚本条目顺序——具体轮次分支(`round 4`)要排在 `feedback.category` 类分支**之前**,否则被抢占。
- `tests/unit/test_ci_config.py` 等"配置即测试"守护 CI 配置/Dockerfile/README 的合规性(§A.4 精神)。

## 最核心的纪律(违反即不合格)

来自 §A.4,本项目红线,**任何代码工作开始前必须牢记**:

1. **必须自己实现 harness 内核**:agent 主循环(组织上下文 → 调 LLM → 解析动作 → 分发执行 → 回灌结果 → 停机判断)、可注入 mock 的 LLM 抽象层、工具分发、治理护栏、反馈校验器、记忆读写。
2. **禁止寄生于现成 agent 框架的高层循环**:不能用 LangChain `AgentExecutor`、AutoGen、CrewAI、LlamaIndex agent 或某编码智能体 SDK 自带的 agent runner 充当产物。允许使用底层零件(单次对话补全 API、HTTP 库、向量库、解析库)。
3. **机制必须是代码,不是提示词**:反馈信号 = 确定性校验器/传感器;危险动作拦截 = `guardrail(action)` 函数。"提醒 LLM 注意安全"这种提示词不算实现。
4. **判定标准:移除真实 LLM 后,机制能否用单测验证?** 每个核心机制替换为 mock/stub LLM 后仍能用确定性单测验证,才算编码实现。配置/规则/技能/提示词文件属于"内容物",不计入 harness 工作量。
5. **基础要完整,重点要深入**:决策/工具/记忆/治理/反馈/配置六维度都要有可运行最低实现;本项目选择**反馈闭环**做深(validator 分类 + 策略提示回灌 + 状态机停机 + 修复记忆)。
6. **开发工具 vs 交付产物的界线**:开发时可用 Claude Code / Superpowers 的子 agent、Skill、hooks、memory 辅助写代码;但交付的 harness 内核必须自己运转,不能让宿主框架的 agent loop / Skill / 治理钩子充当产物功能。

## 强制工作流程(Superpowers 七步)

通用要求 §4 规定的流程。**SPEC/PLAN 已产出并通过冷启动验证**(见 `SPEC_PROCESS.md`、`SPEC_PROCESS_coldstart_report.md`),后续改动仍须遵守:每功能/大模块一 worktree 一 PR;每 task 派新鲜 subagent;TDD 强制(红→绿→重构,先写失败测试再写实现);每 task 两阶段评审(spec 合规 → 代码质量,Critical 必修)后 `finishing-a-development-branch`;commit/PR 描述标注由哪个 subagent 完成、人工改了哪些;PLAN.md 每完成一 task 即标记并附 commit hash。任何偏离必须在 `AGENT_LOG.md` 中记录与解释。

## 交付物清单与安全硬要求(简版,详见 README)

- 交付物:`SPEC.md`/`PLAN.md`/`SPEC_PROCESS.md`、完整源码 + mock 驱动确定性单测、§A.6 机制演示、分发产物(Dockerfile)、`README.md`(含安全边界说明)、`AGENT_LOG.md`、CI(`.gitlab-ci.yml` 含 `unit-test` job)、`REFLECTION.md`(1500-2500 字本人撰写)、线上可访问 WebUI。
- **凭据**:LLM/付费 API key 绝不硬编码、绝不进 git(含历史)、不进日志/shell history/明文配置;经 keychain 隐藏录入,查看不回显。仓库内不得出现任何真实凭据,提交前自查 `.env`、history、配置文件。

## 与本会话交互的约定

- 永远用中文回答。
- 终端回答不用 LaTeX、`$...$` 等无法直接理解的表达;复杂公式/图表/密集版面改用图片或 PDF 表达。
