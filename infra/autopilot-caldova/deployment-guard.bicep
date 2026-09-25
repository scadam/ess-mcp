targetScope = 'resourceGroup'

// This resource-free nested deployment rejects the wrong scope before anything is written.
@allowed(['54b04cf7-73f7-4ea0-aa82-b15694ea8033'])
param actualSubscriptionId string

@allowed(['17371818-07cb-47f2-9ca3-18f96f0125d7'])
param actualTenantId string

@allowed(['essmcp-caldova-rg'])
param actualResourceGroupName string

@allowed([true])
param appConfigurationIsReady bool

output passed bool = actualSubscriptionId == subscription().subscriptionId && actualTenantId == tenant().tenantId && actualResourceGroupName == resourceGroup().name && appConfigurationIsReady
