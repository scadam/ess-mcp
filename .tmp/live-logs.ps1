param([int] $Tail = 300, [string] $Pattern = 'POST /api/messages|bot\.|SDK|Replying|compliance\.')
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$raw = az containerapp logs show -n ca-autopilot-caldova-78f0 -g essmcp-caldova-rg --type console --tail $Tail --format json 2>$null
$lines = foreach ($line in $raw) {
  try { $o = $line | ConvertFrom-Json } catch { continue }
  "{0} {1}" -f $o.TimeStamp, $o.Log
}
"live lines: $(@($lines).Count)  now UTC: $([DateTime]::UtcNow.ToString('HH:mm:ss'))"
$lines | Where-Object { $_ -match $Pattern } | ForEach-Object { $_.Substring(0, [Math]::Min(220, $_.Length)) }
