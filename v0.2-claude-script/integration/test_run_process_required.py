"""run_process_required.json（2026-11-09）：required = 调 mcp_run_process 必带的预设键，请求没值不传、不兜底，只记 notes；
enumFallbacks = 规则引用的枚举键没取到值时的兜底，值须是选项，只记 notes.toolIssues，不进摘要。"""
import json
import os
import shutil
import subprocess
import sys
import unittest

try:
    from . import test_scripts as fx
except ImportError:
    import test_scripts as fx


class RunProcessRequiredTests(unittest.TestCase):
    def setUp(self):
        self.f = fx.ScriptTests()
        self.f.setUp()
        self.cat = os.path.join(self.f.ws, "cat")
        shutil.copytree(os.path.dirname(fx.SCRIPTS), self.cat, ignore=shutil.ignore_patterns("__pycache__", "*.zip"))
        self.cfg = os.path.join(self.cat, "scripts", "run_process_required.json")

    def tearDown(self):
        self.f.tearDown()

    def enum_fallback(self, key, value):
        c = json.load(open(self.cfg, encoding="utf-8"))
        c["enumFallbacks"].append({"key": key, "fallback": value, "why": "测试"})
        json.dump(c, open(self.cfg, "w", encoding="utf-8"), ensure_ascii=False)

    def run_(self, script, *args, stdin=""):
        r = subprocess.run([sys.executable, "-I", os.path.join(self.cat, "scripts", script), *args], cwd=self.f.ws, input=stdin,
                           capture_output=True, text=True, env={"LANG": "C.UTF-8"}, timeout=30)
        return r.returncode, r.stdout + r.stderr

    def ready_without(self, item, why):
        rc, out = self.run_("detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json", stdin=fx.read("init_spec.json"))
        self.assertEqual(rc, 0, out)
        rc, out = fx.fill_fixture(self.f.ws, self.run_)
        self.assertEqual(rc, 0, out)
        rc, out = self.run_("detail.py", "fill", "--rid", fx.RID, "--force", stdin=json.dumps({"rows": [[item, None, why]]}, ensure_ascii=False))
        self.assertEqual(rc, 0, out)

    def build(self, rules="rules.json", props="props.json", spec=None):
        rc, out = self.run_("combine.py", "build", "--rid", fx.RID, "--rules", rules, "--props", props, stdin=spec or fx.read("map_spec.json"))
        self.assertEqual(rc, 0, out)
        self.assertIn("validate: OK", out)
        notes = json.loads(out.split("NOTES ", 1)[1].split("\n", 1)[0])
        cb = json.load(open(os.path.join(self.f.ws, "work", fx.RID, "input-combine.json"), encoding="utf-8"))
        return out, self.f.inp(out), notes, cb

    def test_required_present_is_passed(self):
        out, inp, notes, _ = self.build_ready()
        self.assertEqual(inp["Demand"]["demand_id"], "2899")
        self.assertFalse(any("必填键" in t for t in notes["toolIssues"]), notes["toolIssues"])

    def build_ready(self):
        self.ready_without("A09", "R01｜请求没有项目简介")
        return self.build()

    def test_required_missing_is_omitted_and_only_noted(self):
        """必填键没有兜底：请求没值就不传，只记 notes，build 照常通过。"""
        self.ready_without("A03", "R01｜请求没有需求 ID")
        out, inp, notes, _ = self.build()
        self.assertNotIn("demand_id", inp.get("Demand", {}))
        self.assertNotIn("FALLBACK_FILLED", out)
        self.assertTrue(any("必填键 Demand.demand_id" in t and "未传给 mcp_run_process" in t for t in notes["toolIssues"]), notes["toolIssues"])

    def test_required_keys_ignore_enum_fallbacks(self):
        self.enum_fallback("Demand.demand_id", "0")
        self.ready_without("A03", "R01｜请求没有需求 ID")
        out, inp, _, _ = self.build()
        self.assertNotIn("demand_id", inp.get("Demand", {}))
        self.assertNotIn("FALLBACK_FILLED", out)

    def enum_ws(self, enum):
        prop = {"name": "industry_category", "label": "所属行业", "comment": "金融类、一般行业"}
        if enum:
            prop["enum"] = {"finance": "金融类", "ordinary": "一般行业"}
        props = {"data": [{"name": "Employer", "label": "企业", "properties": [prop]}]}
        rules = {"data": [{"ruleId": "RULE-IND-001", "label": "金融类", "condition": "Employer.industry_category = finance"}]}
        for name, data in (("s-props.json", props), ("s-rules.json", rules)):
            json.dump(data, open(os.path.join(self.f.ws, name), "w", encoding="utf-8"), ensure_ascii=False)
        self.ready_without("A09", "R01｜请求没有项目简介")

    def build_enum(self):
        return self.build("s-rules.json", "s-props.json", json.dumps({"map": {"Employer.employer_name": ["A02"]}}))

    def test_enum_fallback_fills_unset_enum_key(self):
        self.enum_fallback("Employer.industry_category", "一般行业")
        self.enum_ws(enum=True)
        out, inp, notes, cb = self.build_enum()
        self.assertEqual(inp["Employer"]["industry_category"], "ordinary")          # 中文选项换成 enum 编码
        self.assertIn('Employer.industry_category="ordinary"', out.split("FALLBACK_FILLED", 1)[1].split("\n", 1)[0])
        prop = cb["entities"]["Employer"]["properties"]["industry_category"]
        self.assertTrue(prop["value_source"].startswith("兜底｜run_process_required.json"))
        self.assertNotIn("industry_category", json.dumps(cb["unfilled"], ensure_ascii=False))
        self.assertFalse(any(l.startswith("Employer.[industry_category]") for l in notes["unresolvedProperties"]))
        self.assertTrue(any("枚举键 Employer.industry_category" in t and "兜底传入" in t for t in notes["toolIssues"]))

    def test_enum_fallback_not_an_option_is_not_passed(self):
        self.enum_fallback("Employer.industry_category", "其他")
        self.enum_ws(enum=True)
        out, inp, notes, cb = self.build_enum()
        self.assertNotIn("industry_category", inp.get("Employer", {}))
        self.assertNotIn("FALLBACK_FILLED", out)
        self.assertTrue(any("兜底值不可用" in t for t in notes["toolIssues"]), notes["toolIssues"])

    def test_enum_fallback_does_not_override_model_value(self):
        self.enum_fallback("Employer.industry_category", "一般行业")
        self.enum_ws(enum=False)
        spec = {"map": {"Employer.employer_name": ["A02"], "Employer.industry_category": ["A02", "A08"]},
                "set": {"Employer.industry_category": ["金融类", "派生:A02,A08｜金融类｜置信度约90%｜测试"]}}
        out, inp, _, _ = self.build("s-rules.json", "s-props.json", json.dumps(spec, ensure_ascii=False))
        self.assertEqual(inp["Employer"]["industry_category"], "金融类")
        self.assertNotIn("FALLBACK_FILLED", out)


if __name__ == "__main__":
    unittest.main()
