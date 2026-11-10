"""用工场景按本次定义取值：有枚举时接收模型单选编码，没有枚举时预设取项目原文。
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
    comment = None

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

    def test_enum_definition_requires_selection_instead_of_passing_raw_text(self):
        self.props["data"][0]["properties"][0]["enum"] = {"ordinary": "一般行业", "sensitive": "敏感类"}
        self.f.ready()
        out, inp = self.ok(BASE)
        self.assertNotIn("usage_scenario", inp.get("Employer", {}))
        self.assertIn("NEED_VALUE", out)
        self.assertNotIn("ENUM_DROPPED", out)

    def test_model_enum_selection_is_preserved_and_checked(self):
        self.props["data"][0]["properties"][0]["enum"] = {"ordinary": "一般行业", "sensitive": "敏感类"}
        self.f.ready()
        spec = {"map": {TARGET: ["A08"]}, "set": {TARGET: ["ordinary", "派生:A08｜一般行业｜置信度约95%｜内部管理系统开发调试"]}}
        out, inp = self.ok(spec)
        self.assertEqual(inp["Employer"]["usage_scenario"], "ordinary")
        self.assertNotIn("PRESET_OVERRIDE_IGNORED", out)
        self.assertNotIn("NEED_VALUE", out)
        spec["set"][TARGET][0] = ["ordinary", "sensitive"]
        rc, out = self.build(spec)   # v42：第一次被丢弃 CHECK ENUM_CHOICE 拦一次
        self.assertEqual(rc, 1, out)
        self.assertIn("CHECK ENUM_CHOICE", out)
        out, inp = self.ok(spec)
        self.assertNotIn("usage_scenario", inp.get("Employer", {}))
        self.assertIn("ENUM_DROPPED", out)

    def test_comment_enum_is_also_classified(self):
        self.props["data"][0]["properties"][0]["comment"] = "枚举 UsageScenario：医药、直播带货、一般用工场景"
        self.f.ready()
        out, inp = self.ok({"map": {TARGET: ["A08"]}, "set": {TARGET: ["一般用工场景", "派生:A08｜一般用工场景｜内部管理系统开发调试"]}})
        self.assertEqual(inp["Employer"]["usage_scenario"], "一般用工场景")

    def test_enum_selection_is_kept_on_rebuild(self):
        """v43：set 落盘，重跑 build 不重提也沿用；set 引用的依据比默认映射多时同步映射，不再退回。"""
        self.props["data"][0]["properties"][0]["enum"] = {"ordinary": "一般行业", "sensitive": "敏感类"}
        self.f.ready()
        self.ok({"set": {TARGET: ["ordinary", "派生:A08,A07｜一般行业｜内部管理系统开发调试"]}})
        out, inp = self.ok(BASE)
        self.assertEqual(inp["Employer"]["usage_scenario"], "ordinary")
        self.assertIn("SET_KEPT", out)

    def test_enum_skip_is_preserved_and_later_selection_can_replace_it(self):
        self.props["data"][0]["properties"][0]["enum"] = {"ordinary": "一般行业", "sensitive": "敏感类"}
        self.f.ready()
        out, inp = self.ok({"skip": {"R10": [TARGET]}})
        self.assertNotIn("usage_scenario", inp.get("Employer", {}))
        out, inp = self.ok({"map": {TARGET: ["A08"]}, "set": {TARGET: ["ordinary", "派生:A08｜一般行业｜内部管理系统开发调试"]}})
        self.assertEqual(inp["Employer"]["usage_scenario"], "ordinary")

    def test_enum_preset_accepts_multiple_evidence_items_even_without_rule_reference(self):
        self.props["data"][0]["properties"][0]["enum"] = {"ordinary": "一般行业", "sensitive": "敏感类"}
        self.props["data"][0]["properties"].append({"name": "enterprise_name", "label": "企业名称"})
        self.rules["data"] = [{"ruleId": "OTHER-GATE", "label": "企业名称为空", "condition": "Employer.enterprise_name IS EMPTY"}]
        self.f.ready()
        out, inp = self.ok({"map": {TARGET: ["A07", "A08"]}, "set": {TARGET: ["ordinary", "派生:A07,A08｜一般行业｜内部管理系统开发调试"]}})
        self.assertEqual(inp["Employer"]["usage_scenario"], "ordinary")

    def test_all_sensitive_scenario_codes_reach_input(self):
        cases = [
            ("pharma", "医药", "销售药品和医疗器械并拜访医院客户"),
            ("live_stream", "直播", "开展在线直播节目主持和互动直播服务"),
            ("live_commerce", "直播带货", "主播直播介绍商品并引导观众下单购买"),
            ("film_tv", "影视", "负责影视传媒项目拍摄和制作执行"),
            ("law_firm", "律所", "律师事务所承接法律咨询及诉讼代理"),
            ("accounting_firm", "会计", "会计师事务所承接财务审计和专业会计服务"),
            ("insurance_broker", "保险经纪", "为客户推介保险产品并跟进保险经纪代理业务"),
        ]
        self.props["data"][0]["properties"][0]["enum"] = [{code: label} for code, label, _ in cases] + [{"general": "一般用工场景"}]
        self.rules["data"].append({"ruleId": "SCENE-RESTRICTED", "label": "敏感类用工场景禁入",
                                  "condition": TARGET + " IN {" + ", ".join(x[0] for x in cases) + "}", "riskMeasure": "拦截"})
        for code, label, project in cases:
            with self.subTest(code=code):
                spec = json.loads(fx.read("init_spec.json"))
                spec["request"].update({"projCont": project, "dlvrDemd": project})
                rc, out = fx.run(self.f.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json", stdin=json.dumps(spec, ensure_ascii=False))
                self.assertEqual(rc, 0, out)
                rc, out = fx.fill_fixture(self.f.ws)
                self.assertEqual(rc, 0, out)
                out, inp = self.ok({"map": {TARGET: ["A07", "A08"]}, "set": {TARGET: [code, "派生:A07,A08｜%s｜置信度约95%%｜%s" % (label, project)]}})
                self.assertEqual(inp["Employer"]["usage_scenario"], code)
                self.assertNotIn("NEED_VALUE", out)
                self.assertEqual(self.combined()["entities"]["Employer"]["properties"]["usage_scenario"]["extractIds"], ["A07", "A08"])

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
        rc, out = fx.fill_fixture(self.f.ws)
        self.assertEqual(rc, 0, out)
        out, inp = self.ok(BASE)
        self.assertNotIn("usage_scenario", inp.get("Employer", {}))             # 请求没值不传，交给 RULE-GATE-003 按“为空”处理
        self.assertIn("usage_scenario", json.dumps(self.combined()["unfilled"], ensure_ascii=False))

    def build_with_inst(self, inst):
        self.write("s-props.json", self.props)
        self.write("s-rules.json", self.rules)
        self.write("inst.json", inst)
        return fx.run(self.f.ws, "combine.py", "build", "--rid", fx.RID, "--rules", "s-rules.json", "inst.json",
                      "--props", "s-props.json", stdin=json.dumps({"map": dict(BASE["map"], **{"Project.project_name": ["A08"]})}))

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
