$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$token = az account get-access-token --resource https://graph.microsoft.com --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token"; ConsistencyLevel = 'eventual' }
$blueprint = '77ae0985-4084-4bc1-bb3c-ab6dd0ad9bde'
$sps = Invoke-RestMethod -Headers $headers -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/microsoft.graph.agentIdentity?`$filter=agentIdentityBlueprintId eq '$blueprint'&`$select=id,appId,displayName"
foreach ($sp in $sps.value) {
  $name = [string]$sp.displayName
  $users = Invoke-RestMethod -Headers $headers -Uri ("https://graph.microsoft.com/v1.0/users?`$filter=displayName eq '" + $name.Replace("'", "''") + "'&`$select=id,displayName,userPrincipalName")
  if (-not $users.value) { "$name | no user"; continue }
  foreach ($user in $users.value) {
    try {
      $meta = Invoke-RestMethod -Headers $headers -Uri "https://graph.microsoft.com/v1.0/users/$($user.id)/photo"
      "$name | $($user.id) | photo $($meta.width)x$($meta.height) etag=$($meta.'@odata.mediaEtag')"
    } catch {
      $status = $_.Exception.Response.StatusCode.value__
      $detail = ([string]$_.ErrorDetails.Message)
      if ($detail.Length -gt 220) { $detail = $detail.Substring(0, 220) }
      "$name | $($user.id) | photo HTTP $status $detail"
    }
    try {
      $sized = Invoke-WebRequest -Headers $headers -Uri "https://graph.microsoft.com/v1.0/users/$($user.id)/photos/96x96/`$value" -UseBasicParsing
      "  96x96 bytes=$($sized.RawContentLength) type=$($sized.Headers['Content-Type'])"
    } catch {
      "  96x96 HTTP $($_.Exception.Response.StatusCode.value__)"
    }
  }
}
exit 0
