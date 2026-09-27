$ErrorActionPreference = 'Stop'
Set-Location C:\Users\scadam\AgentsToolkitProjects\ess-mcp
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$graph = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
$h = @{ Authorization = "Bearer $graph" }
$it = Invoke-RestMethod "https://graph.microsoft.com/v1.0/users/itsm-agent@caldova74201480.onmicrosoft.com?`$select=id,displayName,userPrincipalName,accountEnabled" -Headers $h
'IT agent user: {0} | {1} | {2} | enabled={3}' -f $it.id, $it.displayName, $it.userPrincipalName, $it.accountEnabled
$members = Invoke-RestMethod "https://graph.microsoft.com/v1.0/groups/fb991034-107a-4ab8-ac5a-a57400088d4b/members?`$select=id,displayName,userPrincipalName" -Headers $h
'records group members:'
$members.value | ForEach-Object { '  {0} | {1}' -f $_.id, $_.displayName }
'IT agent in group: ' + [bool]($members.value | Where-Object { $_.id -eq $it.id })
exit 0
