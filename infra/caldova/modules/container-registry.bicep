targetScope = 'resourceGroup'

import { DeploymentTags } from '../types.bicep'

param registryName string
param location string
param tags DeploymentTags

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled'
    // AcrPull is a registry RBAC role, not an ABAC repository role.
    roleAssignmentMode: 'LegacyRegistryPermissions'
    policies: {
      azureADAuthenticationAsArmPolicy: {
        status: 'enabled'
      }
    }
  }
}

output resourceId string = registry.id
output name string = registry.name
output loginServer string = registry.properties.loginServer
