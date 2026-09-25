import inspect
import os

import microsoft_agents_a365.notifications as n

root = os.path.dirname(n.__file__)
for folder, _dirs, files in os.walk(root):
    for name in files:
        if not name.endswith(".py"):
            continue
        path = os.path.join(folder, name)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("from_property", "EmailReference", "sender", "email"):
            if needle in text:
                print("==", os.path.relpath(path, root), "has", needle)
                break
