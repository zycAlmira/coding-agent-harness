# SPEC_PROCESS.md

> 记录与 Superpowers 协作生成 SPEC 与 PLAN 的过程,以及正式实现前的"陌生智能体"冷启动验证(§4.5)。
> 基准日期:2026-07-22。

---

## 一、brainstorming 关键节点

brainstorming 技能在本项目里反复追问"你究竟想做什么",在以下节点改变了原设想:

1. **重点维度从"治理"被改到"反馈闭环"**:技能追问"哪个维度做深"时,我原倾向治理(护栏演示最直观)。反思后选反馈闭环——它最能体现"agent 能闭环",且校验器/分类/回灌/停机全是确定性代码,过 §A.4-C 判定最干净。
2. **记忆维度从"做深"降级为"按分类检索的增强"**:技能追问记忆形态时,我一度想把记忆做深(语义检索)。但技能 YAGNI 原则 + §A.4-C 判定(记忆做深须自实现检索且确定性可测)让我意识到:记忆做深会模糊主贡献。最终降为最低实现,与反馈共享同一套 `FailureCategory` taxonomy 作为检索 key,演示时 freeze 记忆库保确定性。这是"方案 C 落地"的关键收敛。
3. **"动作意图 intent"创新点**:我提出"危险动作审批时让 LLM 自述意图方便人类判断"。技能帮我把红线守清:guardrail 判定仍是确定性代码,intent 只是 LLM 生成的解释性散文附在 action 上;判断权仍在人类,不外包给 LLM。最终落地为"每个 action 都带 intent"(方式 1),既给审批用、也给 WebUI 每步可观察性、给 AGENT_LOG 现成动机记录——一举三得。
4. **WebUI 从"可选"变"硬要求"**:技能在我选 WebUI 复杂度前提醒——通用要求 §五第9项规定"必须提供可访问 WebUI 接口",不是可选项。这把项目从纯 CLI 抬到必须有 web 层,直接催生了 FastAPI + SSE 单页观察台设计。
5. **跨平台(Windows)处理**:技能在我定完分发后追问 Windows 支持,触发了对路径围栏(`Path.is_relative_to`)、shell 黑名单(补 `del /s`/`rmdir /s` 等)、`make` 不可依赖(改 `uv run` 主命令)、CI 矩阵(ubuntu+windows)、行尾兼容(validator 用 `splitlines`)的系统性补强。

## 二、至少 3 轮关键迭代

### 迭代 1:LLM 供应商从 Anthropic 改为 OpenAI 兼容

- **对话节选**:我初选 Anthropic Claude。用户中途"等等,我想把 llm 接口改为通用 openAI"。
- **处理决策**:立即改记录。OpenAI 兼容接口可接 GPT/DeepSeek/智谱等,选择面广;凭据因此要存三样(`api_key` + `base_url` + `model`);LLM 抽象层用 Chat Completions + function-calling 协议,mock 实现同接口。

### 迭代 2:反馈闭环方案 A → C(加记忆联动)

- **对话节选**:我推荐方案 A(纯校验器+分类+回灌)。用户"我更认可方案 c"(A + 历史修复记忆联动)。
- **处理决策**:采纳 C,但解决其最大隐患——记忆检索破坏 mock-LLM 确定性。办法:失败分类 taxonomy 同时作反馈信号与记忆检索 key(一个分类表打通两维度);记忆库在机制演示时 freeze 为预置 JSON,检索返回固定结果。这样 C 既深又能过 §A.4-C 判定。

### 迭代 3:WebUI 形态被拦下澄清

- **对话节选**:我抛出 WebUI 复杂度选项,用户没直接选,要求澄清(SSE 是什么、是否挤占做深时间、Open Design 是否必须)。
- **处理决策**:逐条解释 SSE(服务器单向推送,比 WebSocket 轻、比轮询实时)、确认硬要求不可豁免、确认含前端须用 Open Design。用户理解后选"单页观察台",并主动加一条:"状态栏加一个记忆检索到的历史修复"。我据此把记忆检索结果加入右侧状态面板。

## 三、AI 提出而采纳 vs 推翻或修正

**采纳的 AI 建议**:
- "机制必须是代码不是提示词"的红线判断(护栏=函数、反馈=校验器,非提示词)。
- 方案 A 的失败分类 taxonomy 作主贡献脊柱。
- `MAX_ROUNDS=8`、`same_category_stop_at=3`、`no_change_stop_at=2` 等阈值的初值。
- `list_dir` 工具的补加(agent 探索项目结构要用)。
- "演示时 freeze 记忆库保确定性"的设计。

**推翻或修正的**:
- 推翻我最初倾向的"治理做深",改反馈闭环(用户决策)。
- 推翻方案 A,改方案 C(用户决策,我加 freeze 补救确定性)。
- 修正"WebUI 可选"的隐含假设——技能指出它是硬要求。

## 四、brainstorming 技能的好与不满

