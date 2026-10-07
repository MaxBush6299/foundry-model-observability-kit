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

Check that only the supplied account's subscription initializes the subscription picker, and **Compare accounts** defaults to native **All** eligible discovered accounts. Fleet/Health default to seven days, Signals to 24 hours, and Capacity to one hour. Change time/scope and confirm the corresponding overview follows them.

Select two accessible accounts in **Compare accounts**, including identical deployment names if available. Confirm full-ID rows remain separate. Change **Investigate resource** below and verify overview resource rows/totals do not narrow. Change comparison/subscription scope to exclude that resource; verify it and its deployment are removed/reset, with no stale configuration/filter. Clear scope and check required-input/no-data behavior, not fallback to an out-of-scope account. Return to **All** and refresh discovery. Use an unsaved dynamic-list fixture to add a third discovered entry without provisioning a resource: All must include it, while an explicit subset remains a subset.

Fleet's native token merge can retain cached source rows when its resource parameter clears. Its visibility explicitly depends on a nonempty investigation resource, so those cached rows are not displayed after scope exclusion. Verify the token table disappears when investigation clears and returns with current-source rows after selecting an in-scope resource; the original input/output left join is unchanged.

Check projects map to their parent account and that multiple projects do not duplicate that account's usage. Inventory is permission-filtered, not proof that inaccessible resources do not exist.

In Fleet, confirm the default totals table groups by subscription resource ID and underlying `ModelName`, not deployment alias. Select accounts with the same model and compare each group against the sum of those accounts' model-split metrics for the same range. Expand model rows to verify contributing account IDs. All-missing output must remain blank and measured zero must remain zero. Rollup timeline columns must be absent; token/request trend headings must explicitly say account/deployment scope, not subscription/model rollup. The original detail-account deployment input/output table remains available.

Grouped resource rows should display short account names and genuine subscription display names when the portal resolves them. Hover the native resource links to verify full IDs and resource-group/subscription context. Model rows should remain plain model names, not resource links. Verify identically named accounts in different resource groups/subscriptions retain separate full-ID leaves and unchanged scalar totals; short labels must not change grouping keys or imply project attribution.

When two subscriptions are accessible in the same directory, repeat with the same model in both and verify separate groups. Otherwise, record the one-subscription live-test limitation and use `tests\fixtures\subscription-model-metrics.json` for two-subscription/two-account collision and null regressions; do not claim live cross-subscription validation.

For Capacity, verify traffic/PTU comparisons precede investigation and the help explicitly limits pay-as-you-go TPM/RPM to deployment detail. The native root batch configuration prototype is not supported and must not ship.

For drilldown, compare exact `PT1M` REST samples with each chart, including missing samples and actual zeroes. Check a ten-second request rule normalizes to `count * 6`, not raw count. Compare TPM/RPM with raw rules. Exercise **Unavailable** TPM and RPM charts, not only scalar text: only the usage-only branch should render, with the threshold property absent and no nonnumeric-line error. Verify the full deployment ID belongs to the selected resource and `{Deployment:label}` is an actual ARM deployment name, never `Any one`. Case differences must not drop metric samples. On non-PTU/no-traffic deployments, expect missing data rather than synthesized 0% or zero 429 counts. No inference traffic or paid PTU deployment is needed.

The optional read-only helper queries actual deployment configuration and one-minute metrics for multiple accounts. It preserves account/deployment identity and reports measured zeroes separately from missing samples/series:

```powershell
.\scripts\Test-LiveMetrics.ps1 -Subscription "<subscription-id>" `
  -AccountResourceIds "<account-resource-id-1>", "<account-resource-id-2>"
```

Always use explicit `--subscription` in Azure CLI tests. Resource Graph CLI tests need both `--subscription` (authentication context) and `--subscriptions` (query scope), especially when accessible subscriptions span tenants. Do not change the shared global account context.

For a root ARM endpoint without a subscription in its URL, `az rest` can authenticate against the CLI default identity despite an explicit subscription option. Use an in-memory `az account get-access-token --subscription` result with the approved tenant/context if testing such an endpoint; do not persist or print tokens. This does not make rejected native Workbook paths supported.

## Estate coverage and performance

Every shipped wildcard Metrics List request has `top=1000` (direct JSON regressions cover the original three omissions). The API's default is ten, and no documented next-page/completeness marker exists. A selected-resource returned-series count at 1,000 warns of possible truncation, not definite incompleteness; counts below 1,000 are not proof of full estate coverage. The response table exposes per-metric errors even when the HTTP envelope is 200. Authorization failures remain failures.

Native resource and grid limits are 10,000, and Resource Graph discovery can be result-limited before that. All means all **returned eligible discoveries**, not an unlimited tenant scan. Compare resource inventory with independent scoped discovery when operating large estates. Test shorter ranges/subsets for interactive performance; no broad production-estate SLA or completeness guarantee is claimed. Live evidence is restricted to the approved subscription; duplicate RG/subscription behavior is also exercised with synthetic full-ID fixtures, not claimed as live cross-subscription proof.

Read-only validation on 2026-10-07 covered 17 discovered accounts in one approved subscription. Seven-day `ModelRequests`, `TotalTokens`, and `ModelAvailabilityRate` reads completed in about 35.54 seconds sequentially, with at most six returned series per account/metric. Initial HTTP-200 metric envelopes included `Throttled`/`ServerBusy`; bounded retries completed without remaining metric errors. This is a small-estate coverage observation, not a large-estate performance guarantee. No inference traffic was generated. PTU samples were absent, so positive PTU utilization and 429 rendering are not live-proven.

Authenticated unsaved portal checks exercised native All expanding from two existing IDs to three simulated discoveries and an explicit single-account subset remaining unchanged. Excluding the investigation account cleared both resource/deployment detail rather than retaining stale configuration. Fleet rendered positive seven-day scalar totals, 17 full-ID resource rows, and six primary-account deployment request totals without narrowing All. A temporary fixture forced both TPM/RPM to Unavailable: the usage-only branches rendered explicit no-sample messages without nonnumeric-threshold errors, while current ARM rules remained visible. Fixtures were not saved as shared workbooks. Cross-subscription collisions/null arithmetic remain fixture evidence, not live cross-subscription discovery.

Health's native seven-day grids displayed resource/deployment availability and first-response latency, including reported HTTP 500 and 400 rows. Signals' default 24-hour grid preserved measured request zeroes separately from blank resources; switching its latency source to Azure OpenAI updated native response diagnostics to `AzureOpenAITimeToResponse` (four reported series) while retaining all 17 overview resources.

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
