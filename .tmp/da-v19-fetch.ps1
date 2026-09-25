$ErrorActionPreference = 'Continue'
$out = Join-Path $env:TEMP 'da-v19-schema.json'
try {
  Invoke-WebRequest 'https://developer.microsoft.com/json-schemas/copilot/declarative-agent/v1.9/schema.json' -OutFile $out -UseBasicParsing -TimeoutSec 60
  "schema saved: $((Get-Item $out).Length) bytes"
} catch { "schema fetch failed: $($_.Exception.Message)" }
"npm latest cli:"
npm view @microsoft/m365agentstoolkit-cli version 2>&1 | Select-Object -Last 3
"npm cli versions (last 8):"
npm view @microsoft/m365agentstoolkit-cli versions --json 2>&1 | ConvertFrom-Json | Select-Object -Last 8
exit 0
