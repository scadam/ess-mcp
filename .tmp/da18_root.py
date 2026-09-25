import json
import os
from pathlib import Path

root = next(Path(os.environ["LOCALAPPDATA"], "npm-cache", "_npx").glob("*/node_modules/@microsoft/m365agentstoolkit-cli"))
out = open(Path(os.environ["TEMP"]) / "ap-da18-root.txt", "w", encoding="utf-8")
for version in ("v1.8",):
    schema = json.loads((root / "json-schemas/copilot/declarative-agent" / version / "schema.json").read_text(encoding="utf-8"))
    out.write(f"{version} propertyNames={json.dumps(schema.get('propertyNames'))}\n")
    out.write(f"{version} additionalProperties={schema.get('additionalProperties')} required={schema.get('required')}\n")
    out.write(f"{version} version enum={json.dumps(schema.get('properties', {}).get('version'))}\n")
out.close()
