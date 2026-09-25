[CmdletBinding()]
param(
  [string] $Registry = 'cressmcpcaldovaf61b',
  [string] $Repository = 'autopilot'
)
# Builds the Autopilot image in ACR from an allowlisted temporary context (no
# local credentials, generated A365 state or tests) and prints its digest reference.
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$tag = 'v' + (Get-Date -Format 'MMddHHmm')
$stage = Join-Path ([IO.Path]::GetTempPath()) "autopilot-build-$tag"
$agent = Join-Path $root 'demo_agent'
New-Item -ItemType Directory -Path (Join-Path $stage 'demo_agent') -Force | Out-Null
try {
  Copy-Item (Join-Path $agent '*.py'), (Join-Path $agent 'requirements.txt'), (Join-Path $agent 'constraints.txt'),
    (Join-Path $agent 'ToolingManifest.json'), (Join-Path $agent 'purview-policy.yaml') (Join-Path $stage 'demo_agent')
  Copy-Item (Join-Path $agent 'skills') (Join-Path $stage 'demo_agent/skills') -Recurse
  Copy-Item (Join-Path $agent 'guardrail_policy') (Join-Path $stage 'demo_agent/guardrail_policy') -Recurse
  Copy-Item (Join-Path $agent 'static') (Join-Path $stage 'demo_agent/static') -Recurse
  Copy-Item (Join-Path $PSScriptRoot 'Dockerfile.autopilot') (Join-Path $stage 'Dockerfile')
  $unexpected = Get-ChildItem $stage -Recurse -File | Where-Object { $_.Name -match '^\.env|secret|credential|generated' }
  if ($unexpected) { throw 'The staged build context contains a credential-like file.' }
  Push-Location $stage
  try {
    $result = az acr build -r $Registry -t "${Repository}:$tag" -f Dockerfile . --no-logs --query '{status:status, digest:outputImages[0].digest}' -o json | ConvertFrom-Json
  } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0 -or $result.status -ne 'Succeeded' -or $result.digest -notmatch '^sha256:[0-9a-f]{64}$') {
    throw "ACR build did not succeed (status '$($result.status)')."
  }
  [pscustomobject]@{ tag = $tag; image = "$Registry.azurecr.io/$Repository@$($result.digest)" } | ConvertTo-Json
} finally {
  Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}
