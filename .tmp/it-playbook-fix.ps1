$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
# Host image with the IT playbook change, then a fresh battery incident to check the caller is told.
& .\.tmp\ship-host.ps1 *> .tmp\ship-host.txt
"host exit=$LASTEXITCODE"
& .\infra\demo\Invoke-Provisioning.ps1 -System servicenow -Mode reset -Scenario battery
& .\infra\demo\Invoke-Provisioning.ps1 -System servicenow -Mode demo -Scenario battery
"done"
exit 0
