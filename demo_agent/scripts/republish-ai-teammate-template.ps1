# Republishes the ESS AI Teammate Template to the M365/Teams app catalog.
#
# What this does:
#   1. Connects to Microsoft Graph with AppCatalog.ReadWrite.All (device code).
#   2. Deletes the existing catalog entry (catalog teamsApp id, NOT the manifest's internal id).
#   3. Builds a fresh zip from demo_agent/manifest/ (manifest.json, agenticUserTemplateManifest.json, color.png, outline.png).
#   4. POSTs the new zip to /appCatalogs/teamsApps so the app re-enters the approval queue with the fresh GUIDs.

[CmdletBinding()]
param(
    [string]$TenantId       = '8030d928-e557-4a4c-ae1e-95c1c4125eaa',
    [string]$OldCatalogId   = 'd5406780-bd6a-4e2f-a2e8-a4921cd77621',  # from Teams admin URL
    [string]$ManifestFolder = (Join-Path $PSScriptRoot '..\manifest'),
    [string]$ZipOutputPath  = (Join-Path $PSScriptRoot '..\manifest\ess-ai-teammate-template.zip'),
    [switch]$SkipDelete
)

$ErrorActionPreference = 'Stop'

Import-Module Microsoft.Graph.Authentication

Write-Host "==> Connecting to Graph (tenant $TenantId)" -ForegroundColor Cyan
Disconnect-MgGraph -ErrorAction SilentlyContinue | Out-Null
Connect-MgGraph -TenantId $TenantId -Scopes 'AppCatalog.ReadWrite.All' -NoWelcome | Out-Null
$ctx = Get-MgContext
Write-Host ("    signed in as {0}" -f $ctx.Account)
# Sanity: force a token resolution before doing real work.
Invoke-MgGraphRequest -Method GET -Uri 'https://graph.microsoft.com/v1.0/me?$select=userPrincipalName' | Out-Null

# ---- 1. Delete old catalog entry ----
if (-not $SkipDelete) {
    Write-Host "==> Looking up existing catalog entry $OldCatalogId" -ForegroundColor Cyan
    try {
        $existing = Invoke-MgGraphRequest -Method GET -Uri "https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/$OldCatalogId`?`$expand=appDefinitions"
        Write-Host ("    found: displayName='{0}' externalId={1} distributionMethod={2}" -f $existing.displayName, $existing.externalId, $existing.distributionMethod)
        Write-Host "==> Deleting" -ForegroundColor Yellow
        Invoke-MgGraphRequest -Method DELETE -Uri "https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/$OldCatalogId" | Out-Null
        Write-Host "    deleted." -ForegroundColor Green
    } catch {
        $msg = $_.Exception.Message
        if ($msg -match '404' -or $msg -match 'NotFound') {
            Write-Host "    not found (already gone) — continuing." -ForegroundColor DarkYellow
        } else {
            throw
        }
    }
} else {
    Write-Host "==> Skipping delete (per -SkipDelete)" -ForegroundColor DarkYellow
}

# ---- 2. Build fresh zip ----
Write-Host "==> Building fresh package zip" -ForegroundColor Cyan
$ManifestFolder = (Resolve-Path $ManifestFolder).Path
$files = @(
    'manifest.json',
    'agenticUserTemplateManifest.json',
    'color.png',
    'outline.png'
) | ForEach-Object { Join-Path $ManifestFolder $_ }

foreach ($f in $files) {
    if (-not (Test-Path $f)) { throw "Required file missing: $f" }
}

if (Test-Path $ZipOutputPath) { Remove-Item $ZipOutputPath -Force }
Compress-Archive -Path $files -DestinationPath $ZipOutputPath -CompressionLevel Optimal
$zipInfo = Get-Item $ZipOutputPath
Write-Host ("    {0} ({1} bytes)" -f $zipInfo.FullName, $zipInfo.Length) -ForegroundColor Green

# ---- 3. Publish to app catalog ----
Write-Host "==> Publishing to /appCatalogs/teamsApps" -ForegroundColor Cyan

# Pull the bearer token by inspecting the underlying HttpRequestMessage from a benign call.
$probe = Invoke-MgGraphRequest -Method GET -Uri 'https://graph.microsoft.com/v1.0/$metadata' -OutputType HttpResponseMessage
$accessToken = $probe.RequestMessage.Headers.Authorization.Parameter
if (-not $accessToken) { throw 'Could not obtain bearer token from MgGraph session.' }

$publishUri = 'https://graph.microsoft.com/v1.0/appCatalogs/teamsApps?requiresReview=true'
Write-Host "    POST $publishUri"
try {
    $resp = Invoke-WebRequest -Method POST -Uri $publishUri `
        -Headers @{ Authorization = "Bearer $accessToken" } `
        -ContentType 'application/zip' `
        -InFile $ZipOutputPath `
        -UseBasicParsing
    Write-Host "==> Published." -ForegroundColor Green
    $resp.Content
} catch {
    Write-Host "==> Publish failed:" -ForegroundColor Red
    $errResp = $_.Exception.Response
    if ($errResp) {
        Write-Host ("Status: {0}" -f $errResp.StatusCode)
        try {
            $stream = $errResp.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $body = $reader.ReadToEnd()
            Write-Host "Body:`n$body"
        } catch {
            Write-Host "(could not read response stream: $($_.Exception.Message))"
        }
    } else {
        Write-Host $_.Exception.Message
    }
    if ($_.ErrorDetails) { Write-Host "ErrorDetails:`n$($_.ErrorDetails.Message)" }
    throw
}
