targetScope = 'resourceGroup'

import { DeploymentTags } from '../types.bicep'

param environmentName string
param location string
param tags DeploymentTags

@description('Full ARM resource ID, not the workspace customer GUID. No workspace key is needed.')
param workspaceResourceId string

resource environment 'Microsoft.App/managedEnvironments@2026-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    publicNetworkAccess: 'Enabled'
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    zoneRedundant: false
  }
}

// The supported preview is needed for categoryGroup; the 2016 stable schema lacks it.
// Diagnostic settings do not support tags; retention is managed on the workspace.
resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'container-logs'
  scope: environment
  properties: {
    workspaceId: workspaceResourceId
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
  }
}

output resourceId string = environment.id
output defaultDomain string = environment.properties.defaultDomain
