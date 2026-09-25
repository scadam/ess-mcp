$ErrorActionPreference = 'Continue'
$env:TEAMSFX_AGENT_SKILLS = 'true'
$project = Join-Path $PSScriptRoot '..\declarative_agent'
$log = Join-Path $env:TEMP 'ap-atk-provision.txt'
"started $(Get-Date -Format o)" | Set-Content $log
npx.cmd -y @microsoft/m365agentstoolkit-cli@1.1.17 provision --env caldova --folder $project --interactive false 2>&1 |
  Where-Object { $_ -notmatch '^npm warn' } | Add-Content $log
"provision exit=$LASTEXITCODE" | Add-Content $log
exit 0
