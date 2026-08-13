# Coding Agent Harness

AI4SE 期末项目 · Project A · Coding Agent Harness。一个**由学生自己编码实现**的 Coding Agent 内核,以**反馈闭环(feedback loop)**作为主贡献维度。

## 简介

本仓库承载一个自研的 Coding Agent Harness 内核:agent 主循环(组织上下文 → 调 LLM → 解析动作 → 分发执行 → 回灌结果 → 停机判断)、可注入 mock 的 LLM 抽象层、工具分发、治理护栏、反馈校验器、记忆读写,全部自实现,**不寄生于任何现成 agent 框架的高层循环**(§A.4 红线)。

六维度最低实现齐全(决策/工具/记忆/治理/反馈/配置),其中**反馈闭环**做深:

- `feedback/validator.py` 是**纯函数**,解析 pytest 输出得到结构化 `Feedback`(失败分类 `FailureCategory` + 文件/行/traceback 摘要),回灌给 agent 使其在下一步改变行为。
- 反馈信号 = 确定性校验器,不是"提醒 LLM 注意"的提示词。
- 每个核心机制(工具分发、治理拦截、反馈回灌、记忆读写、停机)在 **mock/stub LLM 下均可用确定性单元测试验证**(§A.4 判定标准:移除真实 LLM 后机制能否用单测验证)。

## 分支与交付

- **默认分支 `feature/coding-agent-harness` 即交付分支**:全部实现代码(24 个 Plan task + 后续 WebUI/CI/部署打磨)都在该分支,clone 下来即可直接使用。`main` 分支仅含项目文档与 SPEC/PLAN 初始提交,不承载实现。
- 开发流程遵循 Superpowers 七步(§4):每功能/大模块开分支(或 worktree)一个 PR,提交/PR 描述标注由哪个 subagent 完成、人工改了哪些;`PLAN.md` 每完成一个 task 即标记完成并附 commit hash(详见根目录 `AGENT_LOG.md` 的全程记录)。

## 安装

