# Metric Sources and Semantics

References checked: 2026-10-07.

## Official references

- [Monitor model deployments in Microsoft Foundry Models](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/monitor-models): automatic metrics collection, model metric families, provider coverage, and Monitoring Reader access.
- [Supported metrics for Microsoft.CognitiveServices/accounts](https://learn.microsoft.com/azure/azure-monitor/reference/supported-metrics/microsoft-cognitiveservices-accounts-metrics): metric names, dimensions, units, aggregations, and latency coverage.
- [Azure Workbooks data sources](https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-data-sources): native metrics and Azure Resource Manager query sources.
- [Metrics - List REST API](https://learn.microsoft.com/rest/api/monitor/metrics/list): `Total`, `Average`, `Minimum`, `Maximum`, dimension filters, and `interval=FULL`.

## Signals used

| Metric | Unit | Aggregation used | Deployment split |
| --- | --- | --- | --- |
| `ModelRequests` | Count | Total | `ModelDeploymentName` (also `StatusCode` in Inference Health) |
| `InputTokens`, `OutputTokens`, `TotalTokens` | Count | Total | `ModelDeploymentName` |
| `ModelAvailabilityRate` | Percent | Average, Minimum | `ModelDeploymentName` |
| `TimeToResponse` | Milliseconds | Average, Maximum | `ModelDeploymentName` |
| `AzureOpenAITimeToResponse` | Milliseconds | Average, Maximum | `ModelDeploymentName` |

Native metric charts use workbook aggregation codes `1` (Total) and `4` (Average). Summary tables call the account's metrics REST endpoint with `interval=FULL` for the selected range and a wildcard deployment filter. Each summary row represents one deployment's reported values, not an individual request.

The focused workbook explicitly requests up to 1,000 deployment series in both trends and summaries; its summaries do not inherit the REST API's default top-10 limit.

Requests include unsuccessful responses. Availability is `(total calls - server errors) / total calls`, expressed as a percentage; server errors are HTTP 5xx. HTTP 4xx and throttling (429) do not reduce this signal. Average/minimum values are platform aggregates, not an independently calculated, request-weighted SLO.

Time to response is a gateway-side first-response signal and excludes client latency. `TimeToResponse` is documented for PTU/PTU-managed models; `AzureOpenAITimeToResponse` additionally supports Azure OpenAI pay-as-you-go workloads. Neither is total completion duration or p95. Do not use the generic Cognitive Services `Latency` metric for Azure OpenAI.

Metric availability varies by model/provider. Missing fields and samples must remain blank: they are not measured zeroes or evidence of 100% availability. The workbooks do not require or query diagnostic log tables.
