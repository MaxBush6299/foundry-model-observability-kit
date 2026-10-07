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

Both entrypoints deploy **four workbooks only**, plus optional workbook-scoped Reader assignments. They do not provision monitoring backends, accounts, models, or diagnostic settings.

Confirm these outputs:

- `modelFleetWorkbookResourceId`
- `modelHealthWorkbookResourceId`
- `modelSignalsWorkbookResourceId`
- `modelCapacityWorkbookResourceId`

## Shared viewer access

Pass `sharedViewerPrincipalObjectIds` as an array and set `sharedViewerPrincipalType` if needed. The identity deploying this option must be allowed to create role assignments. The template grants Reader on all four workbook resources; metrics/configuration-read access on the account must be granted separately.

## Local template checks

```powershell
python scripts\build_workbooks.py
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
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
| Fleet & Usage | Combined subscription/model input/output/total-token and request totals; blank embedding output; separate account/deployment token/request trends and detail |
| Inference Health | Status trend, status summary, per-deployment status counts, availability, time to response, and traffic |
| Volume, Latency & Availability | Three trends and three summary tables; request totals, average/maximum latency in ms, average/minimum availability in percent |
| Usage vs Capacity | Multi-account token/request comparison; deployment detail with current TPM/RPM reference lines, one-minute token/request charts, PTU average/maximum vs 100%, and one-minute 429 counts |

Check that the resource picker defaults to the account passed at deployment. Change both the account and time range and confirm all visuals follow the selection. The focused workbook should default to 24 hours.

Select two accessible accounts in **Compare accounts**, including accounts with identical deployment names if available. Confirm native chart legends/results keep resource identity and deployments separate; use the account inventory's full IDs to disambiguate names. Select **Detail account** from the comparison set and confirm ARM summaries use only that account. Changing subscription/account must refresh dependent inventory and detail/deployment selections.

Check projects map to their parent account and that multiple projects do not duplicate that account's usage. Inventory is permission-filtered, not proof that inaccessible resources do not exist.

In Fleet, confirm the default totals table groups by subscription resource ID and underlying `ModelName`, not deployment alias. Select accounts with the same model and compare each group against the sum of those accounts' model-split metrics for the same range. Expand model rows to verify contributing account IDs. All-missing output must remain blank and measured zero must remain zero. Rollup timeline columns must be absent; token/request trend headings must explicitly say account/deployment scope, not subscription/model rollup. The original detail-account deployment input/output table remains available.

Grouped resource rows should display short account names and genuine subscription display names when the portal resolves them. Hover the native resource links to verify full IDs and resource-group/subscription context. Model rows should remain plain model names, not resource links. Verify identically named accounts in different resource groups/subscriptions retain separate full-ID leaves and unchanged scalar totals; short labels must not change grouping keys or imply project attribution.

When two subscriptions are accessible in the same directory, repeat with the same model in both and verify separate groups. Otherwise, record the one-subscription live-test limitation and use `tests\fixtures\subscription-model-metrics.json` for two-subscription/two-account collision and null regressions; do not claim live cross-subscription validation.

For capacity drilldown, compare exact `PT1M` REST samples with each chart, including missing samples and actual zeroes. Check a ten-second request rule normalizes to `count * 6`, not raw count. Compare the displayed TPM/RPM with the raw rule table; missing rules must yield no capacity line. Verify the full deployment ID belongs to the selected detail account and that case differences in deployment names do not drop metric samples. Confirm current capacity is clearly labeled and that charts are not range totals. On non-PTU/no-traffic deployments, expect missing data rather than a synthesized 0% or zero 429 count. No inference traffic or paid PTU deployment is needed to perform these checks.

The optional read-only helper queries actual deployment configuration and one-minute metrics for multiple accounts. It preserves account/deployment identity and reports measured zeroes separately from missing samples/series:

```powershell
.\scripts\Test-LiveMetrics.ps1 -Subscription "<subscription-id>" `
  -AccountResourceIds "<account-resource-id-1>", "<account-resource-id-2>"
```

Always use explicit `--subscription` in Azure CLI tests. Resource Graph CLI tests need both `--subscription` (authentication context) and `--subscriptions` (query scope), especially when accessible subscriptions span tenants. Do not change the shared global account context.

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
