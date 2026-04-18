# 长期规划记忆

- [2026-04-17 19:20 UTC] 目标=查看当前文件夹下文件；观察=run_bash: stdout:
total 568
drwxr-xr-x@ 19 poem  staff     608  4月 18 03:14 .
drwxr-xr-x@ 22 poem  staff     704  4月 17 23:07 ..
drwxr-xr-x@  3 poem  staff      96  4月 16 16:10 .cursor
-rw-r…；结果=当前文件夹下包含以下文件和目录：

- `.cursor`、`.DS_Store`、`.env`、`.env.example`、`.git`、`.gitignore`、`.ruff_cache`、`.venv`（隐藏文件和目录）
- `log`、`memory`、`scripts`、`src`、`tui`（目录）
- `Makefile`、`pyprojec…
- [2026-04-18 12:38 UTC] 目标=当前仓库内loommind具有哪些权限；观察=read_file: # 记忆手册

长期约定、术语与操作说明；**主要由人工维护**。启动会话时，系统提示会附带本文件的节选（有长度上限），完整内容始终以本文件为准。

## 本仓库 `memory/` 目录分工

| 文件 | 作用 |
|------|------|
| `MEMORY.md`（本文件） | 手册与约定；经 `read_handbook` 节选注入系统提示。…；结果=从当前记忆手册中，我未找到关于 LoomMind 具体权限的明确描述。如果您需要了解 LoomMind 的具体权限（例如文件访问权限、系统权限等），可以通过以下方式进一步确认：

1. **查看项目文档**：检查 `README.md` 或其他项目文档，了解权限相关的说明。
2. **检查代码**：通过 `src/` 目录下的代码分析权限控制逻辑。
3. *…
- [2026-04-18 12:39 UTC] 目标=当前仓库内loommind具有哪些权限；观察=run_bash: stdout:
total 576
drwxr-xr-x@ 19 poem  staff     608  4月 18 03:14 .
drwxr-xr-x@ 22 poem  staff     704  4月 17 23:07 ..
drwxr-xr-x@  3 poem  staff      96  4月 16 16:10 .cursor
-rw-r…；结果=当前目录下的文件和权限结构如下：

- **隐藏文件和目录**（以`.`开头）：
  - `.cursor`（目录）
  - `.DS_Store`（文件）
  - `.env`（文件）
  - `.env.example`（文件）：
  - `.git`（目录）
  - `.gitignore`（文件）
  - `.ruff_cache`（目录）
  -…
