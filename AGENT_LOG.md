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

## 最终全分支审查与收尾(2026-07-23)

- 技能:`superpowers:requesting-code-review`(全局验收,非逐 task)。范围 f07f8cd..HEAD(46 commits,86 files,+4517/-33)。
- 交付物 §五.1-9 逐条核验:§五.1-6/8 PASS(SPEC/PLAN/SPEC_PROCESS 软链+文件、自实现内核+mock 确定性单测、Dockerfile、README 必含六章节、AGENT_LOG Task1-24、.gitlab-ci.yml unit-test job);§五.7 CI 真实 pass 待 push、§五.9 URL 待用户部署(环境限制诚实记录)。§A.4 红线六条全 PASS(自实现/无框架寄生 grep langchain|autogen|crewai|llama_index 无命中/机制为代码/mock 驱动确定性可测/六维度齐全反馈闭环做深/内核自己运转)。§3.1 凭据安全 PASS(grep sk-/api_key 无命中,.env 不在 git history,keychain 不回显)。98 passed,lint All checks passed。
- **1 Major(合入前必修)**:§五.8 REFLECTION 须本人撰写。AI 已起草约 2100 字并标注"AI 起草需本人改写",但本人逐节改写+删除标注只能用户做——AI 无法代劳。
- **2 Minor(已修)**:progress Task 4 账本漏勾→补 [x];README keychain"回落文件后端"措辞精确化。
- 人工干预/用户决策:**暂不合 main,保持 feature/coding-agent-harness 分支**(无 remote,无法 push/建 PR)。本人后续:改写 REFLECTION(§五.8)、配 NJU Git remote push 触发 CI(§五.6/§五.7)、Fly.io 部署填 URL(§五.9)。
- 教训:§五.8"本人撰写"、§五.9"可访问公网 URL"、§五.7"最后一次 CI pass"是 AI 协作的天然边界——AI 能准备好全部前置物(起草 REFLECTION、Dockerfile+fly.toml+deploy.sh、CI 配置),但"本人撰写""持云 token 部署""push 触发真实 CI"这三步必须人类完成。诚实标注这些边界比伪装完成更有价值。

## 7/24–7/30 补记(真实 LLM 打磨 → 双平台 CI → 阿里云部署 → WebUI 重构)

> 本节为 2026-08-06 事后补记,基于 git commit 记录与 message 中的根因分析重建;当时未留档的 prompt/context 细节以 commit message 为准,不虚构。

### 阶段一(7/24):真实 LLM 端到端打磨

- **c62a5ac 修复真实 LLM 无法执行多轮工具调用的三个 bug**(`loop.py` +68)。用 `harness serve --real --project-root ./fixtures/sample_pkg` 手工验证时暴露(mock 单测全绿但真实 API 跑不通):
  1. `_build_messages` 每轮从零构建,缺对话历史 → LLM"失忆"无法续作。修:新增 `conversation_history`,每轮追加含上一步动作+结果的 user 消息。
  2. `llm.complete()` 传空 tools 列表 → `tools: null`,DeepSeek 无法返回 function call,纯文本被转 `Stop('no_tool_call')`。修:定义 `_AGENT_TOOLS`(7 工具 JSON Schema)。
  3. 系统提示未约束修改范围 → LLM 可能改测试文件迁就实现。修:加"修复实现代码,不要修改测试文件;测试断言是真理"规则。
- **fa31e5a intent 必填**(`loop.py`):每个工具 Schema 的 properties 加 `intent` 并进 required,DeepSeek 每次 function call 填写动机;`_ACTION_BUILDERS` lambda 按 key 取值,多余字段忽略,兼容性安全。
- **54a60ba Respond 文字回复与工作总结**(`loop.py` + models/guardrail/dispatch/前端):LLM 输出纯文本不再粗暴转 `Stop("no_tool_call")`,而是作为 `Respond` 发给前端并继续循环;PASS 后 `decide_stop` 不再自动返回 success,留给 agent 一轮文字总结再 Stop;**语义变化同步更新 3 个测试(PASS→stopped)**;FAIL 反馈消息 role 从 tool 改 user(DeepSeek 要求 tool_call_id 配对)。
- **9b319e5 memory 记录成功修复**(`loop.py` +49):改进前仅 FAIL 记录且 fix 固定"(未修复)",历史检索无参考价值;改进后 PASS 也记录(从 feedback_history 找最近 FAIL 归类,无则 Unknown),fix 字段从 WriteFile 步骤提取文件+意图、从 Stop.reason 提取工作总结,symptom 区分"修复成功: N passed"。
- **a30c77e serve 加 `--project-root`**:project_root 原硬编码 ./workspace,WebUI 内无法切换工作目录。

