param([int] $Minutes = 240, [string] $Pattern = 'compliance\.|bot\.in|bot\.rejected|emailNotification|SDK turn failed|Traceback|Error')
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$env:PYTHONIOENCODING = 'utf-8'
$ws = az monitor log-analytics workspace show -g essmcp-caldova-rg -n log-essmcp-caldova-f61b --query customerId -o tsv
$query = "ContainerAppConsoleLogs | where TimeGenerated > ago(${Minutes}m) and ContainerAppName == 'ca-autopilot-caldova-78f0' and (Log has 'compliance.' or Log has 'bot.in' or Log has 'bot.rejected' or Log has 'SDK turn failed' or Log has 'email') | project TimeGenerated, RevisionName, Log | order by TimeGenerated asc | take 300"
$body = New-TemporaryFile; $out = New-TemporaryFile
try {
  @{ query = $query } | ConvertTo-Json -Compress | Set-Content $body -Encoding utf8NoBOM
  az rest --method POST --url "https://api.loganalytics.io/v1/workspaces/$ws/query" --resource 'https://api.loganalytics.io' --headers 'Content-Type=application/json' --body "@$body" --output-file $out | Out-Null
  $rows = @((Get-Content $out -Raw -Encoding utf8 | ConvertFrom-Json).tables[0].rows)
  $rows | ForEach-Object { $l = ('{0} [{1}] {2}' -f $_[0], ($_[1] -replace '^.*--', ''), ($_[2] -replace '[^\x20-\x7E]', '?')) -replace '(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-\.]+)', '<jwt>'; $l.Substring(0, [Math]::Min(300, $l.Length)) } |
    Where-Object { $_ -notmatch 'healthz' } | Out-File "$env:TEMP\ap-email-logs.txt" -Encoding utf8
  "rows=$($rows.Count)"
} finally { Remove-Item $body, $out -ErrorAction SilentlyContinue }
