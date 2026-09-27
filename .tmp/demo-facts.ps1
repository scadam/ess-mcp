$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$base = 'https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
$token = az account get-access-token --scope api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user --query accessToken -o tsv
$room = Invoke-RestMethod "$base/api/control-room" -Headers @{ Authorization = "Bearer $token" }
'== instances'
foreach ($tile in $room.instances) {
  '{0} | key={1} | app={2} | user={3} {4} | manager={5} | skills={6} | servers={7}' -f $tile.name, $tile.key, $tile.appId,
    $tile.user.id, $tile.user.upn, $tile.manager.name, ($tile.policy.skills -join ','), ($tile.policy.servers -join ',')
}
$graph = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
'== people'
foreach ($name in 'Aadi', 'Aisha', 'Kian', 'Scott', 'Colin', 'Karin', 'Isaac', 'Daisy') {
  $r = Invoke-RestMethod "https://graph.microsoft.com/v1.0/users?`$filter=startswith(displayName,'$name')&`$select=id,displayName,userPrincipalName,mail,jobTitle,department" -Headers @{ Authorization = "Bearer $graph" }
  foreach ($u in $r.value) { '{0} | {1} | {2} | {3} | {4}' -f $u.displayName, $u.userPrincipalName, $u.id, $u.jobTitle, $u.department }
}
exit 0
