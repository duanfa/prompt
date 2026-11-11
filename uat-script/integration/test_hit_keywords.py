"""python3 integration/test_hit_keywords.py
引擎对关键词类规则（机构规则 CONTAINS [..]）在命中项里返回 "hit": ["使用的应用"]。
summary 要把关键词和 comment 拼成一句放进引用该规则的那条依据/下一步：「命中关键词「使用的应用」，触发风控行业限制，不予准入」。"""
import json, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_summary as TS  # noqa: E402

INST = "2080184341491822592-projectName"
SENT = "命中关键词「使用的应用」，触发风控行业限制，不予准入"


def inst_rule(level="建议拦截", hit=("使用的应用",)):
    r = TS.mk(INST, INST, "true", level, comment="触发风控行业限制，不予准入｜适用阶段：准入", src="risk")
    if hit is not None:
        r["hit"] = list(hit)
    return r


class HitKeywordTests(TS.T):
    def summary_text(self):
        return self.final(raw=True)["summary"]

    def test_hit_kept_in_hit_rules_file(self):
        eng = self.put("e.json", [inst_rule()])
        rc, out = self.run_("result", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 0, out)
        doc = json.load(open(os.path.join(self.ws, "work", "r1", "hit-rules.json"), encoding="utf-8"))
        self.assertEqual(doc["hits"][0]["hit"], ["使用的应用"])
        self.assertIn("HIT_KEYWORDS", out)
        self.assertIn(SENT, out)

    def test_basis_line_starts_with_keyword_sentence(self):
        eng = self.put("e.json", [inst_rule()])
        rc, out = self.summary(eng, [{"ruleIds": [INST], "text": "本次项目内容里出现了该字样，需人工复核实际业务"}],
                               ["请补充项目的业务说明，供人工复核"])
        self.assertEqual(rc, 0, out)
        s = self.summary_text()
        self.assertIn(SENT + "；本次项目内容里出现了该字样，需人工复核实际业务", s)

    def test_keyword_may_be_quoted_by_model(self):
        eng = self.put("e.json", [inst_rule()])
        rc, out = self.summary(eng, [{"ruleIds": [INST], "text": "项目内容含有「使用的应用」字样，需人工复核实际业务"}],
                               ["请补充项目的业务说明，供人工复核"])
        self.assertEqual(rc, 0, out)

    def test_not_duplicated_when_model_already_wrote_it(self):
        eng = self.put("e.json", [inst_rule()])
        rc, out = self.summary(eng, [{"ruleIds": [INST], "text": SENT + "，需人工复核实际业务"}], ["请补充项目的业务说明，供人工复核"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.summary_text().count("命中关键词"), 1)

    def test_other_level_rule_goes_into_next(self):
        top = TS.mk("R1", "拦截规则", "true", "拦截", comment="主体类型不符直接禁入｜适用阶段：准入")
        eng = self.put("e.json", [top, inst_rule(level="转人工")])
        rc, out = self.summary(eng, [{"ruleIds": ["R1"], "text": "按审核要求主体类型不符时不予准入，本次主体类型不符"}],
                               ["请更换为符合要求的主体后重新提交", {"ruleIds": [INST], "text": "请补充项目的业务说明，供人工复核"}])
        self.assertEqual(rc, 0, out)
        self.assertIn(SENT + "；请补充项目的业务说明，供人工复核", self.summary_text())

    def test_rule_without_hit_unchanged(self):
        eng = self.put("e.json", [inst_rule(hit=None)])
        rc, out = self.summary(eng, [{"ruleIds": [INST], "text": "本次项目内容触发了机构的行业限制，需人工复核实际业务"}],
                               ["请补充项目的业务说明，供人工复核"])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("命中关键词", self.summary_text())
        self.assertNotIn("HIT_KEYWORDS", self.run_("result", "--rid", "r1", "--file", eng)[1])

    def test_lenient_fallback_uses_keyword_sentence(self):
        eng = self.put("e.json", [inst_rule()])
        for _ in range(3):                    # 两次被拒后进入宽松模式，缺的依据由脚本补齐
            rc, out = self.summary(eng, [], ["请补充项目的业务说明，供人工复核"], fresh=False)
        self.assertEqual(rc, 0, out)
        self.assertIn(SENT, self.summary_text())


if __name__ == "__main__":
    unittest.main()
