import asyncio
import json
import sys

sys.path.insert(0, r"C:\Users\scadam\AgentsToolkitProjects\ess-mcp")

from demo_agent.code_sandbox import analyse
from demo_agent.skill_runtime import Workspace, run_code

PROGRAMS = {
    "ok": "import json, statistics\nrows = json.load(open('data/coupa/list_invoices.json'))\n"
          "total = sum(r['amount'] for r in rows)\nopen('analysis/summary.json', 'w').write(json.dumps({'total': total}))\n"
          "print('total', total, statistics.mean(r['amount'] for r in rows))",
    "socket": "import socket\nprint(socket.gethostname())",
    "urllib": "import urllib.request\nurllib.request.urlopen('https://example.com')",
    "subprocess": "import os\nos.system('echo hi')",
    "read_outside": "print(open(r'C:\\Windows\\win.ini' if __import__('os').name == 'nt' else '/etc/passwd').read()[:40])",
    "write_outside": "open('../escape.txt', 'w').write('x')",
    "pathlib": "from pathlib import Path\nprint(sorted(p.name for p in Path('data').rglob('*.json')))",
    "gc": "import gc\nprint(len(gc.get_objects()))",
    "listdir_outside": "import os\nprint(os.listdir('..'))",
    "syntax": "def broken(:\n  pass",
}


async def main():
    for name, code in PROGRAMS.items():
        workspace = Workspace("t")
        workspace.write("data/coupa/list_invoices.json", json.dumps([{"amount": 10}, {"amount": 32.5}]), source="test")
        facts = analyse(code)
        result = await run_code(code, workspace, timeout=10)
        tail = (result["stderr"].strip().splitlines() or [""])[-1]
        print(f"{name:16} exit={result['exitCode']} files={result['files']} out={result['stdout'].strip()[:70]!r} err={tail[:110]!r}")
        print(f"{'':16} facts imports={facts['imports']} calls={facts['calls'][:6]} attrs={facts['attributes']} syntax={facts['syntax_ok']} {facts['error']}")


asyncio.run(main())
