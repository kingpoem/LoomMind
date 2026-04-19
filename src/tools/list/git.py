"""git 工具：在工作区根目录执行 Git 子命令，供模型完成版本管理相关任务。"""

import shlex
import shutil
import subprocess

from mcp.server.fastmcp import FastMCP

from trust import TrustCategory, workspace_root

_MAX_OUTPUT_BYTES = 256 * 1024
_TIMEOUT_SEC = 120


def _truncate_output(text: str) -> str:
    raw = text or ""
    if len(raw.encode("utf-8", errors="replace")) <= _MAX_OUTPUT_BYTES:
        return raw
    out = raw
    while len(out.encode("utf-8", errors="replace")) > _MAX_OUTPUT_BYTES:
        out = out[:-1]
    return out + "\n…（输出已截断）\n"


def register(mcp: FastMCP) -> dict[str, TrustCategory]:
    @mcp.tool()
    def git(args: str) -> str:
        """在工作区根目录（当前进程 cwd 对应的工作区）执行 `git` 子命令，返回 stdout、stderr 与退出码。

        与 `run_bash` 的区别：只调用 `git` 可执行文件，参数经 `shlex.split` 解析，不使用 shell，
        可避免注入；工作目录固定为工作区根，适合查看状态、提交、分支、远端同步等常规 Git 操作。

        参数 args：`git` 后面的子命令与参数（纯文本）。示例：
        - `status -s` — 简短状态
        - `diff HEAD` — 工作区与 HEAD 差异
        - `log -3 --oneline --decorate`
        - `branch -a`
        - `remote -v`
        - `stash list`
        - `help commit` — 查看子命令帮助（等价于 `git commit --help` 时可写 `commit --help`）

        常用能力速查：
        - 基础：`status` / `add` / `commit` / `restore` / `diff`；暂存改动用 `stash`；
          撤销与历史调整见 `reset` / `revert` / `clean`（改写历史需谨慎）。
        - 分支：`branch` / `switch` / `merge` / `rebase` / `cherry-pick`。
        - 远端：`clone` / `remote` / `fetch` / `pull` / `push`；子模块 `submodule`。
        - 历史与查询：`log` / `show` / `blame` / `grep` / `reflog` / `tag`。
        - 工作流：团队可采用 Git Flow（如 git-flow 插件）或约定式提交（Conventional Commits）规范提交说明。

        若需在工作区根之外的路径执行 Git、或必须使用管道与 shell 特性，请改用 `run_bash`。

        stderr 与非零退出码不会导致工具调用失败，会原样返回以便判断是否成功。
        """
        git_bin = shutil.which("git")
        if git_bin is None:
            return "git 失败：未找到 `git` 可执行文件，请确认已安装 Git 并在 PATH 中。"

        argv: list[str]
        try:
            argv = shlex.split(args or "", posix=True)
        except ValueError as ex:
            return f"git 失败：无法解析参数（引号是否配对）：{ex}"

        root = workspace_root()
        try:
            proc = subprocess.run(
                [git_bin, *argv],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            return "git 失败：命令超时"
        except OSError as ex:
            return f"git 失败：{ex}"

        parts: list[str] = []
        if proc.stdout:
            parts.append(f"stdout:\n{_truncate_output(proc.stdout.rstrip())}")
        if proc.stderr:
            parts.append(f"stderr:\n{_truncate_output(proc.stderr.rstrip())}")
        parts.append(f"exit_code: {proc.returncode}")
        return "\n\n".join(parts)

    return {"git": TrustCategory.EXEC}
