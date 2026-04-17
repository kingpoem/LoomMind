# LoomMind

AI Agent Demo. Use in lark.

## Framework

1. Context Management
2. Memory Management
3. Planning
4. Tool use
5. SubAgent

## Introduction

API key should be written in `.env` file.

The bot should act in lark as user profile.

Tools are registered via an in-process MCP server. Each tool lives in `src/tools/list/<name>.py` and exposes a `register(mcp)` function that decorates its handler with `@mcp.tool()`. `src/tools/server.py` auto-imports every module in `list/` at startup, and `src/tools/loader.py` adapts the registered MCP tools into LangChain `StructuredTool`s for the agent.

## TODO

Lark mode will automatically decline the tools that need approval. Refer to `set_confirmation_callback` in `src/tools/loader.py` for details.