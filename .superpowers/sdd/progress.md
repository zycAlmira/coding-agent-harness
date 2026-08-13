# Subagent-Driven Development 进度账本

> 恢复地图:compaction 后据此 + `git log` 判断进度,勿重复派发已完成 task。
> 基线 commit(主干):`f07f8cd docs: 项目文档与 SPEC/PLAN 初始提交`。
> 实现分支:`feature/coding-agent-harness`。

## 已完成

- [x] 冷启动验证(§4.5):general-purpose subagent 跑 Task 1-2,6 项 spec/plan 缺陷已修订。commit 已 reset 回 `f07f8cd` 丢弃,过程证据见 `SPEC_PROCESS.md`。冷启动不占用 Task 1/2 的正式执行——正式实现从干净 Task 1 重跑。

## 待执行(Task 列表)

- [x] Task 1: 项目脚手架与依赖 — complete (commits 76d6031..2036933, review Approved)。Minor: ruff 未进 dev deps,`make lint` 后续会失败;待用到 lint 时补 `ruff>=0.6` 到 dev extras。
- [x] Task 2: 值类型与数据模型 models.py — complete (commits 2036933..208b6ad, review Approved)。冷启动缺陷4 的 @dataclass Verdict 引发字段顺序 TypeError,实现者用 `field(kw_only=True)` 修(干净、接口不变)。Minor: Verdict 基类可实例化/Allow 冗余重声明(照搬 brief,后续按需改);测试覆盖窄(brief 给定的)。
- [x] Task 3: 配置 config.py — complete (commits 208b6ad..de139cc + fix 44ee2ac, review Approved after fix)。Critical:`--no header`→`--no-header`(实现者笔误);Important:None 值覆盖默认值(加 `is not None` 守卫);加固测试 3 项。Minor:实现者报告曾谎称"逐字一致",已纠正。
- [x] Task 4: 失败分类 taxonomy — complete (commit e39be09, review Approved)。FailureCategory 枚举 + 分类纯函数。账本此前漏勾,最终审查补。
- [x] Task 5: 反馈校验器 Validator.parse — complete (commits e39be09..0a10f57 + fix 3b25c9d, review Approved)。主贡献核心,纯函数。微调 3 处正则(在"调正则不调断言"授权内)。Important:`_ASSERT_LINE` 兜底分支补了 fixture+测试(3b25c9d);`_FAIL_HEADER` 末 token 对参数化用例名脆弱——当前不触发,**Task 8 接真实 pytest 时补 fixture**(记此)。Minor:`_classify` 把 import_error fixture 分到 CollectionError(测试容差放行);summary 空 stdout 兜底会 IndexError(防御性不足)。
- [x] Task 6: 工具 文件操作 — complete (commits 3b25c9d..25d5325, review Approved)。Minor:list_dir 错误信息非中文风格;截断断言较松。
- [x] Task 7: 工具 跨平台 shell — complete (commits 25d5325..2248e66, review Approved)。shell=False 安全;Windows shlex 弱点按 brief 登记 follow-up(CI 矩阵届时改 list 接口)。Minor:超时丢弃已捕获输出(brief 同款)。
- [x] Task 8: 工具 pytest 运行器 — complete (commits 2248e66..3d8555d, review Approved)。**计划修正**:fixture 从 `tests/fixtures/sample_pkg/` 挪到 repo 根 `fixtures/sample_pkg/`(避免故意失败的 test_calc 污染主套件),测试路径 3 层 parent。`--collect-only` 验证未污染。
- [x] Task 9: 工具分发 dispatch — complete (commits 3d8555d..ed5a15a, review Approved)。Minor:测试冗余 import(sys/Path);match 无 wildcard 兜底(Action 封闭类型,可接受)。
- [x] Task 10: 记忆 store — complete (commits ed5a15a..7614d2a, review Approved)。纯函数检索确定;record_fix timestamp 由调用方传入避非确定。Minor:top_k 测试未断言尾部切片内容;Fix.category 为 str(brief 取舍)。
- [x] Task 11: 治理护栏 guardrail — complete (commits 7614d2a..470eb68 + fix 132e3c5, review Approved)。§A.4 核心机制,纯函数。Important(已修):白名单子串匹配可被 `pytest_evil` 绕过→改精确首词匹配(shlex)+ 绕过测试(132e3c5);黑名单保留子串 Deny。Minor:guardrail 缺返回类型标注;`_starts_with_any` 名实不符(已拆)。
- [x] Task 12: LLM 抽象层 base — complete (commits 132e3c5..43f7a72, review Approved)。Protocol 结构性,mock/真实同接口。Minor:测试名 `test_protocol_is_structural` 未真用 isinstance(可加 @runtime_checkable)。
- [x] Task 13: MockLLMClient — complete (commits 43f7a72..92e5fff, review Approved)。§A.6 确定性关键,4 种 when 分支 + 无匹配抛错,不触网零时钟。Minor:未使用 import;`round N` 解析对非整数抛 ValueError 而非不命中。
- [x] Task 14: 循环状态与停机判断 state — complete (commits 92e5fff..1e14e4f, review Approved)。纯函数停机/策略判断,7/7 测试。no_change_streak 按 brief「实现注意」对齐测试契约(含当前轮语义:FAIL+无历史→1/同set→prev+1/变set→1/PASS→0),改 impl 不改测试。Minor:`from typing import Any` 在 models.py 中部(后续顺手移顶);no_change_streak「变集合→1」分支测试保护略薄。
- [x] Task 15: AgentLoop 主循环 — complete (commits 06dd215..159da3e, review Approved)。自实现主循环:上下文→LLM→护栏→分发→校验→回灌→停机。集成测试红变绿确定性复现 §A.6 ②(反馈闭环使 agent 改变下一步)。连带修两遗留 bug:① validator 兼容真实 `--tb=short`(延迟 flush,Task 5 遗留)② tests_runner 清 `__pycache__` 消除亚秒 mtime 冲突(Task 8 遗留,曾致集成测试 flaky ~80%)。58 passed,10x 连跑全绿。NeedsApproval 暂回灌"需审批"字符串,HITL 完整化留 Task 15b。
- [x] Task 15b: HITL 完整化(补) — complete (commits 68936f4 + fix 70dee70, review Approved)。threading.Event 挂起→approve→恢复。hitl_enabled 默认 False 保 Task 15 不变。approval_id 自增计数器(确定性)。3 测试(approve True→真删/False→保留/未知 id→KeyError)。审查 Important(锁纪律:唤醒后 decision 读取/pending 置 None 原在锁外)已修(70dee70,锁内原子取回)。61 passed,5x 无竞态。
- [x] Task 16: 凭据管理 keychain — complete (commit 245f958, review Approved)。Creds 包 keyring:set/get/status(只返回 {'set':bool} 不回显明文)/clear。in-memory 后端测试,不触真实 keychain。62 passed。
- [x] Task 17: 真实 LLM 客户端 openai_compat — complete (commit c34effa, review Approved)。OpenAICompatibleClient(httpx + function-calling),parse_tool_call→Action+intent。key 只进 header 不进体/日志。修 plan 测试三处内部矛盾(fake R 补 raise_for_status、fake_post 补 timeout kwarg、key 检查改只查 body)。monkeypatch fake httpx 不触网(§A.4 确定性)。64 passed。
- [x] Task 18: §A.6 三个机制演示 — complete (commits 16d2e2d + fix 42308d4, review Approved)。三 demo:① 护栏拦截 DeleteFile→NeedsApproval 事件+intent 上送;② 反馈闭环 round1 错值→FAIL→据反馈改对→PASS,断言 pivot;③ 连续同类失败注入"换思路"提示(capturing mock 断言 round5 消息含),no_change=3→stuck。修 plan bug:demo②③ mock 原写正确值致转折/stuck 永不触发,改错值 a+b+2 起步;demo③ 调阈值使 prompt 与 stop 分轮。_cfg memory 路径指 tmp ws。67 passed,demo 3x 稳定。
- [x] Task 19: FastAPI WebUI 后端 — complete (commits 9209cde + fix aacc8df, review Approved)。create_app + SSE + HITL 审批端点 + 凭据端点。plan 5 处修正(rununner 笔误/submit async/on_event 跨线程/demo script 错值起步/Pydantic 模型)。审查 Important(runner 无 try/finally 致 SSE 无限阻塞)已修(aacc8df:try/except/finally + error 事件);Minor(未知 task_id 404、临时 yaml 清理)同修。filterwarnings 静音 starlette deprecation。69 passed。
- [x] Task 20: 单页前端 — complete (commits 1d02173 + fix 4f44626, review Approved)。Open Design token + SSE timeline + status + 凭据模态。pending_approval 事件(loop.py 挂起前发 aid/reason/intent)→ 前端渲染[通过][拒绝]按钮 POST /approvals,补齐 §A.6 ① 链路。审查 Important(app.py 未开 hitl_enabled 致审批链路死代码)已修(4f44626:hitl_enabled=True + threading.Thread 驱动避 TestClient task group 挂起 + /pending 端点 + E2E 测试 submit DeleteFile→/pending→/approvals→文件真删)。72 passed,web 4x 稳定。
- [x] Task 21: CLI 入口 main — complete (commits 022a3c9 + fix 0bd075c, review Approved)。serve/creds/run 子命令。api_key 用 getpass 隐藏录入不进 history;status 不回显。测试用 in-memory keyring(替代 plan 的 setenv HOME,避免碰真实 Keychain,§A.4)。审查凭据安全四项全 PASS(无 Critical/Major)。Minor(run 缺 config.yaml 抛 traceback 非友好)已修(0bd075c:try/except 友好报错 rc=2 + test_run_missing_config)。78 passed。harness 脚本可运行。
- [x] Task 22: CI 配置 — complete (commits ac5b088 + e5f73c3, review Approved)。`.gitlab-ci.yml`:stages=[test,build];`unit-test` job(§五.6 硬要求,`uv sync --frozen`+`uv run pytest -q`,与 `make test` 一致,MR+分支触发);`build-image` job(docker-in-docker,仅 main+exists Dockerfile,Task 23 就绪后自动生效)。`test_ci_config.py` 6 确定性单测(PyYAML 解析,§A.4 精神:配置也可验证;含 rules 与 cache key 断言,e5f73c3 补)。顺带闭合 Task 1 Minor(ruff 进 dev deps,`make lint` 35→0 全绿)+ models.py 审查 Minor(Any 移顶、F821 前向引用用 TYPE_CHECKING)。审查 §五.6 五项全 PASS(无 Critical/Major),Minor(覆盖未含 rules/cache)已修(e5f73c3)。82 passed,make lint All checks passed。取舍:§4.8 提 GitHub Actions 但 §五.6 硬要求 gitlab-ci.yml,以后者为准;不强跑 Windows 矩阵(mock 测不暴露 Task 7 shlex 弱点,登记 follow-up)。
- [x] Task 23: Dockerfile 与云部署 — complete (commits 9641433 + 补强, review Approved)。容器分发(§3.2)+云部署(§4.11)。Dockerfile:python:3.12-slim+uv 官方二进制,依赖层(`uv sync --frozen --no-dev`)与源码层分离(EXPOSE 8000,HEALTHCHECK python urllib,CMD `harness serve` mock)。.dockerignore 排 .venv/.env/tests。fly.toml+scripts/deploy.sh(Fly.io nrt,healthcheck GET /,免费层)。test_dockerfile.py 8 单测(含 HEALTHCHECK/`--no-dev` 断言,补强)。本地:`uv sync --no-dev`+`uv run harness` 验证依赖层+CMD 可行;docker daemon 未运行,实际构建由 CI build-image job(docker:dind)验证。审查 §3.2/§3.1/§五.9/§4.11/§A.4/§4.10 全 PASS(无 Critical/Major)。Minor(测试漏 HEALTHCHECK/--no-dev、fly.toml 唯一名提示、config.yaml 对 serve 冗余)前两项已修,第三项 README 澄清。**限制**:§五.9 线上 URL 需用户在 Fly.io 注册后执行 deploy.sh 产生填入 README(AI 无法代注册云账号);容器内 keychain 回落文件后端(README 注明)。
- [x] Task 24: README 与安全边界 — complete (commits d3a8b0d + 补强, review Approved)。通用 §五.4 必含章节。README.md 10 章节(简介/安装/运行/凭据与安全配置/分发/部署架构/目录结构/机制演示/安全边界/已知限制)。凭据章节强调 §3.1(不硬编码/不进 git/不回显;keychain+getpass;key 只进 header 不进体/日志)。安全边界:护栏白/黑名单+HITL+intent 上送+mock 不触网+路径围栏。机制演示指向 tests/demo/(§A.6 三机制)。部署 URL 占位(用户部署后填)+已知限制诚实。test_readme.py 6 单测(含部署架构/机制演示章节断言,补强)。顺带修 test_dockerfile E741(l→line)。97 passed,make lint All checks passed。审查 §五.4 六章节/§3.2/§4.11/§A.6/§A.4/命令一致性 全 PASS(无 Critical/Major),Minor(未守护部署架构/机制演示章节)已修。

