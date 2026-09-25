$ErrorActionPreference = 'Continue'
$env:TEAMSFX_AGENT_SKILLS = 'true'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..\declarative_agent')).Path
$package = Join-Path $project 'appPackage\build\appPackage.caldova.zip'
$log = Join-Path $env:TEMP 'ap-atk-publish.txt'
"started $(Get-Date -Format o) package=$package" | Set-Content $log
npx.cmd -y @microsoft/m365agentstoolkit-cli@1.1.17 publish --env caldova --folder $project --package-file $package --interactive false 2>&1 |
  Where-Object { $_ -notmatch '^npm warn' } | Add-Content $log
"publish exit=$LASTEXITCODE" | Add-Content $log
exit 0
