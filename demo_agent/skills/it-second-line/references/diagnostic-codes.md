# Reading device diagnostic reports

## Battery (Windows battery report, `powercfg /batteryreport`)
- **Design capacity** vs **Full charge capacity**: health = full / design. Below 60% is a failed battery; 60–79%
  is worn (replace at next refresh); 80%+ is healthy.
- **Cycle count** above 800 on a laptop battery is end of life.
- Sudden shutdowns on battery with health below 60% confirm battery failure.

## Storage (SMART)
- **Reallocated sectors count** > 0 and rising, **Current pending sector** > 0, or **Uncorrectable sector count**
  > 0: the disk is failing. Back up immediately; replace the disk (or the device if out of warranty).
- **Percentage used** (NVMe wear) above 90%: plan replacement.

## Memory
- Dell ePSA error codes **2000-0122** to **2000-0126**: memory failure. Windows Memory Diagnostic "hardware
  problems were detected": memory failure.

## Thermal and fan
- Dell ePSA **2000-0511** / **2000-0512** (fan) or CPU temperature above 95°C under light load: thermal fault;
  fan or heatsink service.

## Display
- Dell ePSA **2000-0141** / LCD built-in test failing, or lines on the screen in the BIOS: display panel fault.

## Severity
- **Critical**: data loss risk (failing disk) or the device cannot be used (fails to boot, shuts down).
- **Major**: the device works with a workaround (on mains only, external monitor).
- **Minor**: cosmetic or degraded.
