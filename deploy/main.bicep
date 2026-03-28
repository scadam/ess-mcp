// ---------------------------------------------------------------------------
// ESS-MCP – Azure Container Apps deployment
// Deploys: Log Analytics → Container Registry → Container App Environment
//          → one Container App per selected MCP server
// ---------------------------------------------------------------------------

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Base name used to derive resource names (lowercase, 3–16 characters).')
@minLength(3)
@maxLength(16)
param baseName string = 'essmcp'

@description('MCP servers to deploy. Use a comma-separated string, e.g. "workday,jira" or "all".')
param servers string = 'all'

@description('Docker image tag to deploy.')
param imageTag string = 'latest'

@description('Container App CPU cores (e.g. "0.5").')
param cpu string = '0.5'

@description('Container App memory (e.g. "1Gi").')
param memory string = '1Gi'

@description('Minimum number of replicas.')
param minReplicas int = 0

@description('Maximum number of replicas.')
param maxReplicas int = 3

@description('Environment variables as a JSON array of {name, value} objects.')
param envVars array = []

// ---------------------------------------------------------------------------
// Derived names
// ---------------------------------------------------------------------------
var suffix = uniqueString(resourceGroup().id)
var acrName = toLower('${baseName}acr${suffix}')
var logAnalyticsName = '${baseName}-logs-${suffix}'
var envName = '${baseName}-env-${suffix}'
var imageName = '${acrName}.azurecr.io/ess-mcp:${imageTag}'

var allServers = ['workday', 'servicenow', 'salesforce', 'jira']
var selectedServers = servers == 'all' ? allServers : split(servers, ',')

// ---------------------------------------------------------------------------
// Log Analytics workspace (required by Container App Environment)
// ---------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ---------------------------------------------------------------------------
// Azure Container Registry
// ---------------------------------------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: true }
}

// ---------------------------------------------------------------------------
// Container App Environment
// ---------------------------------------------------------------------------
resource appEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Container Apps – one per selected MCP server
// ---------------------------------------------------------------------------
resource containerApps 'Microsoft.App/containerApps@2024-03-01' = [
  for server in selectedServers: {
    name: '${baseName}-${server}'
    location: location
    properties: {
      managedEnvironmentId: appEnv.id
      configuration: {
        // Ingress is external so MCP clients can reach the endpoints.
        // Authentication is enforced at the application layer via OAuth 2.0
        // bearer token passthrough to each backend SaaS API.
        ingress: {
          external: true
          targetPort: 8080
          transport: 'http'
          allowInsecure: false
        }
        registries: [
          {
            server: acr.properties.loginServer
            username: acr.listCredentials().username
            passwordSecretRef: 'acr-password'
          }
        ]
        secrets: [
          {
            name: 'acr-password'
            value: acr.listCredentials().passwords[0].value
          }
        ]
      }
      template: {
        containers: [
          {
            name: server
            image: imageName
            command: [
              'python'
              '-m'
              'mcp_servers.cli'
              server
              '--transport'
              'both'
              '--host'
              '0.0.0.0'
              '--port'
              '8080'
            ]
            resources: {
              cpu: json(cpu)
              memory: memory
            }
            env: envVars
          }
        ]
        scale: {
          minReplicas: minReplicas
          maxReplicas: maxReplicas
          rules: [
            {
              name: 'http-rule'
              http: { metadata: { concurrentRequests: '50' } }
            }
          ]
        }
      }
    }
  }
]

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output environmentName string = appEnv.name
output deployedServers array = selectedServers
output containerAppFqdns array = [
  for (server, i) in selectedServers: {
    server: server
    fqdn: containerApps[i].properties.configuration.ingress.fqdn
    mcpEndpoint: 'https://${containerApps[i].properties.configuration.ingress.fqdn}/${server}/mcp'
    sseEndpoint: 'https://${containerApps[i].properties.configuration.ingress.fqdn}/${server}/sse'
    healthEndpoint: 'https://${containerApps[i].properties.configuration.ingress.fqdn}/healthz'
  }
]