- **好**:分节呈现+逐节确认,逼我把"intent 红线"、"记忆 freeze"、"Windows shell 黑名单"这些容易在实现期才暴露的细节提前定清;YAGNI 反复砍范围(记忆降级、WebUI 选单页、分发选 clone)。
- **不满**:对"冷启动验证应覆盖哪些 task"未给指引,导致我默认只冷启动 Task 1/2——而这两个 task 太"平"(PLAN 逐字给可运行代码),冷启动信号量偏低(见 §五)。brainstorming 也没提示"脚手架 task 的 TDD 红色容易被工具链错误冒充"这类细节,这些是在冷启动里才暴露的。

## 五、冷启动验证(§4.5,最关键的客观证据)

**做法**:派一个全新 `general-purpose` subagent(与主会话默认 `claude` 类型不同),启动全新上下文、不导入本会话历史,仅给 SPEC+PLAN 两份文档路径,令其实现 Task 1 + Task 2,明确"遇到不确定即暂停询问而非凭猜测继续"。

**类型不同的约束**:§4.5 要求"第二个智能体类型必须不同"。本环境仅 Claude 系列可用,冷启动 subagent 用 `general-purpose` 类型(与主会话默认不同),满足"类型不同";但底层模型同源——记为**部分满足**,在 REFLECTION 中讨论其局限。

### 5.1 第二个 agent 在哪里暂停并提问

**无阻塞性提问**。Task 1/2 描述足够具体(PLAN 给了逐字可运行代码),TDD 闭环跑通。这本身是发现:Task 1/2 属低歧义脚手架层,信号量偏低;真正能暴露 spec 缺陷的 task 在后面(Task 15 loop 的 HITL、Task 19 WebUI 的 `rununner()` 笔误、Task 5 Validator 正则对 pytest 输出的假设)。

### 5.2 暴露的 spec 缺陷(6 项,已据此修订)

| # | 缺陷 | 修订 |
|---|---|---|
| 1 | PLAN Task 1 Step 6"跑红"是工具链失败(pytest 未装),非断言级红;且 Step 7 `uv sync` 在 Step 6 之后 | 调整 step 顺序:`uv sync --extra dev` 移到写测试之后、跑红之前 |
| 2 | PLAN Task 1 `__init__.py` 在写测试之前已建好,导致测试直接绿、跳过"红"阶段,违反 §六第6条 TDD | 把 `__init__.py` 创建移到跑红之后 |
| 3 | PLAN Task 2 `Outcome.ERROR` 越界——SPEC §十二只列 4 值 | SPEC §十二增补 `ERROR` + §3.1 补停机条件"LLM 连续解析失败 3 次→ERROR 停机" |
| 4 | PLAN Task 2 `Verdict` 基类非 dataclass,`is_approval` 是类属性,`asdict` 会丢 | `Verdict` 装饰为 `@dataclass` |
| 5 | PLAN Task 1 .gitignore `!memory/fixes.example.json` 是无效否定 | 删除该无效行 |
| 6 | tests/ 子目录是否需 `__init__.py` 未声明 | File Structure 明确"tests 不加 `__init__.py`,依赖 rootdir+pythonpath" |

### 5.3 修订前后关键 diff

**SPEC §十二(数据模型)— 缺陷 3**:
- 前:`RunResult = { outcome: SUCCESS|STUCK|MAX_ROUNDS|STOPPED, steps, final_feedback }`
- 后:`RunResult = { outcome: SUCCESS|STUCK|MAX_ROUNDS|STOPPED|ERROR, steps, final_feedback }`

**SPEC §3.1(主循环边界)— 缺陷 3 配套**:
- 前(无 error 停机条件)
- 后:补"LLM 连续解析失败 3 次 → outcome=ERROR 停机"

**PLAN Task 1 step 顺序 — 缺陷 1+2**:
- 前:Step2 建 `__init__.py` → Step5 写测试 → Step6 跑红(实为工具链错)→ Step7 `uv sync` → Step8 跑绿
- 后:Step1 pyproject → Step2 写测试 → Step3 `uv sync --extra dev` → Step4 跑红(`ModuleNotFoundError`,断言级)→ Step5 建 `__init__.py` → Step6 跑绿

**PLAN Task 2 Verdict — 缺陷 4**:
- 前:`class Verdict: is_approval: bool = False`(普通类)
- 后:`@dataclass class Verdict: is_approval: bool = False`

**PLAN Task 1 .gitignore — 缺陷 5**:
- 前:含 `!memory/fixes.example.json`(无效)
- 后:删除该行

### 5.4 产出与预期差距

- Task 1/2 均跑通,`uv run pytest -q` 4 passed。
- Task 1 的"红"不纯(工具链错),Task 2 的"红"是真正断言级红。
- commit:`437142b`(Task 1)、`306c2a5`(Task 2)。
- **决策**:冷启动的 commit 将被 reset 回基线 `f07f8cd`,让正式 subagent-driven 执行用修订后的 PLAN 从 Task 1 干净重跑(保 TDD 纪律)。冷启动代码不保留,其价值是上述过程证据。

### 5.5 对 SPEC/PLAN 的整体判断

冷启动证明:SPEC/PLAN 在脚手架层足够清晰可执行;但 PLAN 在 TDD step 顺序上有形式违规(已修订),且存在 1 处越界(`Outcome.ERROR`,已补 SPEC)。修订后可进入实现。
