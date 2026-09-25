$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$env:PYTHONIOENCODING = 'utf-8'
$runs = az acr task list-runs -r cressmcpcaldovaf61b --top 8 --query "[].{id:runId, status:status, created:createTime, image:outputImages[0].tag}" -o json | ConvertFrom-Json
$runs | ForEach-Object { "{0} {1} {2} {3}" -f $_.id, $_.status, $_.created, $_.image }
$ok = $runs | Where-Object { $_.status -eq 'Succeeded' -and $_.image -like 'v0923*' } | Select-Object -First 1
if ($ok) {
  az acr task logs -r cressmcpcaldovaf61b --run-id $ok.id *> "$env:TEMP\ap-buildlog-ok.txt"
  "--- last good run $($ok.id) ($($ok.image))"
  Get-Content "$env:TEMP\ap-buildlog-ok.txt" | Select-String -Pattern 'Digest:|microsoft.agents.hosting.aiohttp|Successfully installed' |
    Select-Object -First 6 | ForEach-Object { $_.Line.Substring(0, [Math]::Min(200, $_.Line.Length)) }
}
