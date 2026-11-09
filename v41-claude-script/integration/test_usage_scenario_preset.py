"""用工场景预设（2026-11-09）：Employer.usage_scenario 必填，和机构 ID 一样由 build 从请求 projCont（A08）原文自动传入。
取代原“一般行业兜底”（generalIndustryFallback）：用工场景不再由模型分类或脚本补漏。
另含规则接口成功码回归：trace e974ced3 中 inst-list-rc-rules 返回 code=200 被误判“不是成功码”。"""
import json
import os
import unittest

try:
    from . import test_scripts as fx
except ImportError:
    import test_scripts as fx

TARGET = "Employer.usage_scenario"
PROJ_CONT = "内部管理系统开发调试"        # fixtures/v25_run/init_spec.json 的 projCont
BASE = {"map": {"Employer.employer_name": ["A02"]}}   # 一条普通映射：完全不提交映射时 build 只打印 PLAN（退出 4）


class UsageScenarioPresetTests(unittest.TestCase):
    comment = "枚举 IndustryCategory：金融类、传销类、违法类、高危类、同业类、敏感类、音视频制作、一般行业"

    def setUp(self):
        self.f = fx.ScriptTests()
        self.f.setUp()
        self.props = {"data": [{"name": "Employer", "label": "企业", "properties": [
            {"name": "usage_scenario", "label": "用工场景", "comment": self.comment}]}]}
        self.rules = {"data": [{"ruleId": "RULE-GATE-003", "label": "用工场景为空转人工", "condition": TARGET + " IS EMPTY"}]}

    def tearDown(self):
        self.f.tearDown()

    def write(self, name, data):
        with open(os.path.join(self.f.ws, name), "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)

    def build(self, spec, rules="s-rules.json"):
        self.write("s-props.json", self.props)
        self.write("s-rules.json", self.rules)
        return fx.run(self.f.ws, "combine.py", "build", "--rid", fx.RID, "--rules", rules,
                      "--props", "s-props.json", stdin=json.dumps(spec, ensure_ascii=False))

    def ok(self, spec):
        rc, out = self.build(spec)
        self.assertEqual(rc, 0, out)
        self.assertIn("validate: OK", out)
        return out, self.f.inp(out)

    def combined(self):
        with open(os.path.join(self.f.ws, "work", fx.RID, "input-combine.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_filled_from_projcont_verbatim_without_enum_conversion(self):
        self.f.ready()
        out, inp = self.ok(BASE)
        self.assertEqual(inp["Employer"]["usage_scenario"], PROJ_CONT)          # 原文照传，不按 comment 枚举转码、不被 ENUM_DROPPED
        self.assertNotIn("ENUM_DROPPED", out)
        self.assertNotIn("UNDECIDED", out)
        prop = self.combined()["entities"]["Employer"]["properties"]["usage_scenario"]
        self.assertEqual(prop["extractIds"], ["A08"])
        self.assertTrue(prop["value_source"].startswith("A08｜"))
        self.assertNotIn("usage_scenario", json.dumps(self.combined().get("unfilled", {}), ensure_ascii=False))

    def test_enum_definition_does_not_drop_raw_text(self):
        self.props["data"][0]["properties"][0]["enum"] = {"ordinary": "一般行业", "sensitive": "敏感类"}
        self.f.ready()
        out, inp = self.ok(BASE)
        self.assertEqual(inp["Employer"]["usage_scenario"], PROJ_CONT)

    def test_model_map_skip_set_are_ignored_not_rejected(self):
        self.f.ready()
        for spec, word in (({"map": dict(BASE["map"]), "skip": {"R10": [TARGET]}}, "skip"),
                           ({"map": dict(BASE["map"], **{TARGET: ["A08", "B08"]})}, "map"),
                           ({"map": dict(BASE["map"], **{TARGET: ["A08"]}), "set": {TARGET: ["一般行业", "派生:A08｜一般行业｜置信度约95%｜软件开发"]}}, "set")):
            with self.subTest(word=word):
                out, inp = self.ok(spec)                                          # 不退回：免得模型多跑一轮
                self.assertEqual(inp["Employer"]["usage_scenario"], PROJ_CONT)
                self.assertIn("PRESET_OVERRIDE_IGNORED " + TARGET, out)
                self.assertIn(word, out.split("PRESET_OVERRIDE_IGNORED", 1)[1].split("\n", 1)[0])

    def test_passed_even_if_definition_or_rule_reference_missing(self):
        self.props["data"][0]["properties"] = [{"name": "employer_name", "label": "企业名称", "comment": None}]
        self.rules["data"] = [{"ruleId": "RULE-X", "label": "企业名称为空", "condition": "Employer.employer_name IS EMPTY"}]
        self.f.ready()
        out, inp = self.ok(BASE)
        self.assertEqual(inp["Employer"]["usage_scenario"], PROJ_CONT)          # 同机构 ID：定义里有没有都传
        self.assertIn("PRESET_UNDEFINED", out)

    def test_empty_projcont_not_invented(self):
        spec = json.loads(fx.read("init_spec.json"))
        spec["request"]["projCont"] = ""
        rc, out = fx.run(self.f.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt",
                         "--rules", "rules.json", stdin=json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        rc, out = fx.run(self.f.ws, "detail.py", "fill", "--rid", fx.RID, stdin=fx.read("fill_spec.json"))
        self.assertEqual(rc, 0, out)
        out, inp = self.ok(BASE)
        self.assertNotIn("usage_scenario", inp.get("Employer", {}))             # 请求没值不传，交给 RULE-GATE-003 按“为空”处理
        self.assertIn("usage_scenario", json.dumps(self.combined()["unfilled"], ensure_ascii=False))

    def build_with_inst(self, inst):
        self.write("s-props.json", self.props)
        self.write("s-rules.json", self.rules)
        self.write("inst.json", inst)
        return fx.run(self.f.ws, "combine.py", "build", "--rid", fx.RID, "--rules", "s-rules.json", "inst.json",
                      "--props", "s-props.json", stdin=json.dumps(BASE))

    def test_rule_list_code_200_is_success_but_other_codes_still_fail(self):
        self.f.ready()
        model = [{"项目名称": "Project.project_name CONTAINS [修匀]"}]
        for code in (200, "200", 0, "0"):
            with self.subTest(code=code):
                rc, out = self.build_with_inst({"code": code, "msg": None, "model": model})
                self.assertNotIn("不是成功码", out)
                self.assertEqual(rc, 0, out)
        rc, out = self.build_with_inst({"code": 500, "msg": "服务异常", "model": []})
        self.assertEqual(rc, 1, out)
        self.assertIn("规则返回不是成功码：code=500", out)


if __name__ == "__main__":
    unittest.main()
