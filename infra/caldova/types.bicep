@export()
@sealed()
type DeploymentTags = {
  'app-onboard-skill': 'true'
  'app-onboard-session-id': string
  'created-at': string
  environment: string
  'deployed-by': string
}

@sealed()
type EnvironmentVariable = {
  @minLength(1)
  name: string
  @description('Non-secret configuration only. Supply exactly one of value or secretRef.')
  value: string?
  @description('Name of a Key Vault-backed secret in this server configuration.')
  secretRef: string?
}

@sealed()
type KeyVaultReference = {
  @minLength(1)
  @maxLength(253)
  name: string
  @description('HTTPS URL of an already-seeded secret in the Caldova vault; never the secret value.')
  @minLength(1)
  keyVaultUrl: string
}

@export()
@sealed()
type ServerConfig = {
  name: 'essmcp-caldova-workday' | 'essmcp-caldova-servicenow' | 'essmcp-caldova-salesforce' | 'essmcp-caldova-jira' | 'essmcp-caldova-sap-sf' | 'essmcp-caldova-ariba' | 'essmcp-caldova-coupa'
  @description('CLI/router spelling is sap_sf, even though the Azure app name ends in sap-sf.')
  cliName: 'workday' | 'servicenow' | 'salesforce' | 'jira' | 'sap_sf' | 'ariba' | 'coupa'
  @description('Optional digest-pinned image override for a targeted server update.')
  image: string?
  env: EnvironmentVariable[]
  secrets: KeyVaultReference[]
}

@export()
@sealed()
type ServerEndpoint = {
  name: string
  cliName: string
  resourceId: string
  baseUrl: string
  mcpUrl: string
  sseUrl: string
  healthUrl: string
}
