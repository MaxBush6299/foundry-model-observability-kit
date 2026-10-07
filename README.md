# Foundry Model Observability Kit

Four deployable **model-only Azure Monitor workbooks** for Microsoft Foundry and Azure OpenAI accounts. This kit uses platform metrics directly: no Application Insights, Log Analytics workspace, tracing, or diagnostic export is required or provisioned.

| Workbook | Focus |
| --- | --- |
| **Model Fleet & Usage** | Combined subscription/underlying-model input/output/total-token and request totals, with separate account/deployment trends and detail |
| **Model Inference Health** | Resource/deployment health and HTTP-status comparisons, then selected-resource status counts and health trends |
| **Model Volume, Latency & Availability** | Resource/deployment volume, first-response latency and availability comparisons, then selected-resource trends and summaries |
| **Model Usage vs Capacity** | Cross-resource traffic and reported PTU utilization, then selected-deployment one-minute usage vs current TPM/RPM, PTU and 429 counts |

Fleet and Health default to **seven days**, Signals to **24 hours**, and Capacity to **one hour**. Capacity offers up to six days at one-minute resolution (8,640 points per series, below the portal chart's 10,000-point limit). These different windows are intentional; use shorter ranges for interactive performance. All four put estate comparison and sortable resource breakdowns before investigation, with inventory/project mappings last. Native trends retain resource/deployment identity; Fleet additionally combines scalar subscription/model totals.

**Admin scope:** explicitly select subscriptions. **Compare accounts** defaults to native **All**: every eligible discovered account in those subscriptions, including new accounts on scope refresh. It does not select every subscription or tenant. A manual subset remains a subset; choose **All** again to restore broad comparison. **Investigate resource** lower down selects a member of that comparison set without narrowing the overview; Capacity also selects a deployment. Native dependent pickers remove values no longer in scope. Resource links show short names and retain full-ID subscription/RG context on hover. Projects are parent-account inventory, **never project-attributed platform metrics**. Discovery is RBAC-filtered, not a complete tenant inventory.

**Coverage limits:** wildcard REST queries explicitly request `top=1000` instead of the API's default ten series, and native metrics use a 1,000-series split cap. This is not unlimited coverage. Native resource/grid limits are 10,000; Resource Graph discovery can itself be result-limited. The selected-resource response table exposes metric errors and returned-series counts; counts at the cap warrant narrower queries. Metrics List has no documented next-page/completeness marker. Large-estate performance beyond the tested scope is not established; reduce subscriptions/accounts and time range when needed.

## Prerequisites

- An existing `Microsoft.CognitiveServices/accounts` resource of kind `AIServices` or `OpenAI`, with model deployments and traffic in the selected range.
- Permission to deploy workbooks in the target resource group.
- **Monitoring Reader** (or equivalent metrics-read access) on the selected account, plus Reader access to the saved workbooks.
- Resource-read access on selected accounts/projects and `Microsoft.CognitiveServices/accounts/deployments/read` for capacity configuration.
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), authenticated with `az login`. Azure Developer CLI is needed only for the optional `azd` deployment below.

See [prerequisites](docs/prerequisites.md) for permissions and metric coverage.

## Deploy

Deploy all four workbooks into an existing resource group:

```powershell
$modelId = az resource show --resource-group "<account-rg>" `
  --resource-type "Microsoft.CognitiveServices/accounts" `
  --name "<foundry-account>" --query id -o tsv

az deployment group create `
  --resource-group "<workbook-rg>" `
  --template-file "infra\main.bicep" `
  --parameters modelAccountResourceId="$modelId"
