"""一般行业兜底：复现分类已有值而用工场景遗漏，以及不应兜底的边界。"""
import json
import os
import unittest

try:
    from . import test_scripts as fx
except ImportError:
    import test_scripts as fx


class IndustryFallbackTests(unittest.TestCase):
    target = "Employer.usage_scenario"
    source1 = "Request.industry_category"
    source2 = "Request.actual_business_category"
    comment = "枚举 IndustryCategory：金融类、传销类、违法类、高危类、同业类、敏感类、音视频制作、一般行业"

    def setUp(self):
        self.f = fx.ScriptTests()
        self.f.setUp()
        self.f.ready()
        self.props = {"data": [
            {"name": "Employer", "label": "企业", "properties": [
                {"name": "usage_scenario", "label": "用工场景", "comment": self.comment}]},
            {"name": "Request", "label": "需求", "properties": [
                {"name": "industry_category", "label": "所属行业类别", "comment": self.comment},
                {"name": "actual_business_category", "label": "实际业务类别", "comment": self.comment}]},
        ]}
        self.rules = {"data": [
            {"ruleId": "RULE-GATE-003", "label": "用工场景为空转人工", "condition": self.target + " IS EMPTY"},
            {"ruleId": "RULE-IND-001", "label": "金融行业", "condition": self.source1 + " = financial"},
            {"ruleId": "RULE-IND-002", "label": "实际敏感业务", "condition": self.source2 + " = sensitive"},
        ]}
        self.spec = {"map": {self.source1: ["A08", "B08"], self.source2: ["A08", "F02"]}, "set": {
            self.source1: ["一般行业", "派生:A08,B08｜一般行业｜置信度约95%｜项目内容及经营范围为软件开发"],
            self.source2: ["一般行业", "派生:A08,F02｜一般行业｜置信度约95%｜项目内容及照片展示软件开发"],
        }}

    def tearDown(self):
        self.f.tearDown()

    def build(self, spec=None):
        for name, data in (("industry-props.json", self.props), ("industry-rules.json", self.rules)):
            with open(os.path.join(self.f.ws, name), "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
        rc, out = fx.run(self.f.ws, "combine.py", "build", "--rid", fx.RID,
                         "--rules", "industry-rules.json", "--props", "industry-props.json",
                         stdin=json.dumps(self.spec if spec is None else spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertIn("validate: OK", out)
        return out, self.f.inp(out)

    def combined(self):
        with open(os.path.join(self.f.ws, "work", fx.RID, "input-combine.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def assert_unfilled(self):
        out, inp = self.build()
        self.assertNotIn("usage_scenario", inp.get("Employer", {}))
        self.assertNotIn("GENERAL_INDUSTRY_FALLBACK", out)
        return out

    def test_trace_regression_fills_omitted_scenario_and_cleans_missing_notes(self):
        out, inp = self.build()
        self.assertEqual(inp["Employer"]["usage_scenario"], "一般行业")
        self.assertIn("GENERAL_INDUSTRY_FALLBACK " + self.target, out)
        self.assertNotIn("UNDECIDED", out)
        cb = self.combined()
        self.assertNotIn("Employer", cb["unfilled"])
        prop = cb["entities"]["Employer"]["properties"]["usage_scenario"]
        self.assertEqual(prop["extractIds"], ["A08", "B08", "F02"])
        self.assertTrue(prop["value_source"].startswith("派生:A08,B08,F02｜一般行业兜底"))
        notes = json.loads(out.split("NOTES ", 1)[1].split("\n", 1)[0])
        self.assertFalse(any("usage_scenario" in row for row in notes["unresolvedProperties"]))

    def test_each_property_uses_its_own_current_enum_code(self):
        self.props["data"][0]["properties"][0]["enum"] = {"ordinary_usage": "一般行业", "restricted": "敏感类"}
        self.props["data"][1]["properties"][0]["enum"] = {"ordinary_industry": "一般行业", "financial": "金融类"}
        self.props["data"][1]["properties"][1]["enum"] = [{"code": "ordinary_business", "label": "一般行业"}]
        out, inp = self.build()
        self.assertEqual(inp["Request"]["industry_category"], "ordinary_industry")
        self.assertEqual(inp["Request"]["actual_business_category"], "ordinary_business")
        self.assertEqual(inp["Employer"]["usage_scenario"], "ordinary_usage")

    def test_special_category_or_disagreement_does_not_fall_back(self):
        for value in ["金融类", "传销类", "违法类", "高危类", "同业类", "敏感类", "音视频制作"]:
            with self.subTest(value=value):
                self.spec["set"][self.source2][0] = value
                self.assert_unfilled()

    def test_one_missing_or_invalid_classifier_does_not_fall_back(self):
        del self.spec["set"][self.source2]
        self.assertIn("NEED_VALUE", self.assert_unfilled())
        self.spec["set"][self.source2] = ["未知行业", "派生:A08,F02｜无法判定业务类别"]
        self.assertIn("ENUM_DROPPED", self.assert_unfilled())

    def test_missing_source_evidence_does_not_fall_back(self):
        self.spec["map"][self.source2] = ["A08", "C02"]
        self.spec["set"][self.source2] = ["一般行业", "派生:A08,C02｜尝试依赖本次未提供的材料"]
        self.assertIn("模型取值缺少依据", self.assert_unfilled())

    def test_explicit_special_scenario_is_preserved(self):
        self.spec["map"][self.target] = ["A08"]
        self.spec["set"][self.target] = ["敏感类", "派生:A08｜本次用工场景另按敏感类处理"]
        out, inp = self.build()
        self.assertEqual(inp["Employer"]["usage_scenario"], "敏感类")
        self.assertNotIn("GENERAL_INDUSTRY_FALLBACK", out)

    def test_explicit_skip_or_pending_mapping_is_preserved(self):
        self.spec["skip"] = {"R10": [self.target]}
        self.assert_unfilled()
        self.spec["skip"] = {"R10": []}
        self.spec["map"][self.target] = ["A08", "B08"]
        self.assertIn("NEED_VALUE", self.assert_unfilled())

    def test_no_general_option_or_no_definition_does_not_invent_value(self):
        prop = self.props["data"][0]["properties"][0]
        prop["comment"] = "枚举 IndustryCategory：金融类、敏感类"
        self.assert_unfilled()
        self.props["data"][0]["properties"] = []
        self.assert_unfilled()
        self.assertIn(self.target, self.combined()["notFoundInDefinition"])

    def test_target_not_referenced_by_active_rules_is_not_added(self):
        self.rules["data"] = self.rules["data"][1:]
        self.assert_unfilled()
        cb = self.combined()
        self.assertNotIn("usage_scenario", cb["refKeys"].get("Employer", []))

    def test_definition_and_rule_type_conflict_does_not_bypass_validation(self):
        self.rules["data"].append({"ruleId": "WRONG-TYPE", "label": "布尔场景", "condition": self.target + " = true"})
        self.assert_unfilled()

    def test_rebuild_requires_current_classification_values(self):
        self.build()
        out, inp = self.build({"map": self.spec["map"]})
        self.assertNotIn("usage_scenario", inp.get("Employer", {}))
        self.assertIn("NEED_VALUE", out)
        self.assertNotIn("GENERAL_INDUSTRY_FALLBACK", out)


if __name__ == "__main__":
    unittest.main()
