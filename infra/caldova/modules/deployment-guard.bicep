targetScope = 'subscription'

@description('Must be the actual deployment subscription. No resources may be provisioned in the original subscription.')
@allowed(['54b04cf7-73f7-4ea0-aa82-b15694ea8033'])
param actualSubscriptionId string

@description('Must be the actual deployment tenant, not an override supplied by a caller.')
@allowed(['17371818-07cb-47f2-9ca3-18f96f0125d7'])
param actualTenantId string

@description('When deploying apps, provide a nonempty tested image from the new ACR using a 64-character lowercase SHA-256 digest.')
@allowed([true])
param imageIsReady bool

@description('Foundation requires an empty config array. App deployment requires all seven exact name/CLI pairs, required settings, unique names, exactly one env value source, and matching Key Vault references for every credential.')
@allowed([true])
param runtimeConfigurationIsValid bool

output passed bool = actualSubscriptionId == subscription().subscriptionId && actualTenantId == tenant().tenantId && imageIsReady && runtimeConfigurationIsValid
