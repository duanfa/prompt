"""机构自定义规则的表达式与本体规则合并，其引用属性是 run_process 的必填输入。"""
import json
import os
import unittest

try:
    from . import test_scripts as fx
except ImportError:
    import test_scripts as fx


class InstRequiredTests(unittest.TestCase):
    def setUp(self):
        self.f = fx.ScriptTests()
        self.f.setUp()
        self.f.ready()
        self.write("inst.json", {
            "succeed": True, "code": "200", "message": "操作成功",
            "model": [
                {"companyName": "Employer.employer_name CONTAINS [使用的应用]"},
                {"projectName": "Project.project_name CONTAINS [使用的应用]"},
            ], "total": 2,
        })
        self.write("base-rules.json", {"data": [{
            "ruleId": "RULE-BASE", "label": "企业类型", "condition": "Employer.enterprise_type = limited_company",
        }]})
        self.write("base-props.json", {"data": [{
            "name": "Employer", "label": "企业", "properties": [
                {"name": "enterprise_type", "label": "企业类型", "comment": None},
            ],
        }]})
        self.spec = {"map": {"Employer.employer_name": ["A02"], "Project.project_name": ["A08"]},
                     "skip": {"R10": ["Employer.enterprise_type"]}}

    def tearDown(self):
        self.f.tearDown()

    def write(self, name, data):
        with open(os.path.join(self.f.ws, name), "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)

    def combined(self):
        return self.f.ws + "/work/" + fx.RID + "/input-combine.json"

    def build(self):
        return fx.run(self.f.ws, "combine.py", "build", "--rid", fx.RID,
                      "--rules", "base-rules.json", "inst.json", "--props", "base-props.json",
                      stdin=json.dumps(self.spec, ensure_ascii=False))

    def test_model_envelope_merges_rules_and_passes_values_without_definitions(self):
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        self.assertIn("validate: OK", out)
        inp = self.f.inp(out)
        self.assertEqual(inp["Employer"]["employer_name"], "上海修匀软件开发有限责任公司")
        self.assertEqual(inp["Project"]["project_name"], "内部管理系统开发调试")
        with open(self.combined(), encoding="utf-8") as handle:
            cb = json.load(handle)
        self.assertEqual(cb["input"], inp)
        self.assertEqual(set(cb["refKeys"]["Employer"]), {"enterprise_type", "employer_name"})
        self.assertEqual(cb["refKeys"]["Project"], ["project_name"])
        self.assertEqual(cb["notFoundInDefinition"], [])
        prop = cb["entities"]["Project"]["properties"]["project_name"]
        self.assertEqual(prop["extractIds"], ["A08"])
        self.assertEqual(prop["rules"][0]["ruleId"], "INST-projectName")
        self.assertEqual(prop["rules"][0]["condition"], "Project.project_name CONTAINS [使用的应用]")

    def test_omitted_mapping_blocks_engine_input(self):
        del self.spec["map"]["Project.project_name"]
        rc, out = self.build()
        self.assertEqual(rc, 1, out)
        self.assertIn("INST_REQUIRED_MISSING Project.project_name", out)
        self.assertNotIn("validate: OK", out)
        self.assertFalse(any(line.startswith("INPUT ") for line in out.splitlines()))

    def test_explicit_skip_does_not_satisfy_required_input(self):
        del self.spec["map"]["Project.project_name"]
        self.spec["skip"]["R13"] = ["Project.project_name"]
        rc, out = self.build()
        self.assertEqual(rc, 1, out)
        self.assertIn("INST_REQUIRED_MISSING Project.project_name", out)
        self.assertFalse(any(line.startswith("INPUT ") for line in out.splitlines()))

    def test_missing_source_is_not_replaced_with_a_placeholder(self):
        rc, out = self.f.force([["A08", None, "R01｜请求没有提供项目内容"]])
        self.assertEqual(rc, 0, out)
        rc, out = self.build()
        self.assertEqual(rc, 1, out)
        self.assertIn("INST_REQUIRED_MISSING Project.project_name", out)
        with open(self.combined(), encoding="utf-8") as handle:
            cb = json.load(handle)
        self.assertNotIn("project_name", cb["input"].get("Project", {}))
        self.assertIn("project_name", cb["unfilled"]["Project"]["R01"])

    def test_arbitrary_referenced_keys_are_required_without_fixed_mapping(self):
        self.write("inst.json", {"model": [{"companyName": "Customer.company_text CONTAINS [使用的应用]"}]})
        self.spec["map"] = {"Customer.company_text": ["A02"]}
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.f.inp(out)["Customer"]["company_text"], "上海修匀软件开发有限责任公司")

    def test_standalone_validate_rejects_empty_custom_rule_input(self):
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        with open(self.combined(), encoding="utf-8") as handle:
            cb = json.load(handle)
        cb["input"]["Project"]["project_name"] = ""
        cb["entities"]["Project"]["properties"]["project_name"]["value"] = ""
        with open(self.combined(), "w", encoding="utf-8") as handle:
            json.dump(cb, handle, ensure_ascii=False)
        rc, out = fx.run(self.f.ws, "combine.py", "validate", "--rid", fx.RID,
                         "--rules", "base-rules.json", "inst.json")
        self.assertEqual(rc, 1, out)
        self.assertIn("INST_REQUIRED_MISSING Project.project_name", out)


if __name__ == "__main__":
    unittest.main()
