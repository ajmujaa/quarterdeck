resource store 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'shopdatafixture'
  location: resourceGroup().location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { allowBlobPublicAccess: true, supportsHttpsTrafficOnly: false }
}
resource nsg 'Microsoft.Network/networkSecurityGroups@2023-04-01' = {
  name: 'nsg-web'
  location: resourceGroup().location
  properties: { securityRules: [ { name: 'ssh', properties: { priority: 100, direction: 'Inbound', access: 'Allow', protocol: 'Tcp', sourceAddressPrefix: '*', sourcePortRange: '*', destinationAddressPrefix: '*', destinationPortRange: '22' } } ] }
}
resource vault 'Microsoft.KeyVault/vaults@2023-02-01' = {
  name: 'kv-shop-fixture'
  location: resourceGroup().location
  properties: { tenantId: subscription().tenantId, sku: { family: 'A', name: 'standard' }, enableSoftDelete: false, enablePurgeProtection: false, accessPolicies: [] }
}
output storageKey string = store.listKeys().keys[0].value
