targetScope = 'resourceGroup'

@allowed(['eastus2'])
param location string = 'eastus2'

@description('Never create an app with an unverified image or missing A365 configuration. Foundation-only by default.')
param deployApp bool = false

@description('Immutable image in the existing Caldova registry: cressmcpcaldovaf61b.azurecr.io/<repository>@sha256:<64 lowercase hex>. Required when deployApp=true.')
param containerImage string = ''

@description('New Caldova A365 blueprint application (client) ID; do not use the old tenant.')
param blueprintClientId string = ''

@description('Optional primary agent identity object ID. AI teammate blueprints have per-instance identities only.')
param agentIdentityObjectId string = ''

@description('New Caldova control plane SPA client ID.')
param controlPlaneClientId string = ''

@description('Exact API audience registered in Caldova for the control plane.')
param controlPlaneAudience string = ''

@description('Exact delegated API scope registered in Caldova for the control plane.')
param controlPlaneScope string = ''

@description('Name of a pre-seeded blueprint credential secret in the EXISTING Caldova Key Vault. Never pass its value in ARM.')
param blueprintSecretName string = ''

@description('Explicit Caldova operator object ID allowlist. The authenticated web API otherwise has no operator.')
@minLength(1)
param operatorObjectId string = '3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d'

@description('Optional already-reviewed nonsecret per-server HTTPS MCP URLs, keyed by server name. Do not populate from old-tenant endpoints.')
param mcpUrls object = {}

@description('Nonsecret JSON array of verified Compliance Partner bindings (instance, agentic user, manager, requesters, evidence paths). Empty disables the workflow.')
param complianceBindings string = ''

@description('Nonsecret JSON array of case desk bindings (function colleague, system of record, playbook, instance). Empty disables the desk.')
param deskBindings string = ''

@description('Existing Key Vault secret names holding webhook signing keys, keyed by source (servicenow, salesforce). Values never pass through ARM.')
param webhookSecretNames object = {}

@description('Integration usernames whose own writes the case desk ignores, keyed by source.')
param integrationUsers object = {}

@description('Scope of the managed-identity assertion the host sends to MCP servers for host-only tools. Empty disables it.')
param callerScope string = ''

@description('Drive (document library) id where colleagues file each run\'s files and manifest as themselves, and its URL. Empty disables filing.')
param runRecordsDriveId string = ''
param runRecordsUrl string = ''

@description('Tags only; no credential or old-tenant values.')
param tags object = {
  'app-onboard-skill': 'true'
  'app-onboard-session-id': '78f002fe-15a9-4ba1-a633-f366fd8558a4'
  'created-at': '2026-09-22T15:09:25Z'
  'deployed-by': 'Microsoft Administrator'
  application: 'group-functions-autopilot'
  environment: 'caldova'
  managedBy: 'bicep'
}

var names = {
  app: 'ca-autopilot-caldova-78f0'
  identity: 'id-autopilot-caldova-78f0'
  storage: 'stautopilotcaldova78f0'
  model: 'oai-autopilot-caldova-78f0'
  insights: 'appi-autopilot-caldova-78f0'
  environment: 'cae-essmcp-caldova-f61b2'
  registry: 'cressmcpcaldovaf61b'
  vault: 'kv-essmcp-caldova-f61b'
  workspace: 'log-essmcp-caldova-f61b'
}

