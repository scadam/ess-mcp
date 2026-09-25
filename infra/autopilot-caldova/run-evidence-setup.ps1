[CmdletBinding()]
param(
  [string] $ResourceGroup = 'essmcp-caldova-rg',
  [string] $Location = 'eastus2',
  [string] $Environment = 'cae-essmcp-caldova-f61b2',
  [string] $Registry = 'cressmcpcaldovaf61b',
  [string] $PullIdentity = 'id-autopilot-caldova-78f0'
)
# Provisions the demo evidence list without keys or user sign-in: a TEMPORARY
# managed identity with only Graph Sites.Manage.All runs a one-shot Container Apps
# job, then the job, its role assignment and the identity are always deleted.
$ErrorActionPreference = 'Stop'
$tempName = 'id-autopilot-evidence-setup'
$jobName = 'job-autopilot-evidence'
$tag = 'v' + (Get-Date -Format 'MMddHHmm')
$body = New-TemporaryFile
$assignmentId = $null
$temp = $null

function Invoke-Az { $out = & az @args; if ($LASTEXITCODE -ne 0) { throw "az $($args[0..2] -join ' ') failed." }; $out }

try {
  $pull = Invoke-Az identity show -g $ResourceGroup -n $PullIdentity --query id -o tsv
  $temp = Invoke-Az identity create -g $ResourceGroup -n $tempName -l $Location --query '{id:id, clientId:clientId, principalId:principalId}' -o json | ConvertFrom-Json
  $graph = Invoke-Az ad sp show --id 00000003-0000-0000-c000-000000000000 -o json | ConvertFrom-Json
  $role = @($graph.appRoles | Where-Object { $_.value -eq 'Sites.Manage.All' -and $_.allowedMemberTypes -contains 'Application' })[0]
  if (-not $role) { throw 'Graph Sites.Manage.All application role was not found.' }
  @{ principalId = $temp.principalId; resourceId = $graph.id; appRoleId = $role.id } | ConvertTo-Json | Set-Content $body -Encoding utf8NoBOM
  # A new identity's service principal takes a short time to replicate in Entra.
  foreach ($i in 1..18) {
    $assignment = az rest --method POST --url "https://graph.microsoft.com/v1.0/servicePrincipals/$($temp.principalId)/appRoleAssignments" --headers 'Content-Type=application/json' --body "@$body" 2>$null | Out-String
    if ($LASTEXITCODE -eq 0) { $assignmentId = ($assignment | ConvertFrom-Json).id; break }
    Start-Sleep -Seconds 10
  }
  if (-not $assignmentId) { throw 'The temporary identity could not be granted Sites.Manage.All.' }

  Push-Location (Join-Path $PSScriptRoot 'evidence-setup')
  try {
    $build = Invoke-Az acr build -r $Registry -t "autopilot-evidence-setup:$tag" -f Dockerfile . --no-logs --query '{status:status, digest:outputImages[0].digest}' -o json | ConvertFrom-Json
  } finally { Pop-Location }
  if ($build.status -ne 'Succeeded') { throw 'The evidence setup image build failed.' }
  $image = "$Registry.azurecr.io/autopilot-evidence-setup@$($build.digest)"

  Start-Sleep -Seconds 60  # Allow the new application permission to reach token issuance.
  Invoke-Az containerapp job create -g $ResourceGroup -n $jobName --environment $Environment --trigger-type Manual `
    --replica-timeout 600 --replica-retry-limit 0 --parallelism 1 --replica-completion-count 1 `
    --image $image --registry-server "$Registry.azurecr.io" --registry-identity $pull `
    --mi-user-assigned $pull $temp.id --env-vars "AZURE_CLIENT_ID=$($temp.clientId)" --cpu 0.5 --memory 1Gi -o none
  $execution = Invoke-Az containerapp job start -g $ResourceGroup -n $jobName --query name -o tsv
  $status = ''
  foreach ($i in 1..60) {
    Start-Sleep -Seconds 10
    $status = Invoke-Az containerapp job execution show -g $ResourceGroup -n $jobName --job-execution-name $execution --query properties.status -o tsv
    if ($status -in 'Succeeded', 'Failed', 'Stopped', 'Degraded') { break }
  }
  "Job execution $execution finished with status '$status'."
} finally {
  if (az containerapp job show -g $ResourceGroup -n $jobName --query name -o tsv 2>$null) { az containerapp job delete -g $ResourceGroup -n $jobName --yes -o none }
  if ($assignmentId -and $temp) { az rest --method DELETE --url "https://graph.microsoft.com/v1.0/servicePrincipals/$($temp.principalId)/appRoleAssignments/$assignmentId" -o none }
  if ($temp) { az identity delete -g $ResourceGroup -n $tempName -o none }
  Remove-Item $body -ErrorAction SilentlyContinue
  "Temporary job, role assignment and identity removed."
}
