targetScope = 'resourceGroup'

import { DeploymentTags } from '../types.bicep'

param vaultName string
param location string
param tags DeploymentTags

// Credentials are seeded through the data plane by the main deployment workflow, not by ARM.
resource vault 'Microsoft.KeyVault/vaults@2026-05-15' = {
  name: vaultName
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 90
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

output resourceId string = vault.id
output name string = vault.name
output vaultUri string = vault.properties.vaultUri
