targetScope = 'resourceGroup'

import { DeploymentTags } from '../types.bicep'

param workspaceName string
param location string
param tags DeploymentTags

resource workspace 'Microsoft.OperationalInsights/workspaces@2026-03-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      disableLocalAuth: true
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

output resourceId string = workspace.id
