"""脚本派生行不被模型提交的值覆盖；B 接口登记状态编码按清单 J05 desc 转成文字。"""
import json, os, unittest

import test_scripts as ts
from test_scripts import RID, run


class DerivedGuardTests(unittest.TestCase):
    def setUp(self):
        self.st = ts.ScriptTests("test_capital_same_value_different_units_is_not_a_conflict")
        self.st.setUp()
        self.ws = self.st.ws

    def tearDown(self):
        self.st.tearDown()

    def fill(self, rows, *extra):
        return run(self.ws, "detail.py", "fill", "--rid", RID, *extra, stdin=json.dumps({"rows": rows}, ensure_ascii=False))

    def test_init_does_not_list_derived_rows_as_pending(self):
        rc, out = self.st.init()
        self.assertEqual(rc, 0, out)
        pend = out.split("PENDING", 1)[1] if "PENDING" in out else ""
        for i in ("B11", "B16", "B17", "B18", "B19", "B26", "A12"):
            self.assertNotIn("\n%s|" % i, pend, i)

    def test_model_value_for_derived_row_is_not_taken(self):
        rc, out = self.st.init()
        self.assertEqual(rc, 0, out)
        rc, out = self.fill([["B02", "有限责任公司", "营业执照 p1 类型栏｜有限责任公司"],
                             ["B04", "2019-03-01", "营业执照 p1 成立日期栏｜2019年03月01日"],
                             ["B16", "999", "模型自算｜999"], ["B17", "股份有限公司", "模型自算｜股份有限公司"]])
        self.assertIn("SKIP", out)
        self.assertEqual(self.st.detail_row("B17")["value"], "有限责任公司")
        self.assertNotEqual(self.st.detail_row("B16")["value"], "999")

    def test_force_still_overrides_derived_row(self):
        rc, out = self.st.init()
        self.fill([["B02", "有限责任公司", "营业执照 p1 类型栏｜有限责任公司"]])
        rc, out = self.fill([["B17", "其他", "人工更正｜其他"]], "--force")
        self.assertEqual(self.st.detail_row("B17")["value"], "其他", out)

    def test_b_entity_status_code_is_decoded(self):
        fp = os.path.join(self.ws, "biz_D.txt")
        s = open(fp, encoding="utf-8").read().replace('"companyStatus": "在营（开业）"', '"companyStatus": null')
        open(fp, "w", encoding="utf-8").write(s)
        fp = os.path.join(self.ws, "biz_B.txt")
        s = open(fp, encoding="utf-8").read().replace('"entityStatus": "1"', '"entityStatus": "2"')
        open(fp, "w", encoding="utf-8").write(s)
        rc, out = self.st.init()
        self.assertEqual(rc, 0, out)
        self.assertTrue(self.st.detail_row("J05")["value"].startswith("注销"), self.st.detail_row("J05"))


if __name__ == "__main__":
    unittest.main()
