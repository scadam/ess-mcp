$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
# New MCP image (synchronous after rule), then re-apply setup and raise a fresh battery incident.
& .\.tmp\mcp-image-deploy.ps1 *> .tmp\mcp-image-deploy3.txt
"mcp exit=$LASTEXITCODE"
& .\infra\demo\Invoke-Provisioning.ps1 -System servicenow -Mode setup
& .\infra\demo\Invoke-Provisioning.ps1 -System servicenow -Mode reset -Scenario battery
& .\infra\demo\Invoke-Provisioning.ps1 -System servicenow -Mode demo -Scenario battery
"done"
exit 0
