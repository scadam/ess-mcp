$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
# MCP image (snc_internal for demo users) through ARM, then the host image (supply playbook asks before disputing).
& .\.tmp\mcp-image-deploy.ps1 *> .tmp\mcp-image-deploy.txt
"mcp exit=$LASTEXITCODE"
& .\.tmp\ship-host.ps1 *> .tmp\ship-host.txt
"host exit=$LASTEXITCODE"
exit 0
