"""
工具集 —— 提供给 LangGraph Agent 使用的工具函数

安全策略：
  - execute_python_code: 通过 RestrictedPython 沙箱执行，禁止 os/sys/subprocess 等危险模块
  - run_shell_command:   白名单命令 + 参数黑名单 + 10s 超时，不使用 shell=True
  - list_files / read_file_content: 路径白名单，只允许访问 /app/workspace
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from datetime import datetime

from langchain_core.tools import tool

from agent_lab.app.services.sandbox import execute_sandboxed
from agent_lab.app.core.logger import get_logger

logger = get_logger("tools")

# ── 文件系统安全白名单 ─────────────────────────────────────────────────────────
# 只允许 Agent 访问这个工作目录，防止路径遍历攻击
_WORKSPACE = os.environ.get("AGENT_WORKSPACE", "/app/workspace")


def _safe_path(raw: str) -> str | None:
    """
    将用户传入路径解析为绝对路径，并检查是否在白名单目录内。
    返回 None 表示路径不合法。
    """
    abs_path = os.path.realpath(os.path.join(_WORKSPACE, raw))
    if not abs_path.startswith(os.path.realpath(_WORKSPACE)):
        return None
    return abs_path


# ── Shell 命令白名单 ───────────────────────────────────────────────────────────

# 允许的顶层命令
_ALLOWED_COMMANDS: frozenset[str] = frozenset({
    # 文件/目录查看（只读）
    "ls", "ll", "la", "cat", "head", "tail", "wc",
    "find", "file", "stat", "du", "df",
    # 文本处理
    "grep", "egrep", "fgrep", "sort", "uniq", "cut", "tr", "diff",
    "awk", "sed",
    # 系统信息（只读）
    "pwd", "date", "echo", "uname", "hostname", "whoami", "id",
    "ps", "free", "uptime", "which", "type", "whereis",
    # 版本控制（只读子命令）
    "git",
    # Python 包查询（只读子命令）
    "pip", "pip3",
    # 环境
    "env", "printenv",
})

# git 允许的子命令
_GIT_SAFE_SUBCMDS: frozenset[str] = frozenset({
    "status", "log", "diff", "branch", "show", "describe",
    "tag", "remote", "config", "--version", "rev-parse",
    "shortlog", "stash", "ls-files",
})

# pip 允许的子命令
_PIP_SAFE_SUBCMDS: frozenset[str] = frozenset({
    "list", "show", "freeze", "--version", "check",
})

# 参数黑名单正则（匹配到任意一个 → 拒绝）
_BLOCKED_ARG_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\$\(",        # 命令替换 $(...)
        r"`",           # 反引号命令替换
        r">\s*\S",      # 输出重定向 > file
        r">>",          # 追加重定向
        r";\s*\S",      # 命令链 ;cmd
        r"&",           # 后台运行 / 逻辑与
        r"\|\s*(?:bash|sh|zsh|fish|python\S*|perl|ruby|node)",  # 管道到解释器
        r"--exec",      # find --exec
        r"-exec\b",     # find -exec
        r"-delete\b",   # find -delete
        r"-i\b",        # sed -i（原地修改）
        r"/etc/passwd", r"/etc/shadow", r"/proc/",  # 敏感路径
    ]
]

# 完全封禁的危险命令（即使用户拼出来也拒绝）
_BLOCKED_COMMANDS: frozenset[str] = frozenset({
    "rm", "rmdir", "del", "shred",
    "mv", "cp",
    "chmod", "chown", "chattr", "setfacl",
    "sudo", "su", "doas", "pkexec",
    "curl", "wget", "nc", "netcat", "ncat", "socat",
    "ssh", "scp", "sftp", "ftp", "rsync",
    "bash", "sh", "zsh", "fish", "ksh", "dash",
    "python", "python3", "perl", "ruby", "node", "php", "lua",
    "dd", "mkfs", "fdisk", "parted", "mount", "umount",
    "kill", "killall", "pkill",
    "crontab", "at", "batch", "nohup",
    "iptables", "nft", "tc",
    "docker", "podman", "kubectl",
})


def _validate_command(cmd_str: str) -> tuple[bool, str]:
    """
    验证 shell 命令是否安全。
    返回 (ok, reason) 元组。
    """
    cmd_str = cmd_str.strip()

    # 检查参数黑名单模式
    for pattern in _BLOCKED_ARG_PATTERNS:
        if pattern.search(cmd_str):
            return False, f"命令包含被禁止的模式: `{pattern.pattern}`"

    # 解析 tokens
    try:
        tokens = shlex.split(cmd_str)
    except ValueError as exc:
        return False, f"命令解析失败: {exc}"

    if not tokens:
        return False, "空命令"

    base_cmd = os.path.basename(tokens[0]).lower()

    # 封禁命令检查
    if base_cmd in _BLOCKED_COMMANDS:
        return False, f"命令 '{base_cmd}' 已被安全策略封禁"

    # 白名单检查
    if base_cmd not in _ALLOWED_COMMANDS:
        return False, (
            f"命令 '{base_cmd}' 不在允许列表中。\n"
            f"允许的命令: {', '.join(sorted(_ALLOWED_COMMANDS))}"
        )

    # git 子命令检查
    if base_cmd == "git":
        if len(tokens) < 2:
            return False, "git 命令需要指定子命令"
        subcmd = tokens[1].lower()
        if subcmd not in _GIT_SAFE_SUBCMDS:
            return False, (
                f"git 子命令 '{subcmd}' 不被允许。\n"
                f"允许的 git 子命令: {', '.join(sorted(_GIT_SAFE_SUBCMDS))}"
            )

    # pip 子命令检查
    if base_cmd in ("pip", "pip3"):
        if len(tokens) < 2:
            return False, "pip 命令需要指定子命令"
        subcmd = tokens[1].lower()
        if subcmd not in _PIP_SAFE_SUBCMDS:
            return False, (
                f"pip 子命令 '{subcmd}' 不被允许。\n"
                f"允许的 pip 子命令: {', '.join(sorted(_PIP_SAFE_SUBCMDS))}"
            )

    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
#  工具定义
# ══════════════════════════════════════════════════════════════════════════════

@tool
def get_current_time() -> str:
    """获取当前的系统时间。当用户询问时间或日期时使用。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def list_files(directory: str = ".") -> str:
    """
    列出工作目录下指定子目录的所有文件。
    路径限制在 /app/workspace 内，不可访问系统目录。

    Args:
        directory: 相对于工作目录的子路径，默认列出工作目录根目录。
    """
    safe = _safe_path(directory)
    if safe is None:
        return f"🚫 路径访问被拒绝：只允许访问工作目录 {_WORKSPACE} 内的路径。"
    try:
        if not os.path.exists(safe):
            os.makedirs(safe, exist_ok=True)
        files = os.listdir(safe)
        return "\n".join(files) if files else "该目录为空。"
    except Exception as exc:
        return f"读取目录失败: {exc}"


