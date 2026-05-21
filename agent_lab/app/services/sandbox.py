"""
Code execution sandbox — RestrictedPython + 白名单 import + 超时保护

防护层次：
  1. RestrictedPython AST 重写  ── 拦截危险语法（__dunder__、open、exec …）
  2. 模块白名单 __import__        ── 只允许安全 stdlib 模块被导入
  3. stdout / stderr 捕获        ── 输出完全隔离，不影响主进程
  4. threading.Timer 超时        ── 防止死循环占用资源
  5. 输出长度截断                 ── 防止超大输出打爆内存
"""

from __future__ import annotations

import io
import threading
from contextlib import redirect_stdout, redirect_stderr
from typing import Any

from RestrictedPython import compile_restricted, safe_globals, safe_builtins
from RestrictedPython.Guards import guarded_iter_unpack_sequence

# ── 允许导入的模块白名单 ────────────────────────────────────────────────────────
_ALLOWED_MODULES: frozenset[str] = frozenset({
    # 数学 / 数值
    "math", "cmath", "decimal", "fractions", "statistics", "random",
    "numbers",
    # 文本 / 正则
    "json", "re", "string", "textwrap", "difflib", "unicodedata",
    # 日期时间
    "datetime", "calendar",
    # 数据结构 / 函数工具
    "itertools", "functools", "operator",
    "collections", "heapq", "bisect", "array",
    # 类型 / 工具
    "typing", "types", "abc", "copy", "pprint", "enum",
    # IO（内存，不涉及文件系统）
    "io",
    # 哈希（纯计算，不涉及网络）
    "hashlib", "hmac", "base64", "binascii",
    # 结构 / 压缩（内存）
    "struct",
})

# 明确封锁的模块（即使不在白名单也会二次拦截，给出明确提示）
_BLOCKED_MODULES: frozenset[str] = frozenset({
    "os", "sys", "subprocess", "socket", "http", "urllib", "httpx",
    "requests", "aiohttp", "ftplib", "smtplib", "ssl", "asyncio",
    "multiprocessing", "threading", "concurrent", "_thread",
    "ctypes", "cffi", "importlib", "importlib_metadata",
    "builtins", "gc", "inspect", "dis", "ast", "code", "codeop",
    "pickle", "pickletools", "shelve", "marshal",
    "signal", "resource", "pty", "tty", "termios",
    "pathlib", "shutil", "glob", "tempfile", "fnmatch",
    "zipfile", "tarfile", "gzip", "bz2", "lzma", "zlib",
    "nt", "posix", "winreg", "msvcrt",
})


def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    """白名单化的 __import__ 替代函数。"""
    top = name.split(".")[0]
    if top in _BLOCKED_MODULES:
        raise ImportError(f"🚫 模块 '{name}' 已被安全策略封锁。")
    if top not in _ALLOWED_MODULES:
        raise ImportError(
            f"🚫 模块 '{name}' 不在允许列表中。\n"
            f"   允许的模块: {', '.join(sorted(_ALLOWED_MODULES))}"
        )
    return __import__(name, *args, **kwargs)


def _safe_write(obj: Any) -> Any:
    """RestrictedPython 写保护 —— 仅允许写 list / dict / set。"""
    if isinstance(obj, (list, dict, set)):
        return obj
    raise AttributeError(f"🚫 不允许对 {type(obj).__name__} 执行属性写操作。")


class _PrintCapture:
    """RestrictedPython _print_ 收集器（兼容 RestrictedPython 8.x 链式协议）。

    RestrictedPython 8.x 将 print(x) 编译为:
        _print_(_getattr_)._call_print(x)
    即：先以 _getattr_ 为参数调用 _print_，再链式调用 _call_print(x)。
    因此需要过滤掉 _getattr_ 这个内部参数，避免它出现在输出中。
    """
    def __init__(self) -> None:
        self._buf: list[str] = []
        self._internal: set = set()  # RestrictedPython 内部对象，不纳入输出

    def set_internals(self, *objs: Any) -> None:
        """注册需要从 print 输出中过滤的内部对象（如 _getattr_）。"""
        self._internal = set(id(o) for o in objs)

    def __call__(self, *args: Any, sep: str = " ", end: str = "\n", **_: Any) -> "_PrintCapture":
        # 过滤 RestrictedPython 注入的内部参数（如 _getattr_ = getattr 内置函数）
        printable = [a for a in args if id(a) not in self._internal]
        if printable:
            self._buf.append(sep.join(str(a) for a in printable) + end)
        return self   # 返回 self 支持链式调用 ._call_print()

    def _call_print(self, *args: Any, **kwargs: Any) -> None:
        """RestrictedPython 链式调用入口。"""
        if args:
            self(*args, **kwargs)

    def getvalue(self) -> str:
        return "".join(self._buf)


