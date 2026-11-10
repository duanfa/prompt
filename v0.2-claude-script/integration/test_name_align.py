"""名称传给引擎前统一口径（2026-11-09）。
trace 416155b0：模型把 H29「…是否一致」的 true 映射给 tax_clearance_taxpayer_name；
trace ac09911b：开户名称「…(个人独资)」与企业名称「…（个人独资）」括号全半角不同，规则 `X != Employer.enterprise_name` 逐字比较误命中。
做法：①combine build 组装 input 时所有字符串取值统一（中文/全角标点 → 英文，去空格），明细文件保持原文；
②章的内容由模型判断，属于该企业就填企业名称（提示词约定）；③名称键收到布尔不传（脚本兜底）+ 提示词约束。"""
import json
import os
import sys
import unittest

try:
    from . import test_scripts as fx
except ImportError:
    import test_scripts as fx

NAME = "上海修匀软件开发有限责任公司"          # 回归夹具的企业名称（A02/B01/工商一致）
PROPS = {"data": [{"name": "Employer", "label": "企业", "properties": [
    {"name": "employer_name", "label": "企业名称"}, {"name": "enterprise_name", "label": "企业名称"},
    {"name": "settlement_account_name", "label": "结算对公账户名称"}]},
    {"name": "AdmissionDoc", "label": "准入材料", "properties": [
        {"name": "lease_contract_party_b_name", "label": "租赁合同承租方章载名称"},
        {"name": "tax_clearance_taxpayer_name", "label": "无欠税证明纳税人名称"}]}]}
RULES = {"data": [
    {"ruleId": "R-ACC", "label": "账户名不一致", "condition": "Employer.settlement_account_name != Employer.enterprise_name"},
    {"ruleId": "R-LEASE", "label": "承租方章不一致", "condition": "AdmissionDoc.lease_contract_party_b_name != Employer.enterprise_name"},
    {"ruleId": "R-TAX", "label": "无欠税名称不一致", "condition": "AdmissionDoc.tax_clearance_taxpayer_name != Employer.enterprise_name"}]}
SPEC = {"map": {"Employer.employer_name": ["A02"], "Employer.settlement_account_name": ["D01"],
                "AdmissionDoc.lease_contract_party_b_name": ["G11"], "AdmissionDoc.tax_clearance_taxpayer_name": ["H29-1"]}}


class NormTextTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, fx.SCRIPTS)
        import combine_tool
        self.n = combine_tool.norm_text

    def tearDown(self):
        sys.path.remove(fx.SCRIPTS)

    def test_chinese_punct_and_spaces(self):
        n = self.n
        self.assertEqual(n("葫芦岛市企通软件科技中心（个人独资）"), "葫芦岛市企通软件科技中心(个人独资)")
        self.assertEqual(n(" 葫芦岛市 企通软件科技中心 （个人独资）　"), "葫芦岛市企通软件科技中心(个人独资)")
        self.assertEqual(n("【上海】某某公司​"), "[上海]某某公司")
        self.assertEqual(n("软件开发；技术服务、咨询。"), "软件开发;技术服务,咨询.")
        self.assertEqual(n("ＡＢＣ１２３"), "ABC123")
        self.assertEqual(n("2025年 12月 31日"), "2025年12月31日")

    def test_space_between_ascii_words_is_kept(self):
        self.assertEqual(self.n("ABC  Technology Co., Ltd."), "ABC Technology Co.,Ltd.")
        self.assertEqual(self.n("2025-12-31 00:00:00"), "2025-12-31 00:00:00")

    def test_non_string_untouched(self):
        self.assertIsNone(self.n(None))
        self.assertIs(self.n(True), True)
        self.assertEqual(self.n("true"), "true")


class NameKeyTests(unittest.TestCase):
    def setUp(self):
        self.f = fx.ScriptTests()
        self.f.setUp()
        self.f.ready()
        for name, data in (("n-props.json", PROPS), ("n-rules.json", RULES)):
            json.dump(data, open(os.path.join(self.f.ws, name), "w", encoding="utf-8"), ensure_ascii=False)

    def tearDown(self):
        self.f.tearDown()

    def rows(self, **vals):
        rc, out = self.f.force([[i, v, "测试材料 p1｜%s" % v] for i, v in vals.items()])
        self.assertEqual(rc, 0, out)

    def build(self, spec=SPEC):
        rc, out = fx.run(self.f.ws, "combine.py", "build", "--rid", fx.RID, "--rules", "n-rules.json", "--props", "n-props.json",
                         stdin=json.dumps(spec, ensure_ascii=False))
        self.assertIn("validate: OK", out)
        return out, self.f.inp(out)

    def test_input_is_normalized_detail_kept_raw(self):
        """开户名称多空格、无欠税名称首尾空格、承租方章按约定填企业名称：input 里与企业名称逐字相同；明细保持原文。"""
        self.rows(D01="上海修匀软件开发 有限责任公司", G11=NAME, **{"H29-1": " %s（测试）" % NAME})
        out, inp = self.build()
        self.assertEqual(inp["Employer"]["settlement_account_name"], inp["Employer"]["enterprise_name"])
        self.assertEqual(inp["AdmissionDoc"]["lease_contract_party_b_name"], inp["Employer"]["enterprise_name"])
        self.assertEqual(inp["AdmissionDoc"]["tax_clearance_taxpayer_name"], NAME + "(测试)")
        self.assertEqual(self.f.items()["D01"]["value"], "上海修匀软件开发 有限责任公司")

    def test_bracket_width_on_both_sides(self):
        """企业名称全角括号、开户名称半角括号：统一后相同。"""
        sys.path.insert(0, fx.SCRIPTS)
        try:
            import combine_tool as ct
            self.assertEqual(ct.norm_text("葫芦岛市企通软件科技中心(个人独资)"), ct.norm_text("葫芦岛市企通软件科技中心（个人独资）"))
        finally:
            sys.path.remove(fx.SCRIPTS)

    def test_different_subject_name_is_kept(self):
        self.rows(G11="上海修匀软件合同专用章")
        out, inp = self.build()
        self.assertEqual(inp["AdmissionDoc"]["lease_contract_party_b_name"], "上海修匀软件合同专用章")

    def test_bool_judgement_is_not_passed_as_name(self):
        """把「…是否一致」条目（true/false）映射给名称键：不传，提示改映射到名称原文条目。"""
        self.rows(H29="true")
        spec = {"map": {"Employer.employer_name": ["A02"], "AdmissionDoc.tax_clearance_taxpayer_name": ["H29"]},
                "skip": {"R10": ["Employer.settlement_account_name", "AdmissionDoc.lease_contract_party_b_name"]}}
        out, inp = self.build(spec)
        self.assertNotIn("tax_clearance_taxpayer_name", inp.get("AdmissionDoc", {}))
        self.assertIn("TYPE_DROPPED", out)
        self.assertIn("是判断结果不是名称", out)


if __name__ == "__main__":
    unittest.main()
