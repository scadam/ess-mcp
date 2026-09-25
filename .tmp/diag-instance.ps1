$env:AZURE_CONFIG_DIR = "$env:LOCALAPPDATA\ess-mcp\azure-caldova74201480"
foreach ($ver in 'beta', 'v1.0') {
  $sp = az rest --method GET --url "https://graph.microsoft.com/$ver/servicePrincipals/a6a9c9be-e1ee-4abc-b661-c8f906dd79b4" -o json | ConvertFrom-Json
  "{0}: id={1} appId={2} type={3} odata={4} blueprint={5} name={6}" -f $ver, $sp.id, $sp.appId, $sp.servicePrincipalType, $sp.'@odata.type', $sp.agentIdentityBlueprintId, $sp.displayName
}
$list = az rest --method GET --url "https://graph.microsoft.com/v1.0/servicePrincipals/microsoft.graph.agentIdentity" --url-parameters "`$filter=agentIdentityBlueprintId eq '77ae0985-4084-4bc1-bb3c-ab6dd0ad9bde'" -o json | ConvertFrom-Json
$list.value | ForEach-Object { "list: id={0} appId={1} name={2}" -f $_.id, $_.appId, $_.displayName }