```

The account can be in a different resource group. Its subscription initializes the subscription picker; other accessible subscriptions can be selected in the workbook. `infra\model-workbooks.bicep` is also a standalone entrypoint with the same inputs and outputs.

### Optional: Azure Developer CLI

```powershell
azd auth login
azd env new foundry-model-observability-dev
azd env set AZURE_LOCATION eastus
azd env set AZURE_RESOURCE_GROUP "<existing-workbook-rg>"
azd env set MODEL_ACCOUNT_RESOURCE_ID "<full-foundry-account-resource-id>"
azd provision
```

The mapping is in [infra/main.parameters.json](infra/main.parameters.json); [.azure/.env.example](.azure/.env.example) lists the environment values. These templates deploy only workbooks and optional workbook-scoped Reader assignments. They do not create accounts, deploy models, enable logs, or generate traffic.

### Open the workbooks

In the Azure portal, go to **Monitor > Workbooks > Saved workbooks** and select the deployment subscription and resource group. The supplied account initializes its subscription; **Compare accounts** defaults to **All** eligible accounts discovered in explicitly selected subscriptions. The separate investigation picker selects one valid member.

Both deployment entrypoints return:

- `modelFleetWorkbookResourceId`
- `modelHealthWorkbookResourceId`
- `modelSignalsWorkbookResourceId`
- `modelCapacityWorkbookResourceId`

Optional `sharedViewerPrincipalObjectIds` and `sharedViewerPrincipalType` inputs grant Reader on **all four workbooks**. They do not grant access to the account's metrics or deployment configuration; grant that separately. See the [deployment and validation guide](docs/deployment-and-validation.md).

## Fleet subscription/model comparisons

Fleet starts with a **combined subscription/model totals** table, then a sortable resource usage breakdown. `ModelName` identifies the underlying model, regardless of deployment aliases; versions with the same model name are combined. It sums input, output, total tokens, and requests across **Compare accounts** within each subscription. Native **All** includes all discovered eligible accounts by default; explicit subsets are optional.

The table groups by full subscription resource ID, then model name, and shows an all-model subscription subtotal. Rows display resource names and genuine subscription display names when resolved by the portal, without changing those ID-based grouping keys. Expand model rows to inspect contributing accounts; hover resource links for the full ID and subscription/resource-group context. Identically named accounts in different resource groups/subscriptions remain distinct. These are account resources, not project-attributed usage. All-missing output remains blank, including embeddings; measured zero remains zero. Totals cover the selected range and are not utilization or billed cost.

**Trends are account/deployment-scoped, not rolled up by subscription/model.** Grouped Sum sparklines are intentionally hidden because the portal fills missing grouped buckets with zero. **Request trends by resource** retains separate resource/deployment series; **Requests by deployment** lower down uses only the investigation resource. The original input/output token join is preserved. If only one subscription is accessible in the signed-in directory, live comparisons cover that subscription only; cross-subscription identity/null regressions use synthetic fixtures.

## Usage versus capacity

The capacity workbook reads **current deployment rate limits** from ARM, without converting SKU capacity units. TPM/RPM equivalents are `60 * count / renewalPeriod` using each reported token/request rule. Ten requests per ten seconds means 60 RPM equivalent, but not a permitted burst of 60 requests. Missing or unusable limits display **Unavailable**; no SKU multiplier or fabricated capacity is substituted.

**User-approved capacity scope:** the estate overview compares resource/deployment traffic and actually reported PTU utilization against 100%. Pay-as-you-go allocated TPM/RPM is compared with exact minute usage only in **selected-deployment drilldown**, not fleet-wide. ARM configuration is available, but the current native Workbook ARM provider rejects root `/batch` enumeration with `Path must be for an Azure Resource`, including the published native batch pattern. No rejected prototype, new backend or inferred allocation is shipped. Range traffic totals are not utilization, and missing PTU samples do not mean 0%.

Processed `TotalTokens` per minute is an **approximate** comparison with allocated TPM: Azure throttles using arrival-time estimated tokens, including requested output, rather than processed totals. Request limits can be enforced over sub-minute windows; dynamic throttling and bursts can produce 429s below the line. PTU uses `ProvisionedUtilization` against 100%, with average and maximum samples. Non-PTU/no-sample deployments do not establish zero utilization.

Horizontal reference lines use capacity read **now**, not the historical limit at each timestamp. When TPM or RPM is **Unavailable**, a separate usage-only chart omits the threshold property entirely; empty charts remain explicitly no-data. This is deployment usage versus capacity, **not subscription assigned quota** or billed cost. The workbook never aggregates hourly token totals against a per-minute limit.

## Interpreting the three signals

| Signal | Metric | Interpretation |
| --- | --- | --- |
| Request volume | `ModelRequests`, Total | All inference requests, including unsuccessful responses; trends show interval totals and tables show selected-range totals |
| Latency | `TimeToResponse` or `AzureOpenAITimeToResponse`, Average/Maximum | Gateway time to first response in milliseconds, not end-to-end completion latency or p95 |
| Availability | `ModelAvailabilityRate`, Average/Minimum | Reported percentage excluding HTTP 5xx; HTTP 4xx and 429 do not reduce this metric |

**Latency coverage matters.** Foundry Models `TimeToResponse` is documented for PTU/PTU-managed workloads. The focused workbook's **Latency metric** picker also supports `AzureOpenAITimeToResponse`, documented for Azure OpenAI PTU and pay-as-you-go deployments. Select the signal appropriate to your models; the workbook does not silently substitute metrics. The existing Inference Health workbook retains the Foundry Models metric.

**Missing samples stay missing.** Empty charts and blank cells are not zero usage, zero latency, or 100% availability. Provider and deployment support varies. Availability aggregates are not a request-weighted SLO or an external uptime check; minimum reported availability helps identify dips but does not measure outage duration. Use Inference Health for HTTP status details. Token counts are usage indicators, not billed cost.

Metrics are collected automatically. Do not rely on `AzureDiagnostics` or exported `AzureMetrics` for per-deployment dimensions; these workbooks query Azure Monitor metrics directly. See [metric sources and semantics](docs/schema-sources.md).

## Earlier model workbook screenshots

**Model Fleet & Usage**:

This earlier capture shows deployment detail; the current Fleet workbook adds subscription/model totals above it.

![Model Fleet and Usage: token trend and deployment token table](docs/images/model-fleet-overview.png)

**Model Inference Health**:

![Model Inference Health: HTTP response trend and status-count columns](docs/images/model-health-overview.png)

![Model Inference Health: status counts and availability by deployment](docs/images/model-health-deployments.png)

## Repository layout

```text
azure.yaml                  # Optional azd project
infra/main.bicep             # Model-only deployment entrypoint
infra/model-workbooks.bicep  # Four workbooks and optional viewer roles
workbooks/                  # Azure Monitor workbook JSON definitions
docs/                       # Prerequisites, metric references, and validation
scripts/build_workbooks.py   # Idempotent common scope and capacity workbook generation
tests/                      # Definition, identity, normalization, and null-semantics checks
```

Derived from [Foundry Observability Kit](https://github.com/MaxBush6299/foundry-observability-kit). This standalone edition retains the model workbooks and removes the tracing-based dashboards and monitoring infrastructure.
