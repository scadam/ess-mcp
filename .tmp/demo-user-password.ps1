$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
. .\infra\demo\environment.ps1
Assert-DemoSubscription
# One-off for the current instance: the demo people's ServiceNow sign-in password, applied by the next setup run.
if (Test-DemoVaultSecret 'servicenow-demo-user-password') { 'exists'; exit 0 }
$password = 'Autopilot-' + (New-DemoSecret 10) + '7!'
Set-DemoVaultSecret 'servicenow-demo-user-password' $password
"created: $password"
exit 0