### 阶段二(7/27):CI 双平台

- **d336bbf 新增 GitHub Actions 并行 CI**(`.github/workflows/ci.yml`):GitLab CI 保留;GH Actions 适配 GitHub 平台,job 命名 `unit-test` 满足 §五.6 硬要求,push+PR 自动触发。
- **30fa58f/fed594e 两个 CI 修复**:裸环境 `uv sync --frozen` 找不到 pytest(本地能跑是因为之前手动 sync 过)→ 去 `--frozen`;`uv sync` 不自动装 optional-dependencies → 显式 `--extra dev`。**教训:本地环境会掩盖依赖声明缺失,CI 裸环境才暴露。**

### 阶段三(7/28):部署方案切换 + 提交审查清理

- **cbdbbf4 Fly.io → 阿里云**:Fly.io 需绑信用卡,替换为阿里云轻量服务器/ECS;新增 `scripts/deploy-aliyun.sh`(本地构建 → SSH 上传镜像 → 服务器启动容器,映射 80→8000);README 部署章节改写,保留 fly.toml + deploy.sh 作参考。**外部约束(支付方式)驱动的方案切换,文档与脚本同步,不遗留死代码。**
- **874c813 W1-W4 提交审查清理**:W1 补提交 index.html 回车键优化(之前漏提交);W2 `config.yaml` 加入 `.gitignore`(防意外提交含 key 配置——§3.1 防线加固);W3 `*.pptx *.pdf workspace/` 入 gitignore;W4 README CI 描述同时提及两平台。

### 阶段四(7/28):WebUI 重构与对话体验(大幅改动,非 Plan 任务,用户驱动的需求迭代)

- **488580b WebUI 全面重构**:三栏布局 + 步骤卡片(折叠/emoji/轮次编号)+ 状态面板实时化 + 任务历史侧栏 + 打字机流式输出;新增后端接口 `GET /api/tasks`(历史)、`GET /api/workspace/tree`(文件树)、`GET /api/workspace/file`(文件内容,路径越界 403);模型下拉(DeepSeek/OpenAI/通义千问/智谱)+ mock/real 切换;凭据管理加 `info()`(不回显)。
- **3d0756c 聊天式 WebUI + 多轮对话**:agent 回复从时间线卡片改为独立聊天气泡(打字机 12ms/字+闪烁光标);工具调用渲染为可展开圆角胶囊;用户可在同会话发后续消息,agent 基于完整上下文继续;「新会话」归档历史;提示词区分「代码修改任务」/「非代码任务」(后者直接回复不跑测试)。
- **722c446 三个 WebUI 问题修复**:① agent 只有工具调用无文字回复——系统提示词重写为「工作流程」三步法,工具回灌 hint 按动作类型分化(ReadFile→描述看到什么、RunTests→说明测试结果、WriteFile→说明改了什么);② 历史列表不可见——loadHistory 三层反馈 + escJs() 防注入;③ 文件树只显示部分文件——移除后缀白名单,过滤 .ruff_cache/.mypy_cache。
- **6d757f7 提示词按用户意图精确分流**:用户说「列出文件」agent 却读代码+跑测试——根因是提示词「查看/问答」分类太宽泛;重构为三条核心规则 + 措辞分流(「列出/看看」→list_dir→回复→stop 不读不测;「读一下 xxx」→read_file→回复→stop 不测;「修复/改/fix」→读→改→测→回复→stop;「问问题」→直接回复→stop 不调工具)+「严禁行为」四类越权红线 + 工具回灌 hint 改「回忆用户意图」范式。
- **64bc27c 修复纯文字回复死循环**:用户输入「你好」→ Respond → continue → 再 Respond → 无限循环直到 max_rounds=8。根因:Respond 分支只 continue 不打破循环,LLM 在纯问答场景不会主动调 stop。修:计数器 `_consecutive_responds` 追踪连续纯文字回复,工具调用时重置(允许 Respond→Tool→Respond 穿插),连续 2 次自动 break(outcome=stopped);第 1 次 Respond 后注入「请调用 stop」引导正常路径。**教训:交互类 bug(死循环)由人工试用发现而非测试发现——mock 脚本化分支不会自发产生 Respond 循环,该场景测试覆盖滞后于真实使用。**

### 阶段五(7/30):UI 细节与模型列表

