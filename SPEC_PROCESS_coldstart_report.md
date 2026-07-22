# 冷启动验证报告(Cold Start Verification)

> 验证对象:`docs/superpowers/specs/2026-07-21-coding-agent-harness-design.md`(SPEC)
> + `docs/superpowers/plans/2026-07-22-coding-agent-harness.md`(PLAN)
> 验证范围:仅 Task 1(项目脚手架与依赖)+ Task 2(值类型与数据模型 models.py)
> 验证者:Cold Start Agent(全新会话,仅凭 SPEC+PLAN,无先前上下文)
> 基准日期:2026-07-22
> 分支:`feature/coding-agent-harness`

---

## 1. 暂停并提问之处

**无。** 整个 Task 1 + Task 2 过程中没有遇到需要暂停提问的阻塞性歧义。两份文档对这两个 task 的描述足够具体(PLAN 给出了逐字可用的 pyproject.toml / Makefile / models.py / 测试代码),TDD 红-绿-提交闭环跑通。

这本身是一个发现:Task 1/2 属于低歧义脚手架层,冷启动验证的"spec 缺陷信号"主要会来自后续 task(尤其 Task 15 主循环、Task 19 WebUI——PLAN 已自承 Task 19 Step 4 有 `rununner()` 笔误占位)。冷启动若只跑 Task 1/2,信号量偏低;建议后续冷启动样本至少覆盖到 Task 5(Validator)或 Task 15(loop)。

---

## 2. SPEC/PLAN 的缺陷、歧义、遗漏(修订建议)

### 2.1 [PLAN Task 1 Step 6] "跑测试验证失败"的红色语义不纯

- **现状**:`uv run pytest tests/test_scaffold.py -v` 在未 `uv sync --extra dev` 时,`uv` 会自动创建 `.venv` 并安装**主依赖**(fastapi/httpx/…),但 pytest 属于 dev extra 未装,于是失败信息是 `error: Failed to spawn: pytest`(工具链错误),而非测试断言失败。
- **问题**:严格 TDD 意义上的"红"应是"测试被收集并断言失败"。这里得到的是"测试根本无法运行"。PLAN 虽然用括号注明"若 uv 未初始化则先 `uv sync`",但顺序上 Step 6(跑红)在 Step 7(`uv sync --extra dev`)之前,导致首次跑必然是工具链失败而非测试失败。
- **修订建议**:把 Step 7(`uv sync --extra dev`)移到 Step 6 之前;或把 Step 6 改为"先 `uv sync --extra dev`,再跑测试,断言 `ModuleNotFoundError: No module named 'coding_agent_harness'`"(因为此时 `src/coding_agent_harness/__init__.py` 已建但 pytest pythonpath=src 配置已生效,实际上包已可 import——见下条矛盾)。
- **前后对照**:
  - 前:`Step 6 跑红 → Step 7 uv sync → Step 8 跑绿`。
  - 后:`Step 6 uv sync --extra dev → Step 7 跑红(断言 ImportError) → Step 8 写实现 → Step 9 跑绿`。

### 2.2 [PLAN Task 1] 测试与实现的"红"几乎不可能真正出现

- **现状**:PLAN Step 2 在 Step 5(写测试)之前就已经写好了 `src/coding_agent_harness/__init__.py`(含 `__version__ = "0.1.0"`),且 `pyproject.toml` 里 `pythonpath = ["src"]`。因此当 Step 5 的测试 `assert m.__version__ == "0.1.0"` 第一次能跑起来时,它**直接 PASS**,根本没有"红"阶段。
- **问题**:违反 TDD 红线"先写失败测试再写实现"(CLAUDE.md §六第 6 条)。脚手架 task 的"实现"(`__init__.py`)与"测试"是同一 step 批次写入,红色被跳过。
- **修订建议**:二选一。
  1. 把 Step 2(`__init__.py`)移到 Step 6(跑红)之后,即先只有测试 + pyproject(无包源码)→ 跑红 → 再建 `__init__.py` → 跑绿。
  2. 或把测试断言改成"更严格的契约",例如 `assert m.__version__ == "0.1.0" and hasattr(m, "__author__")`,先红后补 `__author__`。
