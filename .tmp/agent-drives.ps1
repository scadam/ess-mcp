$ErrorActionPreference = 'Continue'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
# Does each agentic user have a OneDrive (license + provisioning)? Read-only checks.
$token = az account get-access-token --resource 'https://graph.microsoft.com' --query accessToken -o tsv
$h = @{ Authorization = "Bearer $token" }
foreach ($upn in 'hr-agent', 'supply-agent', 'compliance-agent') {
  $id = "$upn@caldova74201480.onmicrosoft.com"
  try {
    $lic = Invoke-RestMethod "https://graph.microsoft.com/v1.0/users/$id/licenseDetails?`$select=skuPartNumber,servicePlans" -Headers $h
    $plans = @($lic.value | ForEach-Object { $_.servicePlans } | Where-Object { $_.servicePlanName -match 'SHAREPOINT|ONEDRIVE' -and $_.provisioningStatus -eq 'Success' } | ForEach-Object { $_.servicePlanName })
    "$upn skus=$(@($lic.value.skuPartNumber) -join ',') sharepointPlans=$($plans -join ',')"
  } catch { "$upn licenseDetails failed: $($_.Exception.Response.StatusCode)" }
  try {
    $drive = Invoke-RestMethod "https://graph.microsoft.com/v1.0/users/$id/drive?`$select=id,webUrl,driveType" -Headers $h
    "$upn drive=$($drive.driveType) $($drive.webUrl)"
  } catch { "$upn drive: HTTP $([int]$_.Exception.Response.StatusCode)" }
}
$token = $null
exit 0
