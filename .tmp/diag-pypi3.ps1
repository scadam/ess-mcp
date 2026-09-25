$r = Invoke-WebRequest 'https://pypi.org/simple/microsoft-agents-hosting-aiohttp/' -Headers @{ Accept = 'application/vnd.pypi.simple.v1+json' } -UseBasicParsing -TimeoutSec 30
$body = [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
"bytes=$($body.Length) has170=$($body.Contains('1.7.0'))"
$j = $body | ConvertFrom-Json
"name=$($j.name) versions=$(@($j.versions).Count) files=$(@($j.files).Count) last=" + ((@($j.versions) | Select-Object -Last 3) -join ',')
"meta: last-serial=$($j.meta.'_last-serial') api=$($j.meta.'api-version')"
$r.Headers.Keys | Where-Object { $_ -match 'Age|Served|Cache|X-PyPI|Last-Modified|ETag' } | ForEach-Object { "$_=$($r.Headers[$_])" }
