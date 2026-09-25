using './main.bicep'

// Foundation only. A separate deployment approval and real A365 registrations,
// seeded KV credential and verified immutable image are required to opt in.
param location = 'eastus2'
param deployApp = false
param containerImage = ''
param blueprintClientId = ''
param agentIdentityObjectId = ''
param controlPlaneClientId = ''
param controlPlaneAudience = ''
param controlPlaneScope = ''
param blueprintSecretName = ''
param operatorObjectId = '3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d'
param mcpUrls = {}
