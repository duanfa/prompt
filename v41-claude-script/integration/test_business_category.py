"""trace ca160198：业务类别的模型单选结果进入 input，相关反证与冲突仍保留。

本地组装回归不调用模型或远端引擎；分类选择本身由 facts skill 指导模型完成。
"""
import json
import os
import subprocess
import sys
import unittest

try:
    from . import test_scripts as fx
except ImportError:
    import test_scripts as fx


BUSINESS = "发展推广人员加入销售团队，报酬按直接发展和间接发展的人员数量计算；下级推广人员再发展的人员及产生的业绩，按上、中、下多个向上返利。"
CONTRACT = "不按发展人员数量计酬，不设多层返利"
CONFLICT = "项目内容与上下游合同冲突：项目描述按直接、间接发展人数计酬并多层向上返利；合同第三条写「%s」" % CONTRACT
CATEGORY_CASES = [
    ("wealth_management", "理财", "面向个人客户销售理财产品，提供理财规划、产品推介和资产配置建议，并跟进客户申购与持仓。"),
    ("fundraising", "集资", "向公众介绍募集项目并招募出资人，归集认购资金和跟进出资。"),
    ("online_lending", "网贷", "在线招揽借款人，提供网络借贷撮合并跟进贷款办理。"),
    ("pawn", "典当", "开展典当收当估值、发放当金并办理赎当。"),
    ("auction", "拍卖", "征集拍品并组织竞拍，跟进拍卖成交业务。"),
    ("debt_collection", "催收", "通过电话催缴逾期欠款并跟进上门债务催收。"),
    ("crypto", "虚拟币", "推广虚拟币并提供代币交易撮合和买卖服务。"),
    ("multi_level_distribution", "多级分销", "设置上中下多层销售分销团队，按下级销售业绩跨层返佣。"),
    ("headcount_rebate", "拉人头返利", BUSINESS),
    ("borderline_service", "擦边服务", "向个人客户提供付费语音陪聊和暧昧情感陪伴服务。"),
    ("pornography", "色情服务", "面向客户提供色情内容及色情交易服务。"),
    ("telecom_fraud", "电信诈骗", "冒充客服以虚假退款诱导客户转账，组织电信诈骗业务。"),
    ("online_gambling", "网络赌博", "运营网络赌博平台，招揽下注并处理赌资结算。"),
    ("construction_labor", "建筑劳务", "向建筑工地提供现场施工作业劳务。"),
    ("construction", "建筑施工", "在施工现场开展土建安装及拆除作业。"),
    ("mining_underground", "矿山井下", "组织工人下井开展矿山井下采掘和现场作业。"),
    ("high_altitude", "高空高危", "组织人员登高进行外墙和塔架高空作业。"),
    ("hazardous_chemical", "危化品生产", "在生产车间进行危险化学品配制反应和生产加工。"),
]


