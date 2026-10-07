targetScope = 'resourceGroup'

@description('Deployment location for workbook resources.')
param location string = resourceGroup().location

@description('Full resource ID of the existing Foundry account to monitor.')
@minLength(1)
param modelAccountResourceId string

@description('Optional object IDs for principals that should get shared workbook viewer (Reader) access, scoped to the workbooks.')
param sharedViewerPrincipalObjectIds array = []

@description('Principal type for the shared viewer role assignments.')
@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param sharedViewerPrincipalType string = 'User'

module modelWorkbooks './model-workbooks.bicep' = {
  name: 'model-workbooks'
  params: {
    location: location
    modelAccountResourceId: modelAccountResourceId
    sharedViewerPrincipalObjectIds: sharedViewerPrincipalObjectIds
    sharedViewerPrincipalType: sharedViewerPrincipalType
  }
}

output modelFleetWorkbookResourceId string = modelWorkbooks.outputs.modelFleetWorkbookResourceId
output modelHealthWorkbookResourceId string = modelWorkbooks.outputs.modelHealthWorkbookResourceId
output modelSignalsWorkbookResourceId string = modelWorkbooks.outputs.modelSignalsWorkbookResourceId
