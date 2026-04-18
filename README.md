# LoomMind

## 概述

面向飞书与本地终端的 LangGraph 智能体。

## 组件与设计思路

### Context（上下文）

上下文模块解决三件事：模型实际读到的消息序列、会话在磁盘上的可追溯副本、以及在固定上下文窗口下的长度控制。`ContentManager` 把完整消息快照落到 `log/raw/`，主要服务于排障与审计，与 LangGraph 内部状态解耦，避免把文件 I/O 和推理状态搅在一起。`token_budget` 用 `tiktoken` 对消息做粗粒度计数，给 CLI/TUI 一个可解释的用量刻度，而不是在图里硬编码供应商上下文长度。`compass` 针对长会话：把首条 `SystemMessage` 之后较早的轮次交给模型压成一段中文摘要，再合并进系统消息并只保留最近若干条原文，用一次额外模型调用的代价换窗口内信息密度；由用户显式触发压缩，避免自动摘要打乱对话节奏。整体设计是「推理态 = 消息列表，工程态 = 日志 + 可选摘要」，不把无限增长的历史原封不动塞进模型。

### Memory（记忆）

记忆分成两条线，避免把所有状态都塞进对话 tokens。一条是仓库根目录 `memory/` 下的人可编辑 Markdown：`memory_summary.md` 承接 compass 产出的跨轮摘要，`MEMORY.md` 作为手册与长期约定，经 `build_system_prompt_with_memory` 在会话开头注入系统提示，使每一轮规划都带上稳定背景知识。另一条是规划图内部的短期与长期条：`short_term_memory` 在图状态里滚动保存本轮工具观察与失败提示，`long_term_memory` 条目来自 `planning_long_term.md`，在 `remember` 节点把结构化摘要追加到文件并回读最近若干条；文件侧有字符上限与裁剪，防止单文件无限膨胀。取舍是不引入向量检索与外部记忆服务，用「文件 + 截断规则 + 规划循环内显式写入」换可维护性与可演示性，代价是检索与关联推理能力有限。

### Planning（规划）

**规划模式现状（简要）**：每条用户消息触发一次完整规划图运行；在单条消息内，模型按 `thought →（可选）action → observation → next_step` 迭代，每轮 `thought` 都会把全量对话与本轮 Planner 系统提示一并送入模型，步数受 `max_cycles` 约束（默认 6，可用环境变量 `LOOMMIND_MAX_PLAN_CYCLES` 或 stdio 的 `set_plan_cycles` 调整，上限 64），达到上限则进入无工具的 `finalize` 强制收尾。`cycle_count`、`task_outline` 等仅存在于当次图运行，不跨用户轮次保留；更长流程需提高上限、拆成多条消息，或依赖对话历史与 `memory/`、`/compass` 控制 token。整体是**有界 ReAct**，而非无限工具循环。

规划层用 LangGraph 把「想—做—看—再想」固化成图（ReAct 四阶段语义写在 `thought` 的Planner提示中：规划拆解、探索执行、观察重试、收尾交付），而不是单次 `invoke` 里隐式工具循环。`thought` 节点在带记忆的系统提示下决定是否调用工具或直接回答；首轮可从模型正文中启发式抽取编号/列表子目标写入 `task_outline`，并在后续轮次与 `finalize`、长期记忆条目中复用。有 `tool_calls` 则进入预置 `ToolNode`（`action`），否则进入 `remember`。`observation` 把最近一批 `ToolMessage` 压成短句写入短期记忆，并在输出里出现错误痕迹时追加可操作的失败提示，把失败反馈显式喂回下一轮 `thought`。`next_step` 递增循环计数，达到 `max_cycles` 时进入 `finalize`，用无工具绑定的模型强制收束最终答复，防止在工具边界上死循环。

**单条用户消息**内的工具链长度受 `max_cycles` 约束（默认 6，可通过环境变量 `LOOMMIND_MAX_PLAN_CYCLES` 或在 stdio 会话中发送 `set_plan_cycles` 调整；上限 64）。需要更长链路时可提高该值，或把任务拆成多条用户消息（每条消息会重新跑一轮规划图；跨条的进度靠对话历史与 `memory/` 衔接）。上下文 token 压力仍受 `token_budget` 约束，长会话可配合 CLI/TUI 的 `/compass` 与会话摘要，避免「步数放开」后把整段历史原样撑满窗口。`planning_trace` 记录节点级摘要，便于导出图或对照日志。`remember` 在循环推进后把「目标—子目标—观察—结果」式条目写入规划长期记忆文件。设计意图是可解释、有上限、对失败敏感，而不是无界 ReAct。

### Tool use（工具使用）

工具层分两类接入，共享同一套 `ToolNode` 执行语义。MCP 侧用进程内 `FastMCP` 扫描 `src/tools/list/` 下各模块的 `register(mcp)`，实现与注册约定集中在一处，新增工具主要加文件而非改中心路由。`loader` 把 MCP 工具描述与入参模式映射成 LangChain `StructuredTool`，调用时转到 `builtin_server.call_tool`；`register` 若返回可迭代的工具名集合，则这些工具在运行前必须经过 `set_confirmation_callback`，在终端、stdio 与飞书场景下用不同策略处理「是否允许执行」，把高风险操作从纯模型决策里剥离出来。Skills 侧用 `skills_config.json` 描述暴露给模型的名字与说明，用 `business_funcs.py` 承载实现，加载器校验 handler 与函数表一致，让改提示的人不必碰 Python 细节。`graph_agent.build_graph` 把 MCP 与 Skills 合成一张工具表交给 `bind_tools`，由模型在 `thought` 里自主选择调用哪一个，没有硬编码的工具优先级或管线顺序。

### SubAgent（子代理）

当前仓库**没有**独立的子智能体编排：全项目只编译**一张**主规划图，`build_graph` 的产物在飞书里按 `chat_id`、在 CLI 里按会话各自维护消息列表，但不存在嵌套的第二张 LangGraph 或「子规划器」互相发消息的协议。设计上的替代是把能力拆成**工具面**与**进程面**：工具面上通过 `enabled_skills` / `enabled_mcps`（以及 TUI 里对 skill、MCP 的多选）在会话级裁剪模型可见工具，等价于给主代理划定权限边界，而不是再挂一个 LLM 子角色；进程面上 Rust TUI `spawn` Python `--cli --stdio`，是**界面宿主与执行体**分离，负责绘制、协议与工具确认，并不构成第二个语言模型代理。若将来要引入真正的 SubAgent，较自然的延伸是在 `thought` 内以「受限工具集 + 独立状态」再跑一小段子图或封装一次子调用，把结果作为 observation 回到主图；该封装在本仓库尚未实现，因此没有单独的子代理代码路径，但主图与工具筛选已为「单主多能力」留出了扩展位置。
