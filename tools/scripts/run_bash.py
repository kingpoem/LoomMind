#!/usr/bin/env python3
"""执行 bash 命令。argv[1] 为要执行的完整命令字符串。"""

import subprocess
import sys

TIMEOUT_SECONDS = 30


def main() -> int:
    if len(sys.argv) < 2:
        print("Error: missing command argument", file=sys.stderr)
        return 2

    cmd = sys.argv[1]
    try:
        result = subprocess.run(
            "bash -c -- " + cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(f"Error: command timed out after {TIMEOUT_SECONDS}s", file=sys.stderr)
        return 124

    parts = []
    if result.stdout:
        parts.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr:
        parts.append(f"stderr:\n{result.stderr.rstrip()}")
    parts.append(f"exit_code: {result.returncode}")
    print("\n\n".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