def _build_globals() -> dict:
    """构建受限执行环境的 globals 字典。"""
    glb = safe_globals.copy()

    # 以 safe_builtins 为基础，补充常用安全内置函数
    rb: dict = dict(safe_builtins)

    _EXTRA_SAFE_BUILTINS = {
        "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
        "callable", "chr", "complex", "dict", "divmod", "enumerate",
        "filter", "float", "format", "frozenset", "getattr",
        "hasattr", "hash", "hex", "id", "int", "isinstance", "issubclass",
        "iter", "len", "list", "map", "max", "min", "next",
        "object", "oct", "ord", "pow", "print", "range", "repr",
        "reversed", "round", "set", "setattr", "slice", "sorted", "str",
        "sum", "super", "tuple", "type", "vars", "zip",
        "__build_class__",
    }
    import builtins as _builtins_mod
    for name in _EXTRA_SAFE_BUILTINS:
        if hasattr(_builtins_mod, name):
            rb[name] = getattr(_builtins_mod, name)

    # 封锁危险内置
    for blocked in ("open", "exec", "eval", "compile", "__import__",
                    "input", "memoryview", "breakpoint", "exit", "quit",
                    "__loader__", "__spec__"):
        rb.pop(blocked, None)

    # 注入白名单 import
    rb["__import__"] = _safe_import

    glb["__builtins__"] = rb
    glb["_write_"] = _safe_write
    glb["_getiter_"] = iter
    glb["_getattr_"] = getattr
    glb["_getitem_"] = lambda obj, key: obj[key]
    glb["_iter_unpack_sequence_"] = guarded_iter_unpack_sequence
    return glb


# ── 公开接口 ────────────────────────────────────────────────────────────────────

MAX_OUTPUT_CHARS = 4000   # 超过此长度截断
DEFAULT_TIMEOUT  = 10     # 秒


def execute_sandboxed(code: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """
    在 RestrictedPython 沙箱中执行 Python 代码，返回字符串结果。

    - 代码通不过安全编译 → 返回错误说明
    - 执行超时            → 返回超时提示
    - 运行时异常          → 返回异常信息
    - 正常完成            → 返回 stdout 内容
    """
    # ── 第一层：安全编译 ───────────────────────────────────────────────────────
    try:
        byte_code = compile_restricted(code, filename="<sandbox>", mode="exec")
    except SyntaxError as exc:
        return f"❌ 语法错误: {exc}"
    except Exception as exc:
        return f"🚫 代码被安全策略拒绝（编译阶段）: {exc}"

    if byte_code is None:
        return "🚫 代码编译失败（包含被禁止的语法结构）"

    # ── 第二层：受限执行 + 超时 ────────────────────────────────────────────────
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    result: dict[str, Any] = {"output": None, "error": None}

    def _run() -> None:
        try:
            printer = _PrintCapture()
            glb = _build_globals()
            glb["_print_"] = printer
            # 告知 printer 哪些对象是 RestrictedPython 内部参数，过滤掉不输出
            printer.set_internals(glb.get("_getattr_"), glb.get("_getitem_"))
            with redirect_stdout(out_buf), redirect_stderr(err_buf):
                exec(byte_code, glb)  # noqa: S102
            result["output"] = printer.getvalue() or out_buf.getvalue()
        except ImportError as exc:
            result["error"] = str(exc)
        except AttributeError as exc:
            result["error"] = f"🚫 属性访问被拒绝: {exc}"
        except Exception as exc:
            stderr_content = err_buf.getvalue()
            result["error"] = (
                f"运行时错误 [{type(exc).__name__}]: {exc}"
                + (f"\nstderr:\n{stderr_content}" if stderr_content else "")
            )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        return f"⏱️ 执行超时（超过 {timeout} 秒），已强制中止。"

    if result["error"]:
        return result["error"]

    output: str = result["output"] or ""
    if not output.strip():
        return "（代码执行完毕，无 stdout 输出）"

    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + f"\n... [输出过长，已截断至 {MAX_OUTPUT_CHARS} 字符]"

    return f"✅ 执行成功:\n{output}"
