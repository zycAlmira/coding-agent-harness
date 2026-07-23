# AGENT_LOG.md

按时间顺序记录关键节点。每条:时间戳、task、Superpowers 技能、关键 prompt/context、subagent 输出/commit、人工干预、教训。

基准时区:本地。ts_provider 在代码里返回固定字符串(不在循环内取系统时间)。

---

## 2026-07-22 开工前

- 技能链:`superpowers:brainstorming` → `superpowers:writing-plans` → `superpowers:subagent-driven-development`。
- brainstorming 沉淀 `docs/superpowers/specs/2026-07-21-coding-agent-harness-design.md`;writing-plans 产出 `docs/superpowers/plans/2026-07-22-coding-agent-harness.md`(24 task + Task 15b HITL 补充)。
- 用户决策:① git init + main 初始 commit + worktree;② 先做冷启动验证(§4.5);③ 连跑全 24 task。
- 人工干预:尝试 `EnterWorktree` 建 worktree,工具因会话启动时缓存的"非 git 仓库"状态拒绝进入(此时仓库已 init)。**偏离 §4.6 worktree 隔离要求**:回退为在主仓库开 `feature/coding-agent-harness` 特性分支实现。原因:工具无法切换会话 cwd。补偿:仍满足 §4.7"每功能一 PR"——用分支+PR;隔离性弱于 worktree,但实际无并行实现冲突(单实现者顺序推进)。
- 偏离记录:冷启动验证(§4.5)要求"第二个智能体类型必须不同"。本环境仅 Claude 系列可用,冷启动 subagent 用 `general-purpose` 类型(与主会话默认 `claude` 不同),满足"类型不同";但其底层模型同源——记为部分满足,REFLECTION 中讨论。
- git:main 上初始 commit `f07f8cd`(项目文档+SPEC+PLAN)。实现分支 `feature/coding-agent-harness`。

## 冷启动验证(§4.5)

- 用 general-purpose subagent 仅凭 SPEC+PLAN 跑 Task 1-2,记录 6 项 spec/plan 缺陷(@dataclass Verdict 字段顺序、--no-header 笔误、None 覆盖默认等),据此修订 SPEC/PLAN,写入 `SPEC_PROCESS.md`。冷启动不占用正式 Task 1/2——正式实现从干净重跑。commit 已 reset 回 `f07f8cd` 丢弃,过程证据见 SPEC_PROCESS。

## Task 1-14:脚手架到停机判断(机械→judgment)

技能:TDD 红→绿→重构;审查 superpowers:requesting-code-review 两阶段(spec 合规→代码质量)。模型:1-2 文件用 cheap,多文件/审查用 standard。

- **Task 1 脚手架** `76d6031..2036933` review Approved。Minor:ruff 未进 dev deps(后续 Task 22 闭合)。
- **Task 2 models** `..208b6ad`。冷启动缺陷4:Verdict @dataclass 字段顺序 TypeError,实现者用 `field(kw_only=True)` 修(接口不变)。**教训:实现者曾谎称"逐字一致",审查核对纠正**——信任但验证。
- **Task 3 config** `..de139cc + 44ee2ac`。Critical:`--no header`→`--no-header`(笔误);Important:None 值覆盖默认(加 `is not None` 守卫)+ 加固测试。
- **Task 4 taxonomy**。
- **Task 5 validator** `e39be09..0a10f57 + 3b25c9d`。主贡献核心,纯函数。Important:`_ASSERT_LINE` 兜底分支补 fixture+测试。遗留:`_FAIL_HEADER` 末 token 对参数化用例名脆弱——Task 15 接真实 pytest 时暴露。
- **Task 6 files** `..25d5325`。**Task 7 shell** `..2248e66`(Windows shlex 弱点登记 follow-up)。**Task 8 pytest runner** `..3d8555d`(fixture 挪 repo 根 fixtures/sample_pkg 避免污染主套件)。**Task 9 dispatch** `..ed5a15a`。**Task 10 memory** `..7614d2a`(timestamp 由调用方传入避非确定)。**Task 11 guardrail** `..470eb68 + 132e3c5`。§A.4 核心纯函数。Important:白名单子串匹配可被 `pytest_evil` 绕过→改精确首词匹配(shlex)+ 绕过测试。**安全教训:子串匹配是危险侧通道**。**Task 12 llm base** `..43f7a72`。**Task 13 MockLLMClient** `..92e5fff`(4 种 when 分支,不触网零时钟)。**Task 14 state** `..1e14e4f`(no_change_streak 按 brief 实现注意对齐测试契约,改 impl 不改测试)。

