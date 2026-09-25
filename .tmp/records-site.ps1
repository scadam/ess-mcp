$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# One-time: a private Microsoft 365 group whose document library holds the colleagues' run records. Idempotent.
$graph = 'https://graph.microsoft.com/v1.0'
$nickname = 'autopilot-records'
$owner = '3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d'
$agents = @('f84f67e1-2e3d-4fe6-a2f8-01191bd74c5c', 'f9f7881a-c4c4-4dad-b9e6-b8b36bf4f2a2', '56bb6152-37b9-4eed-be0d-dbe5b906dad6')
$existing = az rest --method get --url "$graph/groups" --url-parameters "`$filter=mailNickname eq '$nickname'" "`$select=id,displayName" --query "value[0].id" -o tsv
if ($existing) { $groupId = $existing; "group exists: $groupId" }
else {
  $body = @{
    displayName = 'Group Functions Autopilot Records'
    description = 'Files and run records produced by the Group Functions Autopilot colleagues: the audit trail of what each run created.'
    groupTypes = @('Unified'); mailEnabled = $true; mailNickname = $nickname; securityEnabled = $false; visibility = 'Private'
    resourceBehaviorOptions = @('WelcomeEmailDisabled', 'HideGroupInOutlook')
    'owners@odata.bind' = @("$graph/users/$owner")
    'members@odata.bind' = @(@($owner) + $agents | ForEach-Object { "$graph/users/$_" })
  } | ConvertTo-Json -Depth 5
  $file = Join-Path $env:TEMP 'records-group.json'
  Set-Content -Path $file -Value $body -Encoding utf8
  $groupId = az rest --method post --url "$graph/groups" --headers 'Content-Type=application/json' --body "@$file" --query id -o tsv
  Remove-Item $file -Force
  if (-not $groupId) { throw 'Group creation failed.' }
  "group created: $groupId"
}
foreach ($member in @($owner) + $agents) {
  $body = @{ '@odata.id' = "$graph/directoryObjects/$member" } | ConvertTo-Json -Compress
  $file = Join-Path $env:TEMP 'records-member.json'
  Set-Content -Path $file -Value $body -Encoding utf8
  az rest --method post --url "$graph/groups/$groupId/members/`$ref" --headers 'Content-Type=application/json' --body "@$file" 2>$null | Out-Null
  Remove-Item $file -Force
}
foreach ($i in 1..30) {
  $drive = az rest --method get --url "$graph/groups/$groupId/drive" --url-parameters '$select=id,webUrl,driveType' -o json 2>$null | ConvertFrom-Json
  if ($drive.id) { break }
  Start-Sleep -Seconds 10
}
if (-not $drive.id) { throw 'The group site is still provisioning; re-run in a few minutes.' }
"driveId=$($drive.id)"
"webUrl=$($drive.webUrl)"
@{ groupId = $groupId; driveId = $drive.id; webUrl = $drive.webUrl } | ConvertTo-Json | Set-Content .tmp\records-drive.json
exit 0
