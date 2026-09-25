using './main.bicep'

// Full host deployment. Values are Caldova registrations created by the A365 CLI
// and register-control-plane.ps1; the credential is referenced by Key Vault name only.
param location = 'eastus2'
param deployApp = true
param containerImage = readEnvironmentVariable('AUTOPILOT_IMAGE', '')
param blueprintClientId = '77ae0985-4084-4bc1-bb3c-ab6dd0ad9bde'
param agentIdentityObjectId = ''
param controlPlaneClientId = 'a11a4108-2a76-471a-912b-8db27c91879c'
param controlPlaneAudience = 'a11a4108-2a76-471a-912b-8db27c91879c'
param controlPlaneScope = 'api://a11a4108-2a76-471a-912b-8db27c91879c/access_agent_as_user'
param blueprintSecretName = 'autopilot-blueprint-v2-runtime'
param operatorObjectId = '3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d'
param complianceBindings = readEnvironmentVariable('AUTOPILOT_COMPLIANCE_BINDINGS', '')
// Case desk colleagues. IT has no hired instance yet, so it talks through ServiceNow comments and email.
param deskBindings = '[{"function":"it","name":"IT Agent","system":"servicenow","skill":"it-second-line","queue":"Autopilot Service Desk","managerId":"3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d"},{"function":"hr","name":"HR Agent","system":"workday","skill":"hr-second-line","instanceAppId":"ada46fdd-f531-40b0-82cf-4c904d33d022","agenticUserId":"f84f67e1-2e3d-4fe6-a2f8-01191bd74c5c","managerId":"3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d"},{"function":"supply","name":"Supply Chain Agent","system":"coupa","skill":"supply-second-line","instanceAppId":"cdf4df7f-bc0a-4381-883e-fb7f87b9d527","agenticUserId":"f9f7881a-c4c4-4dad-b9e6-b8b36bf4f2a2","managerId":"3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d"},{"function":"compliance","name":"Compliance Agent","system":"salesforce","skill":"compliance-second-line","instanceAppId":"a6a9c9be-e1ee-4abc-b661-c8f906dd79b4","agenticUserId":"56bb6152-37b9-4eed-be0d-dbe5b906dad6","managerId":"3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d"}]'
param webhookSecretNames = {
  servicenow: 'autopilot-webhook-servicenow'
  salesforce: 'autopilot-webhook-salesforce'
}
param integrationUsers = {
  servicenow: 'admin'
  salesforce: readEnvironmentVariable('AUTOPILOT_SALESFORCE_INTEGRATION_USER', '')
}
param callerScope = 'api://a11a4108-2a76-471a-912b-8db27c91879c/.default'
// Private M365 group "Group Functions Autopilot Records" (owner Scott Adams; the three colleagues are members).
param runRecordsDriveId = 'b!J0caXx9Ev0-yfHiHdFL5fbW0Y_3vpJlGpnx3PjaSLjPEx08jI8cyRJ77W6wkNT3g'
param runRecordsUrl = 'https://caldova74201480.sharepoint.com/sites/autopilot-records/Shared%20Documents'
param mcpUrls = {
  workday: 'https://essmcp-caldova-workday.livelysky-91807d17.eastus2.azurecontainerapps.io/workday/mcp'
  servicenow: 'https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp'
  salesforce: 'https://essmcp-caldova-salesforce.livelysky-91807d17.eastus2.azurecontainerapps.io/salesforce/mcp'
  coupa: 'https://essmcp-caldova-coupa.livelysky-91807d17.eastus2.azurecontainerapps.io/coupa/mcp'
}