## Task 15:AgentLoop 主循环(主贡献集成,重点)

`06dd215..159da3e` review Approved。自实现主循环:上下文→LLM→护栏→分发→校验→回灌→停机。集成测试红变绿确定性复现 §A.6 ②(反馈闭环使 agent 改变下一步)。

**跨 task 连带修两遗留 bug**(教训:早期 Minor 不闭合会害集成):
1. validator 兼容真实 `--tb=short`(Task 5 遗留):原 `_TB_LOC` 只匹配位置行在 assert 后的格式;真实 `--tb=short` 位置行在 assert 前(`file:line: in test_name`)。改延迟 flush(`_flush_failed` 纯函数)兼容两种顺序 + tb_short.txt 单测。
2. tests_runner 清 `__pycache__`(Task 8 遗留,致集成测试 flaky ~80%):根因是 Python `.pyc` 次秒级 mtime 冲突——同一秒内多次改写源文件,mtime 不变,Python 误判旧 pyc 有效→导入旧字节码→"改了却没生效"。加 `_clear_bytecode_cache`(rglob 删)+ `PYTHONDONTWRITEBYTECODE=1`。10x 连跑全绿。

**教训:pyc mtime 次秒冲突是 Python 确定性测试的隐形杀手;`PYTHONDONTWRITEBYTECODE` 应是测试默认。**

## Task 15b:HITL 完整化

`68936f4 + 70dee70`。threading.Event 挂起→approve→恢复。approval_id 自增计数器(确定性,非 uuid)。审查 Important(锁纪律:`_suspend_for_approval` 返回后 decision 读取/pending 置 None 原在锁外)已修(锁内原子取回)。

## Task 16-21:凭据→WebUI→CLI

- **Task 16 keychain** `245f958`。Creds 包 keyring:set/get/status(只返回 `{'set':bool}`)/clear。in-memory 后端测试不触真实 keychain。
- **Task 17 openai_compat** `c34effa`。OpenAICompatibleClient(httpx + function-calling)。key 只进 Authorization header 不进体/日志。修 plan 测试三处内部矛盾(fake R 补 raise_for_status、fake_post 补 timeout kwarg、key 检查改只查 body)。**教训:plan 内部矛盾常在实现时才暴露,需逐条核 plan 测试与实现签名。**
- **Task 18 §A.6 三 demo** `16d2e2d + 42308d4`。① 护栏拦截 DeleteFile→NeedsApproval+intent;② 反馈闭环 round1 错值→FAIL→改对→PASS;③ 连续同类失败注入"换思路"提示,no_change=3→stuck。修 plan bug:demo②③ mock 原写正确值致转折/stuck 永不触发,改错值 a+b+2 起步;demo③ 调阈值使 prompt 与 stop 分轮。
- **Task 19 FastAPI 后端** `9209cde + aacc8df`。SSE + HITL 审批端点 + 凭据端点。审查 Important(runner 无 try/finally 致 SSE 无限阻塞)已修。filterwarnings 静音 `starlette.exceptions.StarletteDeprecationWarning`(非 DeprecationWarning 子类,按类别过滤)。
- **Task 20 单页前端** `1d02173 + 4f44626`。Open Design token + SSE timeline + 凭据模态。pending_approval 事件→前端渲染[通过][拒绝]按钮。审查 Important(app.py 未开 hitl_enabled 致审批链路死代码)已修(threading.Thread 驱动避 TestClient anyio task group 挂起 + E2E 测试)。**教训:HITL 默认 False 保旧测试不变是正确取舍,但 WebUI 运行态必须开,审查拦住了这处接线遗漏。**
- **Task 21 CLI** `022a3c9 + 0bd075c`。serve/creds/run。api_key 用 getpass 隐藏录入不进 history;status 不回显。测试用 in-memory keyring(替代 plan 的 setenv HOME,避免碰真实 Keychain)。审查 Minor(run 缺 config.yaml 抛 traceback)已修。

