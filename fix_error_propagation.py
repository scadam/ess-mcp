"""Transform MCP server tool files to propagate httpx.HTTPStatusError.

For each `except Exception` block at tool-function level that returns an
error dict, insert `except httpx.HTTPStatusError: raise` before it so
that HTTP errors (especially 401/403) reach the MCP client as ToolError
responses, enabling token refresh flows.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(r"c:\Users\scadam\AgentsToolkitProjects\ess-mcp\mcp_servers\src\mcp_servers")

FILES = [
    ROOT / "workday" / "tools.py",
    ROOT / "servicenow" / "tools.py",
    ROOT / "salesforce" / "tools.py",
    ROOT / "jira" / "tools.py",
]

# Regex: captures leading whitespace + except Exception (with optional `as varname`)
EXCEPT_RE = re.compile(r"^(\s+)(except\s+Exception(?:\s+as\s+\w+)?\s*:.*)$")


def should_modify(lines, idx):
    """Decide whether an except-Exception block should propagate HTTP errors.

    Returns True for tool-level handlers that return error dicts.
    Returns False for:
      - `pass` blocks (graceful degradation)
      - inner parsing blocks that don't return error dicts
    """
    # Look ahead 8 lines
    window = lines[idx + 1 : idx + 9]
    text = "\n".join(window)

    # Skip if the first non-empty statement is `pass`
    for line in window:
        s = line.strip()
        if s and not s.startswith("#"):
            if s == "pass":
                return False
            break

    # Must have a return statement in the window
    has_return = any("return" in l for l in window)
    if not has_return:
        return False

    # Must reference error-like patterns
    error_keywords = ["error", "Error", "False", "failed", "Failed"]
    has_error = any(kw in text for kw in error_keywords)
    return has_error


def transform_file(path):
    """Add `except httpx.HTTPStatusError: raise` to tool-level except blocks."""
    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")

    has_httpx_import = any(
        re.match(r"^import\s+httpx\b", line) for line in lines
    )

    # Collect insertion points (line indices where we insert BEFORE)
    insertions = []  # list of (line_index, indent_string)

    for i, line in enumerate(lines):
        m = EXCEPT_RE.match(line)
        if m and should_modify(lines, i):
            indent = m.group(1)
            insertions.append((i, indent))

    if not insertions:
        print(f"  {path.name}: 0 changes")
        return 0

    # Apply in reverse so indices stay valid
    for line_idx, indent in reversed(insertions):
        lines.insert(line_idx, f"{indent}    raise")
        lines.insert(line_idx, f"{indent}except httpx.HTTPStatusError:")

    # Add `import httpx` if not present
    if not has_httpx_import:
        last_import_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and not stripped.startswith(
                "#"
            ):
                last_import_idx = i
        lines.insert(last_import_idx + 1, "import httpx")

    new_content = "\n".join(lines)
    path.write_text(new_content, encoding="utf-8")

    # Validate syntax
    try:
        ast.parse(new_content)
        print(f"  {path.name}: {len(insertions)} except blocks modified ✓")
    except SyntaxError as e:
        print(f"  {path.name}: {len(insertions)} changes BUT SYNTAX ERROR: {e}")
        return -1

    return len(insertions)


def main():
    total = 0
    errors = 0
    for f in FILES:
        n = transform_file(f)
        if n < 0:
            errors += 1
        else:
            total += n

    print(f"\nTotal: {total} except blocks modified across {len(FILES)} files")
    if errors:
        print(f"WARNING: {errors} file(s) had syntax errors!")
        sys.exit(1)
    else:
        print("All files pass syntax validation.")


if __name__ == "__main__":
    main()
