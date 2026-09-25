$lines = Get-Content "$env:TEMP\ap-buildlog2.txt"
$s = ($lines | Select-String -Pattern 'Step 6/13' | Select-Object -First 1).LineNumber
$e = ($lines | Select-String -Pattern 'ResolutionImpossible' | Select-Object -First 1).LineNumber
"lines $s..$e"
$lines[($s - 1)..($e)] | Where-Object { $_ -notmatch '^\s*(Collecting|Downloading)' } |
  ForEach-Object { $_.Substring(0, [Math]::Min(200, $_.Length)) }
$lines | Select-String -Pattern 'pip \d|Digest:|Pulling from|devcontainers/python' | Select-Object -First 8 |
  ForEach-Object { $_.Line.Substring(0, [Math]::Min(200, $_.Line.Length)) }
