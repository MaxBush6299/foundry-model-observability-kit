targetScope = 'resourceGroup'

@description('Deployment location for all resources that are created by this template.')
param location string = resourceGroup().location

@description('Enable to reuse an existing Log Analytics workspace and Application Insights instance.')
param useExistingMonitoringResources bool = false

@description('Resource ID of an existing Log Analytics workspace. Required when reuse is enabled.')
param logAnalyticsWorkspaceId string = ''

@description('Resource ID of an existing Application Insights component. Required when reuse is enabled.')
param applicationInsightsResourceId string = ''

@description('Name of an existing Application Insights component in this resource group. Used when reuse is enabled and resource ID is not provided.')
param existingApplicationInsightsName string = ''

@description('Name of the Azure OpenAI/Cognitive Services account in this resource group for diagnostics.')
param cognitiveServicesAccountName string = ''

@description('Optional Foundry account resource ID for model-only metric workbooks. Does not enable diagnostics.')
param modelAccountResourceId string = ''

@description('Minimum retention days for operational signals. Must be a value Application Insights accepts.')
@allowed([
  30
  60
  90
  120
  180
  270
  365
  550
  730
])
param retentionDays int = 30

@description('Optional object IDs for principals that should get shared workbook viewer (Reader) access, scoped to the workbooks.')
param sharedViewerPrincipalObjectIds array = []

@description('Principal type for the shared viewer role assignments.')
@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param sharedViewerPrincipalType string = 'User'

module monitoring './monitoring.bicep' = {
  name: 'monitoring'
  params: {
    location: location
    useExistingMonitoringResources: useExistingMonitoringResources
    logAnalyticsWorkspaceId: logAnalyticsWorkspaceId
    applicationInsightsResourceId: applicationInsightsResourceId
    existingApplicationInsightsName: existingApplicationInsightsName
    retentionDays: retentionDays
  }
}

module diagnostics './diagnostics.bicep' = {
  name: 'diagnostics'
  params: {
    targetResourceName: cognitiveServicesAccountName
    workspaceResourceId: monitoring.outputs.workspaceResourceId
  }
}

module workbooks './workbooks.bicep' = {
  name: 'workbooks'
  params: {
    location: location
    appInsightsResourceId: monitoring.outputs.appInsightsResourceId
    workspaceResourceId: monitoring.outputs.workspaceResourceId
    sharedViewerPrincipalObjectIds: sharedViewerPrincipalObjectIds
    sharedViewerPrincipalType: sharedViewerPrincipalType
  }
}

module modelWorkbooks './model-workbooks.bicep' = if (!empty(modelAccountResourceId)) {
  name: 'model-workbooks'
  params: {
    location: location
    modelAccountResourceId: modelAccountResourceId
    sharedViewerPrincipalObjectIds: sharedViewerPrincipalObjectIds
    sharedViewerPrincipalType: sharedViewerPrincipalType
  }
}

output workspaceResourceId string = monitoring.outputs.workspaceResourceId
output appInsightsResourceId string = monitoring.outputs.appInsightsResourceId
output platformDevWorkbookResourceId string = workbooks.outputs.platformDevWorkbookResourceId
output governanceWorkbookResourceId string = workbooks.outputs.governanceWorkbookResourceId
output modelFleetWorkbookResourceId string = !empty(modelAccountResourceId) ? modelWorkbooks!.outputs.modelFleetWorkbookResourceId : ''
output modelHealthWorkbookResourceId string = !empty(modelAccountResourceId) ? modelWorkbooks!.outputs.modelHealthWorkbookResourceId : ''
