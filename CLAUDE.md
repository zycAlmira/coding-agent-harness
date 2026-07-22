# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目性质

这是 **AI4SE 期末项目 · Project A · Coding Agent Harness**。仓库当前只包含规格说明文档(见根目录 `*.md`),尚未开始实现。一旦进入实现阶段,本仓库将承载一个**由学生自己编码实现的 Coding Agent Harness 内核**。

完整要求 = `# AI4SE 期末项目 · 通用要求（所有项目必读）.md` + `AI4SE_Final_Project_A_Coding_Agent_Harness.md`。后者定义了 Coding Agent Harness 专属的硬性约束。B 方向文件(`AI4SE_Final_Project_B_应用类项目.md`)对本项目不适用,仅作参考。

## 最核心的纪律(违反即不合格)

来自 `AI4SE_Final_Project_A_Coding_Agent_Harness.md` §A.4,这是本项目最核心的红线,**任何代码工作开始前必须牢记**:

1. **必须自己实现 harness 内核**:agent 主循环(组织上下文 → 调 LLM → 解析动作 → 分发执行 → 回灌结果 → 停机判断)、可注入 mock 的 LLM 抽象层、工具分发、治理护栏、反馈校验器、记忆读写。
2. **禁止寄生于现成 agent 框架的高层循环**:不能用 LangChain `AgentExecutor`、AutoGen、CrewAI、LlamaIndex agent 或某编码智能体 SDK 自带的 agent runner 充当产物。允许使用底层零件(单次对话补全 API、HTTP 库、向量库、解析库)。
3. **机制必须是代码,不是提示词**:反馈信号 = 你写的确定性校验器/传感器;危险动作拦截 = 你写的 `guardrail(action)` 函数。"提醒 LLM 注意安全"这种提示词不算实现。
4. **判定标准:移除真实 LLM 后,机制能否用单测验证?** 每个核心机制(工具分发、治理拦截、反馈回灌、记忆读写、停机)替换为 mock/stub LLM 后仍能用确定性单测验证,才算编码实现。配置/规则/技能/提示词文件属于"内容物",不计入 harness 工作量。
5. **基础要完整,重点要深入**:决策/工具/记忆/治理/反馈/配置六维度都要有可运行最低实现,但须选一个机制密集维度(建议:治理、反馈闭环、或工具分发/多 agent)做深,作为主要贡献。
6. **开发工具 vs 交付产物的界线**:开发时可以充分用 Claude Code / Superpowers 的子 agent、Skill、hooks、memory 辅助写代码;但交付的 harness 内核必须自己运转,不能让宿主框架的 agent loop / Skill / 治理钩子充当产物功能。

## 强制工作流程(Superpowers 七步)

通用要求 §4,**在 SPEC.md 与 PLAN.md 完成并通过冷启动验证之前,禁止编写任何实现代码**:

1. `brainstorming` → 产出 `SPEC.md`
2. `writing-plans` → 产出 `PLAN.md`
3. 冷启动验证:用一个**不同类型**的全新 agent,仅凭 SPEC+PLAN(不提供与主 agent 的对话历史)实现 1-2 个 task,记录其受阻处与 spec 缺陷,据此修订 SPEC/PLAN,写入 `SPEC_PROCESS.md`。这是单人项目中最接近同侪评审的机制,**不可跳过**。
4. `using-git-worktrees` 隔离工作区(每功能/大模块一 worktree 一 PR)
5. `subagent-driven-development` / `executing-plans`(每 task 派新鲜 subagent)
6. `test-driven-development` 强制:红 → 绿 → 重构,**先写失败测试再写实现**,不接受"先实现再补测试"
7. `requesting-code-review` → 每个 task 两阶段评审(spec 合规 → 代码质量,Critical 必修才能进下一 task) → `finishing-a-development-branch`

任何对七步流程的偏离必须在 `AGENT_LOG.md` 中记录与解释。

## 交付物清单(通用要求 §五 + §A.7)

必须提交到同一个 NJU Git 仓库:

- `SPEC.md`(须含「领域与机制设计」一节,见 §A.5)、`PLAN.md`、`SPEC_PROCESS.md`
- 完整源码:含**自己实现的 harness 内核** + **mock/stub LLM 驱动的确定性单元测试**(不依赖网络与真实 LLM)
- **机制演示**:在 mock LLM 下确定性复现 ① 治理护栏拦截危险动作 ② 注入失败后反馈闭环使 agent 改变下一步 ③ 重点维度的确定性行为(见 §A.6)
- 分发产物(Dockerfile / 二进制打包 / 包管理器任选)与说明
- `README.md`:简介、安装、运行、分发命令、目录结构、**安全边界说明**(必含这几个章节)
- `AGENT_LOG.md`:按时间戳记录每 task 的技能、prompt/context、subagent 输出片段、人工干预、教训
- CI 配置(`.gitlab-ci.yml`):**必须含名为 `unit-test` 的 job**,最后一次 CI 必须 pass
- `REFLECTION.md`(1500-2500 字,本人撰写,AI 仅可润色并须标注)
- 线上部署 URL,必须提供可访问的 WebUI 接口

## 安全与分发硬要求

- **凭据(通用 §3.1)**:LLM/付费 API key 绝不硬编码、绝不进 git(含历史)、不进日志/shell history/明文配置。至少实现一种安全存储(macOS Keychain 等),首次运行引导隐藏录入,可查看/更新/清除(查看不回显明文)。环境变量须经 `.env` 加载而非 `export`。
- **分发(通用 §3.2)**:别人如何获取并安全配置 key。容器/二进制/包管理器任选,README 写清获取、运行、key 在目标机配置、已知限制。
- 仓库内**不得出现任何真实凭据**,提交前自查 `.env`、history、配置文件。

## 技术约束

- 语言不限(TS/Go/Rust/Python 等均可),SPEC 中说明选型理由。
- LLM 供应商不限,SPEC 中说明。
- commit 历史:拒绝单次 commit 提交全部;每 worktree 一 PR;commit/PR 描述标注由哪个 subagent 完成、人工改了哪些;PLAN.md 每完成一 task 即标记并附 commit hash。

## 与本会话交互的约定(来自用户全局指令)

- 永远用中文回答。
- 终端回答不用 LaTeX、`$...$` 等无法直接理解的表达;复杂公式/图表/密集版面改用图片或 PDF 表达。
- 今天日期基准:2026/07/21。
