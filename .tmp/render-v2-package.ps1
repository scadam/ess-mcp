$ErrorActionPreference = 'Stop'
$root = 'C:\Users\scadam\AgentsToolkitProjects\ess-mcp'
$src = Join-Path $root 'demo_agent\manifest'
$dest = Join-Path $root '.copilot-azure\sessions\78f002fe-15a9-4ba1-a633-f366fd8558a4\a365-v2\publish-project\manifest'
$domain = 'ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io'
New-Item -ItemType Directory -Path $dest -Force | Out-Null
Get-ChildItem $dest -File | Remove-Item -Force
Copy-Item (Join-Path $src 'color.png'), (Join-Path $src 'outline.png') $dest
$m = (Get-Content (Join-Path $src 'manifest.json') -Raw).Replace('${{AGENT_DOMAIN}}', $domain) | ConvertFrom-Json
$m.name.short = 'Group Functions Autopilot v2'
$m.name.full = 'Group Functions Autopilot v2'
$m | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $dest 'manifest.json') -Encoding utf8NoBOM
Copy-Item (Join-Path $src 'agenticUserTemplateManifest.json') $dest
$check = Get-Content (Join-Path $dest 'manifest.json') -Raw
if ($check.Contains('${{')) { throw 'Unresolved placeholder remains.' }
$t = Get-Content (Join-Path $dest 'agenticUserTemplateManifest.json') -Raw | ConvertFrom-Json
$r = $check | ConvertFrom-Json
"id=$($r.id) name=$($r.name.short) version=$($r.version) template=$($r.agenticUserTemplates[0].id) templateFile=$($t.id) blueprint=$($t.agentIdentityBlueprintId)"
Get-ChildItem $dest | ForEach-Object { "{0} {1}" -f $_.Name, $_.Length }
