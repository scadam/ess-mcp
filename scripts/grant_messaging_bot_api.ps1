param([switch]$WhatIf)
$az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"

# Messaging Bot API service principal in this tenant (the resource that owns
# the APX_PRODUCTION_SCOPE token the Microsoft 365 Agents SDK requests
# whenever it posts a bot reply through api.botframework.com).
$messagingBotAppId = "5a807f24-c9de-44ee-a3a7-329e88a00ffc"

$mbaSp = (& $az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=appId eq '$messagingBotAppId'") | ConvertFrom-Json
$mbaSpId = $mbaSp.value[0].id
Write-Host "Messaging Bot API SP: $mbaSpId  ($($mbaSp.value[0].displayName))" -ForegroundColor Cyan

# Scopes consistent with what a365.generated.config.json claimed were granted.
$scopes = "Authorization.ReadWrite user_impersonation"

$targets = [ordered]@{
  "HR v2 (eb24d0bc)" = "eb24d0bc-3806-4186-b459-e956394ca39f"
  "IT v2 (c56422b7)" = "c56422b7-a142-461a-a4f7-fbb79f5f9d83"
}

foreach ($name in $targets.Keys) {
  $clientSp = $targets[$name]
  Write-Host "`n--- $name client SP $clientSp ---" -ForegroundColor Yellow

  # See if a grant already exists between client and Messaging Bot API
  $existing = (& $az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/$clientSp/oauth2PermissionGrants") | ConvertFrom-Json
  $match = $existing.value | Where-Object { $_.resourceId -eq $mbaSpId -and $_.consentType -eq "AllPrincipals" }
  if ($match) {
    Write-Host "  AllPrincipals grant ALREADY exists (id=$($match.id) scopes='$($match.scope)') — patching scopes" -ForegroundColor DarkYellow
    if ($WhatIf) { continue }
    $body = @{ scope = $scopes } | ConvertTo-Json -Compress
    $tmp = New-TemporaryFile
    Set-Content -Path $tmp -Value $body -Encoding UTF8 -NoNewline
    & $az rest --method PATCH --url "https://graph.microsoft.com/v1.0/oauth2PermissionGrants/$($match.id)" --headers "Content-Type=application/json" --body "@$($tmp.FullName)" | Out-Null
    Remove-Item $tmp -Force
    Write-Host "  patched." -ForegroundColor Green
  } else {
    Write-Host "  no grant exists — creating AllPrincipals grant for Messaging Bot API"
    if ($WhatIf) { continue }
    $body = @{
      clientId    = $clientSp
      consentType = "AllPrincipals"
      resourceId  = $mbaSpId
      scope       = $scopes
    } | ConvertTo-Json -Compress
    $tmp = New-TemporaryFile
    Set-Content -Path $tmp -Value $body -Encoding UTF8 -NoNewline
    & $az rest --method POST --url "https://graph.microsoft.com/v1.0/oauth2PermissionGrants" --headers "Content-Type=application/json" --body "@$($tmp.FullName)" | Out-Null
    Remove-Item $tmp -Force
    Write-Host "  created." -ForegroundColor Green
  }
}

Write-Host "`nVerification:" -ForegroundColor Cyan
foreach ($name in $targets.Keys) {
  $spId = $targets[$name]
  $g = (& $az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/$spId/oauth2PermissionGrants") | ConvertFrom-Json
  $rows = foreach ($x in $g.value) { [pscustomobject]@{ resourceId=$x.resourceId; consentType=$x.consentType; scope=$x.scope } }
  Write-Host "$name :"
  $rows | Where-Object { $_.resourceId -eq $mbaSpId } | Format-Table -AutoSize -Wrap
}
