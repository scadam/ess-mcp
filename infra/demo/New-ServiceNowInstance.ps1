[CmdletBinding()]
param(
  # The developer instance name from developer.servicenow.com, for example dev123456.
  [Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9-]{2,62}$')][string] $Instance,
  # The instance's 'admin' password; prompted when omitted.
  [securestring] $AdminPassword,
  # The OAuth client you created in the instance (see the steps printed when these are omitted).
  [string] $OAuthClientId,
  [securestring] $OAuthClientSecret,
  # The password the demo people sign in with; prompted when omitted (press Enter to generate one).
  [securestring] $DemoUserPassword,
  # Also raise Kian's battery incident, which opens the first case on the desk.
  [switch] $SeedDemo
)
# Stands a fresh ServiceNow developer instance up for the demo: checks the OAuth client, stores the credentials in Key
# Vault, re-points the ServiceNow MCP server, then runs the provisioning job (groups, demo people with sign-in passwords
# and tool roles, devices, catalog item, outbound email, webhook properties and business rule).
# Developer instances refuse REST basic auth (multi-factor sign-in is on), so everything goes through OAuth.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
Assert-DemoSubscription

$base = "https://$Instance.service-now.com"
$app = 'essmcp-caldova-servicenow'
$teamsRedirect = 'https://teams.microsoft.com/api/platform/v1.0/oAuthRedirect'
if (-not $OAuthClientId) {
  Write-Host @"
Create the OAuth client first (about a minute), signed in to $base as admin:
  1. All > System OAuth > Application Registry > New > Create an OAuth API endpoint for external clients.
  2. Name: Group Functions Autopilot. Redirect URL: $teamsRedirect
  3. Save, open it again, and copy the Client ID and the Client Secret (the lock icon shows it).
"@
  $OAuthClientId = (Read-Host 'Client ID').Trim()
}
if (-not $OAuthClientSecret) { $OAuthClientSecret = Read-Host -AsSecureString 'Client Secret' }
if (-not $AdminPassword) { $AdminPassword = Read-Host -AsSecureString "ServiceNow 'admin' password for $Instance" }
if (-not $DemoUserPassword) { $DemoUserPassword = Read-Host -AsSecureString 'Password for the demo sign-in users (Enter to generate one)' }
$clientSecret = [System.Net.NetworkCredential]::new('', $OAuthClientSecret).Password
$admin = [System.Net.NetworkCredential]::new('', $AdminPassword).Password
$demoPassword = [System.Net.NetworkCredential]::new('', $DemoUserPassword).Password
$generated = -not $demoPassword
if ($generated) { $demoPassword = 'Autopilot-' + (New-DemoSecret 10) + '7!' }
if (-not ($OAuthClientId -and $clientSecret -and $admin)) { throw 'The client ID, client secret and admin password are all required.' }

try {
  # 1. The client issues an admin token by password grant: that's how the MCP server signs in.
  $grant = @{ grant_type = 'password'; client_id = $OAuthClientId; client_secret = $clientSecret; username = 'admin'; password = $admin }
  $token = $null
  foreach ($attempt in 1..6) {
    try {
      $token = (Invoke-RestMethod -Method Post "$base/oauth_token.do" -Body $grant -Headers @{ Accept = 'application/json' } `
        -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 90).access_token
      if ($token) { break }
    } catch { $failure = $_.Exception.Response.StatusCode.value__ }
    Start-Sleep -Seconds 5
  }
  if (-not $token) {
    throw "No token from $base/oauth_token.do (HTTP $failure). Check the client ID/secret and admin password, or wake the instance at developer.servicenow.com."
  }
  $bearer = @{ Accept = 'application/json'; Authorization = "Bearer $token" }
  Write-Host "1/5 $base issues tokens to the OAuth client."

  # 2. Credentials into Key Vault, where the MCP server and the provisioning job read them.
  Set-DemoVaultSecret 'servicenow-auth-code-client-id' $OAuthClientId
  Set-DemoVaultSecret 'servicenow-auth-code-client-secret' $clientSecret
  Set-DemoVaultSecret 'servicenow-demo-password' $admin
  Set-DemoVaultSecret 'servicenow-demo-user-password' $demoPassword
  Write-Host '2/5 Credentials stored in Key Vault.'

  # 3. A new MCP revision reads the new instance and the new Key Vault values.
  $template = (Get-DemoApp $app).properties.template
  $settings = [ordered]@{ SERVICENOW_INSTANCE_URL = $base; SERVICENOW_OAUTH_TOKEN_URL = "$base/oauth_token.do"
                          SERVICENOW_OAUTH_GRANT_TYPE = 'password'; SERVICENOW_OAUTH_AUTH_METHOD = 'client_secret_post'
                          SERVICENOW_OAUTH_USERNAME = 'admin' }
  $template.containers[0].env = @($template.containers[0].env | Where-Object { -not $settings.Contains($_.name) }) +
    @($settings.GetEnumerator() | ForEach-Object { [pscustomobject]@{ name = $_.Key; value = $_.Value } })
  $template.revisionSuffix = 'sn' + (Get-Date -Format 'MMddHHmmss')
  Invoke-DemoArm -Method Patch -Path (Get-DemoAppPath $app) -Body @{ properties = @{ template = $template } } | Out-Null
  Start-Sleep -Seconds 15
  $revision = Wait-DemoApp $app
  Write-Host "3/5 $app now points at $base ($revision)."

  # 4. Everything the demo needs inside the instance.
  & (Join-Path $PSScriptRoot 'Invoke-Provisioning.ps1') -System servicenow -Mode setup
  if ($SeedDemo) { & (Join-Path $PSScriptRoot 'Invoke-Provisioning.ps1') -System servicenow -Mode demo -Scenario battery }
  Write-Host '4/5 Provisioned.'

  # 5. What the presenter needs: the sign-ins, and the OAuth details for the declarative agent.
  $members = (Invoke-RestMethod "$base/api/now/table/sys_user_grmember" -Headers $bearer -Body @{
      sysparm_query = 'group.name=Autopilot Demo Users^ORDERBYuser.user_name'; sysparm_limit = '50'
      sysparm_fields = 'user.user_name,user.name,user.email,user.locked_out' }).result
  Write-Host "5/5 Done.`n"
  Write-Host "Demo sign-ins at $base (roles: itil, approver_user, knowledge, catalog_admin, asset, snc_platform_rest_api_access):"
  $members | ForEach-Object {
    $note = if ($_.'user.locked_out' -eq 'true') { '  <- locked out on purpose for the IT lock-out demo' } else { '' }
    Write-Host ("  {0,-17} {1,-17} {2}{3}" -f $_.'user.user_name', $_.'user.name', $_.'user.email', $note)
  }
  if ($generated) { Write-Host "  Password (generated): $demoPassword" } else { Write-Host '  Password: the one you entered.' }
  Write-Host "`nDeclarative agent OAuth registration (Teams Developer Portal), if the ServiceNow plugin signs users in:"
  Write-Host "  Client ID:         $OAuthClientId (and its secret)"
  Write-Host "  Authorization URL: $base/oauth_auth.do"
  Write-Host "  Token/refresh URL: $base/oauth_token.do"
  Write-Host "  Scope:             useraccount"
  Write-Host "`nNext: .\infra\demo\Reset-Demo.ps1 to start the demo from a clean desk."
} finally {
  $admin = $demoPassword = $clientSecret = $grant = $token = $bearer = $null
}
exit 0
