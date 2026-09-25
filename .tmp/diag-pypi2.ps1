foreach ($accept in 'application/vnd.pypi.simple.v1+json', 'application/vnd.pypi.simple.v1+html', 'text/html') {
  $r = Invoke-WebRequest 'https://pypi.org/simple/microsoft-agents-hosting-aiohttp/' -Headers @{ Accept = $accept } -UseBasicParsing -TimeoutSec 30
  $body = [string]$r.Content
  "{0}: status={1} type={2} bytes={3} has170whl={4} age={5}" -f $accept, $r.StatusCode, $r.Headers['Content-Type'], $body.Length, $body.Contains('microsoft_agents_hosting_aiohttp-1.7.0-py3-none-any.whl'), $r.Headers['Age']
}
