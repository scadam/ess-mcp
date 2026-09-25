Get-Content "$env:LOCALAPPDATA\Microsoft.Agents.A365.DevTools.Cli\logs\a365.publish.log" -Tail 60 |
  Where-Object { $_ -match '\[(INF|WRN|ERR)\]' } | Select-Object -Last 14 |
  ForEach-Object { $l = $_ -replace '[A-Za-z0-9~_\.\-]{40,}', '<redacted>'; $l.Substring(0, [Math]::Min(200, $l.Length)) }