## Task 22-24:CI/分发/README(收尾三件套)

- **Task 22 CI** `ac5b088 + e5f73c3`。`.gitlab-ci.yml`:stages=[test,build];`unit-test` job(§五.6 硬要求,`uv sync --frozen`+`uv run pytest -q`);`build-image` job(docker-in-docker,仅 main+exists Dockerfile)。`test_ci_config.py` 6 单测(PyYAML 解析,§A.4:配置也可验证)。**顺带闭合 Task 1 Minor**(ruff 进 dev deps,`make lint` 35→0)+ models.py F821/E402(TYPE_CHECKING + Any 移顶)。取舍:§4.8 提 GitHub Actions 但 §五.6 硬要求 gitlab-ci.yml,以后者为准。
- **Task 23 Dockerfile+云部署** `9641433 + 补强`。容器分发(§3.2)+ Fly.io(§4.11)。Dockerfile:python:3.12-slim+uv 二进制,依赖层与源码层分离,EXPOSE 8000,HEALTHCHECK python urllib,CMD `harness serve`(mock)。test_dockerfile.py 8 单测。**限制(诚实)**:本地 docker daemon 未运行,实际构建由 CI build-image job(docker:dind)验证;§五.9 线上 URL 需用户在 Fly.io 注册后执行 deploy.sh 产生(AI 无法代持云 token)。
- **Task 24 README** `d3a8b0d + 补强`。10 章节(§五.4 必含六章节 + 凭据/部署架构/机制演示/已知限制)。安全边界实质(护栏白/黑名单+HITL+intent+mock 不触网+路径围栏)。test_readme.py 6 单测。顺带修 test_dockerfile E741(l→line)。

## 根目录 SPEC.md/PLAN.md 软链

软链指向 docs/superpowers/{specs,plans}/ 下事实源,满足通用 §五.1 根目录 SPEC.md/PLAN.md 文件名要求,单一来源避免重复维护。

## 全程教训汇总

1. **TDD 红→绿在 AI 协作下是放大器**:红测试是"规格的可执行形式",迫使 plan 把模糊处钉死;先实现再补测试会放过 plan 内部矛盾(Task 17/18/19/20 均在实现时发现 plan 测试与签名不符)。
2. **早期 Minor 不闭合会害集成**:Task 5/8 的 Minor 在 Task 15 集成测试以 flaky/解析失败形式爆发,代价远高于当时修补。
3. **pyc mtime 次秒冲突**是 Python 确定性测试的隐形杀手,`PYTHONDONTWRITEBYTECODE` 应作测试默认。
4. **子串匹配是危险侧通道**:护栏白名单子串匹配被 `pytest_evil` 绕过,安全侧必须精确匹配 + 绕过测试。
5. **plan 内部矛盾逐条核**:实现者不能照搬 plan 测试,必须与已实现模块签名逐条核对(fake R 补方法、demo mock 起步值、runner try/finally、hitl_enabled 接线)。
6. **诚实记录限制 > 掩盖**:本地 docker daemon 未运行、§五.9 URL 待用户部署、容器 keychain 文件后端、Windows shlex、冷启动样本——均如实记于 README/AGENT_LOG/REFLECTION,并以单测 + CI job 缓解。
7. **审查两阶段有效**:spec 合规(红线)先于代码质量,拦住 hitl_enabled 接线遗漏、锁纪律违规、runner 无 finally 等会致死锁/无限阻塞的 Important。
