# Coding Agent Harness — 设计文档（SPEC）

> 项目:AI4SE 期末项目 · Project A · Coding Agent Harness
> 完整要求 =《通用要求》+《AI4SE_Final_Project_A_Coding_Agent_Harness.md》
> 本文档由 brainstorming 技能沉淀,签字确认后转入 writing-plans。
> 基准日期:2026-07-21。

---

## 一、问题陈述

**要解决什么问题**:当 LLM 能完成大部分"思考"时,工程师的价值落在 harness 这层工程。本项目构建一个 Coding Agent Harness 内核——把"只会产生下一步设想的 LLM"封装成"能稳定、可靠完成修测试任务"的系统,并重点打磨**反馈闭环**(让 agent 获得关于"其行为是否正确"的客观信号并据此自我修正)。

**目标用户**:需要一个能读写代码、执行命令、运行测试,并根据测试结果自我修正的 agent 的开发者——他们想要一个可观察、可治理、内核自实现(而非寄生于现成框架)的 coding agent,在本地即可运行。

**为什么值得做**:反馈闭环是 agent 从"单轮生成"走向"自主多轮修正"的关键。把它做成确定性代码(校验器 + 失败分类 + 结构化回灌 + 停机),并用 mock LLM 离线复现,是对"哪些工程是 LLM 替不掉的"的第一手回答。

## 二、用户故事（INVEST）

1. 作为开发者,我想在一个全新仓库 clone 后用一条命令起 WebUI,以便快速用上这个 agent。(*I*NVEST:独立、可协商、有价值、可估、小、可测)
2. 作为开发者,我想看 mock LLM 下确定性复现"注入失败 → agent 据反馈改变下一步",以便确信反馈闭环是真机制而非一句提示词。
3. 作为开发者,我想在 WebUI 单页实时看到 agent 每一步的思考意图与动作,以便理解 agent 在干什么。
4. 作为开发者,我想在 agent 要删文件 / 跑未知 shell 时被拦截并弹审批(带 LLM 自述意图),以便安全放行。
5. 作为开发者,我想把 API key 存进系统钥匙串、查看状态时不回显明文,以便安全使用付费 LLM。
6. 作为开发者,我想让 agent 记住同类失败的历史修复并在下次回灌,以便它不重复踩坑。

## 三、功能规约（按模块）

### 3.1 agent 主循环 `core/loop.py`
- 输入:任务描述 + workspace 路径 + Config。
- 行为:组织上下文 → 调 LLM → 解析动作(含 intent)→ 护栏判定 → (审批)→ 工具分发执行 → 校验 → 回灌 → 停机判断;每步推 SSE 事件。
- 输出:`RunResult { outcome, steps, final_feedback }`。
- 边界:最大轮数 `max_rounds`;LLM 调用失败时把错误当 feedback 回灌降级,不崩。
- 错误处理:LLM 解析失败 → 回灌"输出格式非法"并重试本轮;连续解析失败 3 次停机。

### 3.2 LLM 抽象层 `llm/`
- 接口 `LLMClient.complete(messages, tools) -> AssistantTurn`。
- 真实实现 `OpenAICompatibleClient`:OpenAI 兼容 Chat Completions + function-calling;凭据从 Keychain 读;key 不进日志。
- mock 实现 `MockLLMClient`:脚本化分支,据当前 `LoopState`/上一轮 `Feedback` 选动作;不触网。
- 边界:超时、重试、错误回灌。

### 3.3 工具集 `tools/`
- `read_file` / `write_file` / `delete_file` / `list_dir` / `run_shell` / `run_tests` / `stop`。
- `dispatch(action) -> ToolResult`;`run_tests` 返回结构化 `PytestRun`,**不自己判 pass/fail**(交给 Validator)。
- 输出超长截断(阈值可配);跨平台 shell 走 `shell=False` 拆参。