var registryPrefix = '${names.registry}.azurecr.io/'
var imageParts = split(containerImage, '@sha256:')
var digest = last(imageParts)
var validImage = startsWith(containerImage, registryPrefix) && length(imageParts) == 2 && length(first(imageParts)) > length(registryPrefix) && length(digest) == 64 && empty(filter(range(0, length(digest)), index => !contains('0123456789abcdef', substring(digest, index, 1))))
var hasA365Config = length(blueprintClientId) == 36 && (empty(agentIdentityObjectId) || length(agentIdentityObjectId) == 36) && length(controlPlaneClientId) == 36 && !empty(controlPlaneAudience) && !empty(controlPlaneScope) && !empty(blueprintSecretName) && length(operatorObjectId) == 36
// The existing host connects only these four server names; the seven apps are not modified.
var allowedMcpNames = ['workday', 'servicenow', 'salesforce', 'coupa']
var mcpUrlsValid = length(objectKeys(mcpUrls)) == length(allowedMcpNames) && empty(filter(objectKeys(mcpUrls), name => !contains(allowedMcpNames, name) || !startsWith(string(mcpUrls[name]), 'https://') || contains(string(mcpUrls[name]), '@')))
var appReady = deployApp ? validImage && hasA365Config && mcpUrlsValid : empty(containerImage) && empty(blueprintClientId) && empty(agentIdentityObjectId) && empty(controlPlaneClientId) && empty(controlPlaneAudience) && empty(controlPlaneScope) && empty(blueprintSecretName) && empty(mcpUrls)
var mcpEnvironmentPairs = [for name in objectKeys(mcpUrls): [
  { name: 'ESS_${toUpper(replace(name, '_', ''))}_MCP_URL', value: string(mcpUrls[name]) }
  // The Caldova MCP servers mint their own SaaS tokens when no caller bearer is sent.
  { name: 'ESS_${toUpper(replace(name, '_', ''))}_AUTH_MODE', value: 'server-managed' }
]]
var mcpEnvironment = flatten(mcpEnvironmentPairs)
var webhookSources = filter(objectKeys(webhookSecretNames), source => contains(['servicenow', 'salesforce'], source))
var integrationSources = filter(objectKeys(integrationUsers), source => contains(['servicenow', 'salesforce'], source))
var webhookEnvironment = [for source in webhookSources: { name: 'AUTOPILOT_WEBHOOK_SECRET_${toUpper(source)}', secretRef: 'webhook-${source}' }]
var integrationEnvironment = [for source in integrationSources: { name: 'AUTOPILOT_${toUpper(source)}_INTEGRATION_USER', value: string(integrationUsers[source]) }]
var webhookAppSecrets = [for source in webhookSources: { name: 'webhook-${source}', keyVaultUrl: 'https://${names.vault}${az.environment().suffixes.keyvaultDns}/secrets/${string(webhookSecretNames[source])}', identity: identity.id }]
var deskEnvironment = concat(
  empty(deskBindings) ? [] : [{ name: 'AUTOPILOT_DESK_BINDINGS', value: deskBindings }],
  webhookEnvironment,
  integrationEnvironment,
  empty(callerScope) ? [] : [{ name: 'AUTOPILOT_CALLER_SCOPE', value: callerScope }],
  empty(runRecordsDriveId) ? [] : [{ name: 'AUTOPILOT_RUN_RECORDS_DRIVE_ID', value: runRecordsDriveId }, { name: 'AUTOPILOT_RUN_RECORDS_URL', value: runRecordsUrl }]
)

// any() intentionally defers literal narrowing to ARM's allowedValues without
// allowing callers to substitute their own scope or readiness assertion.
module guard './deployment-guard.bicep' = {
  name: 'autopilot-caldova-scope-guard'
  params: {
    actualSubscriptionId: any(subscription().subscriptionId)
    actualTenantId: any(tenant().tenantId)
    actualResourceGroupName: any(resourceGroup().name)
    appConfigurationIsReady: any(appReady)
  }
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: names.environment
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = {
  name: names.registry
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: names.vault
}

resource blueprintCredential 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = if (deployApp) {
  parent: vault
  name: blueprintSecretName
}

resource webhookSecrets 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = [for source in webhookSources: {
  parent: vault
  name: string(webhookSecretNames[source])
}]

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-07-01' existing = {
  name: names.workspace
}

// A separate identity: no role changes to the seven MCP servers' shared UAMI.
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: names.identity
  location: location
  tags: tags
  dependsOn: [guard]
}

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: names.storage
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  tags: tags
  properties: {
    accessTier: 'Hot'
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    // Tenant SFI policy forces Disabled unless perimeter-secured; the ACA environment has no VNet.
    publicNetworkAccess: 'SecuredByPerimeter'
    networkAcls: { defaultAction: 'Deny', bypass: 'None' }
  }
  dependsOn: [guard]
}

// Admits only managed identities from this subscription (Entra RBAC still applies); no keys, no public IP rules.
resource perimeter 'Microsoft.Network/networkSecurityPerimeters@2024-07-01' = {
  name: 'nsp-autopilot-caldova-78f0'
  location: location
  tags: tags
  properties: {}
  dependsOn: [guard]
}

