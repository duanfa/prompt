"""python3 integration/test_biz_compare.py
工商与原件比对的误报回归（豆包 job_329-3，执照与工商实为同一事实，却在 summary「注意」里报不一致）：
  1. 营业期限：执照「至长期」对工商 operationEnddate=9999-09-09（占位截止日）
  2. 经营范围：执照「…商品）。（除依法…）」对工商「…商品）（除依法…）。」，只差句号位置
  3. 注册资本：执照「人民币壹佰万元」对工商 D.capital=100.000000（无单位），notice 按字面比对判成不一致
同时确认真正的不一致仍会报出。"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "skills", "admission-v0-1-1-catalog", "scripts"))
import detail as dt  # noqa: E402
import combine as cb  # noqa: E402

SCOPE_LIC = ("一般项目：软件开发；技术服务、技术开发、技术咨询、技术交流、技术转让、技术推广；信息技术咨询服务；网络技术服务；"
             "互联网销售（除销售需要许可的商品）。（除依法须经批准的项目外，凭营业执照依法自主开展经营活动）")
SCOPE_BIZ = ("一般项目：软件开发；技术服务、技术开发、技术咨询、技术交流、技术转让、技术推广；信息技术咨询服务；网络技术服务；"
             "互联网销售（除销售需要许可的商品）（除依法须经批准的项目外，凭营业执照依法自主开展经营活动）。")


def row(i, v):
    return {"id": i, "value": v, "source": "Y｜回归夹具"}


class PeriodTests(unittest.TestCase):
    def test_long_term_vs_placeholder_end(self):
        self.assertTrue(dt.same_fact("period", "2021年03月09日至长期", "2021-03-09 起，截止 9999-09-09"))

    def test_long_term_vs_no_end(self):
        self.assertTrue(dt.same_fact("period", "2021年03月09日至长期", "2021-03-09 起，截止日未返回"))

    def test_real_end_differs(self):
        self.assertFalse(dt.same_fact("period", "2021年03月09日至长期", "2021-03-09 起，截止 2041-03-08"))
        self.assertFalse(dt.same_fact("period", "2021年03月09日至2041年03月08日", "2021-03-09 起，截止 9999-09-09"))

    def test_same_real_end(self):
        self.assertTrue(dt.same_fact("period", "2021年03月09日至2041年03月08日", "2021-03-09 起，截止 2041-03-08"))


class ScopeTests(unittest.TestCase):
    def test_only_punctuation_differs(self):
        self.assertTrue(dt.same_fact("scope", SCOPE_LIC, SCOPE_BIZ))

    def test_item_differs(self):
        self.assertFalse(dt.same_fact("scope", SCOPE_LIC, SCOPE_BIZ.replace("网络技术服务；", "")))


class CapitalNoticeTests(unittest.TestCase):
    COND_B10 = "和'工商.注册资本'不一致"
    COND_J08 = "和'营业执照.注册资本'不一致"
    J08_RAW = "注册资本100.000000；实收资本100.000000；币种人民币"

    def by_name(self, b10, j08):
        return {"营业执照.注册资本": row("B10", b10), "工商.注册资本": row("J08", j08)}

    def test_unitless_biz_value_not_reported(self):
        bn = self.by_name("人民币壹佰万元", self.J08_RAW)
        self.assertFalse(cb.notice_compare(self.COND_B10, bn["营业执照.注册资本"], bn))
        self.assertFalse(cb.notice_compare(self.COND_J08, bn["工商.注册资本"], bn))

    def test_real_capital_mismatch_reported(self):
        bn = self.by_name("人民币壹佰万元", "注册资本500万元；实收资本500万元；币种人民币")
        self.assertTrue(cb.notice_compare(self.COND_B10, bn["营业执照.注册资本"], bn))
        self.assertTrue(cb.notice_compare(self.COND_J08, bn["工商.注册资本"], bn))

    def test_non_pair_items_still_literal(self):
        bn = {"营业执照.类型": row("B02", "有限责任公司"), "工商.企业类型": row("J06", "股份有限公司")}
        self.assertTrue(cb.notice_compare("和'工商.企业类型'不一致", bn["营业执照.类型"], bn))


if __name__ == "__main__":
    unittest.main()
