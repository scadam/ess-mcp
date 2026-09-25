[CmdletBinding()]
param(
  [string] $App = 'ca-autopilot-caldova-78f0',
  [string] $Revision = '',
  [int] $Minutes = 30,
  [int] $Take = 120
)
# Reads the app's console logs from Log Analytics as ASCII-safe text. az.cmd runs
# Python in isolated mode, so `containerapp logs show` fails on non-cp1252 output.
$ErrorActionPreference = 'Stop'
$ws = az monitor log-analytics workspace show -g essmcp-caldova-rg -n log-essmcp-caldova-f61b --query customerId -o tsv
$filter = "ContainerAppName == '$App'"
if ($Revision) { $filter += " and RevisionName endswith '$Revision'" }
$query = "ContainerAppConsoleLogs | where TimeGenerated > ago(${Minutes}m) and $filter | project TimeGenerated, RevisionName, Log | order by TimeGenerated desc | take $Take"
$body = New-TemporaryFile
$out = New-TemporaryFile
try {
  @{ query = $query } | ConvertTo-Json -Compress | Set-Content $body -Encoding utf8NoBOM
  az rest --method POST --url "https://api.loganalytics.io/v1/workspaces/$ws/query" --resource 'https://api.loganalytics.io' --headers 'Content-Type=application/json' --body "@$body" --output-file $out | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Log Analytics query failed.' }
  $result = Get-Content $out -Raw -Encoding utf8 | ConvertFrom-Json
  $rows = @($result.tables[0].rows)
  [array]::Reverse($rows)
  foreach ($row in $rows) { '{0} [{1}] {2}' -f $row[0], ($row[1] -replace '^.*--', ''), ($row[2] -replace '[^\x20-\x7E]', '?') }
} finally {
  Remove-Item $body, $out -ErrorAction SilentlyContinue
}
