import re
from pathlib import Path

data = Path(__file__).with_name("acs").joinpath("unpacked", "agent_control_specification", "_native.abi3.so").read_bytes()
for key in ["regorus", "opa eval", "opa", "cedar", "cedar_policy", "OPA_PATH", "opa_path", "bundle", "rego.v1", "wasm"]:
    print(f"{key!r}: {data.count(key.encode())}")
names = sorted({m.decode() for m in re.findall(rb"(?:ACS|AGT|OPA)_[A-Z0-9_]{2,40}", data)})
print("env-like:", names[:60])
hits = sorted({m.decode(errors="replace") for m in re.findall(rb"[ -~]{0,60}opa[ -~]{0,60}", data) if b"opa" in m.lower()})
for hit in hits[:40]:
    print("  ", hit)