- **335a1e2 模型列表更新至 2026-07 最新主流大模型**:DeepSeek V4-Pro/V4-Flash/V3.2;OpenAI GPT-5.6 Sol/5.5/5.4 系列;新增 Claude(Fable 5/Opus 4.8/Sonnet 5/Haiku 4.5)与 Gemini(3.6/3.5 系列);Qwen3.8/3.7 系列;GLM-5 系列;移除 Moonshot。每供应商带 base_url,前端切换模型自动更新 keychain 中的 base_url(跨供应商切换后 API 端点正确)。
- **3eeebbd 发送按钮美化**:渐变圆形 + 箭头图标 + hover 放大辉光 + active 按压 + disabled 灰化。
- **7f7e6ea 工作目录改系统原生文件夹选择器**:`POST /api/workspace/picker` 后端调 OS 原生对话框(macOS AppleScript 访达 / Windows PowerShell / Linux zenity,无 GUI 则手动输入),前端按钮+文件夹名替代文本输入框,选中后自动刷新文件树与配置。

### 补记教训(承接全程教训汇总)

8. **mock 单测全绿 ≠ 真实 LLM 可用**:c62a5ac 三 bug 全部只在 `--real` 手工验证暴露(失忆/tools 空列表/改测试文件)——mock 脚本化分支不验证 API 协议细节,真实集成验证应作为每轮打磨的固定步骤。
9. **语义变化必须同步更新测试契约**:PASS→stopped 语义调整(54a60ba)同步改 3 个测试,避免"测试迁就新行为"或"行为与测试脱钩"。
10. **CI 裸环境暴露依赖声明缺失**:`--frozen`/`--extra dev` 两连修——本地手工 sync 过的依赖会掩盖 pyproject 声明不完整。
11. **外部约束驱动方案切换要清干净**:Fly.io 信用卡限制 → 阿里云,旧脚本保留为参考但 README 主路径更新,无死链接。
12. **交互类 bug 靠人工试用暴露**:Respond 死循环(64bc27c)在真实使用中才发现;UI 打磨期的测试策略应是"测试守护核心机制 + 人工试用守护交互体验"。

## 2026-08-06 交付前合规补全与工程修复(对照通用 §五 + §A.4 逐项核查后执行)

- 触发:对照通用要求 + Project A 文件核查项目现状,发现 3 处硬缺口(§4.7 PLAN 无完成标记、§4.9 AGENT_LOG 截止 7/23、死配置 approval_timeout_sec)与 2 处工程改进点。
- 技能:常规编辑(非 subagent 派发——收尾小项,主会话直接执行)。
- 人工干预:无;用户决策"做第 3 组全部项"(文档合规 + 工程改进)。
- **PLAN.md**(§4.7):24 个 task 标题补「**状态**:✅ 已完成 — commit: ...」,映射取自 AGENT_LOG 原始记录与 git log 核实。
- **AGENT_LOG.md**(§4.9):补记 7/24–7/30 共 20 个 commit(真实 LLM 打磨→双平台 CI→阿里云部署→WebUI 重构→UI 细节),标注为事后补记(基于 commit 重建,不虚构 prompt),教训 8-12。
- **审批超时实现**(死配置治理):`approval_timeout_sec` 从"定义了但从没生效"变为真实机制——`_suspend_for_approval` 返回三态,超时按拒绝处理(危险动作不执行)、发 `approval_timeout` 事件、审批失效;WebUI 按钮置灰 + 友好 404;integration 测试 0.1s 超时验证。**设计取舍:不引入系统时钟判定,超时由 threading.Event.wait(timeout) 承担,循环内仍零时钟**。
- **对话历史截断**:`MAX_HISTORY_MESSAGES=30` + `_append_history` 统一入口(长会话真实 LLM 上下文保护),单元测截断边界。
- **validator 三缺陷修复**(真实 pytest 端到端实测暴露):含空格参数化 nodeid(`\S+`→`.*?`)、header 末 token 错位(`_extract_name` 含 `[` 起提取)、pytest 截断 diff(`a...`)与 `AssertionError: assert` 前缀格式(分类回退与兼容)。TDD 先红后绿,端到端 4 失败全部正确分类。
- 教训 13:**"配置项存在 ≠ 机制生效"**——dead config 是交付前核查的高价值目标(比新增功能更值得查)。
- 教训 14:**真实 pytest 输出格式比想象中多形态**(含空格参数化、无短路信息的 AssertionError 前缀、超长 diff 截断),手工 fixture 会掩盖格式多样性——用真实 pytest 跑一次参数化用例做端到端验证,比纯手工构造 fixture 更能暴露解析缺陷。

## 2026-08-06 WebUI 与对话优化(审查后全部实施)

