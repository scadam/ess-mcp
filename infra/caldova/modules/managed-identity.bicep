targetScope = 'resourceGroup'

import { DeploymentTags } from '../types.bicep'

param identityName string
param location string
param tags DeploymentTags

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: identityName
  location: location
  tags: tags
}

output resourceId string = identity.id
output principalId string = identity.properties.principalId
output clientId string = identity.properties.clientId
