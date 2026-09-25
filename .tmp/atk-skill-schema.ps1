$ext = Get-ChildItem "$env:USERPROFILE\.vscode\extensions" -Directory -Filter 'teamsdevapp.ms-teams-vscode-extension-*' | Sort-Object Name -Descending | Select-Object -First 1
"extension=$($ext.Name)"
$schemas = Join-Path $ext.FullName 'out\json-schemas'
if (Test-Path $schemas) {
  Get-ChildItem $schemas -Recurse -File | Where-Object { $_.FullName -match 'declarative|copilot' } | ForEach-Object { $_.FullName.Substring($schemas.Length) } | Select-Object -First 40
  "--- teams schema versions with agentSkills"
  Get-ChildItem (Join-Path $schemas 'teams') -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $p = Join-Path $_.FullName 'MicrosoftTeams.schema.json'
    if (Test-Path $p) { "$($_.Name) agentSkills=$([bool](Select-String -Path $p -Pattern '"agentSkills"' -Quiet))" }
  }
}
"--- files mentioning agent_skills / agentSkills (first 20)"
Get-ChildItem $ext.FullName -Recurse -File -Include *.json, *.js -ErrorAction SilentlyContinue |
  Where-Object { $_.Length -lt 60MB } |
  Select-String -Pattern 'agent_skills|agentSkills|TEAMSFX_AGENT_SKILLS' -List -ErrorAction SilentlyContinue |
  Select-Object -First 20 | ForEach-Object { $_.Path.Substring($ext.FullName.Length) }
exit 0
