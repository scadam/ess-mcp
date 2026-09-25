Push-Location "$PSScriptRoot\..\declarative_agent"
try {
  $env:TEAMSFX_AGENT_SKILLS = 'true'
  npx -y @microsoft/m365agentstoolkit-cli@1.1.17 package --help 2>&1
} finally { Pop-Location }
exit 0
