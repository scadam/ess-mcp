$ErrorActionPreference = 'Stop'
Push-Location "$PSScriptRoot\..\declarative_agent"
try {
  $zip = '.\appPackage\build\appPackage.caldova.zip'
  $backup = '.\appPackage\build\appPackage.caldova-1.0.0.zip'
  if ((Test-Path $zip) -and -not (Test-Path $backup)) { Copy-Item $zip $backup; "backed up previous package to $backup" }
  $env:TEAMSFX_AGENT_SKILLS = 'true'
  npx.cmd -y @microsoft/m365agentstoolkit-cli@1.1.17 package --env caldova --telemetry false 2>&1 | Where-Object { $_ -notmatch '^npm warn' }
  "package exit=$LASTEXITCODE"
  if ($LASTEXITCODE -ne 0) { exit 1 }
  $appId = (Select-String -Path .\env\.env.caldova -Pattern '^TEAMS_APP_ID=(.+)$').Matches[0].Groups[1].Value
  pwsh -NoProfile -File .\prepare_caldova_package.ps1 -PackagePath $zip -Environment caldova -ExpectedAppId $appId
  "prepare exit=$LASTEXITCODE"
} finally { Pop-Location }
exit 0
