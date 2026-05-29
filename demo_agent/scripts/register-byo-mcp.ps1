<#
.SYNOPSIS
  Register Workday / ServiceNow / Coupa MCP servers as Agent 365 BYO MCP.

.DESCRIPTION
  Walks the docs-recommended flow:
    a365 develop-mcp register-external-mcp-server -f <spec.json>
  for each of the three JSON spec files in this folder.

  Pipes 'y' to auto-confirm the "Proceed with registration?" prompt.
  Detects real failures by scanning output for 'ERROR:' / 'Failed' /
  'Registration cancelled' — the CLI returns exit code 0 even on failure.

  After registration completes, an IT admin must approve each request in:
    https://admin.cloud.microsoft → Agents → Tools → Requests
  and grant the Entra consent prompt that follows.

.PARAMETER OnlyKey
  Optionally process a single server (workday | servicenow | coupa).
#>
[CmdletBinding()]
param(
  [string]$TenantId = "8030d928-e557-4a4c-ae1e-95c1c4125eaa",
  [ValidateSet('workday','servicenow','coupa','')] [string]$OnlyKey = ''
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$specs = @(
  @{ key='workday';    name='ext_ESSWorkday';    file=(Join-Path $scriptDir 'byo-workday.json')    },
  @{ key='servicenow'; name='ext_ESSServiceNow'; file=(Join-Path $scriptDir 'byo-servicenow.json') },
  @{ key='coupa';      name='ext_ESSCoupa';      file=(Join-Path $scriptDir 'byo-coupa.json')      }
)
if ($OnlyKey) { $specs = $specs | Where-Object { $_.key -eq $OnlyKey } }

$version = a365 --version 2>&1 | Select-Object -Last 1
Write-Host "a365 CLI version: $version" -ForegroundColor DarkGray

$results = @()
foreach ($s in $specs) {
  if (-not (Test-Path $s.file)) { throw "Missing spec file: $($s.file)" }
  Write-Host ""
  Write-Host "=== Registering $($s.name) ===" -ForegroundColor Cyan
  Write-Host "Spec: $($s.file)" -ForegroundColor DarkGray

  # Pipe 'y' to bypass the y/N confirmation prompt.
  $output = 'y' | a365 develop-mcp register-external-mcp-server -f $s.file -t $TenantId 2>&1 | ForEach-Object { $_.ToString() }
  $joined = ($output -join [Environment]::NewLine)
  $output | ForEach-Object { Write-Host $_ }

  $cancelled = $joined -match 'Registration cancelled'
  $errored   = $joined -match '(?m)^\s*ERROR:|Failed to add MCP server|Server registration failed'
  if ($cancelled -or $errored) {
    Write-Host "FAILED — $($s.name) was not registered (see output above)" -ForegroundColor Red
    $results += [pscustomobject]@{ Server=$s.name; Status='FAILED' }
  } else {
    Write-Host "OK — $($s.name) submitted for admin review" -ForegroundColor Green
    $results += [pscustomobject]@{ Server=$s.name; Status='OK' }
  }
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Yellow
$results | Format-Table -AutoSize | Out-Host

Write-Host ""
Write-Host "=== Next steps (IT admin) ===" -ForegroundColor Yellow
Write-Host "1. Sign in to https://admin.cloud.microsoft as AI Admin or Global Admin"
Write-Host "2. Navigate to Agents > Tools > Requests"
Write-Host "3. For each successfully registered server above:"
Write-Host "   - Review server URL, declared tools, publisher"
Write-Host "   - Click Approve"
Write-Host "   - Consent the Entra permissions prompt"
Write-Host "4. Allow up to 30 min for propagation to Copilot Studio environments"