- **前后对照**:
  - 前:Step 2 建 `__init__.py` → Step 5 写测试 → Step 6 跑(直接绿)。
  - 后:Step 1 建 pyproject → Step 2 写测试 → Step 3 跑红(`ModuleNotFoundError`) → Step 4 建 `__init__.py` → Step 5 跑绿。

### 2.3 [SPEC §十二 vs PLAN Task 2] `Outcome` 枚举的 `ERROR` 值越界

- **现状**:SPEC §十二 `RunResult = { outcome: SUCCESS|STUCK|MAX_ROUNDS|STOPPED, … }`——只列 4 个值。PLAN Task 2 Step 3 的 `Outcome` 枚举额外加了 `ERROR = "error"`,且 Task 15 `loop.py` 的 `outcome = "error"` 分支会用到它。
- **问题**:PLAN 超出 SPEC 定义。SPEC 没有声明 `ERROR` 这个停机原因,也没有对应的停机条件(SPEC §3.4 停机列举:成功/max_rounds/same_category_stop/no_change_stop/LLM stop——没有"error")。
- **修订建议**:要么在 SPEC §十二补 `ERROR`(并补对应停机条件"LLM 调用/解析连续失败"),要么从 PLAN 删除 `ERROR`、用 `STUCK` 兜底。
- **前后对照**:
  - 前(SPEC §十二):`outcome: SUCCESS|STUCK|MAX_ROUNDS|STOPPED`。
  - 后(建议 SPEC 增补):`outcome: SUCCESS|STUCK|MAX_ROUNDS|STOPPED|ERROR`,并在 §3.1 边界补"LLM 连续解析失败 3 次 → outcome=ERROR 停机"。

### 2.4 [PLAN Task 2] `Verdict` 基类设计脆弱(非 dataclass 作 dataclass 基类)

- **现状**:`class Verdict: is_approval: bool = False`(普通类,非 `@dataclass`),其子类 `Allow/Deny/NeedsApproval` 是 `@dataclass`。`Deny` 未声明 `is_approval`,依赖从 `Verdict` 继承的**类属性** `False`。
- **问题**:`is_approval` 在 `Deny` 上是类属性而非实例字段,`dataclasses.asdict(Deny(...))` 不会包含它;若后续 Task 11 guardrail 或 Task 19 WebUI 用 `asdict` 序列化 verdict,`is_approval` 会丢失。同时 `Verdict` 不是 dataclass 却被当基类,读者易误以为它是。
- **修订建议**:把 `Verdict` 也装饰为 `@dataclass`(field 带 default),或干脆让 `Allow/Deny/NeedsApproval` 各自独立声明 `is_approval` 字段,不共享基类。当前测试能过,但留给后续 task 隐患。
- **前后对照**:
  - 前:`class Verdict: is_approval: bool = False`(普通类)。
  - 后:`@dataclass class Verdict: is_approval: bool = False`(统一为 dataclass,字段语义一致)。

### 2.5 [PLAN Task 1 .gitignore] `!memory/fixes.example.json` 是无效否定

- **现状**:.gitignore 只 ignore 了 `memory/fixes.json`,并没有 ignore 整个 `memory/` 目录。`!memory/fixes.example.json` 这条否定规则不会起任何作用(`fixes.example.json` 本来就没被忽略)。
- **问题**:无害但误导,读者会以为有某条规则忽略了 `memory/` 需要反向打洞。
- **修订建议**:删除 `!memory/fixes.example.json`,或改成 `memory/*.json` + `!memory/fixes.example.json` + `!memory/conventions.example.json`(如果确实只想跟踪 example)。
- **前后对照**:
  - 前:`memory/fixes.json` / `!memory/fixes.example.json`。
  - 后:`memory/*.json` / `!memory/fixes.example.json`(若要真正起作用)。

### 2.6 [PLAN Task 1 Step 9] commit 命令不含 `tests/unit/` 的 `__init__.py`

