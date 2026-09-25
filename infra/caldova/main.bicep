targetScope = 'subscription'

import { DeploymentTags, ServerConfig, ServerEndpoint } from './types.bicep'

@allowed(['essmcp-caldova-f61b'])
param environmentName string

@allowed(['eastus'])
param location string

@description('Compute-only regional fallback after East US platform capacity exhaustion; foundation resources remain in East US.')
@allowed(['eastus2'])
param computeLocation string = 'eastus2'

@minLength(1)
param sessionId string

@minLength(1)
param deployedBy string

@description('Stable ISO 8601 creation timestamp, captured at scaffold time and reused on redeployment.')
@minLength(1)
param createdAt string

@description('Approved new-tenant user object ID; grants secret seeding access on this vault only.')
@allowed(['3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d'])
param deployerObjectId string

@description('False provisions foundation and RBAC only. Enable only after image testing, vault seeding, and RBAC propagation.')
param deployApps bool = false

@description('Tested image in the new registry, pinned as repository@sha256:digest. Empty is permitted only when deployApps=false.')
param containerImage string = ''

@description('All seven configurations; non-secret values and Key Vault references only. Workday, Salesforce and ServiceNow use bearer-first stored-credential fallback. Optional per-server images permit targeted updates.')
@maxLength(7)
param serverConfigs ServerConfig[] = []

// These names are copied verbatim from the approved plan; no generated suffixes.
var resourceNames = {
  resourceGroup: 'essmcp-caldova-rg'
  registry: 'cressmcpcaldovaf61b'
  logAnalytics: 'log-essmcp-caldova-f61b'
  identity: 'id-essmcp-caldova-f61b'
  keyVault: 'kv-essmcp-caldova-f61b'
  containerEnvironment: 'cae-essmcp-caldova-f61b2'
}

var tags DeploymentTags = {
  'app-onboard-skill': 'true'
  'app-onboard-session-id': sessionId
  'created-at': createdAt
  environment: environmentName
  'deployed-by': deployedBy
}

// This catalog contains names and classifications only, never existing backend values.
var serverCatalog = loadJsonContent('./server-catalog.json')
var appNames = map(serverConfigs, server => server.name)
var cliNames = map(serverConfigs, server => server.cliName)
var registryImagePrefix = '${resourceNames.registry}.azurecr.io/'
// Intentionally pinned to this public-cloud vault; reject references to the original tenant's vault.
#disable-next-line no-hardcoded-env-urls
var vaultSecretPrefix = 'https://${resourceNames.keyVault}.vault.azure.net/secrets/'
var selectedImages = concat([containerImage], map(serverConfigs, server => server.?image ?? containerImage))
var imageChecks = [for image in selectedImages: {
  validPrefix: startsWith(image, registryImagePrefix)
  validParts: length(split(image, '@sha256:')) == 2 && length(first(split(image, '@sha256:'))) > length(registryImagePrefix)
  validDigestLength: length(last(split(image, '@sha256:'))) == 64
  digestIsHex: empty(filter(range(0, length(last(split(image, '@sha256:')))), index => !contains('0123456789abcdef', substring(last(split(image, '@sha256:')), index, 1))))
}]

var runtimeChecks = [for server in serverConfigs: {
  nameMatches: server.name == serverCatalog[server.cliName].name
  uniqueEnvNames: length(server.env) == length(union(map(server.env, setting => setting.name), map(server.env, setting => setting.name)))
  uniqueSecretNames: length(server.secrets) == length(union(map(server.secrets, secret => secret.name), map(server.secrets, secret => secret.name)))
  knownEnvNames: empty(filter(server.env, setting => !contains(serverCatalog[server.cliName].plainEnv, setting.name) && !contains(serverCatalog[server.cliName].secretEnv, setting.name)))
  exactlyOneValueSource: empty(filter(server.env, setting => contains(setting, 'value') == contains(setting, 'secretRef')))
  credentialsAreReferences: empty(filter(server.env, setting => contains(serverCatalog[server.cliName].secretEnv, setting.name) && (contains(setting, 'value') || empty(setting.?secretRef ?? ''))))
  referencesExist: empty(filter(server.env, setting => contains(setting, 'secretRef') && !contains(map(server.secrets, secret => secret.name), setting.?secretRef ?? '')))
  requiredEnvPresent: empty(filter(serverCatalog[server.cliName].requiredEnv, requiredName => empty(filter(server.env, setting => setting.name == requiredName && (!empty(trim(setting.?value ?? '')) || !empty(setting.?secretRef ?? ''))))))
  vaultUrlsMatch: empty(filter(server.secrets, secret => !startsWith(secret.keyVaultUrl, vaultSecretPrefix) || length(secret.keyVaultUrl) <= length(vaultSecretPrefix) || contains(secret.keyVaultUrl, '?') || contains(secret.keyVaultUrl, '#')))
  noUnusedSecrets: empty(filter(server.secrets, secret => !contains(map(server.env, setting => setting.?secretRef ?? ''), secret.name)))
  salesforceBearerFirst: server.cliName != 'salesforce' || empty(filter(server.env, setting => setting.name == 'SF_AUTH_MODE' && (setting.?value ?? '') != 'auto'))
}]

