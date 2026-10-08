# Deployment Prerequisites

## Tooling and permissions

- Azure CLI with Bicep available (`az bicep version`), authenticated with `az login`.
- Azure Developer CLI (`azd auth login`) only if using the optional `azd provision` path.
- An existing workbook resource group and permission to create/update `Microsoft.Insights/workbooks`.
- Reader access to workbooks and **Monitoring Reader** or equivalent metrics-read permission on each monitored account.
- Account/project resource-read permission for Resource Graph inventory and `Microsoft.CognitiveServices/accounts/deployments/read` for ARM deployment configuration. Inaccessible resources are omitted by RBAC; workbook Reader does not grant account/project access.
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
| `ProvisionedUtilization` | PTU percentage utilization, where reported; absence on non-PTU deployments is not zero |

The focused workbook offers a latency metric picker. It does not infer missing latency, substitute unrelated service latency, or calculate percentiles from averages.

## Configuration

- Required: `modelAccountResourceId`, the full resource ID of an existing account.
- Optional: `location`, defaulting to the workbook resource group's location.
- Optional: `sharedViewerPrincipalObjectIds`, an array of user/group/service-principal object IDs.
- Optional: `sharedViewerPrincipalType`, one of `User` (default), `Group`, or `ServicePrincipal`.

For `azd`, configure `AZURE_LOCATION`, `AZURE_RESOURCE_GROUP`, and `MODEL_ACCOUNT_RESOURCE_ID`; see [.azure/.env.example](../.azure/.env.example).

The workbook account picker queries Azure Resource Graph over the portal's selected subscriptions. If an account is missing, check the subscription selection and resource-read access. The account can be in a different resource group from the workbooks.

Each workbook has an explicit subscription picker and **Compare accounts**, defaulting to native **All** eligible discovered accounts in those subscriptions. The supplied account initializes only its subscription; no other subscription/tenant is selected automatically. Discovery refresh adds new eligible accounts while All is active. Manual subsets are preserved; return to All to restore broad scope.

**Investigate resource** is separate and lower in the report. Dependent pickers remove out-of-scope selections on refresh. Native comparisons retain full resource/deployment identity; ARM summaries and TPM/RPM drilldown use only the investigation resource/deployment. Projects are inventoried by resource type and mapped to their parent account, never attributed platform metrics.

Capacity's estate overview covers traffic and reported PTU utilization. Fleet-wide pay-as-you-go allocation comparison is not available through the current native ARM query provider; current TPM/RPM remains deployment-level detail. This scope does not require additional resources or permissions. Discovery, series and rendering caps also limit estate coverage; see the [validation guide](deployment-and-validation.md).
