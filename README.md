# Coding Agent Harness

AI4SE 期末项目 · Project A · Coding Agent Harness。一个**由学生自己编码实现**的 Coding Agent 内核,以**反馈闭环(feedback loop)**作为主贡献维度。

## 简介

本仓库承载一个自研的 Coding Agent Harness 内核:agent 主循环(组织上下文 → 调 LLM → 解析动作 → 分发执行 → 回灌结果 → 停机判断)、可注入 mock 的 LLM 抽象层、工具分发、治理护栏、反馈校验器、记忆读写,全部自实现,**不寄生于任何现成 agent 框架的高层循环**(§A.4 红线)。

六维度最低实现齐全(决策/工具/记忆/治理/反馈/配置),其中**反馈闭环**做深:

- `feedback/validator.py` 是**纯函数**,解析 pytest 输出得到结构化 `Feedback`(失败分类 `FailureCategory` + 文件/行/traceback 摘要),回灌给 agent 使其在下一步改变行为。
- 反馈信号 = 确定性校验器,不是"提醒 LLM 注意"的提示词。
- 每个核心机制(工具分发、治理拦截、反馈回灌、记忆读写、停机)在 **mock/stub LLM 下均可用确定性单元测试验证**(§A.4 判定标准:移除真实 LLM 后机制能否用单测验证)。

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

```bash
# WebUI(mock LLM 演示,默认 http://0.0.0.0:8000,无需 key):
uv run harness serve

# WebUI(真实 LLM,需先录入凭据):
uv run harness serve --real

# 命令行跑一次任务(真实 LLM,需 config.yaml + 凭据):
cp config.example.yaml config.yaml
uv run harness run "修复 calc.py 的加法测试"

# 测试与 lint:
make test     # 等价 uv run pytest -q
make lint     # uv run ruff check src tests
```

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

云部署用阿里云轻量应用服务器 / ECS(通用 §4.11):

### 准备工作

1. 阿里云账号 + 一台轻量应用服务器或 ECS(最低配置即可,1 核 1G 够用)
2. 安全组放行 80 端口(HTTP)
3. 服务器安装 Docker:
   ```bash
   # 在服务器上执行
   curl -fsSL https://get.docker.com | sh
   ```

### 一键部署

```bash
# 设置服务器 IP,然后部署
export ALIYUN_HOST=47.96.x.x        # 换成你的服务器公网 IP
export ALIYUN_USER=root
sh scripts/deploy-aliyun.sh
```

脚本自动完成:本地构建镜像 → 上传到服务器 → 启动容器(映射 80→8000,mock 模式无需 key)。

### 阿里云容器镜像服务(ACR,可选)

如果要在多台机器间分发或走 CI/CD,可以将镜像推送到 ACR:
```bash
# 登录 ACR
docker login --username=<阿里云账号> registry.cn-hangzhou.aliyuncs.com
# 打标签 + 推送
docker tag coding-agent-harness registry.cn-hangzhou.aliyuncs.com/<命名空间>/coding-agent-harness:latest
docker push registry.cn-hangzhou.aliyuncs.com/<命名空间>/coding-agent-harness:latest
```

- CI/CD:`unit-test` job 每次 push/PR 跑测试(§4.8);`build-image` job 在 main 构建推送镜像。
- **线上部署 URL**:`http://<你的服务器公网 IP>`(部署后填入)。

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
- **HITL 审批**:`core/loop.py` 用 `threading.Event` 挂起 → WebUI `[通过]/[拒绝]` → `POST /api/tasks/{id}/approvals/{aid}` 恢复;`approval_id` 自增计数器(确定性,非 uuid)。
- **intent 上送**:每个 Action 携带 LLM 自述 `intent: str`,穿透到 WebUI 审批按钮,供人判断动机。
- **mock 模式不触网**:`MockLLMClient` 脚本化分支,首匹配胜出,无匹配抛错;默认 `serve` 即 mock,不碰真实 LLM key。
- **不硬编码 key**:见上文「凭据与安全配置」;Dockerfile 无任何预置 key(`test_dockerfile.py::test_no_hardcoded_key` 守护)。
- **路径围栏**:文件工具限定在 `project_root` 内,防越界。

## 已知限制

- **本地 docker daemon**:Mac 需启动 Docker Desktop GUI 才能本地 `docker build`;未启动时镜像构建由 CI `build-image` job(GitLab runner docker:dind)完成。
- **§五.9 线上 URL**:需用户在阿里云购买轻量服务器后执行 `scripts/deploy-aliyun.sh` 产生公网 URL,AI 无法代持云账号。
- **容器内 keychain**:Linux 容器内 macOS Keychain 不可用,`keyring` 无可用后端时不会自动文件回落;真实 LLM 跑建议本地运行,或在容器内显式配 `keyring` 文件后端(`keyrings.alt`)/环境注入。
- **Windows shlex**:`tools/shell.py` 的 `shell=False` 在 Windows 上对复杂命令解析较弱(Task 7 登记 follow-up;mock 单测不暴露,CI 未跑 Windows 矩阵)。
- **冷启动样本**:SPEC_PROCESS 冷启动验证仅覆盖 Task 1/2(单人项目,信号量偏低,见 SPEC_PROCESS §5.5)。

---

测试现状:`make test` → 全套件通过(mock-LLM 确定性单测,不依赖网络与真实 LLM)。CI(`unit-test` job)在 GitHub Actions 与 GitLab CI 双平台通过。
