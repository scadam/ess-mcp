$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# Build the host image, record its digest, then deploy with the desk and records configuration.
& .\infra\autopilot-caldova\build-image.ps1 *> .tmp\build-host.txt
$raw = (Get-Content .tmp\build-host.txt -Raw) -replace "\r?\n", ""
$match = [regex]::Match($raw, 'cressmcpcaldovaf61b\.azurecr\.io/autopilot@sha256:[0-9a-f]{64}')
if (-not $match.Success) { throw 'The image build did not report a digest.' }
Set-Content -Path .copilot-azure\sessions\78f002fe-15a9-4ba1-a633-f366fd8558a4\last-image.txt -Value $match.Value -NoNewline
"image=$($match.Value)"
$env:AUTOPILOT_SALESFORCE_INTEGRATION_USER = 'scadam@microsoft.com'
& .\.tmp\deploy-host.ps1
exit 0
