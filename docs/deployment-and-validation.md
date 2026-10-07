# Deployment and Validation Guide

## Deploy

Authenticate with `az login`, then deploy into an existing workbook resource group:

```powershell
az deployment group create `
  --resource-group "<workbook-rg>" `
  --template-file "infra\main.bicep" `
  --parameters modelAccountResourceId="<full-foundry-account-resource-id>"
```

Alternatively, use `infra\model-workbooks.bicep` with the same parameters. For Azure Developer CLI, follow the `azd provision` instructions in the [README](../README.md).

Both entrypoints deploy **three workbooks only**, plus optional workbook-scoped Reader assignments. They do not provision monitoring backends, accounts, models, or diagnostic settings.

Confirm these outputs:

- `modelFleetWorkbookResourceId`
- `modelHealthWorkbookResourceId`
- `modelSignalsWorkbookResourceId`

## Shared viewer access

Pass `sharedViewerPrincipalObjectIds` as an array and set `sharedViewerPrincipalType` if needed. The identity deploying this option must be allowed to create role assignments. The template grants Reader on all three workbook resources; metrics-read access on the account must be granted separately.

## Local template checks

```powershell
az bicep build --file "infra\main.bicep" --stdout > $null
az bicep build --file "infra\model-workbooks.bicep" --stdout > $null
```

Before deploying to Azure, optionally validate against your actual account and target group:

```powershell
az deployment group validate `
  --resource-group "<workbook-rg>" `
  --template-file "infra\main.bicep" `
  --parameters modelAccountResourceId="<full-foundry-account-resource-id>"
```

## Portal validation

Open **Monitor > Workbooks > Saved workbooks**, filtered to the workbook subscription and resource group.

| Workbook | Expected result when metrics exist |
| --- | --- |
| Fleet & Usage | Token trend and deployment input/output totals; output can be blank for embeddings |
| Inference Health | Status trend, status summary, per-deployment status counts, availability, time to response, and traffic |
| Volume, Latency & Availability | Three trends and three summary tables; request totals, average/maximum latency in ms, average/minimum availability in percent |

Check that the resource picker defaults to the account passed at deployment. Change both the account and time range and confirm all visuals follow the selection. The focused workbook should default to 24 hours.

In the focused workbook, test both **Latency metric** choices on accounts/deployments that support them. Foundry Models uses `TimeToResponse`; Azure OpenAI uses `AzureOpenAITimeToResponse`. Confirm both the trend and summary switch together. Unsupported/no-sample latency must remain empty, not report zero.

Compare request totals with Metrics explorer using `ModelRequests`, Sum, and a deployment split over the same time range. Compare latency with the selected time-to-response metric, Average/Maximum. Compare availability with `ModelAvailabilityRate`, Average/Minimum. Maximum latency is not p95; minimum availability is a reported metric minimum, not outage duration.

## Empty data and access errors

- Check the account has model traffic in the selected range; widen the time range if necessary.
- Verify Monitoring Reader or equivalent metrics-read permission on the selected account. Workbook Reader alone is insufficient.
- Check metric coverage in the account's Metrics explorer; providers and deployment types differ.
- Select Azure OpenAI latency for supported pay-as-you-go deployments.
- Check the portal's selected subscriptions if the resource picker omits an account.
- Treat authorization/API errors as errors. Do not reinterpret them or missing data as healthy, zero-usage results.

No `AzureDiagnostics`, request/response logs, or Log Analytics ingestion is needed for these checks.
