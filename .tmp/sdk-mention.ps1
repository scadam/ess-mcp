$site = 'C:\Users\scadam\AppData\Roaming\Python\Python312\site-packages'
$out = foreach ($root in @("$site\microsoft_agents_a365", "$site\microsoft_agents")) {
  if (-not (Test-Path $root)) { "missing: $root"; continue }
  Get-ChildItem $root -Recurse -Filter *.py | Select-String -Pattern 'mention|orgid' |
    ForEach-Object { $l = $_.Line.Trim(); "{0}:{1}: {2}" -f ($_.Path -replace '^.*site-packages\\', ''), $_.LineNumber, $l.Substring(0, [Math]::Min(180, $l.Length)) }
}
$out | Out-File "$env:TEMP\sdk-mention.txt" -Encoding utf8
"lines: $(@($out).Count)"
