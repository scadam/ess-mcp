$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
$label = 'defa4170-0d19-0005-0005-bc88714345d2'
foreach ($url in 'https://graph.microsoft.com/beta/security/informationProtection/sensitivityLabels',
                 'https://graph.microsoft.com/beta/me/security/informationProtection/sensitivityLabels',
                 'https://graph.microsoft.com/v1.0/security/informationProtection/sensitivityLabels') {
  $file = Join-Path $env:TEMP 'ap-labels.json'
  az rest --method get --url $url --output-file $file 2>$env:TEMP\ap-labels-err.txt
  if ($LASTEXITCODE -eq 0) {
    $labels = (Get-Content $file -Raw | ConvertFrom-Json).value
    "$url -> $(@($labels).Count) labels"
    $match = @($labels) | Where-Object { $_.id -eq $label }
    if ($match) { "label $label = '$($match.name)' active=$($match.isActive) appliesTo=$($match.applicableTo)" } else { "label $label NOT found. Labels: " + ((@($labels) | ForEach-Object { "$($_.name) ($($_.id))" }) -join '; ') }
    break
  } else { "$url -> failed: " + ((Get-Content $env:TEMP\ap-labels-err.txt -Raw) -replace '\s+', ' ').Substring(0, 200) }
}
exit 0
