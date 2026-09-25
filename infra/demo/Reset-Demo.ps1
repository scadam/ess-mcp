[CmdletBinding()]
param(
  # Leave Kian's battery incident and the Salesforce cases for later (raise them live instead).
  [switch] $NoSeed
)
# Puts the demo back to its starting line: Coupa's simulated data to its seed, a clean control room and case desk,
# last run's demo incidents and cases closed, the ServiceNow demo people restored, and fresh demo records raised so
# the colleagues start working them straight away. Takes about ten minutes.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Assert-DemoSubscription
$provision = Join-Path $PSScriptRoot 'Invoke-Provisioning.ps1'

# 1. Coupa keeps its simulated state in memory, so a restart returns the invoices to their seeded exceptions.
$coupa = 'essmcp-caldova-coupa'
$revision = az containerapp show -n $coupa -g $DemoResourceGroup --query properties.latestReadyRevisionName -o tsv
az containerapp revision restart -n $coupa -g $DemoResourceGroup --revision $revision -o none
if ($LASTEXITCODE -ne 0) { throw "Could not restart $coupa." }
Start-Sleep -Seconds 20
Wait-DemoApp $coupa | Out-Null
Write-Host '1/4 Coupa is back to its seeded invoices.'

# 2. Clears cases, runs, activity, chat memory and waiting approvals (approved skills stay); the desk restarts and
#    its first sweep, about 30 seconds later, finds the Coupa invoice exceptions on its own.
$token = Get-DemoOperatorToken
$result = Invoke-RestMethod -Method Post "$DemoHostUrl/api/control-room/reset" -Headers @{ Authorization = "Bearer $token" } `
  -ContentType 'application/json' -Body '{"confirm":"RESET"}' -TimeoutSec 180
$token = $null
Write-Host "2/4 Control room reset ($($result.removedRecords) stored records cleared)."

# 3. ServiceNow: close last run's demo incidents, restore the people, lock-out and devices, raise Kian's incident.
& $provision -System servicenow -Mode reset
& $provision -System servicenow -Mode setup
if (-not $NoSeed) { & $provision -System servicenow -Mode demo -Scenario battery }
Write-Host '3/4 ServiceNow ready.'

# 4. Salesforce: close last run's demo cases and raise fresh ones.
& $provision -System salesforce -Mode reset
if (-not $NoSeed) { & $provision -System salesforce -Mode demo }
Write-Host '4/4 Salesforce ready.'
Write-Host "`nWatch the colleagues pick the cases up: $DemoHostUrl/control-plane#/cases"
exit 0