- 触发:用户要求审查 WebUI/对话部分,指出改进点(简洁美观 + agent 合理回答),随后要求全部实施。
- 技能:常规编辑;TDD 红→绿(7 个新测试先红后绿);冒烟验证(uvicorn 启动 + SSE 事件流)。
- 人工干预:无。
- **对话质量(核心)**:
  1. 消息顺序修复——`_build_messages` 从 `[system, user(新), ...历史]` 改为 `[system, ...历史, user(新), ...反馈]`。原顺序把最新指令夹在历史中间,真实 LLM 按错误时间顺序理解上下文,是此前多轮对话效果差的首要原因。
  2. Respond 连续停机 2→3 次:原 2 次阈值会误杀"先说明发现、再补充细节"的分段回复;第 2 段注入更强提示。
  3. 意图分流补充:只跑指定测试 / 分析评估项目 / 衔接词(继续/然后呢)/ 多任务逐个完成。
  4. 回灌截断改头尾保留(整段截尾会让 agent 只见文件开头,基于错误信息决策)。
  5. run_tests 加 path 参数(可只跑指定文件),路径越界 resolve+is_relative_to 拒绝——安全边界与文件工具一致。
- **WebUI**:
  1. 步骤胶囊合并:后端 guardrail_verdict+tool_result 两事件合并为单个 action 事件(带动作名),前端从"两个英文内部名胶囊"变为"一个带图标动作胶囊"。事件协议变更同步 demo 测试。
  2. SVG 图标全套(发送纸飞机/新会话/工作目录/凭据钥匙),模式徽章可点击切换。
  3. 打字机点击跳过、历史步骤详情可点击、DOM id 自增替代 Date.now()、insertAdjacentHTML。
  4. 右面板精简(计数折叠)+ 内联样式抽 class。
- 验证:108 passed,ruff 全过,node --check 语法过,冒烟测试 SSE action 事件流正确。
- 教训 15:**内部事件协议(guardrail_verdict/tool_result)泄漏到 UI 是架构信号**——后端为"机制"发的事件直接当"展示"用,两者应分离;合并为 action 事件后前端一个分支搞定,历史存储与实时渲染天然一致。
- 教训 16:**防御性自动停机阈值要按真实对话模式校准**——2 次 Respond 停机会误杀正常分段回复,阈值放宽 + 分层提示(先提示继续/停,再兜底)比一刀切更稳。

## 2026-08-06 对话逻辑与提示词优化(参考 Claude Code/Codex)

- 触发:用户反馈「与 agent 对话经常没有回答,且回答有冗余内容」,要求参考 Claude Code/Codex 思路优化。
- 技能:常规编辑;TDD 红→绿(4 个新测试)。
- 人工干预:无。测试对话残留已按约定清理。
- **「无回答」根因与修复**:真实 LLM(DeepSeek)常直接调 stop 且 reason 写 "done"/空,被 loop.py 的 trivial 过滤丢弃 → 前端只剩胶囊无文字。修复:Stop trivial reason 且本轮无文字输出时发兜底 response "(任务完成)";本轮已有 Respond 则不兜底(避免冗余)。
- **「回答冗余」根因与修复**:
  1. 每轮 [结果] 全文回灌(RunTests 3000 字符,与 feedback 消息重复)→ 改 RunTests 一行摘要(fb 结果),详情由 feedback 消息提供。
  2. next_hint 按动作类型分化且逐轮累积引导 → 统一为一句简短提示。
  3. 历史无限膨胀 → 新增 MAX_FULL_STEPS=8 轮后最早轮次压缩为一行"(历史) ActionName: intent"(Claude Code 式历史压缩,保留要点丢全文)。
  4. 系统提示词冗长缺风格约束 → 重写:工作方式/意图分流/严禁精简合并,新增「回复风格」段(直接简洁、先结论后细节、不复述任务/思考过程、不列举工具调用、测试结果一句话)。
- 验证:112 passed,lint 全过。
- 教训 17:**"没回答"往往是展示层与协议层的过滤共同造成的**——LLM 确实产出了 reason,但被 trivial 过滤吞掉;兜底文案应中性(「(任务完成)」而非捏造总结)。
- 教训 18:**给 LLM 的上下文要像 Claude Code 一样"按需精简"**:完整工具输出给模型 ≠ 更好的回答——反馈闭环已把关键信息结构化提取(feedback 消息),再回灌全文只会稀释注意力、放大冗余。

## 2026-08-09 修复「只有工具调用没有回复」

- 触发:用户反馈「要求 agent 列出文件内容,没有回复,只有工具调用」。
- 根因(真实 LLM 协议):OpenAI 兼容 API 允许 content 与 tool_calls 同时返回(工具调用前的文字说明)。openai_compat 只取 tool_calls 丢弃 content → 前端只见胶囊无文字。这是「无回答」的协议层根因,与之前 stop-trivial 过滤是不同层面的问题。
- 修复:
  1. AssistantTurn.text 字段 + openai_compat 携带 content(工具前文字)
  2. loop 工具执行前先发 response 展示伴随文字
  3. stop trivial 兜底改展示最近一次工具结果摘要(列出文件后直接看到列表)——Stop 自身回灌输出不覆盖摘要
  4. max_rounds/stuck 停机兜底(全程无文字时发中性回复)
