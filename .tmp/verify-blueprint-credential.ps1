param([string] $Scope = '5a807f24-c9de-44ee-a3a7-329e88a00ffc/.default')
$ErrorActionPreference = 'Stop'
$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$tenant = '17371818-07cb-47f2-9ca3-18f96f0125d7'
$client = '77ae0985-4084-4bc1-bb3c-ab6dd0ad9bde'
$s = az keyvault secret show --vault-name kv-essmcp-caldova-f61b --name autopilot-blueprint-v2-runtime --query value -o tsv
try {
  $body = @{ client_id = $client; client_secret = $s; scope = $Scope; grant_type = 'client_credentials' }
  $r = Invoke-RestMethod -Method Post "https://login.microsoftonline.com/$tenant/oauth2/v2.0/token" -Body $body -ContentType 'application/x-www-form-urlencoded'
  $p = $r.access_token.Split('.')[1].Replace('-', '+').Replace('_', '/')
  switch ($p.Length % 4) { 2 { $p += '==' } 3 { $p += '=' } }
  $c = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($p)) | ConvertFrom-Json
  "token OK: aud=$($c.aud) appid=$($c.appid) tid=$($c.tid) expires_in=$($r.expires_in)"
} catch {
  "token FAILED: " + ($_.ErrorDetails.Message -replace '"trace_id":"[^"]*"', '' | Out-String).Substring(0, 300)
} finally {
  $s = $null; $body = $null; $r = $null
}
