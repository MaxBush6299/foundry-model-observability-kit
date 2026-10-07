targetScope = 'resourceGroup'

@description('Deployment location for workbook resources.')
param location string = resourceGroup().location

@description('Full resource ID of the Foundry account to monitor.')
@minLength(1)
param modelAccountResourceId string

@description('Optional object IDs for shared viewer (Reader) assignments on these workbooks.')
param sharedViewerPrincipalObjectIds array = []

@description('Principal type for the shared viewer assignments.')
@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param sharedViewerPrincipalType string = 'User'

var readerRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')

resource modelFleetWorkbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: guid(resourceGroup().id, 'model-fleet-workbook')
  location: location
  kind: 'shared'
  properties: {
    category: 'workbook'
    displayName: 'Foundry Model Fleet and Usage'
    serializedData: replace(loadTextContent('../workbooks/model-fleet.workbook.json'), '__MODEL_ACCOUNT_RESOURCE_ID__', modelAccountResourceId)
    sourceId: 'Azure Monitor'
    version: 'Workbook/1.0'
  }
}

resource modelHealthWorkbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: guid(resourceGroup().id, 'model-health-workbook')
  location: location
  kind: 'shared'
  properties: {
    category: 'workbook'
    displayName: 'Foundry Model Inference Health'
    serializedData: replace(loadTextContent('../workbooks/model-health.workbook.json'), '__MODEL_ACCOUNT_RESOURCE_ID__', modelAccountResourceId)
    sourceId: 'Azure Monitor'
    version: 'Workbook/1.0'
  }
}

resource modelSignalsWorkbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: guid(resourceGroup().id, 'model-signals-workbook')
  location: location
  kind: 'shared'
  properties: {
    category: 'workbook'
    displayName: 'Foundry Model Volume, Latency and Availability'
    serializedData: replace(loadTextContent('../workbooks/model-signals.workbook.json'), '__MODEL_ACCOUNT_RESOURCE_ID__', modelAccountResourceId)
    sourceId: 'Azure Monitor'
    version: 'Workbook/1.0'
  }
}

resource modelFleetViewerAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalObjectId in sharedViewerPrincipalObjectIds: {
  name: guid(modelFleetWorkbook.id, principalObjectId, 'workbook-reader')
  scope: modelFleetWorkbook
  properties: {
    principalId: principalObjectId
    roleDefinitionId: readerRoleDefinitionId
    principalType: sharedViewerPrincipalType
  }
}]

resource modelHealthViewerAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalObjectId in sharedViewerPrincipalObjectIds: {
  name: guid(modelHealthWorkbook.id, principalObjectId, 'workbook-reader')
  scope: modelHealthWorkbook
  properties: {
    principalId: principalObjectId
    roleDefinitionId: readerRoleDefinitionId
    principalType: sharedViewerPrincipalType
  }
}]

output modelFleetWorkbookResourceId string = modelFleetWorkbook.id
output modelHealthWorkbookResourceId string = modelHealthWorkbook.id
output modelSignalsWorkbookResourceId string = modelSignalsWorkbook.id

resource modelSignalsViewerAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalObjectId in sharedViewerPrincipalObjectIds: {
  name: guid(modelSignalsWorkbook.id, principalObjectId, 'workbook-reader')
  scope: modelSignalsWorkbook
  properties: {
    principalId: principalObjectId
    roleDefinitionId: readerRoleDefinitionId
    principalType: sharedViewerPrincipalType
  }
}]