- 端到端验证:「列出文件内容」→「我来看看项目目录结构。」→ ListDir 胶囊 → 兜底显示 README.md+calc.py。
- 教训 19:**协议层字段被丢弃 = 用户可见的「没回答」**——content+tool_calls 并存是 OpenAI 协议标准行为,不是 LLM 异常;展示层必须把两者都呈现,顺序为「先文字说明,再工具执行」。

## 2026-08-09 执行轮数优化 + 工具调用即时展示

- 触发:用户反馈「实际执行中到达最大执行轮数」,要求提高上限、告知 LLM 规划工具调用、工具调用即时展示。
- 技能:常规编辑;TDD 红→绿(系统提示词含轮数上限断言);SSE 冒烟验证。
- 人工干预:无。测试对话已清理。
- **max_rounds 8 → 20**:真实修复任务(读→改→测→重试)常 3-5 轮起步,8 轮容易在任务完成前耗尽(config 可配,改默认 + config.example.yaml 同步)。
- **提示词告知轮数并促规划**:系统提示词注入「本轮最多 N 轮工具调用。请提前规划:一次读齐所需文件、避免重复跑相同测试、避免重复执行已成功的操作」——把轮数约束从"停机兜底"前移到"规划引导"。
- **工具调用即时展示**:前端移除 pendingSteps 攒批机制(原设计等 response/loop_stopped 才一次性渲染),action 事件到达即渲染胶囊——任务执行中用户实时看到 agent 每一步动作(Claude Code/Codex 的实时动作流体验)。
- 验证:117 passed,lint 全过,node --check 过,SSE 冒烟事件实时推送。
- 教训 20:**"等任务结束才展示"是糟糕的交互默认**——攒批渲染省了 DOM 操作,但让用户对 agent 动作零可见性;即时渲染(事件到达即画)是 coding agent UI 的基本要求。

## 2026-08-09 轮数耗尽根因修复(基于真实 LLM 历史分析)

- 触发:用户反馈「工具调用达到 20 次自动停止」,要求改进。
- 根因分析(读 conversations/04f98578db97.json 真实历史):「列出文件内容」被理解成探索整个项目,25 steps 中约 8 个重复 ListDir(src/main/java 逐层看两遍)、5 个被护栏拒绝后反复尝试的 RunShell——**轮数不是不够,是被浪费了**。
- 修复(减少浪费而非无限加轮数):
  1. 意图分流强化:列文件→列一次→回复→stop;查文件内容→读该文件→回复→stop。加「不要深入子目录/不用 shell」硬约束
  2. 新增「shell 命令不可用」提示段:当前模式 shell 需审批,不要 grep/find/cat,被拦截后不要换命令重试
  3. 被拒回灌文案强化:明确「该动作不可执行,不要重复尝试,改用 read_file/list_dir/write_file 或直接回复」——之前文案太弱,agent 不知道该放弃
  4. 连续被拦截计数干预:连续 3 次被拒注入「停止尝试被拦截的操作」提示(确定性可测机制,非提示词)
- 端到端模拟:第 3 次被拒后提示注入,agent 停止尝试 shell 改用 list_dir。
- 验证:120 passed,lint 全过。
- 教训 21:**轮数耗尽 ≠ 轮数不够,先读真实执行轨迹找浪费**——分析 conversations/ 历史是最直接的诊断手段;修复优先"减少浪费"(意图分流 + 被拒不重试)而非单纯提高上限。
- 教训 22:**护栏拒绝的反馈要"教 agent 放弃"**——非 HITL 下 NeedsApproval 反复回灌同一句"需审批"会被 LLM 当作可重试信号;明确「该动作当前不可执行、不要重复尝试」+ 连续计数干预,才是真正的反馈闭环。

## 2026-08-09 轮数耗尽根治 + WebUI 工具行重构

- 触发:用户反馈「20 轮仍终止」+ 三点 WebUI 要求(工具调用前展示完整意图/美化图标/分行渲染占空间加自动折叠)。
- 根因分析(真实历史 b3f512a28846,21 steps):「列出文件内容」被理解成读整个项目所有文件完整内容;read_file 截断后 agent 反复重读被截断文件(连续 2 轮),甚至试 cat。
- 修复(治本):
  1. read_file 加 offset/lines 行区间参数(1-based)— 解决"想读中间部分"的合理需求,agent 不再反复整读/试 cat;截断标记明确告知「已截断,可用 offset/lines 分段读取」,消除"反复重读"行为
  2. 意图分流:「列出文件内容」= 清单 + 每文件 1-2 行概述,不读所有文件完整内容
