import ast
import copy
import json
import operator
import sys
import unittest
from pathlib import Path

from jsonpath_ng.ext import parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_workbooks as builder


def extract(spec, payload):
    transform = json.loads(spec)["transformers"][0]["settings"]
    if not transform["columns"]:
        return [row.value for row in parse(transform["tablePath"]).find(payload)]

    def field(path, row):
        if path.endswith(".length"):
            parent = next((hit.value for hit in parse(path[:-7]).find(row)), None)
            return len(parent) if isinstance(parent, list) else None
        return next((hit.value for hit in parse(path).find(row)), None)

    return [
        {col["columnid"]: field(col["path"], row.value)
         for col in transform["columns"]}
        for row in parse(transform["tablePath"]).find(payload)
    ]


def arithmetic(expression):
    node = ast.parse(expression, mode="eval").body

    def compute(item):
        if isinstance(item, ast.Constant) and isinstance(item.value, (int, float)):
            return item.value
        if isinstance(item, ast.BinOp) and type(item.op) in (ast.Mult, ast.Div):
            op = {ast.Mult: operator.mul, ast.Div: operator.truediv}[type(item.op)]
            return op(compute(item.left), compute(item.right))
        raise ValueError("Unexpected expression")
    return compute(node)


def nullable_sum(values):
    reported = [value for value in values if value is not None]
    return sum(reported) if reported else None


def evaluate_criteria(param, values):
    if any(not row["criteriaContext"]["resultVal"] for row in param["criteriaData"]):
        raise ValueError("Portal criteria results must be nonempty")
    for row in param["criteriaData"]:
        rule = row["criteriaContext"]
        value = values.get(rule.get("leftOperand"))
        matches = rule["operator"] == "Default"
        if rule["operator"] == "is Empty":
            matches = value is None or value == ""
        if rule["operator"] == ">":
            matches = value not in (None, "") and float(value) > float(rule["rightVal"])
        if matches:
            result = rule["resultVal"]
            if rule["resultValType"] == "expression":
                for name, val in values.items():
                    result = result.replace("{" + name + "}", str(val))
                return arithmetic(result)
            return result
    raise AssertionError("Criteria had no result")


class WorkbookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.books = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in (builder.ROOT / "workbooks").glob("*.json")
        }
        cls.capacity = cls.books["model-capacity.workbook"]
        cls.params = {
            param["name"]: param
            for item in cls.capacity["items"] if item["type"] == 9
            for param in item["content"]["parameters"]
        }

    def test_native_all_defaults_and_isolated_cascading_detail(self):
        for book in self.books.values():
            params = {p["name"]: p for i in book["items"] if i["type"] == 9
                      for p in i["content"]["parameters"]}
            comparison = params["FoundryResources"]
            self.assertEqual(["value::all"], comparison["value"])
            self.assertEqual(["value::all"],
                             comparison["typeSettings"]["additionalResourceOptions"])
            self.assertNotIn("selectAllValue", comparison["typeSettings"])
            self.assertIn("selected=false", comparison["query"])
            self.assertNotIn("value::all", params["Subscriptions"]["value"])
            self.assertIn("id in~ ({FoundryResources})", params["FoundryResource"]["query"])
            names = [i["name"] for i in book["items"]]
            self.assertLess(names.index("resource-comparison"),
                            names.index("investigation-parameters"))
            self.assertLess(names.index("investigation-parameters"),
                            names.index("account-inventory"))
            for i in book["items"][:names.index("investigation-parameters")]:
                self.assertNotIn("{FoundryResource}", json.dumps(i))
                self.assertNotIn("{Deployment}", json.dumps(i))

    def test_shipped_wildcard_rest_queries_explicitly_request_1000_series(self):
        required = {"status-by-deployment", "metric-response-status"}
        found = set()
        for book in self.books.values():
            for item in book["items"]:
                if item["type"] != 3 or item["content"].get("queryType") != 12:
                    continue
                spec = json.loads(item["content"]["query"])
                args = {p["key"]: p["value"] for p in spec["urlParams"]}
                if "/metrics" in spec["path"] and "eq '*'" in args.get("$filter", ""):
                    self.assertEqual("1000", args.get("top"), item["name"])
                    found.add(item["name"])
        self.assertTrue(required <= found)

    def test_fleet_token_detail_is_hidden_without_investigation_resource(self):
        fleet = self.books["model-fleet.workbook"]
        merge = next(i for i in fleet["items"] if i["name"] == "token-mix")
        self.assertEqual({"parameterName": "FoundryResource", "comparison": "isNotEqualTo",
                          "value": ""}, merge["conditionalVisibility"])

    def test_fleet_token_detail_does_not_join_schema_less_empty_rest_tables(self):
        items = {i["name"]: i for i in self.books["model-fleet.workbook"]["items"]}
        tokens = items["token-mix"]
        self.assertEqual(10, tokens["type"])
        content = tokens["content"]
        self.assertEqual(["{FoundryResource}"], content["resourceIds"])
        self.assertEqual("FULL", content["timeGrain"])
        self.assertEqual(
            ["microsoft.cognitiveservices/accounts--InputTokens",
             "microsoft.cognitiveservices/accounts--OutputTokens"],
            [m["metric"] for m in content["metrics"]])
        self.assertTrue(all(m["splitBy"] == ["ModelDeploymentName"]
                            and m["aggregation"] == 1 for m in content["metrics"]))
        self.assertFalse({"token-input-source", "token-output-source"} & items.keys())

    def test_signals_comparisons_bind_static_metric_ids_for_each_latency_selection(self):
        signals = self.books["model-signals.workbook"]
        for name in ("resource-comparison", "deployment-comparison"):
            alternatives = [i for i in signals["items"]
                            if i["name"] in (name, name + "-openai")]
            self.assertEqual(2, len(alternatives))
            for item, latency in zip(alternatives,
                                     ("TimeToResponse", "AzureOpenAITimeToResponse")):
                self.assertEqual(
                    {"parameterName": "LatencyMetric", "comparison": "isEqualTo",
                     "value": latency}, item["conditionalVisibility"])
                self.assertEqual(
                    ["ModelRequests", "ModelAvailabilityRate", latency],
                    [m["metric"].split("--")[1] for m in item["content"]["metrics"]])
                self.assertNotIn("{LatencyMetric}", json.dumps(item["content"]))
                self.assertEqual(["{FoundryResources}"], item["content"]["resourceIds"])

    def test_fleet_unset_detail_has_prompt_instead_of_blank_coverage(self):
        items = {i["name"]: i for i in self.books["model-fleet.workbook"]["items"]}
        self.assertIn("detail-selection-required", items)
        prompt = items["detail-selection-required"]
        self.assertEqual(
            {"parameterName": "FoundryResource", "comparison": "isEqualTo", "value": ""},
            prompt["conditionalVisibility"])
        self.assertIn("Investigate resource", prompt["content"]["json"])
        for name in ("token-mix", "requests", "metric-response-status"):
            self.assertEqual(
                {"parameterName": "FoundryResource", "comparison": "isNotEqualTo",
                 "value": ""}, items[name]["conditionalVisibility"])
        requests = items["requests"]["content"]
        self.assertEqual("FULL", requests["timeGrain"])
        self.assertEqual(2, requests["gridFormatType"])

    def test_fleet_coverage_distinguishes_successful_empty_series_and_metric_errors(self):
        items = {i["name"]: i for i in self.books["model-fleet.workbook"]["items"]}
        spec = items["metric-response-status"]["content"]["query"]
        fixtures = json.loads((builder.ROOT / "tests" / "fixtures" /
                               "fleet-detail-responses.json").read_text())
        self.assertEqual([
            {"Metric": metric, "Metric result": "Success", "Metric error": None,
             "Series returned": 0}
            for metric in ("InputTokens", "OutputTokens", "ModelRequests")
        ], extract(spec, fixtures["empty"]))
        self.assertEqual([
            {"Metric": "InputTokens", "Metric result": "ServerBusy",
             "Metric error": "Metric query is temporarily unavailable.",
             "Series returned": 0}
        ], extract(spec, fixtures["metric_error"]))
        self.assertEqual([], extract(spec, fixtures["no_records"]))
        self.assertIn("noDataMessage", items["metric-response-status"]["content"])
        self.assertEqual([2, 2, 0], [row["Series returned"]
                                    for row in extract(spec, fixtures["asymmetric"])])

    def test_unavailable_limits_select_charts_without_thresholds(self):
        items = {i["name"]: i for i in self.capacity["items"]}
        for name, limit in (("tokens-vs-tpm", "TPM"), ("requests-vs-rpm", "RPM")):
            numeric, unavailable = items[name], items[name + "-unavailable"]
            self.assertEqual("{" + limit + "}",
                             numeric["content"]["chartSettings"]["customThresholdLine"])
            self.assertNotIn("customThresholdLine",
                             unavailable["content"]["chartSettings"])
            for item, comparison in ((numeric, "isNotEqualTo"),
                                     (unavailable, "isEqualTo")):
                self.assertEqual({"parameterName": limit, "comparison": comparison,
                                  "value": "Unavailable"}, item["conditionalVisibility"])
            self.assertEqual(numeric["content"]["query"], unavailable["content"]["query"])

    def test_comparison_grids_do_not_average_across_resource_rows(self):
        for book in self.books.values():
            for item in book["items"]:
                if item["name"] not in ("resource-comparison", "deployment-comparison",
                                        "ptu-comparison"):
                    continue
                settings = item["content"]["gridSettings"]
                self.assertNotIn("hierarchySettings", settings)
                self.assertEqual("FULL", item["content"]["timeGrain"])
                self.assertFalse(any("aggregation" in f.get("formatOptions", {})
                                     for f in settings["formatters"]))
                renderer = next(f for f in settings["formatters"]
                                if f["columnMatch"] == "Name")
                self.assertEqual(13, renderer["formatter"])
                self.assertEqual(False, renderer["formatOptions"]["showIcon"])
                labels = {row["columnId"]: row["label"] for row in settings["labelSettings"]}
                self.assertEqual("Subscription", labels["Subscription"])
                self.assertEqual("Resource", labels["Name"])

    def test_capacity_fallback_is_explicit_and_has_no_rejected_batch_prototype(self):
        source = json.dumps(self.capacity)
        self.assertNotIn('"/batch"', source)
        self.assertNotIn("CapacityRequests", source)
        by_name = {i["name"]: i for i in self.capacity["items"]}
        self.assertIn("selected deployment below",
                      by_name["capacity-scope-limit"]["content"]["json"])
        self.assertEqual(3, by_name["ptu-comparison"]["content"]["metrics"][0]["aggregation"])

    def test_four_books_and_idempotent_generation(self):
        self.assertEqual(4, len(self.books))
        self.assertEqual(self.capacity, builder.capacity_workbook())
        for name, book in self.books.items():
            apply = builder.fleet_workbook if name == "model-fleet.workbook" else builder.apply_scope
            self.assertEqual(book, apply(copy.deepcopy(book)))

    def test_all_books_have_subscription_comparison_and_project_inventory(self):
        for book in self.books.values():
            names = {item["name"] for item in book["items"]}
            self.assertTrue({"account-inventory", "project-inventory"} <= names)
            params = [p for item in book["items"] if item["type"] == 9
                      for p in item["content"]["parameters"]]
            by_name = {param["name"]: param for param in params}
            self.assertTrue(by_name["FoundryResources"]["multiSelect"])
            self.assertIn("id in~ ({FoundryResources})", by_name["FoundryResource"]["query"])
            detail_index = next(n for n, item in enumerate(book["items"])
                                if item["name"] == "investigation-parameters")
            for index, item in enumerate(book["items"]):
                if item["type"] == 10:
                    expected = "{FoundryResources}" if index < detail_index else "{FoundryResource}"
                    if item["name"] in ("compare-tokens", "compare-requests"):
                        expected = "{FoundryResources}"
                    self.assertEqual([expected], item["content"]["resourceIds"])
                if item["type"] == 3 and item["content"]["queryType"] == 12:
                    path = json.loads(item["content"]["query"])["path"]
                    self.assertTrue(path.startswith("{FoundryResource}") or
                                    path in ("{Deployment}", "/batch"))
            projects = next(item for item in book["items"] if item["name"] == "project-inventory")
            self.assertIn("accounts/projects", projects["content"]["query"])
            self.assertNotIn("kind", projects["content"]["query"])
            self.assertIn("tolower(id)", projects["content"]["query"])

    def test_rpm_normalizes_actual_10_second_response_shape(self):
        payload = {"properties": {"rateLimits": [
            {"key": "token", "count": 10000, "renewalPeriod": 60},
            {"key": "request", "count": 10, "renewalPeriod": 10},
        ]}}
        values = {name: str(extract(self.params[name]["query"], payload)[0])
                  for name in ("TokenCount", "TokenWindow", "RequestCount", "RequestWindow")}
        self.assertEqual(10000, evaluate_criteria(self.params["TPM"], values))
        self.assertEqual(60, evaluate_criteria(self.params["RPM"], values))
        values.update(RequestCount=125, RequestWindow=60)
        self.assertEqual(125, evaluate_criteria(self.params["RPM"], values))

    def test_portal_subscription_picker_resource_id_not_just_guid(self):
        self.assertEqual(["/subscriptions/__MODEL_ACCOUNT_SUBSCRIPTION_ID__"],
                         self.params["Subscriptions"]["value"])
        for book in self.books.values():
            params = next(item["content"]["parameters"] for item in book["items"]
                          if item["type"] == 9)
            graph_queries = [p["query"] for p in params if p.get("queryType") == 1]
            graph_queries += [i["content"]["query"] for i in book["items"]
                              if i["type"] == 3 and i["content"]["queryType"] == 1]
            for source in graph_queries:
                for selection in ("'/subscriptions/test-guid'", "'test-guid'"):
                    rendered = source.replace("{Subscriptions}", selection)
                    self.assertIn(f"subscriptionId in~ ({selection})", rendered)
                    self.assertIn(
                        f"strcat('/subscriptions/', subscriptionId) in~ ({selection})",
                        rendered)

    def test_missing_limits_and_invalid_periods_are_not_zero_capacity(self):
        self.assertEqual([], extract(self.params["RequestCount"]["query"], {"properties": {}}))
        for values in ({}, {"RequestCount": None, "RequestWindow": 60},
                       {"RequestCount": 10, "RequestWindow": None},
                       {"RequestCount": 10, "RequestWindow": 0},
                       {"RequestCount": 10, "RequestWindow": -1}):
            self.assertEqual("Unavailable", evaluate_criteria(self.params["RPM"], values))
        self.assertEqual(0, evaluate_criteria(self.params["RPM"],
                                           {"RequestCount": 0, "RequestWindow": 60}))

    def test_portal_criteria_require_nonempty_results_even_for_unmatched_rules(self):
        for name in ("TPM", "RPM"):
            for row in self.params[name]["criteriaData"]:
                self.assertTrue(row["criteriaContext"]["resultVal"],
                                "Portal rejects the entire criteria parameter for empty results")

    def test_exact_minute_queries_and_thresholds(self):
        expected = {
            "tokens-vs-tpm": "{TPM}", "requests-vs-rpm": "{RPM}",
            "ptu-utilization": "100", "throttling-429": None,
        }
        for item in self.capacity["items"]:
            if item["name"] not in expected:
                continue
            content = item["content"]
            spec = json.loads(content["query"])
            args = {p["key"]: p["value"] for p in spec["urlParams"]}
            self.assertEqual("PT1M", args["interval"])
            self.assertEqual("false", args["autoAdjustTimegrain"])
            self.assertIn("ModelDeploymentName eq '{Deployment:label}'", args["$filter"])
            self.assertEqual(expected[item["name"]],
                             content["chartSettings"].get("customThresholdLine"))
            if item["name"] == "throttling-429":
                self.assertIn("StatusCode eq '429'", args["$filter"])

    def test_minute_window_stays_below_actual_portal_10000_point_limit(self):
        for value in self.params["TimeRange"]["typeSettings"]["selectableValues"]:
            self.assertLessEqual(value["durationMs"] // 60000 + 1, 10000)

    def test_missing_zero_and_ptu_no_series_shapes(self):
        source = next(i["content"]["query"] for i in self.capacity["items"]
                      if i["name"] == "tokens-vs-tpm")
        payload = {"value": [{"timeseries": [{"data": [
            {"timeStamp": "2026-01-01T00:00:00Z", "total": 0},
            {"timeStamp": "2026-01-01T00:01:00Z"},
            {"timeStamp": "2026-01-01T00:02:00Z", "total": 4359},
        ]}]}]}
        rows = extract(source, payload)
        self.assertEqual([0, None, 4359], [r["Processed tokens/minute"] for r in rows])
        self.assertEqual([], extract(source, {"value": [{"timeseries": []}]}))
        ptu = next(i["content"]["query"] for i in self.capacity["items"]
                   if i["name"] == "ptu-utilization")
        self.assertEqual([], extract(ptu, {"value": [{"timeseries": []}]}))

    def test_capacity_identity_is_full_resource_not_deployment_name_join(self):
        spec = json.loads(self.params["Deployment"]["query"])
        self.assertEqual("$.id", spec["transformers"][0]["settings"]["columns"][0]["path"])
        first = "/subscriptions/s/resourceGroups/a/providers/Microsoft.CognitiveServices/accounts/a"
        second = first.replace("accounts/a", "accounts/b")
        payload = {"value": [
            {"id": first + "/deployments/shared", "name": "shared"},
            {"id": second + "/deployments/shared", "name": "shared"},
        ]}
        rows = extract(self.params["Deployment"]["query"], payload)
        self.assertNotEqual(rows[0]["value"], rows[1]["value"])
        for item in self.capacity["items"]:
            if item["type"] == 3:
                self.assertNotEqual(7, item["content"]["queryType"])

    def test_dropdown_browser_value_label_and_scalar_text_contract(self):
        self.assertNotEqual("value::1", self.params["Deployment"].get("value"))
        dropdown = json.loads(self.params["Deployment"]["query"])
        self.assertEqual("$.name", dropdown["transformers"][0]["settings"]["columns"][2]["path"])
        value = "/subscriptions/s/resourceGroups/r/providers/Microsoft.CognitiveServices/accounts/a/deployments/MixedCase"
        label = "MixedCase"
        for name in ("TokenCount", "TokenWindow", "RequestCount", "RequestWindow"):
            spec = json.loads(self.params[name]["query"])
            self.assertEqual(value, spec["path"].replace("{Deployment}", value))
            self.assertEqual([], spec["transformers"][0]["settings"]["columns"])
        for item in self.capacity["items"]:
            if item["name"] not in ("tokens-vs-tpm", "requests-vs-rpm",
                                    "ptu-utilization", "throttling-429"):
                continue
            spec = json.loads(item["content"]["query"])
            args = {p["key"]: p["value"] for p in spec["urlParams"]}
            rendered = args["$filter"].replace("{Deployment:label}", label)
            self.assertIn("ModelDeploymentName eq 'MixedCase'", rendered)
            self.assertNotIn(value, rendered)
            self.assertNotIn("{Deployment:name}", args["$filter"])

    def test_fleet_combines_scalar_totals_by_subscription_and_underlying_model(self):
        fleet = self.books["model-fleet.workbook"]
        rollup = next((i for i in fleet["items"] if i["name"] == "subscription-model-totals"), None)
        self.assertIsNotNone(rollup)
        content = rollup["content"]
        self.assertEqual(10, rollup["type"])
        self.assertEqual(2, content["gridFormatType"])
        self.assertEqual(["{FoundryResources}"], content["resourceIds"])
        self.assertEqual(["Subscription", "Segment"],
                         content["gridSettings"]["hierarchySettings"]["groupBy"])
        self.assertEqual({"InputTokens", "OutputTokens", "TotalTokens", "ModelRequests"},
                         {m["metric"].split("--")[-1] for m in content["metrics"]})
        for metric in content["metrics"]:
            self.assertEqual(["ModelName"], metric["splitBy"])
            self.assertEqual(1, metric["aggregation"])
        for formatter in content["gridSettings"]["formatters"]:
            if formatter["columnMatch"].endswith(" Timeline"):
                self.assertEqual(5, formatter["formatter"])
                self.assertNotIn("aggregation", formatter.get("formatOptions", {}))
            elif "--" in formatter["columnMatch"]:
                self.assertEqual("Sum", formatter["formatOptions"]["aggregation"])
                self.assertNotIn("emptyValCustomText", formatter.get("numberFormat", {}))

    def test_fleet_fixture_preserves_subscription_collisions_missing_output_and_zero(self):
        rows = json.loads((builder.ROOT / "tests" / "fixtures" /
                           "subscription-model-metrics.json").read_text())
        groups = {}
        for row in rows:
            key = (row["subscription"], row["model"])
            self.assertTrue(key[0].startswith("/subscriptions/"))
            groups.setdefault(key, []).append(row)
        totals = {
            key: {field: nullable_sum(row[field] for row in group)
                  for field in ("input", "output", "total", "requests")}
            for key, group in groups.items()
        }
        a = "/subscriptions/11111111-1111-1111-1111-111111111111"
        b = "/subscriptions/22222222-2222-2222-2222-222222222222"
        self.assertEqual({"input": 30, "output": 5, "total": 35, "requests": 5},
                         totals[a, "shared-model"])
        self.assertEqual({"input": 70, "output": 40, "total": 110, "requests": 7},
                         totals[b, "shared-model"])
        self.assertEqual(15, totals[a, "embedding-model"]["input"])
        self.assertIsNone(totals[a, "embedding-model"]["output"])
        self.assertEqual(0, totals[a, "zero-model"]["total"])
        self.assertIsNone(totals[a, "missing-model"]["total"])
        self.assertNotEqual(groups[a, "shared-model"][0]["deployment"],
                            groups[a, "shared-model"][1]["deployment"])
        self.assertEqual([10, None, 0], groups[a, "shared-model"][0]["inputTrend"])

    def test_fleet_trends_stay_account_deployment_scoped(self):
        fleet = self.books["model-fleet.workbook"]
        by_name = {i["name"]: i for i in fleet["items"]}
        for name in ("token-trend", "request-trend"):
            self.assertEqual(2, by_name[name]["content"]["chartType"])
            self.assertEqual(["{FoundryResources}"], by_name[name]["content"]["resourceIds"])
            self.assertEqual("ModelDeploymentName",
                             by_name[name]["content"]["metrics"][0]["splitBy"])
            expected = "Request trends by resource" if name == "request-trend" else "Account/deployment"
            self.assertIn(expected, by_name[name]["content"]["title"])
        names = list(by_name)
        self.assertLess(names.index("subscription-model-totals"), names.index("token-trend"))
        self.assertTrue({"token-mix", "requests", "metric-response-status"}
                        <= set(by_name))

    def test_fleet_friendly_labels_are_display_only_with_full_id_leaf_keys(self):
        fleet = self.books["model-fleet.workbook"]
        grid = next(i["content"]["gridSettings"] for i in fleet["items"]
                    if i["name"] == "subscription-model-totals")
        formatter = next((f for f in grid["formatters"]
                          if f["columnMatch"] == "$gen_group"), None)
        self.assertIsNotNone(formatter)
        self.assertEqual(13, formatter["formatter"])
        self.assertEqual({"showIcon": False}, formatter["formatOptions"])
        self.assertEqual(["Subscription", "Segment"], grid["hierarchySettings"]["groupBy"])
        self.assertEqual("Name", grid["hierarchySettings"]["finalBy"])
        rows = json.loads((builder.ROOT / "tests" / "fixtures" /
                           "subscription-model-metrics.json").read_text())
        shared = [row for row in rows if row["model"] == "shared-model"]
        self.assertEqual(1, len({row["account"] for row in shared}))
        self.assertEqual(3, len({row["accountResourceId"] for row in shared}))
        leaves = {}
        for row in shared:
            self.assertTrue(row["accountResourceId"].startswith(row["subscription"] + "/"))
            leaves.setdefault((row["subscription"], row["model"]), {}).setdefault(
                row["accountResourceId"], []).append(row)
        a = "/subscriptions/11111111-1111-1111-1111-111111111111"
        b = "/subscriptions/22222222-2222-2222-2222-222222222222"
        self.assertEqual(2, len(leaves[a, "shared-model"]))
        self.assertEqual(1, len(leaves[b, "shared-model"]))
        self.assertEqual(30, nullable_sum(row["input"] for leaf in leaves[a, "shared-model"].values()
                                         for row in leaf))
        self.assertEqual(70, nullable_sum(row["input"] for leaf in leaves[b, "shared-model"].values()
                                         for row in leaf))


if __name__ == "__main__":
    unittest.main()
