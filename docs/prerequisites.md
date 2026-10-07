# Deployment Prerequisites

## Tooling and permissions

- Azure CLI with Bicep available (`az bicep version`), authenticated with `az login`.
- Azure Developer CLI (`azd auth login`) only if using the optional `azd provision` path.
- An existing workbook resource group and permission to create/update `Microsoft.Insights/workbooks`.
- Reader access to workbooks and **Monitoring Reader** or equivalent metrics-read permission on each monitored account.
- Permission to create role assignments only if using `sharedViewerPrincipalObjectIds`. Workbook Reader assignments do not grant metrics access on the account.

## Signal source

An existing Foundry or Azure OpenAI account (`Microsoft.CognitiveServices/accounts`, kind `AIServices` or `OpenAI`) with at least one model deployment. Platform metrics are collected automatically; traffic must exist in the selected range for request and token signals to populate.

No Application Insights, Log Analytics workspace, diagnostic settings, or application instrumentation is required.

| Signal | Coverage |
| --- | --- |
| `ModelRequests`, `ModelAvailabilityRate` | Foundry Models metrics, where populated by the selected provider/deployment |
| `InputTokens`, `OutputTokens`, `TotalTokens` | Input/output support depends on model type; embeddings commonly report input only |
| `TimeToResponse` | Gateway time to first response; documented for PTU/PTU-managed workloads |
| `AzureOpenAITimeToResponse` | Azure OpenAI time to first response; documented for PTU and pay-as-you-go workloads |

The focused workbook offers a latency metric picker. It does not infer missing latency, substitute unrelated service latency, or calculate percentiles from averages.

## Configuration

- Required: `modelAccountResourceId`, the full resource ID of an existing account.
- Optional: `location`, defaulting to the workbook resource group's location.
- Optional: `sharedViewerPrincipalObjectIds`, an array of user/group/service-principal object IDs.
- Optional: `sharedViewerPrincipalType`, one of `User` (default), `Group`, or `ServicePrincipal`.

For `azd`, configure `AZURE_LOCATION`, `AZURE_RESOURCE_GROUP`, and `MODEL_ACCOUNT_RESOURCE_ID`; see [.azure/.env.example](../.azure/.env.example).

The workbook account picker queries Azure Resource Graph over the portal's selected subscriptions. If an account is missing, check the subscription selection and resource-read access. The account can be in a different resource group from the workbooks.
