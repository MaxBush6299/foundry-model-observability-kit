"""Apply shared subscription scope and build the usage/capacity workbook."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "KqlParameterItem/1.0"
SUBSCRIPTION_FILTER = (
    "resources | where subscriptionId in~ ({Subscriptions}) "
    "or strcat('/subscriptions/', subscriptionId) in~ ({Subscriptions}) "
)
ACCOUNT_QUERY = (
    SUBSCRIPTION_FILTER +
    "| where type =~ 'microsoft.cognitiveservices/accounts' "
    "and kind in~ ('AIServices', 'OpenAI') "
)


def compact(value):
    return json.dumps(value, separators=(",", ":"))


def parameter(name, kind, **settings):
    return dict(id=name, version=VERSION, name=name, type=kind, **settings)


def text(name, body):
    return dict(type=1, name=name, content=dict(json=body))


def arm(path, table, columns, **url_params):
    return compact(dict(
        version="ARMEndpoint/1.0", data=None, headers=[], method="GET",
        path=path, urlParams=[dict(key=k, value=v) for k, v in url_params.items()],
        batchDisabled=False,
        transformers=[dict(type="jsonpath", settings=dict(
            tablePath=table, columns=columns))],
    ))


def column(path, name, kind="string"):
    return dict(path=path, columnid=name, columnType=kind)


def query(name, value, kind=12, **settings):
    return dict(type=3, name=name, content=dict(
        version="KqlItem/1.0", query=value, queryType=kind, size=0, **settings))


def scope_parameters():
    return [
        parameter("Subscriptions", 6, label="Subscriptions", isRequired=True,
                  multiSelect=True, quote="'", delimiter=",",
                  value=["/subscriptions/__MODEL_ACCOUNT_SUBSCRIPTION_ID__"]),
        parameter("FoundryResources", 5, label="Compare accounts", isRequired=True,
                  multiSelect=True, quote="'", delimiter=",",
                  query=ACCOUNT_QUERY + (
                      "| project value=id, label=strcat(name, ' (', resourceGroup, ')'), "
                      "selected=id =~ '__MODEL_ACCOUNT_RESOURCE_ID__', group=subscriptionId"),
                  crossComponentResources=["{Subscriptions}"], queryType=1,
                  resourceType="microsoft.resourcegraph/resources",
                  typeSettings=dict(additionalResourceOptions=[])),
        parameter("FoundryResource", 5, label="Detail account", isRequired=True,
                  query=ACCOUNT_QUERY + (
                      "| where id in~ ({FoundryResources}) "
                      "| project value=id, label=strcat(name, ' (', resourceGroup, ')'), "
                      "selected=id =~ '__MODEL_ACCOUNT_RESOURCE_ID__'"),
                  crossComponentResources=["{Subscriptions}"], queryType=1,
                  resourceType="microsoft.resourcegraph/resources",
                  typeSettings=dict(additionalResourceOptions=[])),
    ]


def inventory():
    return [
        text("scope-notes", "### Subscription comparison and account drilldown\n"
             "**Compare accounts** supports multiple accounts in the selected subscriptions. "
             "Native metrics retain separate resource/deployment series; matching deployment "
             "names in different accounts are not joined. **Detail account** selects one of "
             "those accounts for ARM summary tables and capacity drilldown.\n\n"
             "Only RBAC-accessible resources are discoverable. Project inventory is metadata: "
             "metrics belong to the parent account/deployment and are **not project-attributed**."),
        query("account-inventory", ACCOUNT_QUERY +
              "| where id in~ ({FoundryResources}) "
              "| project Account=name, ResourceGroup=resourceGroup, Subscription=subscriptionId, "
              "Region=location, Kind=kind, AccountResourceId=id",
              kind=1, visualization="grid",
              crossComponentResources=["{Subscriptions}"],
              resourceType="microsoft.resourcegraph/resources"),
        query("project-inventory",
              SUBSCRIPTION_FILTER +
              "| where type =~ 'microsoft.cognitiveservices/accounts/projects' "
              "| extend AccountResourceId=tostring(split(tolower(id), '/projects/')[0]) "
              "| where AccountResourceId in~ ({FoundryResources}) "
              "| project Project=name, ResourceGroup=resourceGroup, Subscription=subscriptionId, "
              "AccountResourceId, ProjectResourceId=id",
              kind=1, visualization="grid",
              noDataMessage="No accessible Foundry projects for the selected accounts.",
              crossComponentResources=["{Subscriptions}"],
              resourceType="microsoft.resourcegraph/resources"),
        text("detail-scope", "### Detail account: {FoundryResource:name}\n"
             "`{FoundryResource}`\n\nARM summary tables below use this account only; "
             "native metric visuals compare all **Compare accounts** selections."),
    ]


def apply_scope(workbook):
    params = next(item for item in workbook["items"] if item["type"] == 9)
    retained = [p for p in params["content"]["parameters"]
                if p["name"] not in ("Subscriptions", "FoundryResources", "FoundryResource")]
    params["content"]["parameters"] = scope_parameters() + retained
    workbook["items"] = [
        item for item in workbook["items"]
        if item["name"] not in {i["name"] for i in inventory()}
    ]
    index = workbook["items"].index(params) + 1
    workbook["items"][index:index] = inventory()
    for item in workbook["items"]:
        if item["type"] == 10:
            item["content"]["resourceIds"] = ["{FoundryResources}"]
            for metric in item["content"]["metrics"]:
                metric["splitByLimit"] = 1000
    return workbook


def limit_parameter(name, key, field):
    return parameter(
        name, 1, isHiddenWhenLocked=True, queryType=12,
        query=arm("{Deployment}", f"$.properties.rateLimits[?(@.key=='{key}')].{field}",
                  [], **{"api-version": "2024-10-01"}),
    )


def per_minute_parameter(name, count, window):
    def criterion(**values):
        return dict(criteriaContext=values)
    return parameter(name, 1, isHiddenWhenLocked=True, criteriaData=[
        criterion(leftOperand=count, operator="is Empty",
                  resultValType="static", resultVal=""),
        criterion(leftOperand=window, operator=">",
                  rightValType="static", rightVal="0",
                  resultValType="expression", resultVal=f"60 * {{{count}}} / {{{window}}}"),
        criterion(operator="Default", resultValType="static", resultVal=""),
    ])


def minute_query(name, metric, aggregation, fields, threshold=None, status=None):
    filters = "ModelDeploymentName eq '{Deployment:label}'"
    if status:
        filters += f" and StatusCode eq '{status}'"
    columns = [column("$.timeStamp", "Time", "datetime")]
    columns += [column(f"$.{field}", label, "real") for field, label in fields]
    chart = dict(xAxis="Time", yAxis=[label for _, label in fields],
                 showLegend=True, showMetrics=False)
    if threshold is not None:
        chart.update(customThresholdLine=threshold, customThresholdLineStyle=1)
    return query(
        name, arm("{FoundryResource}/providers/microsoft.insights/metrics",
                  "$.value[0].timeseries[0].data[*]", columns,
                  **{"api-version": "2018-01-01", "metricnames": metric,
                     "aggregation": aggregation, "interval": "PT1M",
                     "autoAdjustTimegrain": "false",
                     "timespan": "{TimeRange:startISO}/{TimeRange:endISO}",
                     "$filter": filters}),
        visualization="timechart", chartSettings=chart,
        timeContextFromParameter="TimeRange",
        noDataMessage="No reported samples for this deployment/metric. Missing is not zero.",
    )


def capacity_workbook():
    params = [
        parameter("TimeRange", 4, isRequired=True, value=dict(durationMs=3600000),
                  typeSettings=dict(selectableValues=[
                      dict(durationMs=3600000), dict(durationMs=21600000),
                      dict(durationMs=86400000), dict(durationMs=604800000)])),
        parameter("Deployment", 2, label="Detail deployment", isRequired=True,
                  queryType=12,
                  query=arm("{FoundryResource}/deployments", "$.value[*]",
                            [column("$.id", "value"), column("$.name", "label")],
                            **{"api-version": "2024-10-01"}),
                  typeSettings=dict(showDefault=False)),
        limit_parameter("TokenCount", "token", "count"),
        limit_parameter("TokenWindow", "token", "renewalPeriod"),
        limit_parameter("RequestCount", "request", "count"),
        limit_parameter("RequestWindow", "request", "renewalPeriod"),
        per_minute_parameter("TPM", "TokenCount", "TokenWindow"),
        per_minute_parameter("RPM", "RequestCount", "RequestWindow"),
    ]
    items = [
        text("intro", "## Foundry Model Usage vs Capacity\n"
             "Compare account/deployment traffic, then drill into one deployment's "
             "**current allocated limits**, not subscription-wide assigned quota. "
             "No logs, quota-unit conversions, monitoring backend, or inference calls.\n\n"
             "All capacity drilldown charts use **one-minute buckets**. Missing samples "
             "remain missing; reported zero samples remain zero. Capacity is read now "
             "from ARM and is not a historical limit series."),
        dict(type=9, name="parameters", content=dict(
            version=VERSION, parameters=params, style="pills")),
    ]
    for name, metric in [("compare-tokens", "TotalTokens"), ("compare-requests", "ModelRequests")]:
        items.append(dict(type=10, name=name, content=dict(
            chartId=f"model-capacity-{name}", version="MetricsItem/2.0", size=0,
            title="Account/deployment comparison (interval totals, not utilization)",
            chartType=2, resourceIds=["{FoundryResources}"],
            timeContextFromParameter="TimeRange",
            resourceType="microsoft.cognitiveservices/accounts",
            metrics=[dict(namespace="microsoft.cognitiveservices/accounts",
                          metric=f"microsoft.cognitiveservices/accounts--{metric}",
                          aggregation=1, splitBy="ModelDeploymentName", splitByLimit=1000)])))
    items.extend([
        text("deployment-scope", "### Capacity drilldown: {Deployment:label}\n"
             "`{Deployment}`\n\nCurrent allocated TPM: **{TPM}**; current RPM equivalent: "
             "**{RPM}**. Blank limits mean unavailable, not zero or unlimited. "
             "The charts' horizontal reference lines use those current values."),
        query("deployment-configuration", arm(
            "{Deployment}", "$", [
                column("$.id", "Deployment resource ID"),
                column("$.sku.name", "Deployment type"),
                column("$.sku.capacity", "SKU capacity units (not TPM)", "real"),
                column("$.properties.dynamicThrottlingEnabled", "Dynamic throttling", "boolean"),
            ], **{"api-version": "2024-10-01"}), visualization="grid"),
        query("rate-limits", arm(
            "{Deployment}", "$.properties.rateLimits[*]", [
                column("$.key", "Limit kind"), column("$.count", "Count", "real"),
                column("$.renewalPeriod", "Renewal period (seconds)", "real"),
            ], **{"api-version": "2024-10-01"}), visualization="grid",
            noDataMessage="ARM did not report rate limits. No capacity is inferred from SKU units."),
        text("tokens-label", "### Processed tokens/minute vs current allocated TPM (approximate)\n"
             "`TotalTokens`, Sum, PT1M. Azure admission throttling uses **arrival-time estimated "
             "tokens** (including requested output), not these processed-token totals. "
             "Below-limit processed traffic can still receive 429s. Do not interpret "
             "this as exact throttling headroom or billed cost."),
        minute_query("tokens-vs-tpm", "TotalTokens", "Total",
                     [("total", "Processed tokens/minute")], "{TPM}"),
        text("requests-label", "### Requests/minute vs current RPM equivalent\n"
             "`ModelRequests`, Sum, PT1M, including failures. RPM = 60 x reported request "
             "count / renewal period in seconds. For example, 10 requests per 10 seconds "
             "means 60 RPM equivalent, **not** permission to burst 60 requests at once. "
             "Sub-minute enforcement and dynamic throttling can cause 429s below this line."),
        minute_query("requests-vs-rpm", "ModelRequests", "Total",
                     [("total", "Requests/minute")], "{RPM}"),
        text("ptu-label", "### PTU utilization vs 100% capacity\n"
             "`ProvisionedUtilization`, Average/Maximum, PT1M. The **100%** reference is "
             "the PTU capacity threshold, not 100 TPM or SKU units. Non-PTU or unsupported "
             "deployments may have no samples; an empty chart does not mean 0% utilization. "
             "One-minute averages can hide bursts; maximum reported samples help identify peaks."),
        minute_query("ptu-utilization", "ProvisionedUtilization", "Average,Maximum",
                     [("average", "Average utilization (%)"),
                      ("maximum", "Maximum utilization (%)")], "100"),
        text("throttling-label", "### 429 throttling counts/minute\n"
             "Reported HTTP 429 responses for this account/deployment, not a count of "
             "quota units. Missing series are not a measured zero. Use Inference Health "
             "for other HTTP status codes."),
        minute_query("throttling-429", "ModelRequests", "Total",
                     [("total", "HTTP 429 responses/minute")], status="429"),
    ])
    return apply_scope(dict(version="Notebook/1.0", isLocked=False,
                            fallbackResourceIds=["__MODEL_ACCOUNT_RESOURCE_ID__"], items=items))


def main():
    for name in ("model-fleet", "model-health", "model-signals", "model-capacity"):
        path = ROOT / "workbooks" / f"{name}.workbook.json"
        workbook = capacity_workbook() if name == "model-capacity" else apply_scope(
            json.loads(path.read_text(encoding="utf-8")))
        path.write_text(json.dumps(workbook, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
