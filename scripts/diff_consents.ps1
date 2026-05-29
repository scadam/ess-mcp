$az = "C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"

$sps = [ordered]@{
  "HR v2"     = "eb24d0bc-3806-4186-b459-e956394ca39f"
  "IT v2"     = "c56422b7-a142-461a-a4f7-fbb79f5f9d83"
  "Blueprint" = "612885df-960e-4900-b065-cc3ff00287bf"
  "Primary"   = "ed4046aa-a3ef-4685-a73d-ecda5a4f01da"
}

$resCache = @{}
function Resolve-Resource($id) {
  if ($resCache.ContainsKey($id)) { return $resCache[$id] }
  $r = (& $az rest --method GET --url ("https://graph.microsoft.com/v1.0/servicePrincipals/" + $id)) | ConvertFrom-Json
  $obj = [pscustomobject]@{ name = $r.displayName; appId = $r.appId }
  $resCache[$id] = $obj
  return $obj
}

foreach ($name in $sps.Keys) {
  $spId = $sps[$name]
  Write-Host ""
  Write-Host ("=" * 70) -ForegroundColor DarkGray
  Write-Host "$name  (sp $spId)" -ForegroundColor Cyan
  Write-Host ("=" * 70) -ForegroundColor DarkGray

  Write-Host "[delegated grants — oauth2PermissionGrants]" -ForegroundColor Yellow
  $deleg = (& $az rest --method GET --url ("https://graph.microsoft.com/v1.0/servicePrincipals/$spId/oauth2PermissionGrants")) | ConvertFrom-Json
  $rows = foreach ($g in $deleg.value) {
    $r = Resolve-Resource $g.resourceId
    [pscustomobject]@{ resource = $r.name; resourceAppId = $r.appId; consentType = $g.consentType; principalId = $g.principalId; scopes = $g.scope }
  }
  $rows | Format-Table -AutoSize -Wrap

  Write-Host "[application roles — appRoleAssignments]" -ForegroundColor Yellow
  $approles = (& $az rest --method GET --url ("https://graph.microsoft.com/v1.0/servicePrincipals/$spId/appRoleAssignments")) | ConvertFrom-Json
  $rows2 = foreach ($a in $approles.value) {
    [pscustomobject]@{ resource = $a.resourceDisplayName; appRoleId = $a.appRoleId }
  }
  if ($rows2) { $rows2 | Format-Table -AutoSize } else { Write-Host "  (none)" }
}
