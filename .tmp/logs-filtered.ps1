param([int] $Minutes = 60, [int] $Take = 150, [string] $Extra = '')
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$env:PYTHONIOENCODING = 'utf-8'
$ws = az monitor log-analytics workspace show -g essmcp-caldova-rg -n log-essmcp-caldova-f61b --query customerId -o tsv
$noise = "Log !has 'msi/token' and Log !has 'Request method' and Log !has 'Request headers' and Log !has 'X-IDENTITY-HEADER' and Log !has 'User-Agent' and Log !has 'No body was attached' and Log !has 'Response status' and Log !has 'Response headers' and Log !has 'Content-Type' and Log !has 'Date' and Log !has 'Server' and Log !has 'Transfer-Encoding' and Log !has 'X-CORRELATION-ID' and Log !has 'Unable to load the proper Managed Identity' and Log !has 'Code: None' and Log !has 'feed flush failed' and Log !has 'GET /healthz'"
$query = "ContainerAppConsoleLogs | where TimeGenerated > ago(${Minutes}m) and ContainerAppName == 'ca-autopilot-caldova-78f0' and $noise $Extra | project TimeGenerated, RevisionName, Log | order by TimeGenerated desc | take $Take"
$body = New-TemporaryFile
$out = New-TemporaryFile
try {
  @{ query = $query } | ConvertTo-Json -Compress | Set-Content $body -Encoding utf8NoBOM
  az rest --method POST --url "https://api.loganalytics.io/v1/workspaces/$ws/query" --resource 'https://api.loganalytics.io' --headers 'Content-Type=application/json' --body "@$body" --output-file $out | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Log Analytics query failed.' }
  $rows = @((Get-Content $out -Raw -Encoding utf8 | ConvertFrom-Json).tables[0].rows)
  [array]::Reverse($rows)
  foreach ($row in $rows) {
    $l = ('{0} [{1}] {2}' -f $row[0], ($row[1] -replace '^.*--', ''), ($row[2] -replace '[^\x20-\x7E]', '?')) -replace '(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-\.]+)', '<jwt>'
    $l.Substring(0, [Math]::Min(320, $l.Length))
  }
} finally { Remove-Item $body, $out -ErrorAction SilentlyContinue }