需 Python >= 3.11。用 [uv](https://docs.astral.sh/uv/) 管理依赖。

```bash
# 开发(含 pytest/ruff):
uv sync --extra dev
# 仅运行(主依赖):
uv sync
```

控制台脚本 `harness` 已在 `pyproject.toml` 的 `[project.scripts]` 注册。

## 运行

### CLI:harness 命令(交互式对话 / 单次任务 / WebUI / 凭据)

控制台脚本 `harness` 已注册,支持三种使用方式:

**① 交互式对话 `harness chat`(推荐,类 Claude Code)**

```bash
# 在任意项目目录打开终端,chat 自动以当前目录为工作目录(无需配置):
cd /path/to/my-project
harness chat

# 首次使用需录入一次凭据(真实 LLM):
harness creds set

# 进入对话模式后:
❯ 列出文件                      # 输入任务
  📂 ListDir . | 查看目录        # 工具动作实时显示
🤖 已列出项目目录树:...          # agent 回复(markdown 渲染)
❯ 继续,看看 KWIC.java          # 多轮对话,上下文保持
❯ exit                          # 退出(或 Ctrl+C)
```

- 无 `config.yaml` 时自动用默认配置(默认 DeepSeek + 当前目录),**开箱即用**
- 也可 `HARNESS_PROJECT_ROOT=/path` 显式指定工作目录
- 支持 Windows 终端(自动禁用 ANSI 乱码、emoji 换 ASCII)

**② 单次任务 `harness run`**

```bash
# 跑一次任务,输出 agent 完整过程:
harness run "修复 calc.py 的加法测试"
```

**③ WebUI `harness serve`**

```bash
harness serve                          # mock LLM(无需 key,演示)
harness serve --real                   # 真实 LLM(需 creds set)
harness serve --real --project-root ./my-project
```

浏览器访问 `http://localhost:8000`。

**④ 全局安装(任意目录可用)**

```bash
uv tool install .
# 之后任何目录 `cd` 进去即可 `harness chat`(无需 uv run)
```

### 测试与 lint

```bash
make test     # 等价 uv run pytest -q
make lint     # uv run ruff check src tests
```

## WebUI 使用说明

启动后(`harness serve` 或线上部署)浏览器访问,界面为三栏布局:

**顶栏**
- `＋ 新会话`:开始新对话
- 模型下拉:切换 LLM 供应商/模型(切换自动更新 base_url)
- `📁 工作目录`:选择 agent 工作区(本地 macOS/Windows 用系统选择器;无 GUI 服务器弹输入框手动填绝对路径)
- 模式徽章 `mock ⇄ real`:点击切换 mock/真实 LLM(real 需先录入凭据)
- `🔑` 凭据管理:录入 API Key/Base URL/Model(隐藏输入)

**聊天区**
- 输入任务 → agent 实时显示工具动作(📖读/✏️写/🧪测/📂列/🔍搜,可点击展开详情)
- agent 回复为 markdown 渲染(标题/列表/代码块)
- 多轮对话:同一会话可继续追问,上下文保持
- 任务完成后工具调用自动折叠成「N 步工具调用」按钮,点击展开

**侧栏**:`📋 历史`(所有对话,点击加载)/ `📂 文件`(工作区文件树,点击查看内容)

**右面板**:会话状态/对话轮/模型/模式 + 「更多统计」折叠(轮次/护栏拦截/审批/工具调用)

**典型演示流程**(详见「机制演示」):选工作区 → 输入「阅读并完成代码」→ agent 读文件、search 定位填空、写代码、`mvn test` 验证、反馈修复 → 测试全绿 → 总结。

## 凭据与安全配置

LLM/付费 API key **绝不硬编码、绝不进 git(含 history)、不进日志/shell history/明文配置**(通用 §3.1)。本仓库用 macOS Keychain(经 `keyring`)安全存储,首次运行引导隐藏录入,可查看/更新/清除,**查看不回显明文**。

```bash
# 录入(api_key 用 getpass 隐藏录入,不经 readline,不进 shell history):
uv run harness creds set
# 查看(只返回"已设置/未设置",绝不回显 key):
uv run harness creds status
# 清除:
uv run harness creds clear
```

- `.env`(若用)经环境加载而非 `export`;仓库内 `.gitignore` 已忽略 `.env`/`.env.*`。
- 真实 LLM 客户端(`llm/openai_compat.py`)的 key 只进 `Authorization` header,**不进请求体、不进日志**。
- 仓库自查:无任何真实凭据。

**容器内凭据(文件后端回落)**:Linux 容器无 macOS Keychain/Secret Service 时,`Creds` 自动回落**权限 600 的 JSON 文件**(路径 `HARNESS_CREDS_FILE`,默认 `/app/data/creds.json`),WebUI 凭据端点正常录入,real 模式可用。部署时挂载卷持久化:

```bash
docker run -v /host/creds-data:/app/data -e HARNESS_CREDS_FILE=/app/data/creds.json ...
```

## 分发

容器分发(通用 §3.2,单条 `docker build` + 单条 `docker run` 可启动):

```bash
docker build -t coding-agent-harness .
docker run -p 8000:8000 coding-agent-harness
# 浏览器访问 http://localhost:8000(mock 模式,无需 key 即可访问 WebUI)
```

镜像默认 `harness serve`(mock LLM),提供可访问 WebUI(§A.6 机制演示 + §五.9)。真实 LLM 经 WebUI 凭据端点 `POST /api/credentials/set` 录入(不硬编码进镜像)。

CI 双平台配置:`.gitlab-ci.yml`(GitLab CI,含 `unit-test` + `build-image` job)与 `.github/workflows/ci.yml`(GitHub Actions,含 `unit-test` + `build-image` job)。`build-image` 在 `main` 分支且 `Dockerfile` 存在时自动跑(§4.10)。

## 部署架构

项目已部署到阿里云轻量服务器(容器 + Docker),**线上 WebUI:http://116.62.58.112** (mock 模式,无需 key 即可访问,可直接体验 agent 对话)。

使用方式:

- **工作目录**:点 📁 → 无 GUI 服务器弹输入框,手动输入服务器上的绝对路径(如 `/app/demo-projects/105-01-kwic-mainprogram`,服务器已预置 7 个 KWIC 演示项目)
- **直接对话**:输入「列出文件」「阅读并完成代码」等,agent 实时显示工具动作 + markdown 回复
- **real 模式**:点 🔑 录入凭据 → 顶栏切 real → 用真实 LLM 执行(凭据经文件后端存挂载卷,重启不丢)
- **演示项目**:服务器预置 7 个 KWIC 风格作业(主程序/OO/管道过滤器/分层/MVC 等),含 TODO 填空,适合演示「反馈闭环」完整流程
- **容器工具链**:镜像含 Python 3.12 + Java 17 + Maven 3.9,agent 可修改并测试多语言项目

## 目录结构

```
.
├── src/coding_agent_harness/
│   ├── core/loop.py          # agent 主循环(自实现,§A.4 核心)
│   ├── core/state.py         # 循环状态 + 停机/策略判断(纯函数)
│   ├── llm/base.py           # LLMClient 抽象(可注入 mock)
│   ├── llm/mock.py           # MockLLMClient(脚本化分支,确定性)
│   ├── llm/openai_compat.py  # 真实 OpenAI 兼容客户端
│   ├── tools/{dispatch,files,shell,tests_runner}.py  # 工具分发与工具
│   ├── guardrails/guardrail.py  # 治理护栏(纯函数:Allow/Deny/NeedsApproval)
│   ├── feedback/{validator,taxonomy}.py  # 反馈校验器(纯函数)+ 失败分类
│   ├── memory/store.py       # 记忆读写(纯函数检索)
│   ├── creds/keychain.py     # 凭据安全存储(keychain,不回显)
│   ├── web/app.py            # FastAPI WebUI + SSE + HITL 审批端点
│   ├── web/static/index.html # 单页前端(Open Design 令牌)
│   ├── config.py / models.py / main.py
├── tests/{unit,integration,demo}/   # mock-LLM 确定性单测 + 机制演示
├── fixtures/sample_pkg/      # 测试夹具(故意失败的 calc.py,供反馈闭环)
├── Dockerfile / .dockerignore / fly.toml / scripts/deploy.sh
├── .gitlab-ci.yml            # CI(含名为 unit-test 的 job,§五.6)
├── config.example.yaml       # 配置示例(base_url/model/护栏/反馈/记忆)
└── Makefile                  # make test / run / lint
```

## 机制演示

mock LLM 下确定性复现 §A.6 三个机制(`tests/demo/`):

```bash
uv run pytest tests/demo/ -v
```

1. **治理护栏拦截危险动作**(`test_demo_1_guardrail.py`):agent 试图 `DeleteFile` → `guardrail` 返 `NeedsApproval` → 挂起等审批;`intent`(LLM 自述动机)穿透上送 WebUI 审批按钮。
2. **反馈闭环使 agent 改变下一步**(`test_demo_2_feedback_loop.py`):round1 写错值 → pytest FAIL → `validator.parse` 分类反馈 → 据反馈改对 → PASS。断言 pivot(行为转折)。
3. **停机与策略切换**(`test_demo_3_strategy_and_stop.py`):连续同类失败注入"换思路"提示;`no_change_streak` 达阈值 → `stuck` 停机。

三 demo 均**不触网、零时钟、确定性**(mock LLM 脚本化分支驱动)。

## 安全边界

- **治理护栏**(`guardrails/guardrail.py`,纯函数):白名单精确首词匹配(`pytest`/`ruff`/`mypy` 等放行)+ 黑名单子串 Deny(`rm -rf`/`git push`/`sudo`/`curl`/`wget`/`chmod 777` 等);危险动作(删文件/写 shell)返 `NeedsApproval`,**机制是代码不是提示词**。
- **HITL 审批**:`core/loop.py` 用 `threading.Event` 挂起 → WebUI `[通过]/[拒绝]` → `POST /api/tasks/{id}/approvals/{aid}` 恢复;`approval_id` 自增计数器(确定性,非 uuid)。审批超过 `guardrails.approval_timeout_sec`(默认 300s)无人响应则**按拒绝处理**,循环继续,前端收到 `approval_timeout` 事件后按钮置灰;超时后该审批失效,再次审批返回 404(友好错误,非 500)。
- **intent 上送**:每个 Action 携带 LLM 自述 `intent: str`,穿透到 WebUI 审批按钮,供人判断动机。
- **mock 模式不触网**:`MockLLMClient` 脚本化分支,首匹配胜出,无匹配抛错;默认 `serve` 即 mock,不碰真实 LLM key。
- **不硬编码 key**:见上文「凭据与安全配置」;Dockerfile 无任何预置 key(`test_dockerfile.py::test_no_hardcoded_key` 守护)。
- **路径围栏**:文件工具限定在 `project_root` 内,防越界。

## 已知限制

- **本地 docker daemon**:Mac 需启动 Docker Desktop GUI 才能本地 `docker build`;未启动时镜像构建由 CI `build-image` job(GitLab runner docker:dind)完成。
- **容器凭据为文件后端(非 keychain)**:Linux 容器无 Keychain/Secret Service,凭据存权限 600 的 JSON 文件(`HARNESS_CREDS_FILE` 指定)。安全性弱于系统 keychain,但满足「不硬编码、不回显」;生产多用户场景建议加认证层。
- **WebUI 无用户认证**:单用户设计(项目 §3.5 单人),公网部署时任何知道 URL 的人可访问对话历史并发起任务;不适合多用户公开。
- **Windows shlex**:`tools/shell.py` 的 `shell=False` 在 Windows 上对复杂命令解析较弱(Task 7 登记 follow-up;mock 单测不暴露,CI 未跑 Windows 矩阵)。CLI 交互界面本身已兼容 Windows 终端。
- **冷启动样本**:SPEC_PROCESS 冷启动验证仅覆盖 Task 1/2(单人项目,信号量偏低,见 SPEC_PROCESS §5.5)。

---

测试现状:`make test` → 全套件通过(mock-LLM 确定性单测,不依赖网络与真实 LLM)。CI(`unit-test` job)在 GitHub Actions 与 GitLab CI 双平台通过。
