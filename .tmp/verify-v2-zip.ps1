$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = 'C:\Users\scadam\AgentsToolkitProjects\ess-mcp\.copilot-azure\sessions\78f002fe-15a9-4ba1-a633-f366fd8558a4\a365-v2\publish-project\manifest\manifest.zip'
$z = [IO.Compression.ZipFile]::OpenRead($zip)
try {
  $z.Entries | ForEach-Object { "{0} {1}" -f $_.FullName, $_.Length }
  $read = { param($n) $e = $z.GetEntry($n); $s = New-Object IO.StreamReader($e.Open()); try { $s.ReadToEnd() } finally { $s.Dispose() } }
  $m = (& $read 'manifest.json') | ConvertFrom-Json
  $t = (& $read 'agenticUserTemplateManifest.json') | ConvertFrom-Json
  "id=$($m.id) short=$($m.name.short) full=$($m.name.full) version=$($m.version) manifestVersion=$($m.manifestVersion)"
  "template=$($m.agenticUserTemplates[0].id) -> file id=$($t.id) blueprint=$($t.agentIdentityBlueprintId) protocol=$($t.communicationProtocol)"
  "tab=$($m.staticTabs[0].contentUrl) domains=$($m.validDomains -join ',')"
  $raw = & $read 'manifest.json'
  "placeholders=" + $raw.Contains('${{') + " oldBlueprint=" + $raw.Contains('7b3bf810') + " oldTemplate=" + $raw.Contains('7b0926a6')
} finally { $z.Dispose() }
$h = (Get-FileHash $zip -Algorithm SHA256).Hash.Substring(0, 16)
$copy = Join-Path $env:USERPROFILE 'Downloads\Group-Functions-Autopilot-v2-manifest.zip'
Copy-Item $zip $copy -Force
"sha256[0:16]=$h copied=$copy"
