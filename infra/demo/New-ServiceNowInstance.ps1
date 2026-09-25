[CmdletBinding()]
param(
  # The developer instance name from developer.servicenow.com, for example dev123456.
  [Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9-]{2,62}$')][string] $Instance,
  # The instance's 'admin' password; prompted when omitted.
  [securestring] $AdminPassword,
  # The password the demo people sign in with; prompted when omitted (press Enter to generate one).
  [securestring] $DemoUserPassword,
  # Also raise Kian's battery incident, which opens the first case on the desk.
  [switch] $SeedDemo,
  # Print the new OAuth client secret once, for the declarative agent's OAuth registration.
  [switch] $RevealOAuthSecret
)
# Stands a fresh ServiceNow developer instance up for the demo in one go: an OAuth client for the MCP server (and the
# declarative agent), the credentials in Key Vault, the ServiceNow MCP server re-pointed, then the provisioning job
# (groups, demo people with sign-in passwords and tool roles, devices, catalog item, webhook and business rule).
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Assert-DemoSubscription

$base = "https://$Instance.service-now.com"
$app = 'essmcp-caldova-servicenow'
$clientName = 'Group Functions Autopilot'
$teamsRedirect = 'https://teams.microsoft.com/api/platform/v1.0/oAuthRedirect'
if (-not $AdminPassword) { $AdminPassword = Read-Host -AsSecureString "ServiceNow 'admin' password for $Instance" }
if (-not $DemoUserPassword) { $DemoUserPassword = Read-Host -AsSecureString 'Password for the demo sign-in users (Enter to generate one)' }
$admin = [System.Net.NetworkCredential]::new('', $AdminPassword).Password
$demoPassword = [System.Net.NetworkCredential]::new('', $DemoUserPassword).Password
$generated = -not $demoPassword
if ($generated) { $demoPassword = 'Autopilot-' + (New-DemoSecret 10) + '7!' }
if (-not $admin) { throw 'The admin password is required.' }
$basic = @{ Accept = 'application/json'
            Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("admin:$admin")) }
$clientSecret = New-DemoSecret 40

