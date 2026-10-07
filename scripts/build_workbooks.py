"""Apply shared scope, Fleet rollups, and the usage/capacity workbook."""

import json
import copy
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
                  value=["value::all"],
                  query=ACCOUNT_QUERY + (
                      "| project value=id, label=strcat(name, ' (', resourceGroup, ')'), "
                      "selected=false, group=subscriptionId"),
                  crossComponentResources=["{Subscriptions}"], queryType=1,
                  resourceType="microsoft.resourcegraph/resources",
                  typeSettings=dict(additionalResourceOptions=["value::all"],
                                    showDefault=False)),
        parameter("FoundryResource", 5, label="Investigate resource", isRequired=True,
                  value="value::1",
                  query=ACCOUNT_QUERY + (
                      "| where id in~ ({FoundryResources}) "
                      "| extend Preferred=id =~ '__MODEL_ACCOUNT_RESOURCE_ID__' "
                      "| order by Preferred desc, id asc "
                      "| project value=id, label=strcat(name, ' (', resourceGroup, ')'), "
                      "selected=id =~ '__MODEL_ACCOUNT_RESOURCE_ID__'"),
                  crossComponentResources=["{Subscriptions}"], queryType=1,
                  resourceType="microsoft.resourcegraph/resources",
                  typeSettings=dict(additionalResourceOptions=["value::1"],
                                    showDefault=False)),
    ]


def inventory():
    return [
        text("scope-notes", "### Subscription comparison and account drilldown\n"
             "**Compare accounts: All** includes all eligible discovered accounts in the "
             "explicitly selected subscriptions, including new accounts on scope refresh. "
             "Choose a manual subset to filter comparison; return to **All** for broad scope. "
             "**Investigate resource** below never narrows the overview. Changing comparison "
             "scope removes out-of-scope detail selections.\n\n"
             "Only RBAC-accessible accounts are discoverable. Queries request up to **1,000 "
             "series per resource/metric**; this is a cap, not proof of complete results. "
             "Discovery and grids also have limits; reduce scope/range for large estates. "
             "Blank cells/no data are not healthy zeroes; query errors must be investigated."),
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
        text("detail-scope", "### Investigate resource: {FoundryResource:name}\n"
             "`{FoundryResource}`\n\nARM summary tables below use this account only; "
             "estate comparison above remains scoped by **Compare accounts**."),
    ]


def apply_scope(workbook):
    params = next(item for item in workbook["items"] if item["type"] == 9)
    retained = [p for item in workbook["items"] if item["type"] == 9
                for p in item["content"]["parameters"]
                if p["name"] not in ("Subscriptions", "FoundryResources", "FoundryResource")]
    global_names = {"TimeRange", "LatencyMetric"}
    scope = scope_parameters()
    params["content"]["parameters"] = scope[:2] + [
        p for p in retained if p["name"] in global_names]
    detail_params = dict(type=9, name="investigation-parameters", content=dict(
        version=VERSION, parameters=scope[2:] + [
            p for p in retained if p["name"] not in global_names], style="pills"))
    workbook["items"] = [
        item for item in workbook["items"]
        if item["name"] not in {i["name"] for i in inventory()} |
        {"investigation-parameters"}
    ]
    index = workbook["items"].index(params) + 1
    workbook["items"][index:index] = inventory()
    workbook["items"].append(detail_params)
    for item in workbook["items"]:
        if item["type"] == 10:
            item["content"]["resourceIds"] = ["{FoundryResources}"]
            item["content"]["resourceLimit"] = 10000
            for metric in item["content"]["metrics"]:
                metric["splitByLimit"] = 1000
        if item["type"] == 3 and item["content"].get("queryType") == 12:
            spec = json.loads(item["content"]["query"])
            args = {p["key"]: p["value"] for p in spec["urlParams"]}
            if "/metrics" in spec["path"] and "eq '*'" in args.get("$filter", ""):
                args["top"] = "1000"
                spec["urlParams"] = [dict(key=k, value=v) for k, v in args.items()]
                item["content"]["query"] = compact(spec)
    return admin_layout(workbook)