var topologyIsValid = length(serverConfigs) == 7 && length(union(appNames, appNames)) == 7 && length(union(cliNames, cliNames)) == 7
var invalidRuntimeChecks = filter(runtimeChecks, check => !check.nameMatches || !check.uniqueEnvNames || !check.uniqueSecretNames || !check.knownEnvNames || !check.exactlyOneValueSource || !check.credentialsAreReferences || !check.referencesExist || !check.requiredEnvPresent || !check.vaultUrlsMatch || !check.noUnusedSecrets || !check.salesforceBearerFirst)
var runtimeConfigurationIsValid = deployApps ? topologyIsValid && empty(invalidRuntimeChecks) : empty(serverConfigs)

var imageIsReady = !deployApps || empty(filter(imageChecks, check => !check.validPrefix || !check.validParts || !check.validDigestLength || !check.digestIsHex))

// A resource-free nested deployment validates actual scope, not caller-supplied scope claims.
// Its failure prevents creation or modification of the resource group and all foundation modules.
// any() defers these literal-type checks to ARM allowedValues without changing the runtime values.
module deploymentGuard './modules/deployment-guard.bicep' = {
  params: {
    actualSubscriptionId: any(subscription().subscriptionId)
    actualTenantId: any(tenant().tenantId)
    imageIsReady: any(imageIsReady)
    runtimeConfigurationIsValid: any(runtimeConfigurationIsValid)
  }
}

resource resourceGroup 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: resourceNames.resourceGroup
  location: location
  tags: tags
  dependsOn: [deploymentGuard]
}

module containerRegistry './modules/container-registry.bicep' = {
  scope: resourceGroup
  params: {
    registryName: resourceNames.registry
    location: location
    tags: tags
  }
}

module logAnalytics './modules/log-analytics.bicep' = {
  scope: resourceGroup
  params: {
    workspaceName: resourceNames.logAnalytics
    location: location
    tags: tags
  }
}

module runtimeIdentity './modules/managed-identity.bicep' = {
  scope: resourceGroup
  params: {
    identityName: resourceNames.identity
    location: location
    tags: tags
  }
}

module keyVault './modules/key-vault.bicep' = {
  scope: resourceGroup
  params: {
    vaultName: resourceNames.keyVault
    location: location
    tags: tags
  }
}

module containerEnvironment './modules/container-app-environment.bicep' = {
  scope: resourceGroup
  params: {
    environmentName: resourceNames.containerEnvironment
    location: computeLocation
    tags: tags
    workspaceResourceId: logAnalytics.outputs.resourceId
  }
}

module roleAssignments './modules/role-assignments.bicep' = {
  scope: resourceGroup
  params: {
    registryName: containerRegistry.outputs.name
    vaultName: keyVault.outputs.name
    runtimePrincipalId: runtimeIdentity.outputs.principalId
    deployerObjectId: deployerObjectId
  }
}

// No placeholder application. The main thread supplies the tested image and seeded-vault references.
module containerApps './modules/container-apps.bicep' = if (deployApps) {
  scope: resourceGroup
  params: {
    location: computeLocation
    tags: tags
    environmentResourceId: containerEnvironment.outputs.resourceId
    runtimeIdentityResourceId: runtimeIdentity.outputs.resourceId
    registryLoginServer: containerRegistry.outputs.loginServer
    containerImage: containerImage
    serverConfigs: serverConfigs
  }
  dependsOn: [roleAssignments]
}

// Only resource identifiers and public endpoints are outputs. Secret values never enter ARM.
output resourceGroupName string = resourceGroup.name
output registryName string = containerRegistry.outputs.name
output registryLoginServer string = containerRegistry.outputs.loginServer
output keyVaultName string = keyVault.outputs.name
output keyVaultUri string = keyVault.outputs.vaultUri
output runtimeIdentityResourceId string = runtimeIdentity.outputs.resourceId
output runtimeIdentityPrincipalId string = runtimeIdentity.outputs.principalId
output runtimeIdentityClientId string = runtimeIdentity.outputs.clientId
output logAnalyticsResourceId string = logAnalytics.outputs.resourceId
output containerEnvironmentResourceId string = containerEnvironment.outputs.resourceId
output containerEnvironmentDefaultDomain string = containerEnvironment.outputs.defaultDomain
output endpoints ServerEndpoint[] = containerApps.?outputs.endpoints ?? []