- WebUI(参考 Claude Code):
  3. 工具调用改为紧凑工具行:SVG 图标 + 工具名 + **完整 intent 直接可见**(原来藏 title 里);点击展开详情(护栏/反馈/结果 error)
  4. emoji 图标 → 统一线条风格 SVG(8 动作 + pass/deny 勾叉),与头像/按钮同风格
  5. 详情自动折叠:默认一行,▾ 箭头点击展开
- 验证:122 passed,lint 全过,node --check,冒烟工具行结构 + 事件流 error 字段。
- 教训 23:**「20 轮不够」的第二层根因是工具能力缺口**——read_file 不能读中间部分,agent 只能反复整读或试被禁止的 cat;给工具补 offset/lines 参数 + 截断告知,从能力上消除浪费,比提示词约束更可靠。
- 教训 24:**Claude Code 工具行的核心是"intent 直接可见"**——用户要看的是 agent 在做什么(动机),不是动作名;完整 intent 上移到行内、详情折叠,信息层级才正确。

## 2026-08-09 轮数软上限改造(不再限制死)

- 触发:用户反馈「还是终止了,工具调用轮次可能太少或者不应该限制死」。
- 根因分析(最新真实历史):这次没有浪费——agent 按「列出文件内容 = 全部文件清单 + 每文件概述」理解,6 次 ListDir 各不重复、15 次 ReadFile 各读不同文件,被截断用 offset 续读也合理。**任务本身就需要 20+ 轮**,硬上限 20 打断了正在进行的工作流。用户判断正确。
- 改动:
  1. max_rounds 语义改为**软上限**:达到时注入「已执行 N 轮(软上限),若完成请 stop,若需继续请高效执行(最多 M 轮)」——不再立即终止
  2. 新增 **hard_max_rounds(默认 60)** 作为真正安全阀:只有硬上限才强制终止(防死循环;stuck 兜底更早触发)
  3. 系统提示词同步(尽量 N 轮内完成,硬上限 M 轮)
- 端到端验证:超过软上限(5)后继续执行 10 轮,收到警告后由模型自行 stop,不被硬终止。
- 验证:126 passed,lint 全过。
- 教训 25:**硬轮数上限会误杀"任务理解正确但工作量大"的合理流程**——参考 Claude Code 无硬轮数设计:软警告(告知预算)+ 高硬上限(安全阀)+ 无进展检测(stuck)三层,既"不限制死"又防死循环。

## 2026-08-09 工具调用折叠按钮 + 目录探索去重

- 触发:用户反馈「①看最近对话有重复问题 ②任务完成后工具调用应折叠成按钮」。
- 历史分析:最新对话(14 轮)已成功完成(软上限生效,agent 自行 stop);「重复」= 6-7 次 ListDir 逐层探索(root→src→main→java→test)太碎,路径前缀重复。
- 改动:
  1. **工具调用自动折叠成按钮**(需求 2):每轮工具行包进 .tool-round,任务完成(loop_stopped)时折叠成单个「N 步工具调用」按钮,点击展开全部;历史加载同样折叠——工具行不再占满对话,简洁。
  2. **list_dir 加 recursive 参数**(需求 1 根因缓解):一次列出整个目录树,替代多次逐层 ListDir;意图分流引导「recursive=true 一次列出,不要逐层多次」——工具能力 + 提示词双管齐下。
- 验证:127 passed,lint 全过,node --check,冒烟折叠结构正常。
- 教训 26:**"重复"要区分任务理解错误 vs 工具使用低效**——本次 agent 理解正确(读完整个项目是它的目标),重复的是"逐层探索"这一低效工具用法;给 list_dir 加 recursive 是能力层面的解法,提示词只是引导。

## 2026-08-09 最终回复去重(用户澄清:重复 = 最终回答重复输出清单与概述)

- 触发:用户澄清「我说的重复是 agent 最后回答时重复输出了文件清单与概述」——修正上一轮误判(ListDir 逐层探索是另一类低效,但不是用户说的重复)。
- 根因:真实 LLM 中途 Respond/工具前文字已输出文件清单与概述,Stop 时 reason 又把同一份内容完整输出一遍 → 前端两个长气泡重复显示。
- 修复(代码机制,非仅提示词):
  1. `_is_redundant` 确定性去重判定:相同 / 一方包含另一方(短≥20字) / 前30字相同 → 重复
  2. Stop reason 发出前先去重,重复则不发送(已输出的内容即最终答复)
  3. 提示词:「清单/概述等长内容只输出一次」
