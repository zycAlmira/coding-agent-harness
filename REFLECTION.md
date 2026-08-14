# REFLECTION.md


---

## 哪些 Superpowers 技能发挥了最大作用

**`writing-plans`**

## 哪些"形式大于实质"

**worktree 隔离(§4.6)**  本项目为单人项目

## TDD 强制在 AI 协作下:放大器

**TDD 在 AI 协作下是放大器**。红测试是"规格的可执行形式",迫使 plan 把模糊处钉死。Task 17/18/19/20 都在实现时发现 plan 测试与已实现模块签名不符(fake httpx 响应对象缺 `raise_for_status`、demo mock 起步值写成了正确值致反馈转折永不触发、runner 缺 try/finally、hitl_enabled 未接线)——这些矛盾若"先实现再补测试"会被补的测试迁就实现而放过。先写失败测试,矛盾则显形。

这种放大器效应在后期的真实修复中同样成立:例如"探索/修复动作应重置 no_change_streak"这条新语义,agent先写了一个让测试红掉的用例(两次测试失败之间插入 ListDir,断言不 stuck),再改 `_process_action` 重置计数——红测试精确指出了"停机机制不理解 agent 进展"这个缺陷,修复后测试变绿,语义才真正钉死。

## subagent 自主运行多久不偏离主题

审查员 subagent 在"给定审查范围 + 两阶段清单"下可稳定跑完不偏离。实现者 subagent 在"plan 给完整代码 + 接口签名"时也基本不偏离。

## task 颗粒度最优值

PLAN 的 24 task 颗粒度大体最优:每个 task = 一个可独立审查的 commit + 一组测试。

## SPEC/PLAN 质量如何影响实现质量

**规约不清导致 subagent 偏离的具体案例**:Task 17 plan 的测试用 fake httpx 响应对象,但实现里调 `resp.raise_for_status()`,fake 没实现该方法→AttributeError;`fake_post` 缺 timeout kwarg→TypeError;断言"key 不在 calls"与"header 含 Bearer sk-x"互斥(calls 存了 headers)。三处都是 plan 写测试时没与"实现将如何调用"对齐。实现者若照搬 plan 测试会卡住,被迫逐条修

## 最有效的 prompt/context 策略

**给审查员 subagent 的 prompt 固定四件套**:① 审查范围(commit 范围);② 背景一句(项目性质 + 主贡献维度);③ 两阶段清单(spec 合规逐条 + 代码质量逐项,每项标 PASS/Major/Minor/Trivial + 证据 file:line);④ 输出格式模板。这套结构让审查员不跑偏、输出可比、可执行修复建议直接落地。**给实现者的 prompt 则给"完整测试代码 + 实现代码 + 签名"而非自由发挥**——subagent 在"照搬 + 适配"模式下最可靠,在"自由设计"模式下易偏离。

## 凭据与分发两条工程要求想清的问题

**凭据(§3.1)** 迫使想清:① "不进 git(含 history)"意味着连 `export` 都不能有,`.env` 须经环境加载而非 shell history;② "查看不回显明文"意味着 status 端点只返回布尔语义,不是"显示部分字符";

**分发(§3.2)** 迫使想清:① 容器默认 mock 模式才能满足 §五.9"可访问 WebUI"又不碰 key;真实 LLM 经 WebUI 凭据端点录入而非镜像预置;

## 如果重做会改变什么

1. **冷启动验证用真正异构模型**
2. **brainstorm 期间提出更多更明确的要求**

## 对 Superpowers 方法论的批判:它假设了什么,成立吗

Superpowers 假设:**① subagent 可稳定派发不中断**——本环境分类器闪断使其部分落空,退化为混合节奏，但subagent 总体未跑偏，同时保住了主会话的上下文; **② TDD有效性**——现有 agent 能力较强情况下，AI 测试用例基本检查不出问题，红绿测试起到作用较小，反而在代码有更深度问题时降低了 agent 归因速度，浪费了时间和 token。**③ "子代理像人一样可交接上下文"**——实际子代理返回的是扁平文本报告,细节丢失靠主会话补救;这让我更倾向"主会话自己写关键代码,子代理只做机械与审查"的混合模式。
