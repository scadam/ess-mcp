import re
from pathlib import Path

data = Path(__file__).with_name("acs").joinpath("unpacked", "agent_control_specification", "_native.abi3.so").read_bytes()
for pattern in [rb"[ -~]{0,50}0\.3\.[0-9][ -~]{0,50}", rb"[ -~]{0,80}agent_control_specification_version[ -~]{0,80}",
                rb"[ -~]{0,60}cedar[ -~]{0,60}", rb"[ -~]{0,60}policy_set[ -~]{0,60}"]:
    hits = sorted({m.decode(errors="replace") for m in re.findall(pattern, data)})
    print(pattern[:40], len(hits))
    for hit in hits[:25]:
        print("   ", hit)
