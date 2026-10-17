// FIXTURE: invented. No real subscription.
targetScope = 'subscription'
param adminPassword string = 'Fixture-Password-1'
param location string = 'westeurope'

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = { name: 'rg-shop', location: location }

module data 'data.bicep' = { name: 'data', scope: rg }

resource ownerGrant 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, 'owner')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8e3af657-a8ff-443c-a75c-2fe8c4bcb635')
    principalId: '00000000-0000-0000-0000-000000000001'
  }
}
