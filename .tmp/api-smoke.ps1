param([string] $Skill = 'procurement-month-end-close', [string] $Prompt = 'Close the IT hardware procurement month end. This is a dry run: change nothing.')
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$token = az account get-access-token --scope 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user' --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token" }
$guard = Invoke-RestMethod "$base/api/guardrails" -Headers $headers
"guardrails: mode=$($guard.mode) available=$($guard.engine.available) acs=$($guard.engine.acsVersion) opa=$($guard.engine.opaVersion) policy=v$($guard.active.version) error='$($guard.engine.error)'"
"policy has model matcher fix: $([bool]($guard.active.rego -match 'matches_model'))"
$tools = Invoke-RestMethod "$base/api/tools" -Headers $headers
foreach ($server in $tools.servers) { "tools: $($server.name) connected=$($server.connected) count=$($server.tools.Count)" }
$body = @{ prompt = $Prompt; skill = $Skill; dryRun = $true; title = 'Copilot SDK smoke (dry run)' } | ConvertTo-Json
$started = Get-Date
$response = Invoke-WebRequest "$base/api/run" -Method Post -Headers $headers -ContentType 'application/json' -Body $body -UseBasicParsing -TimeoutSec 1500
$out = Join-Path $PSScriptRoot 'api-smoke.sse.txt'
[IO.File]::WriteAllText($out, $response.Content, [Text.Encoding]::UTF8)
"status=$($response.StatusCode) seconds=$([int]((Get-Date) - $started).TotalSeconds)"
$events = [regex]::Matches($response.Content, '(?m)^event: (\S+)') | ForEach-Object { $_.Groups[1].Value }
$events | Group-Object | Sort-Object Count -Descending | ForEach-Object { "event $($_.Name) x$($_.Count)" }
$result = [regex]::Match($response.Content, '(?m)^event: result\r?\ndata: (.+)$')
if ($result.Success) { $text = ($result.Groups[1].Value | ConvertFrom-Json).content; "result: " + $text.Substring(0, [Math]::Min(700, $text.Length)) }
$stats = [regex]::Match($response.Content, '(?m)^event: stats\r?\ndata: (.+)$')
if ($stats.Success) { $s = $stats.Groups[1].Value | ConvertFrom-Json; "stats: harness=$($s.harness) turns=$($s.turns) tool_calls=$($s.tool_calls) tokens=$($s.total_tokens) models=$(($s.models.PSObject.Properties.Name) -join ',')" }
$errors = [regex]::Matches($response.Content, '(?m)^event: error\r?\ndata: (.+)$') | ForEach-Object { $_.Groups[1].Value }
if ($errors) { "errors: $($errors -join ' | ')" }