def metric_grid(name, metrics, split=None):
    namespace = "microsoft.cognitiveservices/accounts"
    formatters = [
        dict(columnMatch="Name", formatter=13, formatOptions=dict(showIcon=False)),
        dict(columnMatch="Subscription", formatter=13,
             formatOptions=dict(showIcon=False)),
    ]
    definitions = []
    labels = [dict(columnId="Subscription", label="Subscription"),
              dict(columnId="Name", label="Resource")]
    if split:
        labels.append(dict(columnId="Segment", label=(
            "Deployment / HTTP status" if len(split) > 1 else "Deployment")))
    else:
        formatters.append(dict(columnMatch="Segment", formatter=5))
    for metric, aggregation, label in metrics:
        key = f"{namespace}--{metric}"
        definition = dict(namespace=namespace, metric=key, aggregation=aggregation,
                          splitByLimit=1000)
        if split:
            definition["splitBy"] = split
        definitions.append(definition)
        labels.append(dict(columnId=key, label=label))
        formatters.extend([dict(columnMatch=key, formatter=1),
                           dict(columnMatch=key + " Timeline", formatter=5)])
    return dict(type=10, name=name, content=dict(
        version="MetricsItem/2.0", chartId="admin-" + name, size=0, chartType=0,
        gridFormatType=2, resourceLimit=10000, resourceIds=["{FoundryResources}"],
        resourceType=namespace, timeContextFromParameter="TimeRange",
        timeGrain="FULL", metrics=definitions, title=name.replace("-", " ").title(),
        gridSettings=dict(formatters=formatters, labelSettings=labels,
                          rowLimit=10000, filter=True)))


