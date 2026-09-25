$r = Invoke-WebRequest 'https://pypi.org/simple/microsoft-agents-hosting-aiohttp/' -Headers @{ Accept = 'application/vnd.pypi.simple.v1+json' } -UseBasicParsing -TimeoutSec 30
"status=$($r.StatusCode) age=$($r.Headers['Age']) served-by=$($r.Headers['X-Served-By'])"
$j = $r.Content | ConvertFrom-Json
"versions: " + (($j.versions | Select-Object -Last 4) -join ', ')
$j.files | Where-Object { $_.filename -match '1\.7\.0' } | ForEach-Object { "{0} yanked={1} py={2}" -f $_.filename, $_.yanked, $_.'requires-python' }
$h = Invoke-WebRequest 'https://pypi.org/simple/microsoft-agents-hosting-aiohttp/' -UseBasicParsing -TimeoutSec 30
"html has 1.7.0 wheel: " + ($h.Content -match 'microsoft_agents_hosting_aiohttp-1\.7\.0-py3-none-any\.whl')
