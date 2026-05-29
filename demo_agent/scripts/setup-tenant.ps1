param(
    [string]$TenantId = "8030d928-e557-4a4c-ae1e-95c1c4125eaa",
    [string]$SubscriptionId = "35b71905-e334-430e-bee1-1575c104c487",
    [string]$ResourceGroup = "essmcp-rg",
    [string]$Location = "eastus",
    [string]$BlueprintDisplayName = "ESS Workday ServiceNow Agent Blueprint",
    [string]$AgentDisplayName = "ESS Workday ServiceNow Hosted Demo Agent",
    [string]$ApimName = "",
    [string]$PublisherEmail = "scadam@microsoft.com",
    [string]$PublisherName = "ESS MCP Demo",
    [string]$WorkdayContainerApp = "essmcp-workday",
    [string]$ServiceNowContainerApp = "essmcp-servicenow",
    [string]$AzureOpenAIEndpoint = "https://essmcp-openai.openai.azure.com/",
    [string]$ModelDeployment = "gpt-5.4-1",
    [string]$EnvPath = "demo_agent/.env"
)

$ErrorActionPreference = "Stop"

function Write-Step($message) {
    Write-Host "`n==> $message" -ForegroundColor Cyan
}

function Get-GraphCollectionAll($Uri) {
    $items = @()
    $next = $Uri
    while ($next) {
        $page = Invoke-MgGraphRequest -Method GET -Uri $next -Headers @{ "OData-Version" = "4.0" }
        if ($page.value) {
            $items += $page.value
        }
        $next = $page.'@odata.nextLink'
    }
    return $items
}

function Set-EnvValue($Path, $Name, $Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return }
    $line = "$Name=$Value"
    if (-not (Test-Path $Path)) {
        New-Item -ItemType File -Path $Path -Force | Out-Null
    }
    $content = Get-Content -Path $Path -ErrorAction SilentlyContinue
    $escaped = [regex]::Escape($Name)
    if ($content -match "^$escaped=") {
        $content = $content | ForEach-Object { if ($_ -match "^$escaped=") { $line } else { $_ } }
    } else {
        $content += $line
    }
    Set-Content -Path $Path -Value $content -Encoding utf8
}

function New-ApimOperationIfMissing($ApimName, $ResourceGroup, $ApiId, $OperationId, $Method, $UrlTemplate, $DisplayName) {
    $existing = az apim api operation show `
        --resource-group $ResourceGroup `
        --service-name $ApimName `
        --api-id $ApiId `
        --operation-id $OperationId `
        --query name -o tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and $existing) {
        return
    }
    az apim api operation create `
        --resource-group $ResourceGroup `
        --service-name $ApimName `
        --api-id $ApiId `
        --operation-id $OperationId `
        --display-name $DisplayName `
        --method $Method `
        --url-template $UrlTemplate | Out-Null
}

