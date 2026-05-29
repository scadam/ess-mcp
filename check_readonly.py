"""Check which MCP tool specs are missing readOnlyHint: True.

Scans all mcp_servers/src/mcp_servers/**/tools.py files and reports each
tool spec's read-only annotation status.
"""

import ast
from pathlib import Path

ROOT = Path(r"c:\Users\scadam\AgentsToolkitProjects\ess-mcp\mcp_servers\src\mcp_servers")


def iter_tool_files():
    for path in sorted(ROOT.glob("*/tools.py")):
        if path.is_file():
            yield path


def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def check_file(path: Path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    missing = []
    ok = []

    for node in ast.walk(tree):
        spec_list = None

        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id.endswith("_TOOL_SPECS") for t in node.targets):
                spec_list = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id.endswith("_TOOL_SPECS"):
                spec_list = node.value

        if not isinstance(spec_list, ast.List):
            continue

        for elt in spec_list.elts:
            if not isinstance(elt, ast.Dict):
                continue

            name = None
            read_only = False
            for k, v in zip(elt.keys, elt.values):
                key = _literal(k)
                if key == "name":
                    name = _literal(v)
                elif key == "annotations":
                    ann = _literal(v)
                    if isinstance(ann, dict) and ann.get("readOnlyHint") is True:
                        read_only = True

            if isinstance(name, str):
                row = (name, getattr(elt, "lineno", 0))
                if read_only:
                    ok.append(row)
                else:
                    missing.append(row)

    return ok, missing


def main():
    total_ok = 0
    total_missing = 0

    for file_path in iter_tool_files():
        ok, missing = check_file(file_path)
        rel = file_path.relative_to(ROOT)

        print(f"\n{rel}:")
        print(f"  WITH readOnlyHint: {len(ok)}")
        print(f"  MISSING readOnlyHint: {len(missing)}")
        for name, line in missing:
            print(f"    MISSING: {name} (line {line})")

        total_ok += len(ok)
        total_missing += len(missing)

    print(f"\nTotal WITH readOnlyHint: {total_ok}")
    print(f"Total MISSING readOnlyHint: {total_missing}")


if __name__ == "__main__":
    main()
