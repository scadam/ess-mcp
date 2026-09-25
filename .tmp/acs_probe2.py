import re
from pathlib import Path

data = Path(__file__).with_name("acs").joinpath("unpacked", "agent_control_specification", "_native.abi3.so").read_bytes()
for key in ["envelope", "Agent::", "Tool::", "PolicyTarget", "advice", "policy_set", "policy_path", "entities_path",
            "schema_path", "principal", "0.4.0-alpha", "0.3.", "agent_control_specification_version", "warnings",
            "liftable", "approval"]:
    print(f"{key!r}: {data.count(key.encode())}")
for pattern in [rb"[ -~]{0,80}advice[ -~]{0,80}", rb"[ -~]{0,60}envelope[ -~]{0,80}", rb"[ -~]{0,40}0\.4\.0-alpha[ -~]{0,40}",
                rb"[ -~]{0,60}PolicyTarget[ -~]{0,60}", rb"[ -~]{0,60}Agent::[ -~]{0,60}"]:
    hits = sorted({m.decode(errors="replace") for m in re.findall(pattern, data)})
    print(pattern[:30], len(hits))
    for hit in hits[:12]:
        print("   ", hit)
