$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
# MCP image (provisioning modes) to ServiceNow/Salesforce/Coupa, then the host image (desk fixes).
& .\.tmp\mcp-desk-deploy.ps1 *> .tmp\mcp-deploy.txt
"mcp exit=$LASTEXITCODE"
& .\.tmp\ship-host.ps1 *> .tmp\ship-host.txt
"host exit=$LASTEXITCODE"
exit 0
