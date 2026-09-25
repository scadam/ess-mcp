[CmdletBinding()]
param(
  [Parameter(Mandatory)] [string] $Origin,
  [string] $DisplayName = 'Group Functions Autopilot Control Plane'
)
# Creates (or reuses) the single-tenant control-plane SPA/API registration and
# grants tenant-wide consent for its own delegated scope. Requires an admin az login.
$ErrorActionPreference = 'Stop'
$graph = 'https://graph.microsoft.com/v1.0'
$tmp = New-TemporaryFile

# Query strings never contain '&' or '%': az.cmd can split or expand them on Windows.
function Invoke-Graph([string] $Method, [string] $Uri, $Body) {
  $azArgs = @('rest', '--method', $Method, '--url', $Uri, '--headers', 'Content-Type=application/json')
  if ($null -ne $Body) {
    ($Body | ConvertTo-Json -Depth 10 -Compress) | Set-Content -Path $tmp -Encoding utf8NoBOM
    $azArgs += @('--body', "@$tmp")
  }
  $out = & az @azArgs
  if ($LASTEXITCODE -ne 0) { throw "Graph $Method failed." }
  if ($out) { return ($out | Out-String | ConvertFrom-Json) }
}

try {
  $existing = @((Invoke-Graph GET "$graph/applications?`$filter=displayName eq '$DisplayName'" $null).value)
  if ($existing.Count -gt 1) { throw 'More than one control-plane registration exists; reconcile manually.' }
  $redirect = "$($Origin.TrimEnd('/'))/control-plane"
  if ($existing.Count -eq 1) {
    $app = $existing[0]
  } else {
    $app = Invoke-Graph POST "$graph/applications" @{
      displayName = $DisplayName
      signInAudience = 'AzureADMyOrg'
      spa = @{ redirectUris = @($redirect) }
      api = @{
        requestedAccessTokenVersion = 2
        oauth2PermissionScopes = @(@{
          id = [guid]::NewGuid().Guid
          value = 'access_agent_as_user'
          type = 'User'
          isEnabled = $true
          adminConsentDisplayName = 'Operate Group Functions Autopilot'
          adminConsentDescription = 'Allows the signed-in operator to use the Group Functions Autopilot control plane.'
          userConsentDisplayName = 'Operate Group Functions Autopilot'
          userConsentDescription = 'Allows you to use the Group Functions Autopilot control plane.'
        })
      }
    }
  }
  $uri = "api://$($app.appId)"
  $scopeId = @($app.api.oauth2PermissionScopes | Where-Object value -eq 'access_agent_as_user')[0].id
  if (-not $scopeId) { throw 'The access_agent_as_user scope is missing.' }
  Invoke-Graph PATCH "$graph/applications/$($app.id)" @{
    identifierUris = @($uri)
    spa = @{ redirectUris = @($redirect) }
    requiredResourceAccess = @(
      @{ resourceAppId = $app.appId; resourceAccess = @(@{ id = $scopeId; type = 'Scope' }) }
    )
  } | Out-Null

  $sp = @((Invoke-Graph GET "$graph/servicePrincipals?`$filter=appId eq '$($app.appId)'" $null).value)[0]
  if (-not $sp) { $sp = Invoke-Graph POST "$graph/servicePrincipals" @{ appId = $app.appId } }

  $grants = @((Invoke-Graph GET "$graph/oauth2PermissionGrants?`$filter=clientId eq '$($sp.id)' and resourceId eq '$($sp.id)'" $null).value)
  if ($grants.Count -eq 0) {
    Invoke-Graph POST "$graph/oauth2PermissionGrants" @{
      clientId = $sp.id; consentType = 'AllPrincipals'; resourceId = $sp.id; scope = 'access_agent_as_user'
    } | Out-Null
  }
  [pscustomobject]@{
    clientId = $app.appId
    audience = $app.appId
    scope = "$uri/access_agent_as_user"
    redirectUri = $redirect
    servicePrincipalId = $sp.id
  } | ConvertTo-Json
} finally {
  Remove-Item $tmp -ErrorAction SilentlyContinue
}