- **现状**:Task 2 在 `tests/unit/` 下建 `test_models.py`,但 `tests/` 与 `tests/unit/` 均无 `__init__.py`。pytest 在 rootdir + pythonpath=src 配置下能跑(本次验证通过),但 SPEC §十三目录结构未声明 tests 子包是否需要 `__init__.py`,PLAN 也未提。
- **问题**:不影响功能,但跨平台/跨 pytest 版本时,无 `__init__.py` 的 test 目录在 rootdir 推断失败时可能报 `import file mismatch`。属隐患。
- **修订建议**:在 PLAN File Structure 里明确"tests 目录不加 `__init__.py`(依赖 rootdir + pythonpath)"或"tests 每级加 `__init__.py`"。建议前者,并在 Task 1 Step 4 的 .gitignore 旁补一句说明。

---

## 3. 与文档原意可能不一致的解读

### 3.1 Task 1 Step 6 的"红"我用工具链失败替代了断言失败

- **我的做法**:直接按 PLAN 顺序跑,得到 `Failed to spawn: pytest` 视作"红",然后 `uv sync --extra dev` 再跑绿。
- **判断**:**文档写法有瑕疵**(见 2.1/2.2),不是我读错。PLAN 的 step 顺序导致"红"被工具链错误冒充,且 `__init__.py` 在测试前已建导致根本不会出现断言级红色。我遵循了 PLAN 字面顺序未自行调整,如实记录于此。

### 3.2 `Outcome.ERROR` 我照 PLAN 写入但 SPEC 未定义

- **我的做法**:按 PLAN Task 2 Step 3 逐字写 `ERROR = "error"`。
- **判断**:**PLAN 越界扩展 SPEC**(见 2.3)。我未自行删除,因为 PLAN 是执行依据;但标记为 spec 缺陷,需 SPEC 增补或 PLAN 回退。

### 3.3 其余无偏离

models.py、pyproject.toml、Makefile、.gitignore、__init__.py、两个测试文件均逐字照 PLAN 写,未自行增删字段或断言。

---

## 4. 产出与预期差距

| Task | 是否跑通 | 红色质量 | 绿色 | 备注 |
|---|---|---|---|---|
| Task 1 | 跑通 | 工具链失败(非断言红,见 2.1/2.2) | 1/1 PASS | commit `437142b` |
| Task 2 | 跑通 | 断言级红(`ModuleNotFoundError`,符合 TDD) | 3/3 PASS | commit `306c2a5` |

- 全量 `uv run pytest -q`:4 passed。
- 无阻塞,无遗留 todo。
- Task 1 的"红"不纯(工具链错),Task 2 的"红"是真正断言级红,符合 TDD。

---

## 5. Commit hash 列表

| commit | task | message |
|---|---|---|
| `437142bd7fb2b243142fd70b27ca39fa3270168f` | Task 1 | `chore: 项目脚手架与依赖` |
| `306c2a537d541fb6492923303896f38a510be62d` | Task 2 | `feat(models): 动作/判定/工具结果值类型` |

(基线 `f07f8cd docs: 项目文档与 SPEC/PLAN 初始提交` 来自主会话,非本冷启动 agent 产出。)

---

## 6. 最大发现

**冷启动在 Task 1/2 上信号量不足——这两个 task 太"平",PLAN 逐字给了可运行代码,agent 几乎只是抄写+跑测试。** 真正能暴露 spec 缺陷的 task 在后面(Task 15 主循环的 HITL 状态机、Task 19 WebUI 的 `rununner()` 笔误、Task 5 Validator 正则对 pytest 输出格式的假设)。建议冷启动样本至少延伸到 Task 5(校验器,有 fixture 契约)或 Task 15(loop,有状态机与 mock 交互),否则"冷启动验证"对 spec 质量的评估会偏乐观。

次级发现:PLAN 的 TDD 纪律在 Task 1 上有形式违规——`__init__.py` 在测试之前就已写好,导致"红"被工具链错误冒充、而非断言失败。CLAUDE.md §六第 6 条"先写失败测试再写实现"在脚手架 task 里被悄悄破例,应修订 step 顺序。