### 3.4 反馈闭环 `feedback/`（**主要贡献**）
- `Validator.parse(PytestRun) -> Feedback`:解析 pytest 输出为结构化反馈(状态、失败用例、分类、file:line、traceback 摘要、断言行)。纯函数。
- `taxonomy.py`:`FailureCategory` 枚举(AssertionFailure / ImportError / AttributeError / NameError / TypeError / SyntaxError / CollectionError / Timeout / Unknown),每个带确定性"建议策略提示"。
- 回灌:主循环组装结构化 feedback 消息注入 `messages`(不塞整段 stdout),并附 `Memory.retrieve(category)` 的历史修复。
- 策略切换:`same_category_streak >= same_category_prompt_at`(默认 2)→ 插"换思路"提示;连续 `no_change_stop_at`(默认 2)轮 `failed_tests` 集合全等 → 插"回退最近改动"提示。
- 停机(代码里写死,阈值来自配置):成功(某轮 PASS)/ 达 `max_rounds`(默认 8)/ `same_category_streak >= same_category_stop_at`(默认 3)/ 连续无变化达 `no_change_stop_at` / LLM 主动 `stop`。

### 3.5 治理护栏 `guardrails/`
- `guardrail(action) -> Verdict{Allow | Deny(reason) | NeedsApproval(reason)}`。纯函数。
  - `delete_*`:一律 `NeedsApproval`。
  - `write_file` 出 project_root:`NeedsApproval`;项目内:`Allow`。
  - `run_shell`:黑名单 `Deny`(不可放行)/ 白名单(pytest/ruff/mypy)`Allow` / 其他 `NeedsApproval`。
  - `read_file` / `list_dir` / `run_tests` / `stop`:`Allow`。
- HITL 状态机:RUNNING → `NeedsApproval` → PENDING_APPROVAL → 推 SSE `approval_request`(带 reason + LLM intent)→ 用户 approve/deny POST → 回灌执行或"被拒"→ RUNNING。审批超时默认 5 分钟按拒绝。
- 路径围栏:`Path.resolve()` + `is_relative_to(project_root)`,防 `../` 逃逸,兼容 Windows 盘符/大小写。

### 3.6 创新点:动作意图 intent
- LLM 输出契约:`AssistantTurn { action, intent, raw }`。**每个** action 都带 `intent`(一句话动机)。
- WebUI 每步显示 intent;审批事件复用 intent 帮助人类判断。
- 红线区分:**机制(guardrail 判定 / 状态机)是确定性代码;intent 是 LLM 生成的内容**。判断权仍在人类,不外包给 LLM。

### 3.7 记忆 `memory/`（最低实现,非重点）
- 自实现 JSON store(不接框架 memory、不走向量库):
  - `fixes.json`:`[{category, symptom, fix, timestamp}]`,按 `FailureCategory` 索引。
  - `conventions.json`:项目约定,启动时全量载入系统提示。
- `retrieve(category, top_k=3)`:精确匹配取最近 top_k 条,纯函数确定。
- 写入:任务结束时若跑出过失败,追加 `(最终分类, 是否修好, 修复手法)`。**循环内不写**(避免破坏 mock 确定性)。
- 演示时 freeze 预置 `fixes.json`。

### 3.8 配置 `config.py`
- `load_config(path) -> Config`(冻结 dataclass)。YAML。
- 字段见 §五配置示例。所有阈值来自配置,代码不写死。

### 3.9 WebUI `web/`
- FastAPI:`POST /api/tasks`、`GET /api/tasks/{id}/events`(SSE)、`POST /api/tasks/{id}/approvals/{aid}`、`GET/POST /api/credentials/*`。
- 单页前端(`EventSource`)+ Open Design 设计系统。左侧主循环时间线(每步 intent + verdict + feedback + 内联审批按钮),右侧状态面板(轮数 / 当前 Feedback / 同分类连续 / **记忆检索到的历史修复**)。红变绿高亮。
- 进程内 `asyncio.Queue` per task 串事件。

### 3.10 凭据 `creds/`
- `keyring` 封装;存 `api_key` + `base_url` + `model`,服务名 `coding-agent-harness`。
- CLI `harness creds status|set|clear`;`status` 不回显明文。首次运行引导隐藏录入。
- 三平台后端:macOS Keychain / Windows Credential Manager / Linux Secret Service。

## 四、非功能性需求

- **性能**:单轮 LLM 调用是主成本;mock 下整 loop < 1s。SSE 延迟 < 200ms。
- **安全**:见 §六凭据威胁模型。
- **可用性**:一条 `uv run harness serve` 起服务;WebUI 自引导配 key。
- **可观测性**:每步推 SSE 事件 + 写 AGENT_LOG;intent 落日志;key 永远 `***`。
- **跨平台**:macOS / Linux / Windows 10+;CI 矩阵跑 ubuntu + windows。

## 五、系统架构与数据流