@tool
def read_file_content(file_path: str) -> str:
    """
    读取工作目录内指定文件的文本内容（最多 2000 字符）。
    路径限制在 /app/workspace 内，不可读取系统文件。

    Args:
        file_path: 相对于工作目录的文件路径。
    """
    safe = _safe_path(file_path)
    if safe is None:
        return f"🚫 路径访问被拒绝：只允许读取工作目录 {_WORKSPACE} 内的文件。"
    try:
        with open(safe, "r", encoding="utf-8") as f:
            content = f.read(2000)
        return content if content else "（文件为空）"
    except Exception as exc:
        return f"读取文件失败: {exc}"


@tool
def execute_python_code(code: str) -> str:
    """
    在安全沙箱中执行 Python 代码并返回输出。

    安全限制（RestrictedPython）：
    - 禁止导入 os、sys、subprocess、socket、http、pathlib 等危险模块
    - 禁止使用 open()、exec()、eval()、__import__() 等危险内置函数
    - 禁止访问 __dunder__ 属性链
    - 允许导入: math, json, re, datetime, collections, itertools, random 等纯计算模块
    - 执行超时 10 秒

    Args:
        code: 要执行的 Python 代码字符串。
    """
    logger.info("[Tool] execute_python_code — 代码长度 %d 字符", len(code))
    result = execute_sandboxed(code, timeout=10)
    logger.info("[Tool] execute_python_code — 执行完毕")
    return result


@tool
def run_shell_command(command: str) -> str:
    """
    在白名单沙箱中执行 shell 命令，仅支持只读/查询类命令。

    ✅ 允许的命令类别：
      - 文件查看: ls, cat, head, tail, wc, find, stat, du, df
      - 文本处理: grep, awk, sort, uniq, cut, diff
      - 系统信息: pwd, date, echo, uname, ps, free, uptime, whoami
      - 版本控制: git status/log/diff/branch/show（只读子命令）
      - 包查询:   pip list / pip show / pip freeze

    🚫 禁止的操作：
      - 写文件（rm、mv、cp、chmod、>重定向）
      - 网络操作（curl、wget、nc、ssh）
      - 启动解释器（python、bash、sh、node）
      - 命令注入（; 链、$()替换、管道到 shell）

    Args:
        command: 要执行的 shell 命令字符串。
    """
    logger.info("[Tool] run_shell_command — cmd='%s'", command[:80])

    ok, reason = _validate_command(command)
    if not ok:
        return f"🚫 命令被拒绝: {reason}"

    try:
        tokens = shlex.split(command)
        result = subprocess.run(
            tokens,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,      # 不使用 shell，避免 shell 注入
            cwd=_WORKSPACE,   # 工作目录限制
            env={              # 最小化环境变量，不暴露主进程 env
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": "/tmp",
                "LANG": "en_US.UTF-8",
            },
        )
    except subprocess.TimeoutExpired:
        return "⏱️ 命令执行超时（超过 10 秒）"
    except FileNotFoundError:
        return f"❌ 命令不存在: {shlex.split(command)[0]}"
    except Exception as exc:
        return f"执行失败: {exc}"

    output = result.stdout
    stderr = result.stderr

    if result.returncode != 0:
        return f"❌ 命令返回非零状态码 ({result.returncode}):\n{stderr or output}"

    if not output.strip():
        return "（命令执行完毕，无输出）"

    if len(output) > 4000:
        output = output[:4000] + "\n... [输出过长，已截断]"

    return f"✅ 执行成功:\n{output}"


# ── 按职责分组，供各 Sub-Agent 按需注入 ────────────────────────────────────────
code_tools    = [execute_python_code]
file_tools    = [list_files, read_file_content]
shell_tools   = [run_shell_command]
general_tools = [get_current_time]

# 向后兼容别名
agent_tools = code_tools + file_tools + shell_tools + general_tools
