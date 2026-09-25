targetScope = 'resourceGroup'

param registryName string
param vaultName string

@description('Object/principal ID of the shared runtime UAMI, not its client ID.')
param runtimePrincipalId string

@allowed(['3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d'])
param deployerObjectId string

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = {
  name: registryName
}

resource vault 'Microsoft.KeyVault/vaults@2026-05-15' existing = {
  name: vaultName
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var secretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var secretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

// Role assignments cannot be tagged. Each grant is confined to its target resource.
resource runtimeAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, runtimePrincipalId, acrPullRoleId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource runtimeSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, runtimePrincipalId, secretsUserRoleId)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
    principalId: runtimePrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerSecretsOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, deployerObjectId, secretsOfficerRoleId)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsOfficerRoleId)
    principalId: deployerObjectId
    principalType: 'User'
  }
}

output assignmentIds string[] = [runtimeAcrPull.id, runtimeSecretsUser.id, deployerSecretsOfficer.id]