class BusinessCategoryTests(unittest.TestCase):
    def setUp(self):
        self.f = fx.ScriptTests()
        self.f.setUp()
        spec = json.loads(fx.read("init_spec.json"))
        spec["request"].update({"projCont": BUSINESS, "dlvrDemd": BUSINESS})
        rc, out = fx.run(self.f.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt",
                         "--rules", "rules.json", stdin=json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        rc, out = fx.fill_fixture(self.f.ws)
        self.assertEqual(rc, 0, out)
        rc, out = fx.run(self.f.ws, "detail.py", "fill", "--rid", fx.RID, "--force", stdin=json.dumps({
            "rows": [["H12", "true", "上下游合同 p1 第三条｜" + CONTRACT]],
            "notes": {"conflicts": [CONFLICT]},
        }, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.schema()

    def tearDown(self):
        self.f.tearDown()

    def schema(self, obj="Request", prop="actual_business_category", code="headcount_rebate", options=None):
        self.obj, self.prop, self.code = obj, prop, code
        self.key = obj + "." + prop
        props = {"data": [{"name": obj, "label": "本次需求", "properties": [{
            "name": prop, "label": "实际业务类别",
            "enum": options or [{"multi_level_distribution": "多级分销"}, {code: "拉人头返利"}, {"general": "一般业务"}],
        }]}]}
        rules = {"data": [{"ruleId": "CATEGORY-REVIEW", "label": "传销类模式禁入", "comment": "适用阶段：准入",
                           "condition": self.key + " IN {multi_level_distribution, " + code + "}", "riskMeasure": "拦截"}]}
        for name, data in (("category-props.json", props), ("category-rules.json", rules)):
            with open(os.path.join(self.f.ws, name), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

    def build(self, spec):
        return fx.run(self.f.ws, "combine.py", "build", "--rid", fx.RID,
                      "--rules", "category-rules.json", "--props", "category-props.json",
                      stdin=json.dumps(spec, ensure_ascii=False))

    def selection(self, value):
        return {"map": {self.key: ["A07", "A08", "H12"]}, "set": {self.key: [value,
            "派生:A07,A08,H12｜拉人头返利｜置信度约95%｜项目和交付要求明确按直接、间接发展人数计酬并多层向上返利；合同第三条虽否认该机制，仍保留冲突并按请求中明确的业务模式分类"]}}

    def test_single_category_and_contrary_contract_are_both_preserved(self):
        rc, out = self.build(self.selection(self.code))
        self.assertEqual(rc, 0, out)
        self.assertIn("validate: OK", out)
        inp = self.f.inp(out)
        self.assertEqual(inp[self.obj][self.prop], "headcount_rebate")
        with open(os.path.join(self.f.ws, "work", fx.RID, "input-combine.json"), encoding="utf-8") as f:
            cb = json.load(f)
        p = cb["entities"][self.obj]["properties"][self.prop]
        self.assertEqual(p["extractIds"], ["A07", "A08", "H12"])
        self.assertIn("合同第三条虽否认", p["value_source"])
        notes = json.loads(out.split("NOTES ", 1)[1].split("\n", 1)[0])
        self.assertIn(CONFLICT, notes["conflicts"])
        self.assertFalse(any(self.prop in s for s in notes["unresolvedProperties"]))

    def test_multiple_categories_are_not_sent_to_engine(self):
        """多选/拼接值不进 input；有人数计酬线索而分类被丢掉时，v43 门禁阻断调用引擎。"""
        for value in ([self.code, "multi_level_distribution"],
                      self.code + ",multi_level_distribution", "拉人头返利、多级分销"):
            with self.subTest(value=value):
                rc, out = self.build(self.selection(value))
                self.assertNotEqual(rc, 0, out)
                self.assertIn("ENUM_DROPPED", out)
                self.assertIn("CHECK CATEGORY_SIGNAL", out)
                self.assertNotIn(self.prop, self.f.inp(out).get(self.obj, {}))

    def test_explicit_selection_replaces_previous_r10_skip(self):
        rc, out = self.build({"skip": {"R10": [self.key]}})
        self.assertNotEqual(rc, 0, out)
        self.assertIn("CHECK CATEGORY_SIGNAL", out)
        self.assertNotIn(self.prop, self.f.inp(out).get(self.obj, {}))
        rc, out = self.build(self.selection(self.code))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.f.inp(out)[self.obj][self.prop], self.code)
        notes = json.loads(out.split("NOTES ", 1)[1].split("\n", 1)[0])
        self.assertFalse(any(self.prop in s for s in notes["unresolvedProperties"]))

    def test_single_project_evidence_does_not_bypass_enum_validation(self):
        spec = {"map": {self.key: ["A08"]}, "set": {self.key: [[self.code, "multi_level_distribution"], "派生:A08｜请求中有人数计酬和多层返利特征"]}}
        rc, out = self.build(spec)
        self.assertNotEqual(rc, 0, out)
        self.assertIn("ENUM_DROPPED", out)
        self.assertNotIn(self.prop, self.f.inp(out).get(self.obj, {}))
        spec["set"][self.key][0] = self.code
        rc, out = self.build(spec)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.f.inp(out)[self.obj][self.prop], self.code)

    def test_code_and_property_follow_current_definition(self):
        self.schema(obj="BusinessReview", prop="mode_category", code="recruitment_based_rebate")
        rc, out = self.build(self.selection("拉人头返利"))
        self.assertEqual(rc, 0, out)
        inp = self.f.inp(out)
        self.assertEqual(inp[self.obj][self.prop], "recruitment_based_rebate")
        self.assertNotIn("actual_business_category", inp.get("Request", {}))

    def test_all_business_codes_are_passed_as_one_enum_value(self):
        self.schema(options=[{code: label} for code, label, _ in CATEGORY_CASES] + [{"general": "一般业务"}])
        for code, label, project in CATEGORY_CASES:
            with self.subTest(code=code):
                spec = json.loads(fx.read("init_spec.json"))
                spec["request"].update({"projCont": project, "dlvrDemd": project})
                rc, out = fx.run(self.f.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt",
                                 "--rules", "rules.json", stdin=json.dumps(spec, ensure_ascii=False))
                self.assertEqual(rc, 0, out)
                rc, out = fx.fill_fixture(self.f.ws)
                self.assertEqual(rc, 0, out)
                rc, out = self.build({"map": {self.key: ["A07", "A08"]}, "set": {self.key: [code,
                    "派生:A07,A08｜%s｜置信度约95%%｜%s" % (label, project)]}})
                self.assertEqual(rc, 0, out)
                self.assertIn("validate: OK", out)
                self.assertEqual(self.f.inp(out)[self.obj][self.prop], code)
                self.assertNotIn("ENUM_DROPPED", out)


ALL_OPTIONS = [{code: label} for code, label, _ in CATEGORY_CASES] + [{"general": "一般业务"}]
RISK_RULES = [
    ("RULE-IND-001", "金融类业务禁入", "wealth_management, fundraising, online_lending, pawn, auction, debt_collection, crypto"),
    ("RULE-IND-002", "传销类业务禁入", "multi_level_distribution, headcount_rebate"),
    ("RULE-IND-003", "违法类业务禁入", "pornography, telecom_fraud, online_gambling, borderline_service"),
    ("RULE-IND-004", "高危类业务禁入", "construction_labor, construction, mining_underground, high_altitude, hazardous_chemical"),
]
USER_CASES = [   # 用户反馈未拦截的原文（2026-11-09）
    ("wealth_management", "面向个人客户销售理财产品，提供理财规划、产品推介和资产配置建议，并跟进客户申购与持仓。"),
    ("headcount_rebate", BUSINESS),
    ("borderline_service", "招募语音陪聊人员，在平台上为付费用户提供语音陪伴聊天服务。"),
]


class CategorySignalGateTests(unittest.TestCase):
    """v43：项目内容/交付要求出现特殊业务线索，而分类未传、选一般业务时，build 阻断；脚本只提示，不替模型定值。"""

    def setUp(self):
        self.f = fx.ScriptTests()
        self.f.setUp()
        self.key = "Request.actual_business_category"
        props = {"data": [{"name": "Request", "label": "本次需求", "properties": [{
            "name": "actual_business_category", "label": "实际业务类别", "enum": ALL_OPTIONS}]}]}
        rules = {"data": [{"ruleId": rid, "label": name, "comment": "适用阶段：准入", "riskMeasure": "拦截",
                           "condition": "%s IN {%s}" % (self.key, codes)} for rid, name, codes in RISK_RULES]}
        for name, data in (("category-props.json", props), ("category-rules.json", rules)):
            with open(os.path.join(self.f.ws, name), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

    def tearDown(self):
        self.f.tearDown()

    def project(self, text):
        import shutil
        shutil.rmtree(os.path.join(self.f.ws, "work"), ignore_errors=True)
        spec = json.loads(fx.read("init_spec.json"))
        spec["request"].update({"projCont": text, "dlvrDemd": text})
        rc, out = fx.run(self.f.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt",
                         "--rules", "rules.json", stdin=json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        rc, out = fx.fill_fixture(self.f.ws)
        self.assertEqual(rc, 0, out)

    def run_(self, cmd, spec=None):
        args = [cmd, "--rid", fx.RID, "--rules", "category-rules.json", "--props", "category-props.json"]
        return fx.run(self.f.ws, "combine.py", *args, stdin=None if spec is None else json.dumps(spec, ensure_ascii=False))

    def pick(self, code):
        return {"set": {self.key: [code, "派生:A08,A07｜%s｜置信度约90%%｜机制见项目内容" % code]}}

    def test_every_category_signal_blocks_skip_and_general(self):
        for code, label, text in CATEGORY_CASES + [(c, c, t) for c, t in USER_CASES]:
            with self.subTest(code=code, text=text):
                self.project(text)
                rc, out = self.run_("build", {"skip": {"R10": [self.key]}})
                self.assertNotEqual(rc, 0, out)
                self.assertIn("CHECK CATEGORY_SIGNAL", out)
                self.assertIn(code + "=", out.split("CHECK CATEGORY_SIGNAL", 1)[1].split("\n", 1)[0])
                rc, out = self.run_("build", self.pick("general"))
                self.assertNotEqual(rc, 0, out)
                self.assertIn("CHECK CATEGORY_SIGNAL", out)
                rc, out = self.run_("build", self.pick(code))
                self.assertEqual(rc, 0, out)
                self.assertNotIn("CATEGORY_SIGNAL", out)
                self.assertEqual(self.f.inp(out)["Request"]["actual_business_category"], code)

    def test_plan_prints_task_card_with_rules_and_clues(self):
        self.project(BUSINESS)
        rc, out = self.run_("plan")
        self.assertIn("CATEGORY_TASK " + self.key, out)
        self.assertIn("headcount_rebate=拉人头返利←", out)
        self.assertIn("RULE-IND-002(拦截)", out)

    def test_set_without_map_reaches_engine_input(self):
        """trace 173：只交 set 的分类曾被静默记 R10。"""
        self.project(BUSINESS)
        rc, out = self.run_("build", self.pick("headcount_rebate"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.f.inp(out)["Request"]["actual_business_category"], "headcount_rebate")
        rc, out = self.run_("build", {"toolIssues": []})
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.f.inp(out)["Request"]["actual_business_category"], "headcount_rebate")

    def test_other_special_option_is_the_models_call(self):
        self.project(BUSINESS)
        rc, out = self.run_("build", self.pick("multi_level_distribution"))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("CATEGORY_SIGNAL", out)

    def test_negated_and_general_text_do_not_block(self):
        for text in ("内部管理系统开发调试，交付测试报告。", "开发客服工单系统，不涉及催收业务，严禁赌博内容。"):
            with self.subTest(text=text):
                self.project(text)
                rc, out = self.run_("build", self.pick("general"))
                self.assertEqual(rc, 0, out)
                self.assertNotIn("CATEGORY_SIGNAL", out)

    def test_false_positive_needs_written_review(self):
        self.project("为银行开发理财产品管理系统的后台软件，交付源代码。")
        rc, out = self.run_("build", self.pick("general"))
        self.assertNotEqual(rc, 0, out)
        self.assertIn("CHECK CATEGORY_SIGNAL", out)
        rc, out = self.run_("build", {"categoryReview": {self.key: "太短"}})
        self.assertNotEqual(rc, 0, out)
        rc, out = self.run_("build", {"categoryReview": {self.key: "项目是为银行开发「理财产品管理系统的后台软件」，人员从事软件开发，不销售理财产品"}})
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.f.inp(out)["Request"]["actual_business_category"], "general")
        notes = json.loads(out.split("NOTES ", 1)[1].split("\n", 1)[0])
        self.assertTrue(any("分类线索复核" in t for t in notes["toolIssues"]))


class RestrictedJobReminderTests(unittest.TestCase):
    def reminders(self, company, job):
        rows = {"A02": {"value": company, "source": "Y｜请求 entpName｜" + company},
                "A08": {"value": job, "source": "Y｜请求 projCont｜" + job}}
        code = "import sys,json; sys.path.insert(0,sys.argv[1]); import combine; print(json.dumps(combine.flex_job_notes(json.load(sys.stdin)),ensure_ascii=False))"
        result = subprocess.run([sys.executable, "-I", "-c", code, fx.SCRIPTS], input=json.dumps(rows, ensure_ascii=False),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_core_industry_jobs_are_not_auxiliary_exceptions(self):
        cases = [
            ("某医药公司", "招聘临时医药销售，负责药品销售及拜访医生"),
            ("某医疗器械公司", "招聘兼职人员销售医疗器械"),
            ("某电商直播公司", "招聘兼职主播直播带货"),
            ("某影视传媒公司", "招聘临时人员开展影视拍摄和影片制作"),
            ("某律师事务所", "招聘短期人员从事法律咨询与诉讼业务"),
            ("某会计师事务所", "招聘临时人员从事会计服务和财务审计"),
            ("某保险经纪公司", "招聘临时地推人员推介保险产品并承接保险经纪业务"),
        ]
        for company, job in cases:
            with self.subTest(job=job):
                self.assertEqual(self.reminders(company, job), [])

    def test_unrelated_temporary_auxiliary_jobs_still_get_a_reminder(self):
        for company in ("某医药公司", "某律师事务所", "某保险经纪公司", "某电商直播公司"):
            with self.subTest(company=company):
                self.assertTrue(self.reminders(company, "招聘临时会场布置和现场引导人员"))


if __name__ == "__main__":
    unittest.main()
