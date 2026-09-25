"""Model-written Python: static facts for the guardrail policy, and the locked-down child that runs it.

The guardrail policy decides from ``analyse`` whether a program may run at all. Whatever the policy
allows, the child interpreter keeps a fixed floor: an isolated interpreter (-I -S -B: standard library
only), no credentials in its environment, CPU/memory/file/process limits, and a PEP 578 audit hook that
refuses sockets, subprocesses, native code and any file access outside the run's scratch workspace.
"""

from __future__ import annotations

import ast
from typing import Any

MAX_FACTS = 200

# Runtime floor, independent of policy: these modules and events never work in the child.
BLOCKED_MODULES = frozenset({
    "_ctypes", "_multiprocessing", "_posixshmem", "_posixsubprocess", "_socket", "_ssl", "asyncio",
    "concurrent.futures.process", "ctypes", "ftplib", "gc", "http.client", "http.server", "imaplib", "mmap",
    "multiprocessing", "poplib", "pty", "smtplib", "socket", "socketserver", "ssl", "subprocess", "telnetlib",
    "urllib.request", "webbrowser", "xmlrpc.client", "xmlrpc.server",
})

_DYNAMIC_ATTRIBUTE_CALLS = frozenset({"getattr", "setattr", "delattr", "hasattr"})


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif parts:
        return parts[0]  # A method on an expression result, e.g. open(p).read -> read.
    else:
        return ""
    return ".".join(reversed(parts))


def analyse(code: str) -> dict[str, Any]:
    """Facts the policy reasons about: imports, called names and dunder attributes. Never executes code."""
    facts: dict[str, Any] = {
        "syntax_ok": True, "error": "", "imports": [], "calls": [], "attributes": [],
        "chars": len(code), "lines": code.count("\n") + 1,
    }
    try:
        tree = ast.parse(code, filename="program.py", mode="exec")
    except SyntaxError as error:
        facts.update(syntax_ok=False, error=f"line {error.lineno}: {error.msg}")
        return facts
    except (ValueError, RecursionError, MemoryError):
        facts.update(syntax_ok=False, error="the program could not be parsed")
        return facts
    imports: set[str] = set()
    calls: set[str] = set()
    attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add("." if node.level else (node.module or "").split(".")[0])
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name:
                calls.add(name)
            if (name in _DYNAMIC_ATTRIBUTE_CALLS and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str) and node.args[1].value.startswith("__")):
                attributes.add(node.args[1].value)
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            attributes.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in {"__builtins__", "__loader__", "__spec__"}:
            attributes.add(node.id)
    facts.update(imports=sorted(imports - {""})[:MAX_FACTS], calls=sorted(calls)[:MAX_FACTS],
                 attributes=sorted(attributes)[:MAX_FACTS])
    return facts


BOOTSTRAP = r'''
import builtins
import os
import sys


def _install(program, seconds, blocked_modules):
    try:
        import resource
    except ImportError:
        resource = None
    if resource is not None:
        for name, value in (("RLIMIT_CPU", seconds + 2), ("RLIMIT_AS", 1 << 30), ("RLIMIT_FSIZE", 25 << 20),
                            ("RLIMIT_NOFILE", 64), ("RLIMIT_NPROC", 0), ("RLIMIT_CORE", 0)):
            limit = getattr(resource, name, None)
            if limit is not None:
                try:
                    resource.setrlimit(limit, (value, value))
                except (ValueError, OSError):
                    pass
    with open(program, encoding="utf-8") as handle:
        source = handle.read()
    work = os.path.normcase(os.path.abspath(os.getcwd()))
    roots = tuple(sorted({os.path.normcase(os.path.abspath(path)) for path in (
        sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(os.__file__),
        "/usr/share/zoneinfo", "/usr/lib/python3", "/etc/localtime")}))
    devices = frozenset({"/dev/null", "/dev/urandom", "/dev/random", "nul"})
    file_events = frozenset({
        "os.listdir", "os.scandir", "os.remove", "os.rename", "os.replace", "os.rmdir", "os.mkdir", "os.chmod",
        "os.chown", "os.utime", "os.truncate", "os.chdir", "shutil.rmtree", "shutil.copyfile", "shutil.copymode",
        "shutil.copystat", "shutil.copytree", "shutil.move", "shutil.make_archive"})
    listing = frozenset({"os.listdir", "os.scandir"})
    process_events = frozenset({
        "os.system", "os.fork", "os.forkpty", "os.kill", "os.killpg", "os.startfile", "os.symlink", "os.link",
        "sys.addaudithook", "builtins.input", "sys.setprofile", "sys.settrace"})
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
    fspath, fsdecode, abspath, normcase, sep = os.fspath, os.fsdecode, os.path.abspath, os.path.normcase, os.sep

    def inside(path, allowed):
        if isinstance(path, int):
            return True
        if path is None:
            path = "."
        path = fsdecode(path) if isinstance(path, bytes) else fspath(path)
        full = normcase(abspath(path))
        return full in devices or any(full == root or full.startswith(root.rstrip("\\/") + sep) for root in allowed)

    def refuse(what):
        raise PermissionError(f"Blocked by the code sandbox: {what}.")

    def audit(event, args):
        if event == "open":
            path, mode, flags = (tuple(args) + (None, None, 0))[:3]
            if path is None:
                return
            writing = bool(mode and any(ch in str(mode) for ch in "wax+")) or bool((flags or 0) & write_flags)
            if not inside(path, (work,) if writing else (work, *roots)):
                refuse("files outside the workspace")
        elif event == "import":
            if args and args[0] in blocked_modules:
                refuse(f"module {args[0]}")
        elif event.startswith(("socket.", "ctypes.", "os.exec", "os.spawn", "os.posix_spawn", "subprocess.", "winreg.")):
            refuse("network, native code or processes")
        elif event in process_events:
            refuse(event)
        elif event in file_events:
            allowed = (work, *roots) if event in listing else (work,)
            for item in args:
                if isinstance(item, (str, bytes, os.PathLike)) and not inside(item, allowed):
                    refuse("files outside the workspace")

    for name in blocked_modules:
        sys.modules.pop(name, None)
    sys.addaudithook(audit)
    return compile(source, "program.py", "exec")


_code = _install(sys.argv[1], int(sys.argv[2]), frozenset(__BLOCKED_MODULES__))
del _install
exec(_code, {"__name__": "__main__", "__builtins__": builtins, "__file__": "program.py"})
'''


def bootstrap_source() -> str:
    return BOOTSTRAP.replace("__BLOCKED_MODULES__", repr(sorted(BLOCKED_MODULES)))
