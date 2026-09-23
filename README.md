# Foundry Agent Observability Starter Kit

A deployable observability kit for **Microsoft Foundry prompt agents and model deployments**. By default it provisions (or reuses) Azure Monitor resources and installs two agent workbooks built on [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/):

- **Platform/Dev workbook** — agent runs, model/tool calls, token usage, latency, and reliability.
- **Governance workbook** — attribution ("who ran what"), access trail, and anomaly flags.

Both workbooks read the GenAI spans Foundry writes to Application Insights (`invoke_agent`, `chat`, `execute_tool`) from the `dependencies` table — no custom instrumentation required beyond connecting Foundry to Application Insights.

Two optional **model-only** workbooks use the Foundry account's Azure Monitor metrics directly, without agent spans or diagnostic logs: **Model Fleet & Usage** and **Model Inference Health**. They cover deployments across Azure OpenAI, Fireworks, and other providers where those metrics are populated.

## Why Application Insights for agent observability?

Application Insights is the application performance monitoring (APM) feature of Azure Monitor, and it's the telemetry backend Microsoft Foundry uses for agent tracing. Based on Microsoft documentation:

- **It's where Foundry already sends traces.** Foundry stores agent traces in Application Insights using OpenTelemetry semantic conventions, and enables server-side tracing automatically for prompt and hosted agents once you connect a resource — no code changes required. See [Set up tracing in Microsoft Foundry](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-agent-setup).
- **Purpose-built agent monitoring.** The **Agents (preview)** view in Application Insights consolidates agent telemetry so you can track agent performance, analyze token usage and cost, troubleshoot errors, and optimize behavior. It's based on OpenTelemetry GenAI Semantics. See [Monitor AI agents with Application Insights](https://learn.microsoft.com/azure/azure-monitor/app/agents-view).
- **Vendor-neutral via OpenTelemetry.** Application Insights collects telemetry through OpenTelemetry, a standardized, vendor-neutral framework, so the same signals work across frameworks and tools. See [Application Insights overview](https://learn.microsoft.com/azure/azure-monitor/app/app-insights-overview).
- **A rich analysis surface.** Beyond workbooks, you get Application Map, Live Metrics, Transaction Search, Failures/Performance views, KQL over Log Analytics, alerts, and Grafana dashboards — all over the same data. See [Application Insights overview](https://learn.microsoft.com/azure/azure-monitor/app/app-insights-overview).

In short: if your agents run in Foundry, their observability data already lives in Application Insights. This kit turns that raw telemetry into curated dashboards.

## Prerequisites

1. An Azure subscription with permission to create resource-group–scoped resources (and to assign roles if you use the optional shared-viewer feature).
2. [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) and [Azure Developer CLI (`azd`)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd), authenticated (`az login`, `azd auth login`).
3. **A Foundry project connected to Application Insights**, with agents that have run at least once. This is the key data prerequisite — without it the workbooks render but stay empty. Follow [Set up tracing in Microsoft Foundry](https://learn.microsoft.com/azure/foundry/observability/how-to/trace-agent-setup#connect-application-insights-to-your-foundry-project).
4. To query telemetry you need the [Log Analytics Reader role](https://learn.microsoft.com/azure/azure-monitor/logs/manage-access?tabs=portal#log-analytics-reader) on the connected Application Insights resource.

> The kit does not generate agent traffic. It visualizes the `gen_ai.*` spans your Foundry agents already emit.

## Deploy

### Option A — Reuse an existing Application Insights resource (recommended)

If your Foundry project is already connected to an Application Insights resource, point the kit at it. This is the fastest path and installs only the workbooks.

```powershell
az deployment group create `
  --resource-group "<your-rg>" `
  --template-file "infra/main.bicep" `
  --parameters `
    useExistingMonitoringResources=true `
    existingApplicationInsightsName="<your-app-insights-name>"
```

The workspace ID is derived automatically from the App Insights resource. If the resource lives in another resource group, pass explicit IDs instead:

```powershell
az deployment group create `
  --resource-group "<your-rg>" `
  --template-file "infra/main.bicep" `
  --parameters `
    useExistingMonitoringResources=true `
    applicationInsightsResourceId="<app-insights-resource-id>" `
    logAnalyticsWorkspaceId="<workspace-resource-id>"
```

### Option B — Provision new monitoring resources with `azd`

For a greenfield setup (new Log Analytics workspace + Application Insights + workbooks):

```powershell
azd auth login
azd env new <environment-name>
# set values in .azure/<environment-name>/.env (see .azure/.env.example)
azd up
```

`azd` reads parameter values from [infra/main.parameters.json](infra/main.parameters.json), which maps to the environment variables documented in [.azure/.env.example](.azure/.env.example).

### Add model-only workbooks

Pass the full **Foundry account** resource ID to the standalone model workbook module. No Application Insights resource, Log Analytics workspace, or agent deployment is needed:

```powershell
$modelId = az resource show --resource-group "<your-rg>" `
  --resource-type "Microsoft.CognitiveServices/accounts" `
  --name "<your-foundry-account>" --query id -o tsv

az deployment group create `
  --resource-group "<your-rg>" `
  --template-file "infra/model-workbooks.bicep" `
  --parameters modelAccountResourceId="$modelId"
```

Find the model workbooks in **Azure portal → Monitor → Workbooks → Saved workbooks**; select the deployment subscription and resource group. Both model workbooks have a Foundry resource picker that defaults to the account specified at deployment; their charts and tables follow the selection. The picker lists accessible Azure AI Services and Azure OpenAI accounts from the portal's default subscriptions through Azure Resource Graph; select an account with model metrics and permission to read Azure Monitor metrics. The account can be in another resource group; the workbook resources themselves are deployed to the chosen resource group. The account ID placeholder in each JSON definition is populated by Bicep at deployment time. This module does **not** enable diagnostic settings or create model inference traffic. Alternatively, pass `modelAccountResourceId` to `infra/main.bicep` to install these alongside the original agent workbooks. If omitted there, only the original agent workbooks are deployed. Readers need permission to read Azure Monitor metrics on the selected Foundry account.

Metrics are collected automatically, but only populated signals appear. Model Fleet & Usage plots total tokens over time by deployment and shows one row per deployment with input and output token totals for the selected range. Its table reads account metrics through Azure Resource Manager and merges on deployment name; it does not require diagnostic export. Blank output cells mean no reported output token samples, not zero. Inference Health plots HTTP response status, reported availability, gateway time to response, and request volume. Its status summary shows HTTP status codes as columns and request counts as values across the selected resource; a separate deployment-detail table provides individual status counts per model deployment. Statuses without reported samples may be omitted or have blank cells, not measured zeroes. Availability excludes client errors and throttling, while time to response primarily applies to streaming PTU workloads. Neither missing metrics nor a blank status series establish perfect health. For request-level logs, configure diagnostic settings separately and account for Log Analytics ingestion costs. Token totals are usage indicators, not actual billed cost; use Azure Cost Analysis for charges. See [Monitor model deployments in Microsoft Foundry Models](https://learn.microsoft.com/azure/foundry/foundry-models/how-to/monitor-models) and [Azure Workbooks data sources](https://learn.microsoft.com/azure/azure-monitor/visualize/workbooks-data-sources).

## Deployment outputs

Both paths return:

- `workspaceResourceId`
- `appInsightsResourceId`
- `platformDevWorkbookResourceId`
- `governanceWorkbookResourceId`
- `modelFleetWorkbookResourceId`, `modelHealthWorkbookResourceId` (empty when model workbooks are not enabled)

Open either workbook from **Application Insights → Workbooks**, or directly by resource ID.

## What you'll see

| Section | Signal |
| --- | --- |
| Summary KPIs | Agent runs, active agents, failure rate, p95 latency, total tokens, tool calls |
| Agent activity | `invoke_agent` runs per agent and over time |
| Workload | `chat` (model) and `execute_tool` (tool) calls per agent |
| Token usage | Input vs. output tokens per agent and per model (from `chat` spans) |
| Performance | Agent run p50/p95 latency, model latency over time |
| Reliability | Errors by agent, failed dependencies, exceptions |

Use the **TimeRange** pills at the top to rescope every tile.

### Screenshots

Live workbooks reading real Foundry `gen_ai.*` telemetry from Application Insights.

**Platform/Dev workbook** — summary KPIs and per-agent activity:

![Platform/Dev workbook overview: summary KPIs and agent activity](docs/images/platform-dev-overview.png)

**Token usage** — input vs. output tokens per agent and per model, from `chat` spans:

![Platform/Dev workbook token usage by agent and model](docs/images/platform-dev-tokens.png)

**Governance workbook** — attribution ("who ran what") and access trail, with a working TimeRange picker:

![Governance workbook: who ran what and access trail](docs/images/governance-overview.png)

## Repository layout

```
azure.yaml                 # azd project definition
infra/                     # Bicep modules (monitoring, diagnostics, workbooks)
workbooks/                 # Workbook definitions deployed as serializedData
docs/                      # Prerequisites and deployment/validation guides
```

## Optional

- **Azure OpenAI diagnostics.** Pass `cognitiveServicesAccountName=<account>` to route Azure OpenAI resource logs/metrics into the same workspace. Skipped automatically when omitted.
- **Shared viewer access.** Pass `sharedViewerPrincipalObjectIds` to grant Reader on the workbooks.
