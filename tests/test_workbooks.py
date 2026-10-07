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
    return [
        {col["columnid"]: next(
            (hit.value for hit in parse(col["path"]).find(row.value)), None)
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


def evaluate_criteria(param, values):
    for row in param["criteriaData"]:
        rule = row["criteriaContext"]
        value = values.get(rule.get("leftOperand"))
        matches = rule["operator"] == "Default"
        if rule["operator"] == "is Empty":
            matches = value is None or value == ""
        if rule["operator"] == ">":
            matches = value not in (None, "") and value > float(rule["rightVal"])
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

    def test_four_books_and_idempotent_generation(self):
        self.assertEqual(4, len(self.books))
        self.assertEqual(self.capacity, builder.capacity_workbook())
        for book in self.books.values():
            self.assertEqual(book, builder.apply_scope(copy.deepcopy(book)))

    def test_all_books_have_subscription_comparison_and_project_inventory(self):
        for book in self.books.values():
            names = {item["name"] for item in book["items"]}
            self.assertTrue({"account-inventory", "project-inventory"} <= names)
            params = next(item["content"]["parameters"] for item in book["items"]
                          if item["type"] == 9)
            by_name = {param["name"]: param for param in params}
            self.assertTrue(by_name["FoundryResources"]["multiSelect"])
            self.assertIn("id in~ ({FoundryResources})", by_name["FoundryResource"]["query"])
            for item in book["items"]:
                if item["type"] == 10:
                    self.assertEqual(["{FoundryResources}"], item["content"]["resourceIds"])
                if item["type"] == 3 and item["content"]["queryType"] == 12:
                    path = json.loads(item["content"]["query"])["path"]
                    self.assertTrue(path.startswith("{FoundryResource}") or path == "{Deployment}")
            projects = next(item for item in book["items"] if item["name"] == "project-inventory")
            self.assertIn("accounts/projects", projects["content"]["query"])
            self.assertNotIn("kind", projects["content"]["query"])
            self.assertIn("tolower(id)", projects["content"]["query"])

    def test_rpm_normalizes_actual_10_second_response_shape(self):
        payload = {"properties": {"rateLimits": [
            {"key": "token", "count": 10000, "renewalPeriod": 60},
            {"key": "request", "count": 10, "renewalPeriod": 10},
        ]}}
        values = {name: extract(self.params[name]["query"], payload)[0]["value"]
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
            self.assertEqual("", evaluate_criteria(self.params["RPM"], values))
        self.assertEqual(0, evaluate_criteria(self.params["RPM"],
                                           {"RequestCount": 0, "RequestWindow": 60}))

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
            self.assertIn("ModelDeploymentName eq '{Deployment:name}'", args["$filter"])
            self.assertEqual(expected[item["name"]],
                             content["chartSettings"].get("customThresholdLine"))
            if item["name"] == "throttling-429":
                self.assertIn("StatusCode eq '429'", args["$filter"])

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


if __name__ == "__main__":
    unittest.main()
