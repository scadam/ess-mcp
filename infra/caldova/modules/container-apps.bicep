targetScope = 'resourceGroup'

import { DeploymentTags, ServerConfig, ServerEndpoint } from '../types.bicep'

param location string
param tags DeploymentTags
param environmentResourceId string
param runtimeIdentityResourceId string
param registryLoginServer string

@minLength(1)
param containerImage string

@minLength(7)
@maxLength(7)
param serverConfigs ServerConfig[]

// A GET-only, backend-independent route confirmed in the existing ASGI CLI.
var healthCheck = {
  path: '/healthz'
  port: 8080
  scheme: 'HTTP'
}

resource apps 'Microsoft.App/containerApps@2026-01-01' = [for server in serverConfigs: {
  name: server.name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${runtimeIdentityResourceId}': {}
    }
  }
  properties: {
    environmentId: environmentResourceId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 8080
        transport: 'http'
        // ASGI already owns CORS (GET/POST/DELETE/OPTIONS, Authorization, and
        // exposed mcp-session-id / mcp-protocol-version). Avoid conflicting proxy headers.
      }
      registries: [
        {
          server: registryLoginServer
          identity: runtimeIdentityResourceId
        }
      ]
      secrets: [for secret in server.secrets: {
        name: secret.name
        keyVaultUrl: secret.keyVaultUrl
        identity: runtimeIdentityResourceId
      }]
    }
    template: {
      containers: [
        {
          name: 'mcp-server'
          image: server.?image ?? containerImage
          command: ['python', '-m', 'mcp_servers.cli']
          args: [server.cliName, '--transport', 'both', '--host', '0.0.0.0', '--port', '8080']
          // User-requested demo contract: caller bearer wins, otherwise stored service credentials.
          // The parent validates Salesforce auto mode and requires all fallback secret references.
          env: server.env
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          probes: [
            {
              type: 'Startup'
              httpGet: healthCheck
              initialDelaySeconds: 5
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 10
              successThreshold: 1
            }
            {
              type: 'Readiness'
              httpGet: healthCheck
              initialDelaySeconds: 5
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
              successThreshold: 1
            }
            {
              type: 'Liveness'
              httpGet: healthCheck
              initialDelaySeconds: 30
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
              successThreshold: 1
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
      terminationGracePeriodSeconds: 30
    }
  }
}]

output endpoints ServerEndpoint[] = [for (server, index) in serverConfigs: {
  name: server.name
  cliName: server.cliName
  resourceId: apps[index].id
  baseUrl: 'https://${apps[index].properties.configuration.ingress.fqdn}'
  mcpUrl: 'https://${apps[index].properties.configuration.ingress.fqdn}/${server.cliName}/mcp'
  sseUrl: 'https://${apps[index].properties.configuration.ingress.fqdn}/${server.cliName}/sse'
  healthUrl: 'https://${apps[index].properties.configuration.ingress.fqdn}/healthz'
}]