```
用户任务 → WebUI(FastAPI+SSE)→ AgentLoop(自实现主循环)
  Loop: 组上下文 → LLMClient(real/mock)→ Action(含 intent)
        → guardrail(action) →[Allow|Deny|NeedsApproval→HITL]
        → dispatch(action) → ToolResult
        → (run_tests 时) Validator.parse → Feedback
        → 回灌 Feedback + Memory.retrieve(category) → 下一轮
        → 停机判断 → RunResult
```

组件:WebUI / AgentLoop / LLM 抽象层 / Tools / Validator+Taxonomy / Guardrail+HITL / Memory / Config / Creds。组件间只经接口依赖,mock 下整条可单测。

## 六、凭据与分发设计

### 6.1 凭据
- 存储:macOS Keychain / Windows Credential Manager / Linux Secret Service(经 `keyring`)。
- 录入/查看/清除:`harness creds set|status|clear`;查看不回显。
- 环境变量仅作可选来源(`HARNESS_API_KEY` 等),主路径走钥匙串;SPEC 说明 `.env`/环境变量明文风险。
- 云部署例外:云上无 Keychain,走平台 secrets 注入环境变量;SPEC 标注此差异的边界。

### 6.2 威胁模型
- key 泄露 → 冒用账号花钱。对策:钥匙串加密、不回显、不进日志/git。
- 路径围栏外写入 → 覆盖用户文件。对策:围栏 + 审批。
- shell 黑名单 → `rm -rf` 等。对策:Deny 不可放行。
- mock/真实混用泄露真实 key。对策:mock 测试不读 Keychain、不触网。

### 6.3 分发
- 主形态:clone + 一键运行。`uv run harness serve`(三平台通用);`make run` 仅 Unix 便利别名。
- 依赖:`uv` 锁 `uv.lock`;目标机需 Python 3.11+ 与 `uv`。
- 云部署(硬要求 §五第9项):Dockerfile + Render/Fly.io 免费层;GitHub Actions 构建+部署;控成本。
- 已知限制:macOS/Linux/Windows 10+ 主流平台;需 Python 3.11+ 与 `uv`;Windows 桌面会话才能用 Credential Manager;真实运行需 OpenAI 兼容端点 key。

## 七、技术选型与理由

- **语言 Python 3.11+**:harness 与 demo 目标同语言(pytest),subprocess 跑测试最顺;mock/单测工具链成熟;把精力放在机制而非语言摩擦。
- **LLM:OpenAI 兼容接口**:可接 GPT / DeepSeek / 智谱等兼容端点,选择面广;LLM 抽象层用 Chat Completions + function-calling 协议,mock 实现同接口。
- **后端 FastAPI**:原生 SSE 支持、asyncio 串事件、轻量。
- **前端 Open Design**(§3.6 强烈推荐):用其设计系统 token + 组件构建单页。
- **凭据 keyring**:跨平台后端一站式。
- **依赖管理 uv**:锁文件可复现,三平台一致。

## 八、领域与机制设计（Project A 专属,§A.5）

- **领域反馈信号(coding)**:运行 pytest → exit code + traceback → 客观、确定、可回灌。落实为 `Validator.parse` 纯函数 + `FailureCategory` taxonomy + 结构化 `Feedback`,而非"让 LLM 自查"的提示词。
- **危险动作(coding)**:删文件/目录、写项目目录外、任意 shell。落实为 `guardrail(action)` 纯函数 + HITL 状态机 + 路径围栏。黑名单 Deny 不可放行。
- **所需工具**:read/write/delete/list_dir/run_shell/run_tests/stop。
- **记忆需求(coding)**:跨会话记同类失败的历史修复 + 项目约定。落实为自实现分类索引 JSON store + 纯函数 retrieve(不接框架 memory)。
- **重点维度:反馈闭环**。理由:它最能体现"agent 能闭环",且校验器/分类/回灌/停机全是确定性代码,过 §A.4-C 判定最干净。记忆作为按分类检索的增强,与反馈共享同一 taxonomy,演示时 freeze 以保确定性。
- **如何编码(呼应 §A.4)**:(A) 主循环、LLM 抽象层、工具分发、护栏、校验器、记忆全部自实现,不寄生 LangChain/AutoGen 等高层循环;(B) 反馈=校验器代码、危险动作=护栏代码,非提示词;(C) 移除真实 LLM 后,validator/guardrail/memory/dispatch/停机均可用 mock LLM 单测;(D) 六维度有最低实现,反馈闭环做深(失败分类 + 策略切换 + 停机 + 记忆联动)。

