$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$tok = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $tok" }
$runs = Invoke-RestMethod "$base/api/runs" -Headers $h -TimeoutSec 30
$list = if ($runs.runs) { $runs.runs } else { $runs }
$run = @($list) | Where-Object { $_.title -like 'Zero-Touch Service Desk*' } | Sort-Object { $_.startedAt } -Descending | Select-Object -First 1
"run=$($run.id) status=$($run.status) artifacts=$(@($run.artifacts).Count)"
foreach ($p in 'reports/queue.csv', 'reports/service-desk-report.md', 'reports/proposed-actions.md') {
  $out = Join-Path $env:TEMP ('ap-' + ($p -replace '[/\\]', '-'))
  try {
    Invoke-WebRequest "$base/api/runs/$($run.id)/artifact?path=$p" -Headers $h -OutFile $out -TimeoutSec 30 -UseBasicParsing
    "saved $p -> $out"
  } catch { "missing $p : $($_.Exception.Message)" }
}
$tok = $null
exit 0
