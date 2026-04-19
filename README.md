# LoomMind

## 组件与设计思路

### Context

- `log` 目录下记录完整对话记录内容
- 用户通过 `compass` 命令手动执行压缩上下文操作（额外调用api进行压缩）
- 使用 `tiktoken` 进行 token 计算
- 超过最大 token 80% 时执行自动压缩

### Memory

#### 系统提示线：`memory/` 文件与会话背景

仓库根目录 `memory/` 下的人可编辑 Markdown：`memory_summary.md` 承接 compass 产出的跨轮摘要，`MEMORY.md` 作为手册与长期约定，经 `build_system_prompt_with_memory` 在会话开头注入系统提示，使每一轮规划都带上稳定背景知识。

#### 规划图线：短期状态与 `planning_long_term.md`

`short_term_memory` 在图状态里滚动保存本轮工具观察与失败提示，`long_term_memory` 条目来自 `planning_long_term.md`，在 `remember` 节点把结构化摘要追加到文件并回读最近若干条；文件侧有字符上限与裁剪，防止单文件无限膨胀。

### Planning

规划模块基于 LangGraph 实现有界 ReAct 模式，每条用户消息触发一次完整规划图运行。模型按 `thought → action → observation → next_step` 迭代，步数受 `max_cycles` 约束。依赖对话历史与 `memory/` 文件控制上下文。

### Tool use（工具使用）

- 构建 LangGraph 时从加载器取出 tool 列表，通过 bind_tools 一次性绑定到 LLM 上
工具层分两类接入，共享同一套 `ToolNode` 执行语义。MCP 侧用进程内 `FastMCP` 扫描 `src/tools/list/` 下各模块的 `register(mcp)`，实现与注册约定集中在一处，新增工具主要加文件而非改中心路由。`loader` 把 MCP 工具描述与入参模式映射成 LangChain `StructuredTool`，调用时转到 `builtin_server.call_tool`；`register` 若返回可迭代的工具名集合，则这些工具在运行前必须经过 `set_confirmation_callback`，在终端、stdio 与飞书场景下用不同策略处理「是否允许执行」，把高风险操作从纯模型决策里剥离出来。Skills 侧用 `skills_config.json` 描述暴露给模型的名字与说明，用 `business_funcs.py` 承载实现，加载器校验 handler 与函数表一致，让改提示的人不必碰 Python 细节。`graph_agent.build_graph` 把 MCP 与 Skills 合成一张工具表交给 `bind_tools`，由模型在 `thought` 里自主选择调用哪一个，没有硬编码的工具优先级或管线顺序。

### SubAgent（子代理）

当前仓库**没有**独立的子智能体编排：全项目只编译**一张**主规划图，`build_graph` 的产物在飞书里按 `chat_id`、在 CLI 里按会话各自维护消息列表，但不存在嵌套的第二张 LangGraph 或「子规划器」互相发消息的协议。设计上的替代是把能力拆成**工具面**与**进程面**：工具面上通过 `enabled_skills` / `enabled_mcps`（以及 TUI 里对 skill、MCP 的多选）在会话级裁剪模型可见工具，等价于给主代理划定权限边界，而不是再挂一个 LLM 子角色；进程面上 Rust TUI `spawn` Python `--cli --stdio`，是**界面宿主与执行体**分离，负责绘制、协议与工具确认，并不构成第二个语言模型代理。若将来要引入真正的 SubAgent，较自然的延伸是在 `thought` 内以「受限工具集 + 独立状态」再跑一小段子图或封装一次子调用，把结果作为 observation 回到主图；该封装在本仓库尚未实现，因此没有单独的子代理代码路径，但主图与工具筛选已为「单主多能力」留出了扩展位置。