## 九、验收标准

- clone 后 `uv run harness serve` 起 WebUI(macOS/Windows CI 均过)。
- `make test` / `uv run pytest` 一键过,不触网、不用真实 LLM。
- §A.6 三个机制演示(`tests/demo/`)可独立运行、确定性复现:
  ① 护栏拦截危险动作并带 intent 推审批;② 注入失败后反馈闭环改变下一步并红变绿;③ 连续同类失败触发策略切换并按停机条件停。
- 凭据 `status` 不回显明文;首次引导录入;三平台 keyring 后端可用。
- 云部署提供可访问公网 WebUI URL。
- 仓库无任何真实凭据。

## 十、风险与未决问题

- **pytest 输出格式变动**:pin 版本 + parser 单测覆盖多 fixture 样例。
- **mock 脚本脆**:演示测试是契约,改逻辑要同步改 mock。
- **Unknown 分类占比高**:先 mock 跑通主流,真实运行后统计再迭代 taxonomy(写 REFLECTION)。
- **Open Design 集成成本**:开跑前确认其与单页静态前端契合度,必要时调整 §3.9 技术选型。
- **云部署 key 边界**:云走环境变量,需在 §6 明确两种路径边界。
- **Windows shell 语义弱**:`cmd` 不如 `bash`,复杂管道行为不同;标为已知限制,演示主跑 macOS/Linux。

## 十一、配置示例（config.example.yaml）

```yaml
project_root: ./workspace

llm:
  provider: openai-compatible
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat

guardrails:
  max_rounds: 8
  same_category_prompt_at: 2    # 达此值插"换思路"提示(不停机)
  same_category_stop_at: 3      # 达此值停机(标记卡住)
  no_change_stop_at: 2          # 连续 failed_tests 全等达此值停机
  approval_timeout_sec: 300
  shell_blacklist: [rm -rf, git push, sudo, curl, wget, chmod 777,
                   "del /s", "rmdir /s", "Remove-Item -Recurse", format, diskpart]
  shell_whitelist: [pytest, ruff, mypy]

feedback:
  pytest_args: [--tb=short, -p, no:cacheprovider, --no-header, -q]
  max_traceback_excerpt_lines: 8

memory:
  fixes_path: ./memory/fixes.json
  conventions_path: ./memory/conventions.json
  retrieve_top_k: 3
```

## 十二、数据模型

```
Action = WriteFile(path,content) | DeleteFile(path) | RunShell(cmd)
       | RunTests() | ReadFile(path) | ListDir(path) | Stop(reason)
AssistantTurn = { action, intent, raw }
Verdict = Allow | Deny(reason) | NeedsApproval(reason)
ToolResult = { ok, output, structured: PytestRun|None, error }
PytestRun = { exit_code, stdout, stderr, duration_s }
Feedback = { status: PASS|FAIL, failed_tests: [FailedTest], passed_count, summary }
FailedTest = { nodeid, category, file, line, traceback_excerpt, assertion_diff }
Fix = { category, symptom, fix, timestamp }
LoopState = { rounds, last_category, same_category_streak,
              no_change_streak, feedback_history, steps }
Step = { turn: AssistantTurn, verdict, tool_result, feedback, ts }
RunResult = { outcome: SUCCESS|STUCK|MAX_ROUNDS|STOPPED, steps, final_feedback }
```

不变式:`Feedback.failed_tests[].category` ∈ taxonomy;`Step` 中 `approval_request` 后必跟 `approval_decision`。

## 十三、目录结构

```
coding-agent-harness/
├─ pyproject.toml uv.lock Makefile README.md CLAUDE.md
├─ config.example.yaml Dockerfile .github/workflows/ci.yml
├─ src/coding_agent_harness/
│  ├─ main.py config.py
│  ├─ core/{loop,state}.py
│  ├─ llm/{base,openai_compat,mock}.py
│  ├─ tools/{dispatch,files,shell,tests_runner}.py
│  ├─ feedback/{validator,taxonomy}.py
│  ├─ guardrails/guardrail.py
│  ├─ memory/store.py
│  ├─ creds/keychain.py
│  └─ web/{app.py, static/}
├─ tests/{unit,integration,demo}/
├─ scripts/demo.sh
└─ workspace/  (demo 目标:failing pytest)
```
