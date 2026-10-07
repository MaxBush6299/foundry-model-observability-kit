# Metric Sources and Semantics

References checked: 2026-10-07.

## Official references

- [Monitor model deployments in Microsoft Foundry Models](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/monitor-models): automatic metrics collection, model metric families, provider coverage, and Monitoring Reader access.
- [Supported metrics for Microsoft.CognitiveServices/accounts](https://learn.microsoft.com/azure/azure-monitor/reference/supported-metrics/microsoft-cognitiveservices-accounts-metrics): metric names, dimensions, units, aggregations, and latency coverage.
- [Azure Workbooks data sources](https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-data-sources): native metrics and Azure Resource Manager query sources.
- [Metrics - List REST API](https://learn.microsoft.com/rest/api/monitor/metrics/list): `Total`, `Average`, `Minimum`, `Maximum`, dimension filters, and `interval=FULL`.
- [Deployments - Get (2024-10-01)](https://learn.microsoft.com/rest/api/aiservices/accountmanagement/deployments/get?view=rest-aiservices-accountmanagement-2024-10-01): deployment `sku`, `properties.rateLimits`, and `ThrottlingRule` count/renewal period.
- [Manage Azure OpenAI quota](https://learn.microsoft.com/azure/ai-foundry/openai/how-to/quota): assigned subscription quota, deployment allocation, arrival-time token estimation, and sub-minute request enforcement.
- [Workbook criteria parameters](https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-criteria): guarded mathematical expressions for normalized per-minute limits.
- [Workbook JSONPath transformation](https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-jsonpath): ARM response-to-table transformation.
- [Official workbook JSON schema](https://github.com/microsoft/Application-Insights-Workbooks/blob/master/schema/workbook.json): chart `customThresholdLine` and parameter criteria shape.

## Signals used

| Metric | Unit | Aggregation used | Deployment split |
| --- | --- | --- | --- |
| `ModelRequests` | Count | Total | `ModelDeploymentName` (also `StatusCode` in Inference Health) |
| `InputTokens`, `OutputTokens`, `TotalTokens` | Count | Total | `ModelDeploymentName` |
| `ModelAvailabilityRate` | Percent | Average, Minimum | `ModelDeploymentName` |
| `TimeToResponse` | Milliseconds | Average, Maximum | `ModelDeploymentName` |
| `AzureOpenAITimeToResponse` | Milliseconds | Average, Maximum | `ModelDeploymentName` |
| `ProvisionedUtilization` | Percent | Average, Maximum | Single selected `ModelDeploymentName` |

Native metric charts use workbook aggregation codes `1` (Total) and `4` (Average). Summary tables call the account's metrics REST endpoint with `interval=FULL` for the selected range and a wildcard deployment filter. Each summary row represents one deployment's reported values, not an individual request.

The focused workbook explicitly requests up to 1,000 deployment series in both trends and summaries; its summaries do not inherit the REST API's default top-10 limit.

Requests include unsuccessful responses. Availability is `(total calls - server errors) / total calls`, expressed as a percentage; server errors are HTTP 5xx. HTTP 4xx and throttling (429) do not reduce this signal. Average/minimum values are platform aggregates, not an independently calculated, request-weighted SLO.

Time to response is a gateway-side first-response signal and excludes client latency. `TimeToResponse` is documented for PTU/PTU-managed models; `AzureOpenAITimeToResponse` additionally supports Azure OpenAI pay-as-you-go workloads. Neither is total completion duration or p95. Do not use the generic Cognitive Services `Latency` metric for Azure OpenAI.

Metric availability varies by model/provider. Missing fields and samples must remain blank: they are not measured zeroes or evidence of 100% availability. The workbooks do not require or query diagnostic log tables.

## Capacity response and chart semantics

The deployment picker uses ARM deployments list, with full deployment resource ID as its value. Configuration uses deployments GET at API version `2024-10-01`. Live read-only validation confirmed `properties.rateLimits` entries with `key` values `token` and `request`, numerical `count`, and `renewalPeriod` in seconds, including a request rule of 10 per 10 seconds. Text criteria parameters compute `60 * count / renewalPeriod`, guarded against missing counts and missing/nonpositive periods. Because expression parameters otherwise coerce nonnumeric values to zero, those guards are essential.

Portal verification also confirmed that an empty static result invalidates the entire criteria parameter, even when that rule does not match. Guards and the default therefore return the explicit text `Unavailable`, not an empty string or zero. Capacity time ranges are capped at six days (8,640 one-minute points) because the portal timechart rejects more than 10,000 points per series.

The capacity charts use Metrics List with `interval=PT1M` and `autoAdjustTimegrain=false`, a single deployment filter, and JSONPath `$.value[0].timeseries[0].data[*]`. Columns extract `timeStamp` and the actual `total`, `average`, or `maximum` without filling gaps. Workbook-supported `customThresholdLine` references the normalized current limit; PTU uses the documented 100% reference. One-minute samples are not converted from range totals. ARM/API permission errors remain errors.

No deployment-name join is used for capacity. The full selected ARM deployment resource ID scopes the capacity lookup, and its account scopes the metric request. The deployment dropdown explicitly returns ARM `$.id` as value and `$.name` as label; metric filters use `{Deployment:label}`, not the resource picker's `:name` formatter (which does not parse a dropdown value). Hidden ARM text parameters use scalar JSONPath projections with no column definitions, following the official ARM text-parameter pattern. A live uppercase deployment-name filter matched a lowercased metric dimension value, confirming the service's case-insensitive filter behavior. Native multi-account metric charts retain separate resource series, so same-named deployments in two accounts are not merged. ARM detail tables remain account-scoped.

Resource Graph inventory filters selected subscriptions/accounts and discovers projects by type `microsoft.cognitiveservices/accounts/projects`, not project kind. The parent account ID is the case-normalized prefix before `/projects/`. This relationship is metadata, not project-specific metric attribution.

The portal subscription picker emits `/subscriptions/<guid>` resource IDs, while Resource Graph `subscriptionId` is a bare GUID. Shared filters accept both forms, and the picker default uses the resource-ID form. This was verified with the actual portal substitution and a live Resource Graph query, not only a bare-GUID CLI query.