- 端到端验证:先 Respond 输出清单、Stop reason 重复清单 → 前端只显示一次。
- 验证:129 passed,lint 全过。
- 教训 27:**用户说的"重复"要按字面理解(最终回答重复),不要自行解读成别的**——先确认理解再动手;上轮把 ListDir 探索当重复,方向偏了,浪费一轮。**文本去重是 LLM 输出治理的常见需求,用确定性重叠判定(相同/包含/前缀)做代码层拦截,比提示词可靠。**

## 2026-08-09 agent 回复 markdown 渲染(输出与显示统一)

- 触发:用户反馈「agent 输出接近 markdown 但网页端未渲染,统一一下」。
- 改动:
  1. 自实现极简安全 markdown 渲染器(mdRender/mdInline,零依赖离线可用)——## 标题/- 列表/1. 有序/``` 代码块/`行内代码`/**加粗**/*斜体*/> 引用/[链接];安全:内容先 esc 再转防 XSS,链接仅 http(s)/mailto
  2. 渲染接入:打字机完成/点击跳过/历史加载统一 mdRender(打字中显示纯文本,完成瞬间渲染)
  3. .bubble 下 markdown 元素统一样式(p/ul/li/h1-3/code/pre/blockquote/a);错误消息保持纯文本
  4. 系统提示词加「使用 markdown 格式回复」——agent 输出与前端渲染统一
- 验证:129 passed,lint 全过,node 实测 8 用例(渲染 6 + XSS/危险链接防护 2)全过,冒烟正常。
- 教训 28:**渲染器选型契合项目纪律**——不引 marked.js CDN(离线不可用、破坏零依赖),自实现极简渲染器 + esc 先行防 XSS + 链接协议白名单,和 harness 内核"自实现、确定性、可单测"一脉相承。
- 教训 29:**markdown 渲染的坑在结构判断 vs 内容转义分离**——先整体 esc 再判结构会让 `>` 引用失效(esc 成 &gt;);结构用原始文本、内容经 mdInline 内 esc,才是正确顺序。

## 2026-08-09 修复「反复重读同一文件」空转(60 轮耗尽根因)

- 触发:用户反馈「轮次达到六十后终止了,应该有重复调用」。
- 真实历史(60 步)分析:agent 陷入「反复重读 KWIC.java」死循环——45+ 步全是读同一文件变体(完整/1-40行/1-60行/开头/中部),一次没写代码。三个根因:
  1. read_file 分段无进度提示,agent 不知已读哪些行,反复读开头
  2. offset/lines 用法不明确(offset=1 永远读开头,得不到"全部")
  3. 无重复读取干预机制
- 修复:
  1. read_file 分段回灌行区间进度:「已读第 X-Y 行(共 N 行),下一段用 offset=Y+1」;整读回灌总行数
  2. 连续 3 次 ReadFile 同一路径 → 注入「不要重复读取同一文件,继续下一步或用 offset 读未读部分」提示(确定性可测机制)
  3. 提示词:「已读过的行区间不要重复读」
- 端到端:第 3 次重复读注入提示后 agent 停止重读转写代码。
- 验证:132 passed,lint 全过。
- 教训 30:**"重复调用"的第三层根因是信息不对称**——工具知道读了哪些行,agent 不知道;让工具回灌"已读区间 + 建议下一步 offset",把执行进度显式化,agent 才不盲目重读。工具的反馈质量决定 agent 能否走出循环。

## 2026-08-10 新增 search_file 工具(修复「卡在第 59 轮」)

- 触发:用户反馈「agent 卡在第 59 轮了,提供的工具是不是需要优化」。
- 真实历史(59 步)分析:8 ListDir + 51 ReadFile 全是读 KWIC.java 不同行区间,无一次 WriteFile——agent 深陷「读文件找 TODO」泥潭,每次读完觉得差一段,永远不开始写。
- 根因:**工具缺"定位"能力**——read_file 只有逐段读,agent 想找所有 TODO/方法位置只能反复读全文拼凑。用户方向正确:工具需要优化。
- 修复:新增 search_file(path, pattern, context?)——按内容搜索,返回匹配行+行号(可带上下文),一次找到所有 TODO 位置。全链路接入(models/files/dispatch/guardrail/openai_compat/schema/提示词/前端图标)。
- 端到端:search_file 一次找到所有 TODO 位置与上下文(替代 45 次逐段读)。
- 验证:134 passed,lint 全过。
- 教训 31:**"卡住"的根因常是工具集缺一个能力,而非提示词不够**——agent 反复做同一件事(读文件),是因为那是它唯一能"推进"的动作;补 search_file 这种"定位型"工具,从能力上让"找 TODO"变成一次调用,才是治本。**读历史先看动作类型分布,一眼看出"全在重复一类动作"就是工具集缺口信号。**

