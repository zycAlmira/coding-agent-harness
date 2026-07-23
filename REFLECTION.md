# REFLECTION.md

> **标注**:本反思报告由 AI(Claude Code)基于本项目全程实际经历**起草**。按通用要求 §五.8,"REFLECTION.md 须本人撰写,AI 仅可润色"——本人须在提交前逐节改写、补充个人视角与批判性判断,确认后再删除本标注行。文中观点为起草者观察,不代表本人最终立场。

字数:约 2100 字(中文)。

---

## 哪些 Superpowers 技能发挥了最大作用

**`writing-plans`(产出 PLAN.md)是本项目第一生产力**。3175 行的 PLAN 把 24 个 task 拆到"每 task 给完整测试代码 + 实现代码 + 接口签名 + 实现注意"的颗粒度,使实现阶段几乎变成"照搬 + 适配签名"的机械作业。它的真正价值不在"给代码",而在**强制把模糊处钉死**:冷启动 subagent 跑 Task 1-2 暴露的 6 项 spec 缺陷(@dataclass 字段顺序、`--no-header` 笔误、None 覆盖默认),正是 plan 把口头规格转成可执行形式时必然显形的矛盾。没有这一步,这些矛盾会在 Task 15 集成时以 flaky 测试形式爆发,代价高一个数量级。

**`requesting-code-review` 两阶段(spec 合规→代码质量)**是第二有效。spec 合规阶段先于代码质量,拦住了几处会致死锁/无限阻塞的 Important:HITL 默认 False 保旧测试不变是正确取舍,但 WebUI 运行态必须开 hitl_enabled,审查拦住了这处接线遗漏;`_suspend_for_approval` 锁外读 decision 的纪律违规;FastAPI runner 无 try/finally 致 SSE 无限阻塞。这些是"代码看起来对、运行会挂"的典型,靠审查而非自检发现。

**`subagent-driven-development`** 在本环境部分有效:派发的实现者 subagent 常被安全分类器闪断 + 用户中断打断,最终退化为"主会话直接 TDD + 派审查员 subagent"的混合节奏。审查员 subagent 稳定可用,是真正的两阶段评审执行者。

## 哪些"形式大于实质"

**冷启动验证(§4.5)"第二个智能体类型必须不同"** 在本环境是形式大于实质。仅 Claude 系列可用,冷启动 subagent 用 `general-purpose` 类型——与主会话默认 `claude` 类型不同,满足字面"类型不同",但底层模型同源,缺乏真正的异构视角。它捕获的 6 项缺陷是真实的,但更像是"plan 自检"而非"同侪评审"。若环境支持真正异构模型(如 GPT 系列),信号会强得多。

**worktree 隔离(§4.6)** 因 `EnterWorktree` 工具被会话缓存的"非 git 仓库"状态拒绝(仓库已 init 但工具不认),回退为特性分支。对单人顺序推进无实际并行冲突,隔离性弱于 worktree 但无功能损失——记为偏离而非损失,但"每功能一 worktree"的仪式在本项目落空。

## TDD 强制在 AI 协作下:放大器,非阻碍

**TDD 在 AI 协作下是放大器**。红测试是"规格的可执行形式",迫使 plan 把模糊处钉死。Task 17/18/19/20 都在实现时发现 plan 测试与已实现模块签名不符(fake httpx 响应对象缺 `raise_for_status`、demo mock 起步值写成了正确值致反馈转折永不触发、runner 缺 try/finally、hitl_enabled 未接线)——这些矛盾若"先实现再补测试"会被补的测试迁就实现而放过。先写失败测试,矛盾当场显形。唯一代价:对纯文档/配置 task(Task 22 CI、Task 23 Dockerfile、Task 24 README),TDD 退化为"解析断言"(PyYAML 解析 .gitlab-ci.yml、Dockerfile 指令断言、README 章节断言),虽不如机制代码的 TDD 严格,但把"交付物也要可验证"的 §A.4 精神延伸到了配置与文档,值得。

## subagent 自主运行多久不偏离主题

审查员 subagent 在"给定审查范围 + 两阶段清单"下可稳定跑完不偏离。实现者 subagent 在"plan 给完整代码 + 接口签名"时也基本不偏离。但**颗粒度过细的机械 task**(如 Task 1 脚手架、Task 12 llm base Protocol)派 subagent 反而比主会话直接做更慢(派发开销 + 上下文重建),这类 task 直接做更优。**判断密集的 task**(Task 15 主循环、Task 20 前后端接线)必须主会话亲自做,subagent 缺乏跨 task 的上下文累积(如 Task 5/8 遗留 bug 在 Task 15 才显形),会把判断做错。

## task 颗粒度最优值