resource perimeterProfile 'Microsoft.Network/networkSecurityPerimeters/profiles@2024-07-01' = {
  parent: perimeter
  name: 'autopilot-state'
  properties: {}
}

resource perimeterInbound 'Microsoft.Network/networkSecurityPerimeters/profiles/accessRules@2024-07-01' = {
  parent: perimeterProfile
  name: 'this-subscription-managed-identities'
  properties: {
    direction: 'Inbound'
    subscriptions: [{ id: subscription().id }]
  }
}

resource perimeterStorage 'Microsoft.Network/networkSecurityPerimeters/resourceAssociations@2024-07-01' = {
  parent: perimeter
  name: 'autopilot-state-storage'
  properties: {
    accessMode: 'Enforced'
    privateLinkResource: { id: storage.id }
    profile: { id: perimeterProfile.id }
  }
  dependsOn: [perimeterInbound]
}

// The vault's public access stays disabled; Container Apps resolve Key Vault references through the perimeter.
resource perimeterVault 'Microsoft.Network/networkSecurityPerimeters/resourceAssociations@2024-07-01' = {
  parent: perimeter
  name: 'essmcp-key-vault'
  properties: {
    accessMode: 'Enforced'
    privateLinkResource: { id: vault.id }
    profile: { id: perimeterProfile.id }
  }
  dependsOn: [perimeterStorage]
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
    containerDeleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource state 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: 'autopilot-state'
  properties: { publicAccess: 'None' }
}

resource openai 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: names.model
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  tags: tags
  properties: {
    customSubDomainName: names.model
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled' // Existing ACA environment requires public endpoint; Entra RBAC only.
  }
  dependsOn: [guard]
}

resource gpt 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openai
  name: 'gpt-4.1'
  sku: { name: 'GlobalStandard', capacity: 100 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4.1', version: '2025-04-14' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

// Skill runs plan on the reasoning tier and fan evidence gathering out to the fast tier.
// Deployments on one account are created one at a time.
resource reasoningModel 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openai
  name: 'gpt-5.4'
  sku: { name: 'GlobalStandard', capacity: 250 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-5.4', version: '2026-03-05' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [gpt]
}

resource fastModel 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openai
  name: 'gpt-4.1-mini'
  sku: { name: 'GlobalStandard', capacity: 200 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4.1-mini', version: '2025-04-14' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [reasoningModel]
}

// The Copilot SDK harness needs reasoning models: sub-agents and the planner run on the mini tier.
resource fastReasoningModel 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openai
  name: 'gpt-5.4-mini'
  sku: { name: 'GlobalStandard', capacity: 200 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-5.4-mini', version: '2026-03-17' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [fastModel]
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: names.insights
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    DisableLocalAuth: true
  }
  dependsOn: [guard]
}

var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var blobContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var openaiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var secretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

resource stateWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, blobContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributor)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource inferenceUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openai.id, identity.id, openaiUser)
  scope: openai
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openaiUser)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource imagePull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, acrPull)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [guard]
}

resource blueprintCredentialReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployApp) {
  name: guid(blueprintCredential.id, identity.id, secretsUser)
  scope: blueprintCredential
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUser)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [guard]
}

resource webhookSecretReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (source, index) in webhookSources: {
  name: guid(webhookSecrets[index].id, identity.id, secretsUser)
  scope: webhookSecrets[index]
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUser)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