try {
  # 1. The instance is awake and the admin credential works (a hibernating instance answers with an HTML page).
  try {
    $probe = Invoke-RestMethod "$base/api/now/table/sys_user" -Headers $basic -TimeoutSec 90 `
      -Body @{ sysparm_query = 'user_name=admin'; sysparm_fields = 'sys_id'; sysparm_limit = '1' }
  } catch {
    throw "Could not sign in to $base as admin (HTTP $($_.Exception.Response.StatusCode.value__)). Check the password, or wake the instance at developer.servicenow.com."
  }
  if (-not $probe.result) { throw "$base is not answering like an awake instance; wake it at developer.servicenow.com and retry." }
  Write-Host "1/6 $base is awake and the admin sign-in works."

  # 2. One OAuth client: password grant for the MCP server, authorization code for the declarative agent in Teams.
  $found = (Invoke-RestMethod "$base/api/now/table/oauth_entity" -Headers $basic `
      -Body @{ sysparm_query = "name=$clientName"; sysparm_fields = 'sys_id,client_id'; sysparm_limit = '1' }).result
  $client = @{ client_secret = $clientSecret; redirect_url = $teamsRedirect; active = 'true'
               access_token_lifespan = '1800'; refresh_token_lifespan = '8640000' }
  if ($found) {
    $clientId = $found[0].client_id
    Invoke-RestMethod -Method Patch "$base/api/now/table/oauth_entity/$($found[0].sys_id)" -Headers $basic `
      -ContentType 'application/json' -Body ($client | ConvertTo-Json) | Out-Null
  } else {
    $clientId = [guid]::NewGuid().ToString('N')
    $client += @{ name = $clientName; client_id = $clientId; type = 'client' }
    Invoke-RestMethod -Method Post "$base/api/now/table/oauth_entity" -Headers $basic `
      -ContentType 'application/json' -Body ($client | ConvertTo-Json) | Out-Null
  }
  $grant = @{ grant_type = 'password'; client_id = $clientId; client_secret = $clientSecret; username = 'admin'; password = $admin }
  $issued = $false
  foreach ($attempt in 1..12) {
    try {
      $answer = Invoke-RestMethod -Method Post "$base/oauth_token.do" -Body $grant -Headers @{ Accept = 'application/json' } `
        -ContentType 'application/x-www-form-urlencoded'
      if ($answer.access_token) { $issued = $true; break }
    } catch { }
    Start-Sleep -Seconds 5
  }
  $answer = $null
  if (-not $issued) {
    throw "ServiceNow did not issue a token to the '$clientName' OAuth client. Check it under System OAuth > Application Registry (Active, type OAuth client)."
  }
  Write-Host "2/6 OAuth client '$clientName' issues tokens."

  # 3. Credentials into Key Vault, where the MCP server and the provisioning job read them.
  Set-DemoVaultSecret 'servicenow-auth-code-client-id' $clientId
  Set-DemoVaultSecret 'servicenow-auth-code-client-secret' $clientSecret
  Set-DemoVaultSecret 'servicenow-demo-password' $admin
  Set-DemoVaultSecret 'servicenow-demo-user-password' $demoPassword
  Write-Host '3/6 Credentials stored in Key Vault.'

  # 4. A new MCP revision reads the new instance and the new Key Vault values.
  az containerapp update -n $app -g $DemoResourceGroup --revision-suffix ('sn' + (Get-Date -Format 'MMddHHmmss')) `
    --set-env-vars "SERVICENOW_INSTANCE_URL=$base" "SERVICENOW_OAUTH_TOKEN_URL=$base/oauth_token.do" `
    'SERVICENOW_OAUTH_GRANT_TYPE=password' 'SERVICENOW_OAUTH_AUTH_METHOD=client_secret_post' 'SERVICENOW_OAUTH_USERNAME=admin' -o none
  if ($LASTEXITCODE -ne 0) { throw "Could not update $app." }
  $revision = Wait-DemoApp $app
  Write-Host "4/6 $app now points at $base ($revision)."

  # 5. Everything the demo needs inside the instance.
  & (Join-Path $PSScriptRoot 'Invoke-Provisioning.ps1') -System servicenow -Mode setup
  if ($SeedDemo) { & (Join-Path $PSScriptRoot 'Invoke-Provisioning.ps1') -System servicenow -Mode demo -Scenario battery }
  Write-Host '5/6 Provisioned.'

  # 6. What the presenter needs: the sign-ins, and the OAuth details for the declarative agent.
  $members = (Invoke-RestMethod "$base/api/now/table/sys_user_grmember" -Headers $basic -Body @{
      sysparm_query = 'group.name=Autopilot Demo Users^ORDERBYuser.user_name'; sysparm_limit = '50'
      sysparm_fields = 'user.user_name,user.name,user.email,user.locked_out' }).result
  Write-Host "6/6 Done.`n"
  Write-Host "Demo sign-ins at $base (roles: itil, approver_user, knowledge, catalog_admin, asset):"
  $members | ForEach-Object {
    $note = if ($_.'user.locked_out' -eq 'true') { '  <- locked out on purpose for the IT lock-out demo' } else { '' }
    Write-Host ("  {0,-17} {1,-17} {2}{3}" -f $_.'user.user_name', $_.'user.name', $_.'user.email', $note)
  }
  if ($generated) { Write-Host "  Password (generated): $demoPassword" } else { Write-Host '  Password: the one you entered.' }
  Write-Host "`nDeclarative agent OAuth registration (Teams Developer Portal), if the ServiceNow plugin signs users in:"
  Write-Host "  Client ID:         $clientId"
  Write-Host "  Authorization URL: $base/oauth_auth.do"
  Write-Host "  Token/refresh URL: $base/oauth_token.do"
  Write-Host "  Scope:             useraccount"
  Write-Host "  Redirect (set):    $teamsRedirect"
  if ($RevealOAuthSecret) { Write-Host "  Client secret:     $clientSecret" }
  else { Write-Host '  Client secret:     in Key Vault; rerun with -RevealOAuthSecret to rotate it and print the new one.' }
  Write-Host "`nNext: .\infra\demo\Reset-Demo.ps1 to start the demo from a clean desk."
} finally {
  $admin = $demoPassword = $clientSecret = $basic = $grant = $null
}
exit 0
