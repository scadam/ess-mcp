"""Fix early-return error patterns in MCP tool functions.

Finds patterns where `resp.is_error` or `not resp.is_success` checks
return error dicts directly (bypassing except blocks), and replaces the
`return` statement with `resp.raise_for_status()` so the HTTP error
propagates through the except handlers.
"""

import ast
import re
from pathlib import Path

ROOT = Path(r"c:\Users\scadam\AgentsToolkitProjects\ess-mcp\mcp_servers\src\mcp_servers")

FILES = [
    ROOT / "workday" / "tools.py",
    ROOT / "servicenow" / "tools.py",
]

# Match `if resp.is_error:` or `if not resp.is_success:` or `if response.is_error:` etc.
GUARD_RE = re.compile(
    r"^\s+if\s+(?:not\s+)?(resp|response|cat_resp)\.(is_error|is_success)\s*:"
)


def process_file(path):
    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")
    changes = 0

    i = 0
    while i < len(lines):
        m = GUARD_RE.match(lines[i])
        if m:
            var_name = m.group(1)  # resp or response
            check = m.group(2)  # is_error or is_success
            guard_line = i

            # Scan forward for return statement within this if block
            # The return should be at a deeper indent than the if
            if_indent = len(lines[i]) - len(lines[i].lstrip())
            body_indent = if_indent + 4  # minimum expected body indent

            # Find the return statement
            j = i + 1
            return_line = None
            while j < min(i + 20, len(lines)):
                sj = lines[j].strip()
                line_indent = len(lines[j]) - len(lines[j].lstrip())

                # Still inside the if block?
                if sj and line_indent <= if_indent:
                    break

                # Is this a return with error dict?
                if line_indent >= body_indent and sj.startswith("return"):
                    # Check if it returns an error dict
                    rest = sj[6:].strip()
                    if (
                        rest.startswith("{")
                        and ("False" in rest or '"error"' in rest or "'error'" in rest)
                    ) or rest == "{}":
                        return_line = j
                    break
                j += 1

            if return_line is not None:
                # Check this isn't already followed by raise_for_status
                # on the very next line
                already_raises = False
                for k in range(guard_line + 1, return_line):
                    if "raise_for_status()" in lines[k]:
                        already_raises = True
                        break

                if not already_raises:
                    ret_indent_str = " " * (
                        len(lines[return_line]) - len(lines[return_line].lstrip())
                    )
                    lines[return_line] = (
                        f"{ret_indent_str}{var_name}.raise_for_status()"
                    )
                    changes += 1
                    print(
                        f"  Line {return_line + 1}: return → "
                        f"{var_name}.raise_for_status()"
                    )

        i += 1

    if changes:
        new_content = "\n".join(lines)
        try:
            ast.parse(new_content)
            path.write_text(new_content, encoding="utf-8")
            print(f"  {path.name}: {changes} early returns fixed ✓")
        except SyntaxError as e:
            print(f"  {path.name}: SYNTAX ERROR after {changes} changes: {e}")
            return -1
    else:
        print(f"  {path.name}: 0 early returns to fix")

    return changes


total = 0
for f in FILES:
    print(f"\n{f.name}:")
    n = process_file(f)
    if n and n > 0:
        total += n

print(f"\nTotal: {total} early returns fixed")