## 2026-08-10 工具集多语言化(三层方案实施)

- 触发:用户问「工具集是否需强化以满足多语言测试,或由 agent 主动组织命令」,确认按方案实施。
- 方案(工具能力强化为主,护栏内给自由度,守住确定性核心):
  1. **run_tests 加 test_command 参数**:pytest(默认)/mvn test/npm test/go test;字符串命令 shell 执行,path 越界校验保留
  2. **校验器新增 Maven surefire 解析**(_parse_maven):识别汇总行、失败测试块、file:line、断言差异——确定性纯函数,与 pytest 同一 Feedback 结构(§A.4 不破:反馈永远来自校验器)
  3. **run_shell 白名单扩展**:javac/java/mvn/gradle/npm/npx/node/yarn/go/git(精确首词匹配,rm -rf 仍拦截)
- 端到端 Java 场景闭环:白名单放行 mvn test + 校验器解析 → testShift AssertionFailure @ KWICTest.java:45。
- 验证:139 passed(新增 test_command/Maven 解析/白名单多语言/危险仍拦截),lint 全过。
- 教训 32:**多语言支持要在"确定性反馈"边界内做**——run_tests 多语言化后,反馈仍由校验器解析(test_command 只是换执行器,不是换判定),§A.4"移除 LLM 后机制可单测"不破;若放开让 agent 自己判断测试结果,主贡献就丢了。

## 2026-08-10 效率优化:批处理多动作 + 重复读提前 + search 引导

- 触发:用户反馈「agent 调用工具次数太多,停在第 60 轮,要优化调用逻辑提高效率,速度太慢」。
- 历史分析:54/60 步是 ReadFile(连续重复 50 次)——效率瓶颈是"每轮一次 LLM 往返 + 串行逐段读"。
- 优化(三管齐下):
  1. **多动作批处理**(核心):OpenAI 协议支持一次返回多个 tool_calls,openai_compat 解析全部 → AssistantTurn.actions 存 (动作,intent) 对 → loop 主循环逐个执行(抽 _process_action 承载单动作完整处理链),一轮执行多个动作减少往返;新增 _llm_calls 计数度量
  2. **重复读检测阈值 3→2**:第 2 次重复读同一文件即提示
  3. **search_file 引导强化**:定位先 search,只读相关行区间,不逐段读全文
- 端到端:5 个读文件 2 次 LLM 往返(原来 6 次),~3x 提升。
- 验证:142 passed(新增批处理/提前提示/search 引导测试),lint 全过。
- 教训 33:**效率瓶颈是"往返次数"不是"轮数"**——多动作批处理(一次 LLM 调用执行多个工具)是 coding agent 提速的最直接手段,与 Claude Code 的并行工具调用一致;结构改动(抽 _process_action)让主循环支持批处理而不破坏单个动作的完整处理链。

## 2026-08-10 已读缓存拦截重复读 + 事件带 path(诊断可见性)

- 触发:用户反馈「agent 还是终止了,注意到一直在反复读取」。
- 真实历史(105 步)分析:94 ReadFile(连续重复段 19/17/12/11),intent 反复「完整读取主程序」「掌握所有填空上下文」——agent 的"完整掌握"确认偏好;且事件不带 path,前端/历史无法诊断在读哪个文件(94 次全显示 ReadFile)。
- 修复:
  1. **已读文件缓存**(核心):记录已读文件的行集合;重复读同一文件(或已读行区间)→ 注入「文件已在前面读取过(缓存),内容在对话历史中,不要重复读取;基于已读内容继续下一步」并跳过执行——重复读零成本,打断确认偏好
  2. **action 事件带 path/cmd**:前端工具行显示路径标签,历史含 path——诊断 agent 在读哪个文件
- 端到端:前 5 轮重读同一文件,缓存拦截后实际只执行 2 次 ReadFile。
- 验证:143 passed,lint 全过。
- 教训 34:**诊断盲区会掩盖根因**——事件不带 path,94 次 ReadFile 全显示"ReadFile"无法定位在读哪个文件;事件协议要带操作对象,否则优化无从下手。
- 教训 35:**"反复读取"的根源是 LLM 的确认偏好**(总觉得没掌握全),不是提示词能完全纠正的——代码层缓存拦截(重复读直接跳过+告知)是确定性解法:即使 LLM 还想读,也不会产生实际调用。