PLAN 的 24 task 颗粒度大体最优:每个 task = 一个可独立审查的 commit + 一组测试。偏粗的会害审查(审查员 diff 太大看不过来);偏细的(如 Task 1 脚手架)派 subagent 不划算。**最关键的颗粒度判断是 Task 15(主循环)单独成 task + Task 15b(HITL)拆出**——主循环是反馈闭环的主贡献,单独成 task 让审查聚焦;HITL 拆出避免一个 task 同时背"主循环 + 并发审批"两座山。这个拆分是 plan 阶段做对的事。

## SPEC/PLAN 质量如何影响实现质量

**规约不清导致 subagent 偏离的具体案例**:Task 17 plan 的测试用 fake httpx 响应对象,但实现里调 `resp.raise_for_status()`,fake 没实现该方法→AttributeError;`fake_post` 缺 timeout kwarg→TypeError;断言"key 不在 calls"与"header 含 Bearer sk-x"互斥(calls 存了 headers)。三处都是 plan 写测试时没与"实现将如何调用"对齐。实现者若照搬 plan 测试会卡住,被迫逐条修——这暴露 plan 质量的弱点:**测试代码不能只看"测什么",要看"实现将如何被测"**。SPEC/PLAN 质量直接决定实现顺畅度:plan 给的接口签名准的 task(Task 6/9/10)实现如行云流水;plan 模糊处(上述三处)实现时间翻倍。

## 最有效的 prompt/context 策略

**给审查员 subagent 的 prompt 固定四件套**:① 审查范围(commit 范围);② 背景一句(项目性质 + 主贡献维度);③ 两阶段清单(spec 合规逐条 + 代码质量逐项,每项标 PASS/Major/Minor/Trivial + 证据 file:line);④ 输出格式模板。这套结构让审查员不跑偏、输出可比、可执行修复建议直接落地。**给实现者的 prompt 则给"完整测试代码 + 实现代码 + 签名"而非自由发挥**——subagent 在"照搬 + 适配"模式下最可靠,在"自由设计"模式下易偏离。

## 凭据与分发两条工程要求想清的问题

**凭据(§3.1)** 迫使想清:① "不进 git(含 history)"意味着连 `export` 都不能有,`.env` 须经环境加载而非 shell history;② "查看不回显明文"意味着 status 端点只返回布尔语义,不是"显示部分字符";③ 测试用 in-memory keyring backend 替代 setenv HOME——后者在 Mac 仍碰真实 Keychain(可能弹 GUI prompt、非确定性),破坏 §A.4 确定性。这些不是"做了就完了",每个约束都有具体的非显然实现后果。

**分发(§3.2)** 迫使想清:① 容器默认 mock 模式才能满足 §五.9"可访问 WebUI"又不碰 key;真实 LLM 经 WebUI 凭据端点录入而非镜像预置;② `docker build` 在本地 daemon 未运行时无法验证,须由 CI build-image job(docker:dind)兜底——这反过来说明"CI 不只是跑测试,是分发产物的真实验证环节";③ `.dockerignore` 排除 `.env`/`.venv`/`tests` 既是减体积也是防密钥入镜像的双重作用。

## 如果重做会改变什么

1. **冷启动验证用真正异构模型**(若环境允许),否则承认它是"plan 自检"而非同侪评审。
2. **Task 5/8 的 Minor 当场闭合**,不等 Task 15 集成暴露——validator 的 `--tb=short` 兼容、tests_runner 的 pycache 清理,当时修代价低、滞后修代价高。
3. **容器 keychain 文件后端在 Task 16 就显式配置**(而非留作"已知限制"),让容器真实 LLM 路径完整。
4. **Windows 矩阵**在 CI 跑(Task 7 shlex 弱点),而非登记 follow-up——mock 测不暴露,但 Windows runner 会。
5. **plan 测试逐条与实现签名预演**(fake 方法的 raise_for_status、timeout kwarg),在 plan 阶段而非实现阶段发现矛盾。

## 对 Superpowers 方法论的批判:它假设了什么,成立吗

Superpowers 假设:**① subagent 可稳定派发不中断**——本环境分类器闪断使其部分落空,退化为混合节奏;**② 异构模型可得**——本环境仅同源模型,冷启动"类型不同"是字面满足;**③ worktree 工具可用**——被会话缓存状态拒绝,仪式落空;**④ plan 质量足够高到照搬即可**——实际 plan 内部矛盾(Task 17/18/19/20)在实现时才暴露,说明 plan 的"给完整代码"反而掩盖了"测试与签名未对齐"的矛盾。这些假设在本项目部分成立(subagent 审查稳定、plan 颗粒度对)、部分不成立(异构模型、worktree、plan 测试与签名对齐)。方法论的价值在结构(TDD、两阶段审查、冷启动),而非特定工具的可用性——结构可迁移,工具假设不可控。
