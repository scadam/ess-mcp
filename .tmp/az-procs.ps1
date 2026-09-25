$out = 'C:\Users\scadam\AgentsToolkitProjects\ess-mcp\.tmp\az-procs.txt'
$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'azure\.cli' -or ($_.CommandLine -match 'az\.cmd') }
$procs | Select-Object ProcessId, CreationDate, @{n = 'cmd'; e = { $_.CommandLine.Substring(0, [Math]::Min(160, $_.CommandLine.Length)) } } | Format-Table -AutoSize | Out-String -Width 300 | Set-Content $out