def admin_layout(workbook):
    by_name = {i["name"]: i for i in workbook["items"]}
    intro = by_name["intro"]["content"]["json"]
    fleet = "Fleet" in intro
    capacity = "Capacity" in intro
    signals = "Volume, Latency" in intro
    totals = [("InputTokens", 1, "Input tokens"), ("OutputTokens", 1, "Output tokens"),
              ("TotalTokens", 1, "Total tokens"), ("ModelRequests", 1, "Requests")]
    operational = [("ModelRequests", 1, "Requests"),
                   ("ModelAvailabilityRate", 4, "Reported availability (%)"),
                   ("TimeToResponse", 4, "First-response latency (ms)")]
    if signals:
        operational[-1] = ("{LatencyMetric}", 4, "First-response latency (ms)")
    comparison = metric_grid("resource-comparison",
                             totals if fleet else totals[2:] if capacity else operational)
    generated = [
        text("comparison-label", "### Compare the estate\n"
             "Sort resource values to identify outliers, then investigate a resource below. "
             "Resource links use full IDs; hover for subscription/resource-group context "
             "when names collide. Missing values remain unavailable. No statistical anomaly "
             "detector or averages-of-averages across resources are used."),
        comparison,
    ]
    if not fleet:
        generated.extend([
            text("deployment-comparison-label", "### Compare resource/deployment signals\n"
                 "Each row retains account identity and the reported deployment dimension. "
                 "Availability is 5xx-only, not a 4xx/429 SLO. Latency is first response, "
                 "not completion or p95. Blank rows do not establish healthy zeroes."),
            metric_grid("deployment-comparison",
                        totals[2:] if capacity else operational, ["ModelDeploymentName"]),
        ])
    if not fleet and not signals and not capacity:
        generated.append(metric_grid(
            "status-comparison", [("ModelRequests", 1, "Requests by HTTP status")],
            ["ModelDeploymentName", "StatusCode"]))
    if capacity:
        generated.extend([
            text("capacity-comparison-label", "### Deployment capacity comparison\n"
                 "Reported PTU utilization compares with **100%**, not token limits. "
                 "Non-PTU/unsupported deployments can have no samples. Current allocated "
                 "token/request rules are read from ARM separately; range traffic totals "
                 "above are **not** divided by TPM/RPM."),
            metric_grid("ptu-comparison", [
                ("ProvisionedUtilization", 3, "Peak reported PTU utilization (%)")],
                ["ModelDeploymentName"]),
            text("capacity-scope-limit", "**Capacity scope:** the overview compares traffic "
                 "and actually reported PTU utilization across resources. Pay-as-you-go "
                 "allocated TPM/RPM is compared with exact one-minute usage for the "
                 "**selected deployment below**, not across the fleet. The current native "
                 "ARM query provider rejects the root batch path needed for multi-account "
                 "configuration enumeration; no backend or inferred allocation is substituted."),
        ])
    generated_names = {i["name"] for i in generated}
    excluded = generated_names | {"account-inventory", "project-inventory",
                                 "detail-scope", "investigation-parameters",
                                 "inventory-label", "metric-response-status",
                                 "metric-response-label"}
    retained = [i for i in workbook["items"] if i["name"] not in excluded]
    if fleet and "requests" in by_name:
        by_name["requests"]["content"]["resourceIds"] = ["{FoundryResource}"]
        by_name["requests"]["content"]["title"] = "Requests by deployment"
        by_name["requests-label"]["content"]["json"] = (
            "### Requests by deployment\nSelected investigation resource only, including "
            "failures. The estate overview above is unchanged.")
    if fleet and "request-trend" in by_name:
        by_name["request-trend"]["content"]["title"] = "Request trends by resource"
        by_name["request-trend-label"]["content"]["json"] = (
            "### Request trends by resource\nSeparate account/deployment series, summed "
            "within each interval, including failures. These are not combined "
            "subscription/model trends. Missing samples are not measured zero.")
    if not fleet and not capacity:
        by_name["intro"]["content"]["json"] = (
            "## Foundry Model " + ("Volume, Latency & Availability" if signals else "Inference Health") +
            "\nCompare the selected estate first, sort resource/deployment signals to identify "
            "outliers, then investigate one resource below. Missing samples are not zero "
            "traffic, zero errors, or perfect availability. Platform metrics require no "
            "diagnostic export or agent traces.")
    if not fleet and not signals and not capacity:
        by_name["status-label"]["content"]["json"] = (
            "### HTTP response trends by resource\nSeparate resource/status series across "
            "Compare accounts. Check 429 throttling, 4xx client errors and 5xx server errors; "
            "a blank chart does not establish zero failures.")
        by_name["status-detail-label"]["content"]["json"] = (
            "### Requests by resource and HTTP status\nSelected-range status totals across "
            "comparison resources, not a combined estate success rate.")
    if not fleet:
        detail_start = next((n for n in ("deployment-scope", "status-by-deployment-label",
                                         "volume-label") if n in by_name), None)
    else:
        detail_start = "mix-label" if "mix-label" in by_name else None
    if detail_start:
        index = next(i for i, item in enumerate(retained) if item["name"] == detail_start)
        overview, detail = retained[:index], retained[index:]
    else:
        overview, detail = retained, []
    # Overview charts are resource comparisons; selected-resource trends belong below.
    if signals:
        for item in detail:
            if item["type"] == 10:
                item["content"]["resourceIds"] = ["{FoundryResource}"]
    if not fleet and not signals and not capacity:
        for item in detail:
            if item["type"] == 10:
                item["content"]["resourceIds"] = ["{FoundryResource}"]
    insertion = next(i for i, item in enumerate(overview) if item["name"] == "scope-notes") + 1
    overview[insertion:insertion] = generated
    if fleet and "subscription-model-totals" in by_name:
        for name in ("model-totals-label", "subscription-model-totals"):
            item = by_name[name]
            overview.remove(item)
            overview.insert(insertion, item)
            insertion += 1
    status_metrics = ("InputTokens,OutputTokens,ModelRequests" if fleet else
                      "TotalTokens,ModelRequests,ProvisionedUtilization" if capacity else
                      "ModelRequests,ModelAvailabilityRate,{LatencyMetric}" if signals else
                      "ModelRequests,ModelAvailabilityRate,TimeToResponse")
    workbook["items"] = overview + [
        by_name["investigation-parameters"], by_name["detail-scope"],
    ] + detail + [
        text("metric-response-label", "### Selected-resource query coverage\n"
             "Metrics List requests up to 1,000 series. A returned count at the cap can "
             "mean truncation; the API has no documented next-page/completeness marker. "
             "Metric error codes/messages below must not be interpreted as no-data or "
             "healthy zeroes. This diagnostic is selected-resource only."),
        query("metric-response-status", arm(
            "{FoundryResource}/providers/microsoft.insights/metrics", "$.value[*]", [
                column("$.name.value", "Metric"),
                column("$.errorCode", "Metric result"),
                column("$.errorMessage", "Metric error"),
                column("$.timeseries.length", "Series returned", "long"),
            ], **{"api-version": "2018-01-01", "metricnames": status_metrics,
                  "interval": "FULL", "top": "1000",
                  "timespan": "{TimeRange:startISO}/{TimeRange:endISO}",
                  "$filter": "ModelDeploymentName eq '*'"}),
              visualization="grid"),
        text("inventory-label", "### Inventory and project mappings\n"
             "Projects map to parent accounts. Platform metrics are **not project-attributed**. "
             "Inventory is RBAC-filtered and may be limited by discovery result caps."),
        by_name["account-inventory"], by_name["project-inventory"],
    ]
    return workbook


