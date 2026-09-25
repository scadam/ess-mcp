"""Skill packages and the working environment an AI colleague uses for multi-step skill runs.

A skill is a folder in the Agent Skills format (https://agentskills.io/specification)::

    skills/<name>/SKILL.md      YAML frontmatter and the playbook the colleague follows
    skills/<name>/references/   detail the colleague reads only when it needs it
    skills/<name>/scripts/      deterministic Python helpers, run in an isolated subprocess
    skills/<name>/templates/    output templates

``allowed-tools`` lists the MCP actions that are pre-approved when an operator approves the skill
colleague: ``server__tool`` or ``server__tool(argument=value|value)``; ``metadata.autonomy-check`` names a
bundled script that must also allow each such action. ``metadata`` values are strings: ``title``, ``summary``,
``version``, ``domain``, ``servers``, ``model-orchestrator``, ``model-subagents``, ``autonomy-budget``,
``autonomy-check``, ``outputs`` and ``launch``. A flat ``skills/<name>.md`` with the same frontmatter (or none)
loads as an instructions-only skill.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_logger = logging.getLogger("group-functions-autopilot.skills")

SKILL_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
TIERS = ("reasoning", "standard", "fast")
SERVERS = ("workday", "servicenow", "coupa", "salesforce", "workiq")
PACKAGE_DIRS = ("references", "scripts", "templates")
READ_ONLY_TOOL = re.compile(r"^(?:get|list|search|find|lookup|read|check)(?:_|$)", re.IGNORECASE)
MAX_BUDGET = 80
MAX_TURNS = 80

_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_GRANT = re.compile(
    r"(workday|servicenow|coupa|salesforce)__([A-Za-z0-9_]{1,64})"
    r"(?:\(([A-Za-z0-9_]{1,64})=([A-Za-z0-9_.-]{1,64}(?:\|[A-Za-z0-9_.-]{1,64}){0,7})\))?"
)
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.DOTALL)
_MAX_SKILL_BYTES = 96_000
_MAX_PACKAGE_FILES = 64


@dataclass(frozen=True)
class ToolGrant:
    """One pre-approved MCP action, optionally limited to certain values of one argument."""

    server: str
    tool: str
    argument: str | None = None
    values: frozenset[str] = frozenset()

    def matches(self, server: str, tool: str, args: dict[str, Any]) -> bool:
        if (server, tool) != (self.server, self.tool):
            return False
        if self.argument is None:
            return True
        value = args.get(self.argument)
        return isinstance(value, str) and value.strip().casefold() in self.values

    def label(self) -> str:
        text = f"{self.server}.{self.tool}"
        return text + (f" ({self.argument}: {'/'.join(sorted(self.values))})" if self.argument else "")


def parse_grants(value: Any) -> tuple[ToolGrant, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("allowed-tools must be a space-delimited string.")
    grants = []
    for token in value.split():
        match = _GRANT.fullmatch(token)
        if match is None:
            raise ValueError(f"Unsupported allowed-tools entry {token[:80]!r}.")
        server, tool, argument, values = match.groups()
        if READ_ONLY_TOOL.match(tool):
            continue  # Reads never need approval; listing them grants nothing extra.
        grants.append(ToolGrant(server, tool, argument, frozenset(item.casefold() for item in (values or "").split("|") if item)))
    return tuple(grants)


@dataclass(frozen=True)
class SkillPackage:
    name: str
    description: str
    body: str
    root: Path | None = None  # None for a legacy flat file.
    metadata: dict[str, str] = field(default_factory=dict)
    grants: tuple[ToolGrant, ...] = ()
    license: str = ""
    compatibility: str = ""

    @property
    def legacy(self) -> bool:
        return self.root is None

    @property
    def title(self) -> str:
        return self.metadata.get("title") or self.name.replace("-", " ").title()

    @property
    def summary(self) -> str:
        text = self.metadata.get("summary") or self.description
        first = re.split(r"(?<=[.!?])\s", " ".join(text.split()), maxsplit=1)[0]
        return first[:220]

    @property
    def version(self) -> str:
        return self.metadata.get("version", "")

    @property
    def domain(self) -> str:
        return self.metadata.get("domain", "")

    @property
    def servers(self) -> tuple[str, ...]:
        named = re.split(r"[\s,]+", self.metadata.get("servers", "").strip())
        return tuple(dict.fromkeys(server for server in named if server in SERVERS))

    @property
    def outputs(self) -> tuple[str, ...]:
        return tuple(item for item in re.split(r"[\s,]+", self.metadata.get("outputs", "").strip()) if item)

    @property
    def launch(self) -> str:
        return self.metadata.get("launch") or f"Run the {self.title} skill."

    @property
    def budget(self) -> int:
        if not self.grants:
            return 0
        try:
            value = int(self.metadata.get("autonomy-budget", "3"))
        except ValueError:
            value = 3
        return max(0, min(MAX_BUDGET, value))

    @property
    def max_turns(self) -> int:
        """Orchestrator turn limit from metadata max-turns (0 = the host default)."""
        try:
            value = int(self.metadata.get("max-turns", "0"))
        except ValueError:
            return 0
        return max(0, min(MAX_TURNS, value))

    def tier(self, role: str) -> str:
        chosen = self.metadata.get(f"model-{role}", "")
        if chosen in TIERS:
            return chosen
        return "standard" if role == "orchestrator" else "fast"

    def files(self) -> list[dict[str, Any]]:
        """The bundled files, with a one-line purpose for progressive disclosure."""
        if self.root is None:
            return []
        entries: list[dict[str, Any]] = []
        for folder in PACKAGE_DIRS:
            base = self.root / folder
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if len(entries) >= _MAX_PACKAGE_FILES:
                    return entries
                if not path.is_file() or path.is_symlink() or path.name.startswith(".") or "__pycache__" in path.parts:
                    continue
                relative = path.relative_to(self.root).as_posix()
                entries.append({"path": relative, "bytes": path.stat().st_size, "purpose": _purpose(path)})
        return entries

    def _resolve(self, relative: Any, folders: tuple[str, ...] = PACKAGE_DIRS) -> Path:
        if self.root is None:
            raise FileNotFoundError("This skill has no bundled files.")
        normalized = Workspace.normalize(relative)
        if normalized.split("/", 1)[0] not in folders:
            raise FileNotFoundError(f"Only files under {', '.join(folders)}/ can be used.")
        root = self.root.resolve()
        path = (root / normalized).resolve()
        if not path.is_relative_to(root) or not path.is_file() or (root / normalized).is_symlink():
            raise FileNotFoundError(f"{normalized} is not a file in this skill.")
        return path

    def read(self, relative: Any, *, offset: int = 0, limit: int = 20_000) -> dict[str, Any]:
        path = self._resolve(relative)
        text = path.read_text(encoding="utf-8", errors="replace")
        return _window(path.relative_to(self.root.resolve()).as_posix(), text, offset, limit)

    def script(self, name: Any) -> Path:
        if not isinstance(name, str) or not name.endswith(".py"):
            raise FileNotFoundError("Name a bundled Python script, for example scripts/analyse.py.")
        relative = name if name.startswith("scripts/") else "scripts/" + name
        return self._resolve(relative, ("scripts",))

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name, "title": self.title, "summary": self.summary, "description": self.description,
            "version": self.version, "domain": self.domain, "servers": list(self.servers),
            "launch": self.launch, "legacy": self.legacy, "outputs": list(self.outputs),
            "models": {"orchestrator": self.tier("orchestrator"), "subagents": self.tier("subagents")},
            "autonomy": {"budget": self.budget, "actions": [grant.label() for grant in self.grants]},
            "files": self.files(),
        }


def _purpose(path: Path) -> str:
    """First heading, docstring or comment line of a bundled file."""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            head = handle.read(2000)
    except OSError:
        return ""
    if path.suffix == ".py":
        match = re.search(r'"""\s*(.+?)\s*(?:\n|""")', head)
        return match[1][:160] if match else ""
    for line in head.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped and not stripped.startswith(("---", "<!--")):
            return stripped[:160]
    return ""


def _window(path: str, text: str, offset: Any, limit: Any) -> dict[str, Any]:
    offset = offset if type(offset) is int and offset >= 0 else 0
    limit = limit if type(limit) is int and 1 <= limit <= 40_000 else 12_000
    chunk = text[offset:offset + limit]
    return {"path": path, "offset": offset, "returned": len(chunk), "total": len(text),
            "more": offset + len(chunk) < len(text), "content": chunk}


def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER.match(text)
    if match is None:
        raise ValueError("SKILL.md must start with YAML frontmatter between --- lines.")
    data = yaml.safe_load(match[1])
    if type(data) is not dict:
        raise ValueError("The SKILL.md frontmatter must be a mapping.")
    return data, match[2].strip()


def _metadata(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if type(value) is not dict or len(value) > 40:
        raise ValueError("metadata must be a mapping of at most 40 entries.")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", key):
            raise ValueError("metadata keys must be short lowercase names.")
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise ValueError("metadata values must be strings.")
        result[key] = str(item).strip()[:600]
    return result


def load_skill(path: Path) -> SkillPackage:
    """A skill folder (SKILL.md plus bundled files) or a flat instructions-only <name>.md file."""
    folder = path.is_dir()
    text = (path / "SKILL.md" if folder else path).read_text(encoding="utf-8")
    name_expected = path.name if folder else path.stem
    if len(text.encode("utf-8")) > _MAX_SKILL_BYTES:
        raise ValueError("The skill file is too large.")
    if folder or text.startswith("---"):
        data, body = _frontmatter(text)
        name, description = data.get("name"), data.get("description")
        if not isinstance(name, str) or not SKILL_NAME.fullmatch(name) or "--" in name or name != name_expected:
            raise ValueError("name must be a lowercase hyphenated name matching the folder.")
        if not isinstance(description, str) or not 1 <= len(description.strip()) <= 1024:
            raise ValueError("description must be 1-1024 characters.")
        compatibility = data.get("compatibility") or ""
        license_text = data.get("license") or ""
        if not isinstance(compatibility, str) or len(compatibility) > 500 or not isinstance(license_text, str):
            raise ValueError("license and compatibility must be short strings.")
        if not body:
            raise ValueError("The skill needs instructions after the frontmatter.")
        return SkillPackage(
            name=name, description=" ".join(description.split()), body=body, root=path if folder else None,
            metadata=_metadata(data.get("metadata")), grants=parse_grants(data.get("allowed-tools")),
            license=license_text.strip()[:200], compatibility=compatibility.strip(),
        )
    if not SKILL_NAME.fullmatch(path.stem):
        raise ValueError("Legacy skill files need a lowercase hyphenated name.")
    first = next((line.strip().lstrip("#").strip() for line in text.splitlines() if line.strip()), path.stem)
    return SkillPackage(name=path.stem, description=first[:200], body=text.strip())


def load_library(root: Path) -> dict[str, SkillPackage]:
    """Every valid skill under root; an invalid package is skipped, never partially loaded."""
    packages: dict[str, SkillPackage] = {}
    if not root.is_dir():
        return packages
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / "SKILL.md").is_file():
            pass
        elif not (entry.is_file() and entry.suffix == ".md"):
            continue
        try:
            package = load_skill(entry)
        except (OSError, ValueError, yaml.YAMLError) as error:
            _logger.warning("Skipped skill %s: %s", entry.name, str(error)[:200])
            continue
        if package.name in packages:
            _logger.warning("Skipped duplicate skill %s", package.name)
            continue
        packages[package.name] = package
    return packages


class Workspace:
    """A bounded, in-memory working folder for one run: raw data, intermediate files and deliverables."""

    MAX_FILES = 128
    MAX_FILE_BYTES = 2_000_000
    MAX_TOTAL_BYTES = 24_000_000

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._files: dict[str, dict[str, Any]] = {}
        self.total = 0

    @staticmethod
    def normalize(path: Any) -> str:
        if not isinstance(path, str):
            raise ValueError("A relative file path is required.")
        path = path.strip()
        if path.startswith("./"):
            path = path[2:]
        if not path or len(path) > 200 or path.startswith("/") or "\\" in path or ":" in path:
            raise ValueError("Use a relative path such as reports/brief.md.")
        segments = path.split("/")
        if len(segments) > 5 or any(_SEGMENT.fullmatch(segment) is None or set(segment) == {"."}
                                    for segment in segments):
            raise ValueError("Path segments may use letters, digits, dot, dash and underscore only.")
        return "/".join(segments)

    def write(self, path: Any, content: str | bytes, *, source: str) -> dict[str, Any]:
        path = self.normalize(path)
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        if len(data) > self.MAX_FILE_BYTES:
            raise ValueError(f"{path} is larger than the {self.MAX_FILE_BYTES:,}-byte file limit.")
        previous = self._files.get(path)
        if previous is None and len(self._files) >= self.MAX_FILES:
            raise ValueError(f"The workspace already holds {self.MAX_FILES} files.")
        total = self.total - (len(previous["data"]) if previous else 0) + len(data)
        if total > self.MAX_TOTAL_BYTES:
            raise ValueError("The workspace is full.")
        self._files[path] = {"data": data, "source": str(source)[:80], "at": int(time.time() * 1000)}
        self.total = total
        return self.entry(path)

    def entry(self, path: str) -> dict[str, Any]:
        record = self._files[path]
        return {"path": path, "bytes": len(record["data"]), "source": record["source"], "updatedAt": record["at"]}

    def exists(self, path: Any) -> bool:
        try:
            return self.normalize(path) in self._files
        except ValueError:
            return False

    def read_bytes(self, path: Any) -> bytes:
        path = self.normalize(path)
        if path not in self._files:
            raise FileNotFoundError(f"{path} is not in the workspace.")
        return self._files[path]["data"]

    def read_text(self, path: Any, *, offset: Any = 0, limit: Any = 12_000) -> dict[str, Any]:
        normalized = self.normalize(path)
        return _window(normalized, self.read_bytes(normalized).decode("utf-8", errors="replace"), offset, limit)

    def listing(self) -> list[dict[str, Any]]:
        return [self.entry(path) for path in sorted(self._files)]

    def snapshot(self) -> dict[str, bytes]:
        return {path: record["data"] for path, record in self._files.items()}

    def save_tool_result(self, server: str, tool: str, args: dict[str, Any], text: str) -> str:
        """Keep the full result where scripts and sub-agents can reach it; the same call overwrites."""
        meaningful = {key: value for key, value in (args or {}).items() if value not in (None, "", [], {})}
        suffix = "-" + hashlib.sha256(json.dumps(meaningful, sort_keys=True, default=str).encode()).hexdigest()[:8] if meaningful else ""
        try:
            json.loads(text)
            extension = ".json"
        except ValueError:
            extension = ".txt"
        path = f"data/{server}/{tool}{suffix}{extension}"
        self.write(path, text, source=f"{server}.{tool}")
        return path


@dataclass
class SkillSession:
    """The per-run state of one skill: its package, workspace and remaining autonomy."""

    package: SkillPackage
    workspace: Workspace
    dry_run: bool = False
    remaining: int = 0
    used: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def start(cls, package: SkillPackage, run_id: str, *, dry_run: bool = False) -> "SkillSession":
        return cls(package, Workspace(run_id), dry_run=dry_run, remaining=0 if dry_run else package.budget)

    def grant_for(self, server: str, tool: str, args: dict[str, Any]) -> ToolGrant | None:
        if self.dry_run or self.remaining <= 0:
            return None
        return next((grant for grant in self.package.grants if grant.matches(server, tool, args)), None)

    def spend(self, grant: ToolGrant, server: str, tool: str, args: dict[str, Any] | None = None) -> None:
        self.remaining -= 1
        self.used.append({"action": f"{server}.{tool}", "grant": grant.label(), "at": int(time.time() * 1000),
                          "args": json.loads(json.dumps(args or {}, default=str))})

    def authority(self) -> str:
        if self.dry_run:
            return ("This is a dry run: no change is made or queued. Treat every change as a recommendation and "
                    "list it in your reply.")
        if not self.package.grants:
            return "No change is pre-approved for this skill: every change goes to a person for approval."
        return (f"The operator pre-approved these actions for this skill, up to {self.package.budget} in total: "
                + "; ".join(grant.label() for grant in self.package.grants)
                + ". Use them only as the playbook's rules allow. Anything else, anything sensitive and anything "
                  "over budget goes to a person for approval.")


class ModelRouter:
    """Route work to model deployments by tier; an unavailable deployment falls back to the default."""

    def __init__(self, default: str, routes: str = "") -> None:
        self.default = default if _MODEL.fullmatch(default or "") else "gpt-4.1"
        self.routes: dict[str, str] = {}
        self.unavailable: set[str] = set()
        if routes.strip():
            try:
                data = json.loads(routes)
            except ValueError:
                data = None
            if type(data) is not dict:
                _logger.warning("AUTOPILOT_MODEL_ROUTES is not a JSON object; every tier uses %s", self.default)
                data = {}
            for tier, model in data.items():
                if tier in TIERS and isinstance(model, str) and _MODEL.fullmatch(model):
                    self.routes[tier] = model

    @classmethod
    def from_env(cls) -> "ModelRouter":
        return cls(os.getenv("ESS_MODEL", "gpt-4.1"), os.getenv("AUTOPILOT_MODEL_ROUTES", ""))

    def model(self, tier: str) -> str:
        chosen = self.routes.get(tier) or self.default
        return self.default if chosen in self.unavailable else chosen

    def options(self, model: str) -> dict[str, Any]:
        effort = os.getenv("AUTOPILOT_REASONING_EFFORT", "").strip().lower()
        if effort in {"minimal", "low", "medium", "high"} and reasoning_model(model):
            return {"reasoning_effort": effort}
        return {}

    def effort(self, model: str, default: str = "medium") -> str | None:
        """Reasoning effort for a Copilot SDK session: AUTOPILOT_REASONING_EFFORT, else the caller's default."""
        if not reasoning_model(model):
            return None
        configured = os.getenv("AUTOPILOT_REASONING_EFFORT", "").strip().lower()
        return configured if configured in {"low", "medium", "high"} else default

    def describe(self) -> dict[str, Any]:
        return {"default": self.default, "tiers": {tier: self.model(tier) for tier in TIERS},
                "unavailable": sorted(self.unavailable)}


def reasoning_model(model: str) -> bool:
    return re.match(r"(?:gpt-5|o\d)", (model or "").lower()) is not None


def model_unavailable(error: BaseException) -> bool:
    status = getattr(error, "status_code", None)
    text = str(error)
    return status == 404 or "DeploymentNotFound" in text or "does not exist" in text


async def run_script(package: SkillPackage, script: Any, args: Any, workspace: Workspace, *,
                     timeout: float = 60.0, stdin: bytes | None = None, collect: bool = True) -> dict[str, Any]:
    """Run one bundled script on a copy of the workspace; files it creates or changes come back.

    The child gets an isolated interpreter (-I -S: no site-packages, no user or PYTHON* settings), a
    minimal environment without managed-identity or other credentials, a scratch directory and a
    time limit. Only scripts shipped inside the skill package can run.
    """
    path = package.script(script)
    if (type(args) is not list or len(args) > 16
            or any(type(item) is not str or len(item) > 500 or any(ch in item for ch in "\x00\r\n") for item in args)):
        raise ValueError("args must be up to 16 single-line strings.")
    result = await _run_isolated(lambda scratch: [sys.executable, "-I", "-S", "-X", "utf8", str(path), *args],
                                 workspace, source=f"script:{path.name}", timeout=timeout, stdin=stdin,
                                 collect=collect, skill_dir=str(package.root))
    return {"script": path.name, "args": args, **result}


async def run_code(code: str, workspace: Workspace, *, timeout: float = 30.0) -> dict[str, Any]:
    """Run model-written Python in the code sandbox on a copy of the workspace; new or changed files come back."""
    from .code_sandbox import bootstrap_source

    if not isinstance(code, str) or not code.strip() or "\x00" in code:
        raise ValueError("code must be a non-empty Python program.")
    seconds = max(1, min(int(timeout), 120))

    def command(scratch: Path) -> list[str]:
        program, bootstrap = scratch / "program.py", scratch / "sandbox_bootstrap.py"
        program.write_text(code, encoding="utf-8")
        bootstrap.write_text(bootstrap_source(), encoding="utf-8")
        return [sys.executable, "-I", "-S", "-B", "-X", "utf8", str(bootstrap), str(program), str(seconds)]

    return await _run_isolated(command, workspace, source="code:model", timeout=seconds + 5)


async def _run_isolated(command: Any, workspace: Workspace, *, source: str, timeout: float,
                        stdin: bytes | None = None, collect: bool = True, skill_dir: str = "") -> dict[str, Any]:
    started = time.monotonic()
    scratch = Path(tempfile.mkdtemp(prefix="skill-run-"))
    try:
        work = scratch / "work"
        work.mkdir()
        before: dict[str, str] = {}
        for relative, data in workspace.snapshot().items():
            target = work.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            before[relative] = hashlib.sha256(data).hexdigest()
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1", "LANG": "C.UTF-8", "WORKSPACE": str(work),
            "TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch),
        }
        if skill_dir:
            environment["SKILL_DIR"] = skill_dir
        if os.name == "nt":
            environment["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        process = await asyncio.create_subprocess_exec(
            *command(scratch), cwd=str(work), env=environment,
            stdin=asyncio.subprocess.DEVNULL if stdin is None else asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(stdin), timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        written: list[str] = []
        skipped: list[str] = []
        for directory, folders, names in (os.walk(work, followlinks=False) if collect else ()):
            folders[:] = [name for name in folders if not os.path.islink(os.path.join(directory, name))]
            for name in sorted(names):
                full = Path(directory) / name
                relative = full.relative_to(work).as_posix()
                if full.is_symlink() or not full.is_file() or "__pycache__" in relative:
                    continue
                if len(written) + len(skipped) >= 64:
                    skipped.append(relative)
                    continue
                try:
                    relative = Workspace.normalize(relative)
                    if full.stat().st_size > Workspace.MAX_FILE_BYTES:
                        raise ValueError("too large")
                    data = full.read_bytes()
                    if before.get(relative) == hashlib.sha256(data).hexdigest():
                        continue
                    workspace.write(relative, data, source=source)
                    written.append(relative)
                except (OSError, ValueError):
                    skipped.append(relative)
        return {
            "exitCode": process.returncode,
            "durationMs": int((time.monotonic() - started) * 1000),
            "stdout": _bounded(stdout.decode("utf-8", errors="replace"), 12_000),
            "stderr": _bounded(stderr.decode("utf-8", errors="replace"), 3_000, tail=True),
            "files": written, "skipped": skipped[:20],
        }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _bounded(text: str, limit: int, *, tail: bool = False) -> str:
    if len(text) <= limit:
        return text
    return "…" + text[-limit:] if tail else text[:limit] + "…(output shortened)"


async def check_autonomy(session: SkillSession, server: str, tool: str, args: dict[str, Any]) -> tuple[bool, str]:
    """Run the skill's deterministic policy check for one pre-approved action; any failure declines it."""
    script = session.package.metadata.get("autonomy-check", "")
    if not script:
        return True, "Pre-approved for this skill."
    payload = json.dumps({"action": {"server": server, "tool": tool, "args": args}, "used": session.used},
                         default=str).encode("utf-8")
    try:
        result = await run_script(session.package, script, [], session.workspace, timeout=20.0,
                                  stdin=payload, collect=False)
        lines = result["stdout"].strip().splitlines()
        verdict = json.loads(lines[-1]) if result["exitCode"] == 0 and lines else None
    except (OSError, ValueError, asyncio.TimeoutError):
        verdict = None
    if type(verdict) is not dict or type(verdict.get("allow")) is not bool:
        return False, "The skill's policy check did not return a verdict, so a person decides."
    reason = verdict.get("reason")
    return verdict["allow"], (reason if isinstance(reason, str) else "")[:300]
