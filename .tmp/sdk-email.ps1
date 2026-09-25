$p = & 'C:\Users\scadam\AgentsToolkitProjects\ess-mcp\.venv\Scripts\python.exe' -c "import microsoft_agents_a365.notifications as m, os; print(os.path.dirname(m.__file__))"
Get-ChildItem $p -Recurse -Filter *.py | Where-Object { $_.Name -in 'email_reference.py', 'email_response.py' } | ForEach-Object {
  "=== $($_.Name)"
  Get-Content $_.FullName | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') } | Select-Object -First 45
} | Out-File "$env:TEMP\ap-sdk-email.txt" -Encoding utf8