function Set-ApimOperationPolicy($ApimName, $ResourceGroup, $ApiId, $OperationId, $BackendBaseUrl) {
    $policy = @"
<policies>
  <inbound>
    <base />
    <choose>
      <when condition="@(context.Request.Headers.GetValueOrDefault(&quot;Authorization&quot;, &quot;&quot;).StartsWith(&quot;Bearer &quot;))" />
      <otherwise>
        <return-response>
          <set-status code="401" reason="Authorization bearer token is required" />
        </return-response>
      </otherwise>
    </choose>
    <check-header name="X-Agent-Identity-Id" failed-check-httpcode="400" failed-check-error-message="X-Agent-Identity-Id is required" ignore-case="true" />
    <check-header name="X-Agent-Blueprint-Client-Id" failed-check-httpcode="400" failed-check-error-message="X-Agent-Blueprint-Client-Id is required" ignore-case="true" />
    <set-header name="X-Gateway-Policy" exists-action="override">
      <value>ess-mcp-workday-servicenow</value>
    </set-header>
    <set-backend-service base-url="$BackendBaseUrl" />
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
"@
    $body = @{
        properties = @{
            format = "rawxml"
            value = $policy
        }
    }
    $token = az account get-access-token --resource https://management.azure.com/ --query accessToken -o tsv
    $policyUri = "https://management.azure.com/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.ApiManagement/service/$ApimName/apis/$ApiId/operations/$OperationId/policies/policy?api-version=2022-08-01"
    Invoke-RestMethod `
        -Method Put `
        -Uri $policyUri `
        -Headers @{ Authorization = "Bearer $token" } `
        -ContentType "application/json" `
        -Body ($body | ConvertTo-Json -Depth 10) | Out-Null
}

Write-Step "Configuring Azure CLI subscription"
az account set --subscription $SubscriptionId

Write-Step "Resolving current signed-in user"
$currentUserJson = az ad signed-in-user show -o json
$currentUser = $currentUserJson | ConvertFrom-Json
$currentUserId = $currentUser.id
if (-not $currentUserId) {
    throw "Unable to resolve signed-in user ID."
}

Write-Step "Connecting to Microsoft Graph with Agent Identity delegated scopes"
$scopes = @(
    "AgentIdentityBlueprint.Create",
    "AgentIdentityBlueprint.ReadWrite.All",
    "AgentIdentityBlueprintPrincipal.Create",
    "AgentIdentity.Create.All",
    "Application.ReadWrite.All",
    "User.Read"
)
Connect-MgGraph -TenantId $TenantId -Scopes $scopes -NoWelcome | Out-Null

Write-Step "Creating or reusing Agent Identity Blueprint"
$escapedBlueprintDisplayName = $BlueprintDisplayName.Replace("'", "''")
$blueprints = Get-GraphCollectionAll "https://graph.microsoft.com/v1.0/applications?`$filter=displayName eq '$escapedBlueprintDisplayName'"
$blueprint = $blueprints | Where-Object { $_.'@odata.type' -eq '#microsoft.graph.agentIdentityBlueprint' -or $_.displayName -eq $BlueprintDisplayName } | Select-Object -First 1
if (-not $blueprint) {
    $body = @{
        displayName = $BlueprintDisplayName
        "sponsors@odata.bind" = @("https://graph.microsoft.com/v1.0/users/$currentUserId")
    }
    $blueprint = Invoke-MgGraphRequest `
        -Method POST `
        -Uri "https://graph.microsoft.com/v1.0/applications/microsoft.graph.agentIdentityBlueprint" `
        -Headers @{ "OData-Version" = "4.0" } `
        -Body ($body | ConvertTo-Json -Depth 10) `
        -ContentType "application/json"
}
$blueprintAppId = $blueprint.appId
$blueprintObjectId = $blueprint.id
if (-not $blueprintAppId) {
    throw "Blueprint creation/retrieval did not return appId."
}

Write-Step "Creating or reusing Agent Identity BlueprintPrincipal"
$blueprintPrincipal = $null
$principalLookup = Get-GraphCollectionAll "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=appId eq '$blueprintAppId'"
$blueprintPrincipal = $principalLookup | Select-Object -First 1
if (-not $blueprintPrincipal) {
    $spBody = @{ appId = $blueprintAppId }
    $blueprintPrincipal = Invoke-MgGraphRequest `
        -Method POST `
        -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/microsoft.graph.agentIdentityBlueprintPrincipal" `
        -Headers @{ "OData-Version" = "4.0" } `
        -Body ($spBody | ConvertTo-Json -Depth 10) `
        -ContentType "application/json"
}
$blueprintPrincipalId = $blueprintPrincipal.id

Write-Step "Creating or reusing Agent Identity instance"
$escapedAgentDisplayName = $AgentDisplayName.Replace("'", "''")
$agentCandidates = Get-GraphCollectionAll "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=displayName eq '$escapedAgentDisplayName'"
$agent = $agentCandidates | Select-Object -First 1
if (-not $agent) {
    $agentBody = @{
        displayName = $AgentDisplayName
        agentIdentityBlueprintId = $blueprintAppId
        "sponsors@odata.bind" = @("https://graph.microsoft.com/v1.0/users/$currentUserId")
    }
    $agent = Invoke-MgGraphRequest `
        -Method POST `
        -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/microsoft.graph.agentIdentity" `
        -Headers @{ "OData-Version" = "4.0" } `
        -Body ($agentBody | ConvertTo-Json -Depth 10) `
        -ContentType "application/json"
}
$agentObjectId = $agent.id
$agentClientId = $agent.appId

Write-Step "Resolving MCP container app FQDNs"
$workdayFqdn = az containerapp show -g $ResourceGroup -n $WorkdayContainerApp --query "properties.configuration.ingress.fqdn" -o tsv
$serviceNowFqdn = az containerapp show -g $ResourceGroup -n $ServiceNowContainerApp --query "properties.configuration.ingress.fqdn" -o tsv
if (-not $workdayFqdn -or -not $serviceNowFqdn) {
    throw "Unable to resolve Workday or ServiceNow Container App FQDN."
}

Write-Step "Creating or reusing APIM Consumption gateway"
if (-not $ApimName) {
    $suffix = ($TenantId.Split('-')[0]).ToLowerInvariant()
    $ApimName = "essmcp-gw-$suffix"
}
$existingApim = az apim show -g $ResourceGroup -n $ApimName --query name -o tsv 2>$null
if ($LASTEXITCODE -ne 0 -or -not $existingApim) {
    az apim create `
        --resource-group $ResourceGroup `
        --name $ApimName `
        --location $Location `
        --publisher-email $PublisherEmail `
        --publisher-name $PublisherName `
        --sku-name Consumption `
        --enable-managed-identity true | Out-Null
}
$gatewayUrl = az apim show -g $ResourceGroup -n $ApimName --query gatewayUrl -o tsv

Write-Step "Creating MCP API and operations"
$apiId = "ess-mcp"
$existingApi = az apim api show -g $ResourceGroup --service-name $ApimName --api-id $apiId --query name -o tsv 2>$null
if ($LASTEXITCODE -ne 0 -or -not $existingApi) {
    az apim api create `
        --resource-group $ResourceGroup `
        --service-name $ApimName `
        --api-id $apiId `
        --path "ess-mcp" `
        --display-name "ESS MCP Workday ServiceNow" `
        --protocols https `
        --subscription-required false `
        --service-url "https://$workdayFqdn" | Out-Null
} else {
    az apim api update `
        --resource-group $ResourceGroup `
        --service-name $ApimName `
        --api-id $apiId `
        --set subscriptionRequired=false | Out-Null
}

foreach ($method in @("GET", "POST", "DELETE")) {
    New-ApimOperationIfMissing $ApimName $ResourceGroup $apiId "workday-$($method.ToLowerInvariant())" $method "/workday/mcp" "Workday MCP $method"
    New-ApimOperationIfMissing $ApimName $ResourceGroup $apiId "servicenow-$($method.ToLowerInvariant())" $method "/servicenow/mcp" "ServiceNow MCP $method"
    Set-ApimOperationPolicy $ApimName $ResourceGroup $apiId "workday-$($method.ToLowerInvariant())" "https://$workdayFqdn"
    Set-ApimOperationPolicy $ApimName $ResourceGroup $apiId "servicenow-$($method.ToLowerInvariant())" "https://$serviceNowFqdn"
}

Write-Step "Writing runtime configuration to $EnvPath"
Set-EnvValue $EnvPath "AZURE_TENANT_ID" $TenantId
Set-EnvValue $EnvPath "ENTRA_AGENT_BLUEPRINT_CLIENT_ID" $blueprintAppId
Set-EnvValue $EnvPath "ENTRA_AGENT_BLUEPRINT_OBJECT_ID" $blueprintObjectId
Set-EnvValue $EnvPath "ENTRA_AGENT_BLUEPRINT_PRINCIPAL_ID" $blueprintPrincipalId
Set-EnvValue $EnvPath "ENTRA_AGENT_IDENTITY_OBJECT_ID" $agentObjectId
Set-EnvValue $EnvPath "ENTRA_AGENT_IDENTITY_CLIENT_ID" $agentClientId
Set-EnvValue $EnvPath "ESS_AGENT_DISPLAY_NAME" $AgentDisplayName
Set-EnvValue $EnvPath "AZURE_OPENAI_ENDPOINT" $AzureOpenAIEndpoint
Set-EnvValue $EnvPath "ESS_MODEL" $ModelDeployment
Set-EnvValue $EnvPath "ESS_AI_GATEWAY_BASE_URL" "$gatewayUrl/ess-mcp"
Set-EnvValue $EnvPath "ESS_WORKDAY_AI_GATEWAY_MCP_URL" "$gatewayUrl/ess-mcp/workday/mcp"
Set-EnvValue $EnvPath "ESS_SERVICENOW_AI_GATEWAY_MCP_URL" "$gatewayUrl/ess-mcp/servicenow/mcp"

$result = [ordered]@{
    tenantId = $TenantId
    subscriptionId = $SubscriptionId
    resourceGroup = $ResourceGroup
    blueprintClientId = $blueprintAppId
    blueprintObjectId = $blueprintObjectId
    blueprintPrincipalId = $blueprintPrincipalId
    agentIdentityObjectId = $agentObjectId
    agentIdentityClientId = $agentClientId
    apimName = $ApimName
    gatewayUrl = $gatewayUrl
    gatewayBaseUrl = "$gatewayUrl/ess-mcp"
    workdayMcpUrl = "$gatewayUrl/ess-mcp/workday/mcp"
    serviceNowMcpUrl = "$gatewayUrl/ess-mcp/servicenow/mcp"
    workdayBackend = "https://$workdayFqdn/workday/mcp"
    serviceNowBackend = "https://$serviceNowFqdn/servicenow/mcp"
}
$result | ConvertTo-Json -Depth 10