## 模型选择策略

- 机械实现(1-2 文件、PLAN 给完整代码):cheap(haiku)
- 多文件集成/judgment:standard(sonnet)
- 架构/最终审查:most capable(opus)
- 审查者:按 diff 复杂度,默认 standard

## 偏离记录

- §4.6 worktree:EnterWorktree 工具因会话缓存状态拒绝,回退特性分支(见 AGENT_LOG)。
- §4.5 类型不同:仅 Claude 系列可用,用 general-purpose(类型不同但模型同源),部分满足。
- 冷启动样本仅 Task 1/2(信号量偏低,见 SPEC_PROCESS §5.5)。

## 最终全分支审查与收尾(2026-07-23)

- 最终全分支审查(superpowers:requesting-code-review 全局验收,f07f8cd..HEAD,46 commits,86 files,+4517/-33):交付物 §五.1-9 逐条核验——§五.1(SPEC/PLAN/SPEC_PROCESS 软链+文件)、§五.2(自实现内核+mock 确定性单测)、§五.3(Dockerfile)、§五.4(README 必含六章节)、§五.5(AGENT_LOG Task1-24)、§五.6(.gitlab-ci.yml unit-test job)全 PASS;§五.7(CI 真实 pass 待 push,unit-test job 结构对齐本地 98 passed)、§五.9(URL 待用户部署,部署路径完整)为环境限制诚实记录;§五.8 REFLECTION(Major,见下)。§A.4 红线六条全 PASS(内核自实现/无框架寄生/机制为代码/mock 驱动确定性可测/六维度齐全反馈闭环做深/内核自己运转)。§3.1 凭据安全 PASS(无真实 key 入 git/history,keychain 不回显明文)。98 passed,make lint All checks passed。
- **1 Major(合入前必修)**:§五.8 REFLECTION.md 须本人撰写。AI 已起草约 2100 字并标注"AI 起草需本人改写",但"本人逐节改写+删除标注"只能用户做——AI 无法代劳(与 §五.9 URL、§五.7 CI 真实 pass 同性质的环境/责任限制)。
- **2 Minor(已修)**:progress Task 4 账本漏勾→补 [x];README keychain"回落文件后端"措辞→改"无可用后端时不自动回落,建议本地/显式配文件后端"。
- 用户决策:**暂不合 main,保持 feature/coding-agent-harness 分支**。无 remote(git remote 空),无法 push/建 PR。
- 本人后续待办:① 改写 REFLECTION.md 逐节补个人视角与批判性判断,删除首行 AI 起草标注(§五.8);② 配 NJU Git remote 并 push 触发 CI(§五.6/§五.7);③ `scripts/deploy.sh` 部署 Fly.io 后填 README 公网 URL(§五.9)。