// No image-less Container App is ever created. The SDK requires the actual
// A365 blueprint credential; its *value* is provided only via a KV reference.
resource app 'Microsoft.App/containerApps@2025-01-01' = if (deployApp) {
  name: names.app
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, allowInsecure: false, targetPort: 8091, transport: 'http' }
      registries: [{ server: '${names.registry}.azurecr.io', identity: identity.id }]
      secrets: concat([{ name: 'a365-blueprint-credential', keyVaultUrl: '${vault.properties.vaultUri}secrets/${blueprintSecretName}', identity: identity.id }], webhookAppSecrets)
    }
    template: {
      containers: [{
        name: 'autopilot'
        image: containerImage
        env: concat([
          { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
          { name: 'AZURE_TENANT_ID', value: tenant().tenantId }
          { name: 'ESS_WEB_HOST', value: '0.0.0.0' }
          { name: 'ESS_WEB_PORT', value: '8091' }
          { name: 'ESS_AGENT_DISPLAY_NAME', value: 'Group Functions Autopilot' }
          { name: 'ESS_PUBLIC_BASE_URL', value: 'https://${names.app}.${environment.properties.defaultDomain}' }
          { name: 'AUTOPILOT_ENVIRONMENT', value: 'production' }
          { name: 'AUTOPILOT_STORAGE_ACCOUNT_URL', value: 'https://${storage.name}.blob.${az.environment().suffixes.storage}' }
          { name: 'AUTOPILOT_STORAGE_CONTAINER', value: state.name }
          { name: 'AZURE_OPENAI_ENDPOINT', value: openai.properties.endpoint }
          { name: 'ESS_MODEL', value: gpt.name }
          { name: 'AUTOPILOT_MODEL_ROUTES', value: string({ reasoning: reasoningModel.name, standard: reasoningModel.name, fast: fastReasoningModel.name }) }
          { name: 'ENTRA_AGENT_BLUEPRINT_CLIENT_ID', value: blueprintClientId }
          { name: 'ENTRA_AGENT_IDENTITY_OBJECT_ID', value: agentIdentityObjectId }
          { name: 'CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID', value: blueprintClientId }
          { name: 'CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID', value: tenant().tenantId }
          { name: 'CONNECTIONS__SERVICE_CONNECTION__SETTINGS__SCOPES', value: '5a807f24-c9de-44ee-a3a7-329e88a00ffc/.default' }
          { name: 'CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET', secretRef: 'a365-blueprint-credential' }
          { name: 'AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__TYPE', value: 'AgenticUserAuthorization' }
          { name: 'AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__ALT_BLUEPRINT_NAME', value: 'SERVICE_CONNECTION' }
          { name: 'AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__SCOPES', value: 'https://graph.microsoft.com/.default' }
          { name: 'CONNECTIONSMAP__0__SERVICEURL', value: '*' }
          { name: 'CONNECTIONSMAP__0__CONNECTION', value: 'SERVICE_CONNECTION' }
          { name: 'AUTH_HANDLER_NAME', value: 'AGENTIC' }
          { name: 'AUTOPILOT_CONTROL_PLANE_CLIENT_ID', value: controlPlaneClientId }
          { name: 'AUTOPILOT_CONTROL_PLANE_AUDIENCE', value: controlPlaneAudience }
          { name: 'AUTOPILOT_CONTROL_PLANE_SCOPE', value: controlPlaneScope }
          { name: 'AUTOPILOT_OPERATOR_IDS', value: operatorObjectId }
          { name: 'AUTOPILOT_TASK_USER_IDS', value: operatorObjectId }
          { name: 'ESS_OBSERVE_TOOL_PAYLOADS', value: 'false' }
          { name: 'A365_CAPTURE_PROMPTS', value: 'false' }
          { name: 'ENABLE_A365_OBSERVABILITY_EXPORTER', value: 'false' }
          { name: 'AUTOPILOT_COMPLIANCE_BINDINGS', value: complianceBindings }
          { name: 'AUTOPILOT_COMPLIANCE_TEAMS_CHANNEL', value: 'graph' }
        ], mcpEnvironment, deskEnvironment)
        resources: { cpu: json('1.0'), memory: '2Gi' }
        probes: [
          { type: 'Startup', httpGet: { path: '/healthz', port: 8091, scheme: 'HTTP' }, periodSeconds: 10, timeoutSeconds: 5, failureThreshold: 18 }
          { type: 'Readiness', httpGet: { path: '/healthz', port: 8091, scheme: 'HTTP' }, periodSeconds: 10, timeoutSeconds: 5, failureThreshold: 3 }
        ]
      }]
      scale: { minReplicas: 1, maxReplicas: 1 }
      terminationGracePeriodSeconds: 60
    }
  }
  dependsOn: [stateWriter, inferenceUser, imagePull, blueprintCredentialReader, perimeterStorage, perimeterVault, webhookSecretReaders]
}

output identityResourceId string = identity.id
output identityPrincipalId string = identity.properties.principalId
output storageAccountName string = storage.name
output stateContainerName string = state.name
output modelAccountName string = openai.name
output modelDeploymentName string = gpt.name
output appResourceId string = deployApp ? app.id : ''