def fleet_workbook(workbook):
    workbook = apply_scope(workbook)
    generated_names = {"model-totals-label", "subscription-model-totals",
                       "request-trend-label", "request-trend"}
    workbook["items"] = [item for item in workbook["items"]
                         if item["name"] not in generated_names]
    by_name = {item["name"]: item for item in workbook["items"]}
    by_name["intro"]["content"]["json"] = (
        "## Foundry Model Fleet & Usage\n"
        "Compare **subscription and underlying model** totals across the accounts selected "
        "in **Compare accounts**. Models are identified by the reported `ModelName`, "
        "not deployment aliases; versions with the same model name are combined. "
        "Blank values mean no reported samples, not zero usage. Token counts are **not billed cost**."
    )
    by_name["trend-label"]["content"]["json"] = (
        "### Account/deployment token trends (not subscription/model rollups)\n"
        "Separate series retain resource identity and deployment names. Values are token "
        "totals within each chart interval, not per-minute capacity. No cross-account "
        "grouped sparklines are shown: native Sum sparklines can turn missing buckets into zero."
    )
    by_name["token-trend"]["content"]["title"] = "Account/deployment token trends"
    by_name["mix-label"]["content"]["json"] = (
        "### Tokens by deployment\n"
        "Input and output totals for **Investigate resource** only. Blank output means no reported "
        "output tokens; embeddings commonly report input only. For charges, use Azure Cost Analysis."
    )
    by_name["token-mix"]["conditionalVisibility"] = dict(
        parameterName="FoundryResource", comparison="isNotEqualTo", value="")
    by_name["requests-label"]["content"]["json"] = (
        "### Requests by deployment\n"
        "Selected investigation resource only, including failures. "
        "The estate comparison above is unchanged."
    )
    metric_labels = [
        ("InputTokens", "Input tokens"), ("OutputTokens", "Output tokens"),
        ("TotalTokens", "Total tokens"), ("ModelRequests", "Requests"),
    ]
    formatters = [
        dict(columnMatch="$gen_group", formatter=13, formatOptions=dict(showIcon=False)),
        *[dict(columnMatch=name, formatter=5) for name in ("Name", "Segment")],
    ]
    labels = [dict(columnId="Subscription", label="Subscription / model / account")]
    for metric, label in metric_labels:
        key = f"microsoft.cognitiveservices/accounts--{metric}"
        formatters.extend([
            dict(columnMatch=key, formatter=1, formatOptions=dict(aggregation="Sum")),
            dict(columnMatch=f"{key} Timeline", formatter=5),
        ])
        labels.append(dict(columnId=key, label=label))
    totals = dict(type=10, name="subscription-model-totals", content=dict(
        chartId="model-fleet-subscription-model-totals", version="MetricsItem/2.0",
        size=0, chartType=0, gridFormatType=2, resourceLimit=10000,
        showExpandCollapseGrid=True, resourceIds=["{FoundryResources}"],
        resourceType="microsoft.cognitiveservices/accounts",
        timeContextFromParameter="TimeRange",
        metrics=[dict(namespace="microsoft.cognitiveservices/accounts",
                      metric=f"microsoft.cognitiveservices/accounts--{metric}",
                      aggregation=1, splitBy=["ModelName"], splitByLimit=1000)
                 for metric, _ in metric_labels],
        gridSettings=dict(
            hierarchySettings=dict(treeType=1, groupBy=["Subscription", "Segment"],
                                   expandTopLevel=True, finalBy="Name"),
            formatters=formatters, labelSettings=labels, rowLimit=10000),
    ))
    detail = by_name["detail-scope"]
    workbook["items"].remove(detail)
    index = workbook["items"].index(by_name["trend-label"])
    workbook["items"][index:index] = [
        text("model-totals-label", "### Combined subscription/model totals\n"
             "Input/output/total-token and request totals for the selected range. "
             "Subscription IDs are grouping keys, so identically named models in different "
             "subscriptions stay separate. Subscriptions also show an all-model subtotal. "
             "Blank cells remain unavailable, not measured zero. Grouped trend columns are "
             "intentionally disabled to preserve missing-versus-zero semantics."),
        totals,
    ]
    index = workbook["items"].index(by_name["token-trend"]) + 1
    workbook["items"][index:index] = [
        text("request-trend-label", "### Account/deployment request trends (not subscription/model rollups)\n"
             "Separate resource/deployment series, summed within each interval, including failures. "
             "These are not combined subscription/model trends. Missing samples are not measured zero."),
        dict(type=10, name="request-trend", content=dict(
            chartId="model-fleet-request-trend", version="MetricsItem/2.0", size=0,
            chartType=2, title="Account/deployment request trends",
            resourceIds=["{FoundryResources}"],
            resourceType="microsoft.cognitiveservices/accounts",
            timeContextFromParameter="TimeRange",
            metrics=[dict(namespace="microsoft.cognitiveservices/accounts",
                          metric="microsoft.cognitiveservices/accounts--ModelRequests",
                          aggregation=1, splitBy="ModelDeploymentName", splitByLimit=1000)])),
    ]
    workbook["items"].insert(workbook["items"].index(by_name["mix-label"]), detail)
    return admin_layout(workbook)


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
                  resultValType="static", resultVal="Unavailable"),
        criterion(leftOperand=window, operator=">",
                  rightValType="static", rightVal="0",
                  resultValType="expression", resultVal=f"60 * {{{count}}} / {{{window}}}"),
        criterion(operator="Default", resultValType="static", resultVal="Unavailable"),
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
                      dict(durationMs=86400000), dict(durationMs=518400000)])),
        parameter("Deployment", 2, label="Detail deployment", isRequired=True,
                  queryType=12,
                  query=arm("{FoundryResource}/deployments", "$.value[*]",
                            [column("$.id", "value"), column("$.name", "label"),
                             column("$.name", "selected")],
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
             "**{RPM}**. Unavailable limits mean ARM did not report a usable limit, "
             "not zero or unlimited. "
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
    for name, limit in (("tokens-vs-tpm", "TPM"), ("requests-vs-rpm", "RPM")):
        numeric = next(i for i in items if i["name"] == name)
        unavailable = copy.deepcopy(numeric)
        unavailable["name"] += "-unavailable"
        unavailable["content"]["chartSettings"].pop("customThresholdLine")
        unavailable["content"]["chartSettings"].pop("customThresholdLineStyle")
        unavailable["content"]["title"] = "Usage only: current limit unavailable"
        for item, comparison in ((numeric, "isNotEqualTo"), (unavailable, "isEqualTo")):
            item["conditionalVisibility"] = dict(
                parameterName=limit, comparison=comparison, value="Unavailable")
        items.insert(items.index(numeric) + 1, unavailable)
    return apply_scope(dict(version="Notebook/1.0", isLocked=False,
                            fallbackResourceIds=["__MODEL_ACCOUNT_RESOURCE_ID__"], items=items))


def main():
    for name in ("model-fleet", "model-health", "model-signals", "model-capacity"):
        path = ROOT / "workbooks" / f"{name}.workbook.json"
        workbook = capacity_workbook() if name == "model-capacity" else apply_scope(
            json.loads(path.read_text(encoding="utf-8")))
        if name == "model-fleet":
            workbook = fleet_workbook(workbook)
        path.write_text(json.dumps(workbook, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
