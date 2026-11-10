"""python3 integration/test_summary.py
v32：result 只把命中规则写进 work/<id>/hit-rules.json，summary 只读这个文件。
v30：combine.py result 的漏斗 + combine.py summary（按漏斗级别校验依据/下一步草稿 → 渲染 summary）。
夹具：fixtures/v30/response-1105.json（用户给的新版引擎返回，测试数据）、response_image_scenario.json（按用户截图假设的场景）。"""
import json, os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "skills", "admission-v0-3-catalog", "scripts", "combine.py")
FX = os.path.join(HERE, "fixtures", "v30")


def mk(rule_id, name, result, rm, comment="描述｜适用阶段：准入", reason="", src="ontology"):
    return {"ruleId": rule_id, "ruleName": name, "result": result, "resultLabel": "", "expression": "A.b = 1", "reason": reason,
            "comment": comment, "riskMeasure": rm, "ruleSource": src}


def unformat(s):
    """摘要排版（combine_config.json 的 summaryHeadings / summaryStyle）还原成原来的纯文本格式，内容断言沿用；
    排版本身由 test_layout_* 检查。只去掉排版记号：标题序号、引用块、结论图标与加粗、列表符号（依次编号）、依据要点加粗。"""
    out, n = [], 0
    for l in s.split("\n"):
        m = re.match(r"^## \d+ · (.+)$", l)
        if m:
            out.append("## " + m.group(1))
            n = 0
            continue
        m = re.match(r"^> (?:\S+ )?\*\*(.+)\*\*$", l)
        if m:
            out.append(m.group(1))
            continue
        m = re.match(r"^(?:> )?- (.*)$", l)
        if m:
            n += 1
            out.append("%d. %s" % (n, m.group(1).replace("**", "")))
            continue
        out.append(l)
    return "\n".join(out)


class T(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def put(self, name, rules=None, fixture=None):
        fp = os.path.join(self.ws, name)
        if fixture:
            shutil.copy(os.path.join(FX, fixture), fp)
        else:
            json.dump({"code": 0, "data": {"ruleCheckResult": "x", "ruleCheckList": rules}}, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        return name

    def run_(self, *a, stdin=""):
        r = subprocess.run([sys.executable, "-I", SCRIPT, *a], cwd=self.ws, input=stdin, capture_output=True, text=True, env={"LANG": "C.UTF-8"}, timeout=30)
        self.assertNotIn("SUMMARY_DEBUG ", r.stdout)
        return r.returncode, r.stdout + r.stderr

    def summary(self, eng, basis, nxt=None, rid="r1", analysis=None, fresh=True):
        draft = {"basis": basis}
        if nxt is not None:
            draft["next"] = nxt
        if analysis is not None:
            draft["analysis"] = analysis
        tries = os.path.join(self.ws, "work", rid, ".summary-tries.json")
        if fresh and os.path.isfile(tries):          # v38：被拒次数会累计；单条校验用例每次都按“第一次提交”测
            os.remove(tries)
        return self.run_("summary", "--rid", rid, "--file", eng, stdin=json.dumps(draft, ensure_ascii=False))

    def final(self, rid="r1", raw=False):
        with open(os.path.join(self.ws, "work", rid, "summary-final.json"), encoding="utf-8") as f:
            result = json.load(f)
        self.assertEqual(set(result), {"summary"})
        return result if raw else {"summary": unformat(result["summary"])}

    # ───── result：漏斗 ─────

    def test_funnel_levels_pick_the_strictest_hit(self):
        order = ["拦截", "建议拦截", "转人工", "通过"]
        for i, lv in enumerate(order):
            rules = [mk("R-%d" % j, "规则%d" % j, "true", order[j]) for j in range(i, len(order))]      # 命中从 lv 到最宽
            rules.append(mk("R-skip", "跳过项", "skip", "拦截"))
            eng = self.put("e.json", rules)
            rc, out = self.run_("result", "--file", eng)
            self.assertIn("FUNNEL_LEVEL %s｜" % lv, out, out)

    def test_skip_never_counts_and_a_miss_is_the_widest_level(self):
        eng = self.put("e.json", [mk("R-1", "命中拦截类", "false", "拦截", reason="不满足 A.b = 1"), mk("R-2", "跳过", "skip", "拦截")])
        rc, out = self.run_("result", "--file", eng)
        self.assertIn("FUNNEL_LEVEL 通过｜", out)                                 # 有已判定规则、一条没命中 → 最宽一级

    def test_no_judged_rule_gives_no_conclusion_not_release(self):
        eng = self.put("e.json", [mk("R-1", "x", "skip", "拦截"), mk("R-2", "y", "skip", "建议拦截")])
        rc, out = self.run_("result", "--file", eng)
        self.assertIn("FUNNEL_LEVEL 无（无已判定", out)
        self.assertNotIn("FUNNEL_LEVEL 通过", out)
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng)                  # 无结论：不用写草稿，脚本直接渲染
        self.assertEqual(rc, 0, out)
        s = self.final()["summary"]
        self.assertIn("暂无结论｜提交的信息还不足以完成自动核验", s)          # 结论行用业务说法
        self.assertIn("转人工研判", s)
        self.assertNotIn("通过｜", s)

    def test_unrecognized_risk_measure_is_listed_and_never_guessed(self):
        eng = self.put("e.json", [mk("R-1", "复合写法", "true", "不足3月拦截，3-6月建议拦截"), mk("R-2", "空值", "true", None), mk("R-3", "转人工类", "true", "转人工")])
        rc, out = self.run_("result", "--file", eng)
        self.assertIn("FUNNEL_LEVEL 转人工｜", out)                           # 未识别的不参与，也不拆分复合写法去猜
        self.assertEqual(out.count("FUNNEL_UNRECOGNIZED"), 2)
        # 命中规则全都不在漏斗内：不给结论
        eng = self.put("e2.json", [mk("R-1", "复合写法", "true", "不足3月拦截，3-6月建议拦截")])
        rc, out = self.run_("result", "--file", eng)
        self.assertIn("FUNNEL_LEVEL 无（命中规则的处置级别", out)

    def test_parse_error_rules_are_dropped_not_marking_result_incomplete(self):
        # 262：引擎无法解析的规则（含 risk 来源重复 ruleId 的那两条）整条抛掉，不再让摘要卡在“结果不完整”
        eng = self.put("e.json", fixture="engine_parse_error_262.json")
        rc, out = self.run_("result", "--file", eng)
        self.assertEqual(rc, 0, out)
        self.assertIn("总条数=51", out)
        self.assertIn("PARSE_ERROR 6 条规则引擎无法解析", out)
        self.assertNotIn("重复ruleId", out)
        self.assertNotIn("WARN 重复 ruleId", out)
        self.assertIn("FUNNEL_LEVEL 通过｜", out)

    def test_user_response_1105_is_blocked_and_the_compound_value_is_flagged(self):
        eng = self.put("e.json", fixture="response-1105.json")
        rc, out = self.run_("result", "--file", eng)
        self.assertEqual(rc, 0, out)
        self.assertIn("已判定=4（命中 T=3，未命中 F=1 U=0）  skip=68", out)
        self.assertIn("PARSE_ERROR 6 条规则引擎无法解析", out)
        self.assertIn("FUNNEL_LEVEL 拦截｜", out)
        self.assertIn("FUNNEL_UNRECOGNIZED RULE-GATE-002|营业执照成立日期为空转人工|riskMeasure=不足3月拦截，3-6月建议拦截", out)
        self.assertIn("FUNNEL_HITS 拦截:RULE-GATE-001,RULE-GATE-003；", out)            # v32：列 ruleId，不再列小表序号
        self.assertNotIn("LATER_STAGES", out)

    # ───── summary：按漏斗级别 ─────

    def image_ws(self):
        eng = self.put("e.json", fixture="response_image_scenario.json")
        os.makedirs(os.path.join(self.ws, "work", "r1"), exist_ok=True)
        shutil.copy(os.path.join(FX, "detail_image_scenario.json"), os.path.join(self.ws, "work", "r1", "input-extract-detail.json"))
        return eng

    def sections(self, s):
        return [l for l in s.split("\n") if l.startswith("## ")]

    def part(self, s, head, nxt_head=None):
        return s.split(head + "\n")[1].split("\n\n## ")[0].split("\n")

    def test_need_basis_shows_comment_and_trigger_condition(self):
        """依据围绕 comment 写由提示词约束（不做脚本字面校验）；NEED_BASIS 同时给出 comment 全文和触发条件，便于发现两者对不上。"""
        rule = mk("2080184341491822592-projectName", "2080184341491822592-projectName", "true", "建议拦截",
                  comment="企业本身有刑事犯罪或重大违法违规即禁入｜适用阶段：准入", src="risk")
        rule["expression"] = "Project.project_name CONTAINS [使用的应用]"
        eng = self.put("eng.json", [rule])
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 4, out)
        self.assertIn("|企业本身有刑事犯罪或重大违法违规即禁入｜适用阶段：准入|Project.project_name CONTAINS [使用的应用]", out)
        self.assertIn("先用自己的话说清 comment 的要求", out)
        rc, out = self.summary(eng, [{"ruleIds": [rule["ruleId"]], "text": "本次资料需要进一步人工确认"}],
                               ["请配合人工复核，说明企业及法定代表人是否存在刑事犯罪或重大违法违规记录"])
        self.assertEqual(rc, 0, out)                 # 脚本不按字面核对 comment 覆盖

    def test_watch_level_writes_basis_from_hit_comments_and_improvement_next_steps(self):
        eng = self.image_ws()
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng)                  # 没草稿：列出该级别命中规则的 comment 和下一步口径
        self.assertEqual(rc, 4, out)
        self.assertIn("NEED_BASIS 结论级别：转人工｜需转人工核验后决定是否入驻", out)
        self.assertIn("RULE-BIZ-001|典型影视灵工场景放行并关注|", out)
        self.assertIn("纳入重点监控，抽查打卡定位与交付成果", out)                        # comment 全文
        self.assertNotIn("RULE-FLOW-001", out)                                         # 只列该级别的命中规则
        self.assertIn("怎么提高不足点", out)
        basis = [{"ruleIds": ["RULE-BIZ-001"], "text": "实际业务属于典型影视灵工场景：「按照场务指示」，平台认可但需持续关注任务是否真实发生"}]
        nxt = ["在项目内容里补写每次任务的具体地点、时间和交付物，方便抽查打卡定位与交付成果", "上传剧组现场任务照片作为交付佐证"]
        rc, out = self.summary(eng, basis, nxt)
        self.assertEqual(rc, 0, out)
        s = self.final()["summary"]
        self.assertEqual(self.sections(s), ["## 结论", "## 依据", "## 下一步"])           # summary 没有“说明”段
        self.assertNotIn("核查完成", s)
        self.assertEqual(set(self.final()), {"summary"})
        self.assertNotIn("【来源", s)
        self.assertIn("## 结论\n转人工｜需转人工核验后决定是否入驻", s)
        self.assertIn("1. 实际业务属于典型影视灵工场景", s)
        self.assertNotIn("（转人工级）", s)                                          # 旧规则的级别/未命中标签不再生成
        self.assertEqual(self.part(s, "## 下一步"), ["1. " + nxt[0], "2. " + nxt[1]])
        self.assertNotIn("重新核查", s)
        self.assertNotIn("可能影响结论", s)
        self.assertNotIn("关联公司", s)                                                  # 旧的收尾追问删了
        self.assertFalse(re.search(r"RULE-[A-Z]+-\d+", s), s)

    def test_basis_must_cover_every_hit_at_the_level_and_only_those(self):
        rules = [mk("R-A", "命中拦截甲", "true", "拦截", comment="企业名称含禁用词，不得入驻｜适用阶段：准入"),
                 mk("R-A2", "命中拦截乙", "true", "拦截", comment="经营范围含禁入项目｜适用阶段：准入"),
                 mk("R-B", "命中建议拦截", "true", "建议拦截"), mk("R-F", "未命中", "false", "拦截", reason="不满足 A.b = 1")]
        eng = self.put("e.json", rules)
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 4, out)
        self.assertIn("R-A|", out); self.assertIn("R-A2|", out)
        self.assertNotIn("R-F|", out)
        self.assertIn("R-B|建议拦截|命中建议拦截|", out)                                 # v37：其余级别的命中单列，不进依据
        self.assertIn("怎么改正", out)
        nxt = ["把企业名称改成不含禁用词的名称后重新提交", {"ruleIds": ["R-B"], "text": "另有一项风险点转人工核验，请按要求说明情况"}]
        cases = [
            ([{"ruleIds": ["R-A"], "text": "企业名称含禁用词，命中拦截规则"}], nxt, "没有出现在任何一条依据里：R-A2"),
            ([{"ruleIds": ["R-A", "R-A2"], "text": "企业名称和经营范围均命中禁入规则"}, {"ruleIds": ["R-B"], "text": "较低级别的命中不写入依据"}], nxt, "不是命中“拦截”级别的规则"),
            ([{"ruleIds": ["R-A", "R-A2"], "text": "企业名称和经营范围均命中禁入规则"}, {"ruleIds": ["R-F"], "text": "未命中的规则也不写入依据"}], nxt, "不是命中“拦截”级别的规则"),
            ([{"ruleIds": ["R-A", "R-A2"], "text": "企业名称和经营范围均命中禁入规则"}], None, "next 应是"),
            ([{"ruleIds": ["R-A", "R-A2"], "text": "企业名称和经营范围均命中禁入规则"}], [], "next 应是"),
            ([{"text": "没写 ruleIds 的依据不行"}], nxt, "须带 ruleIds"),
        ]
        for basis, n, want in cases:
            rc, out = self.summary(eng, basis, n)
            self.assertEqual(rc, 1, (want, out))
            self.assertIn(want, out)
        rc, out = self.summary(eng, [{"ruleIds": ["R-A"], "text": "企业名称含禁用词，命中拦截规则"}, {"ruleIds": ["R-A2"], "text": "经营范围含禁入项目，命中拦截规则"}], nxt)
        self.assertEqual(rc, 0, out)
        s = self.final()["summary"]
        self.assertIn("## 结论\n拦截｜不予准入，请勿自动放行", s)
        self.assertEqual(len(self.part(s, "## 依据", "## 下一步")), 2)

    def test_other_hit_levels_must_be_covered_in_next_steps(self):
        rules = [mk("RULE-AA-001", "命中拦截甲", "true", "拦截", comment="企业名称含禁用词，不得入驻｜适用阶段：准入"),
                 mk("RULE-BB-001", "命中建议拦截", "true", "建议拦截", comment="股东存在关联风险｜适用阶段：准入"),
                 mk("RULE-WW-001", "命中转人工", "true", "转人工", comment="经营场所需持续关注｜适用阶段：准入"),
                 mk("RULE-OK-001", "命中通过", "true", "通过", comment="材料齐全｜适用阶段：准入")]
        eng = self.put("e.json", rules)
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 4, out)
        self.assertIn("RULE-BB-001|建议拦截|", out); self.assertIn("RULE-WW-001|转人工|", out)
        self.assertNotIn("RULE-OK-001|", out)                                                 # 通过级没有要处理的事项
        basis = [{"ruleIds": ["RULE-AA-001"], "text": "企业名称含禁用词，命中拦截规则"}]
        base = "把企业名称改成不含禁用词的名称后重新提交"
        cases = [
            ([base], "没有出现在任何一条下一步里", "RULE-BB-001,RULE-WW-001"),
            ([base, {"ruleIds": ["RULE-BB-001"], "text": "股东关联风险转人工核验，请说明股权关系"}], "没有出现在任何一条下一步里", "RULE-WW-001"),
            ([base, {"ruleIds": ["RULE-OK-001"], "text": "通过级规则不应写进下一步"}], "不是本次命中的结论级别或其余级别", "RULE-OK-001"),
            ([base, {"ruleIds": ["RULE-BB-001", "RULE-WW-001"], "text": "含规则ID RULE-BB-001 的话不行"}], "规则 ID", ""),
        ]
        for n, want, extra in cases:
            rc, out = self.summary(eng, basis, n)
            self.assertEqual(rc, 1, (want, out))
            self.assertIn(want, out); self.assertIn(extra, out)
        nxt = [base, {"ruleIds": ["RULE-BB-001"], "text": "股东关联风险转人工核验，请说明股权关系"}, {"ruleIds": ["RULE-WW-001"], "text": "经营场所合作期间持续关注，请保留现场照片佐证"}]
        rc, out = self.summary(eng, basis, nxt)
        self.assertEqual(rc, 0, out)
        s = self.final()
        self.assertEqual(self.part(s["summary"], "## 下一步"), ["1. " + nxt[0], "2. " + nxt[1]["text"], "3. " + nxt[2]["text"]])
        self.assertEqual(len(self.part(s["summary"], "## 依据", "## 下一步")), 1)       # 其余级别不进依据
        self.assertEqual(self.sections(s["summary"]), ["## 结论", "## 依据", "## 下一步"])
        self.assertFalse(re.search(r"R-[A-Z]+\b", s["summary"]), s["summary"])

    def test_each_blocking_level_has_its_own_next_step_hint(self):
        for lv, hint in (("建议拦截", "怎么降低风险点"), ("转人工", "怎么降低违规嫌疑，或补充哪些佐证"), ("拦截", "怎么改正")):
            eng = self.put("e.json", [mk("R-1", "命中", "true", lv), mk("R-2", "更宽一级", "true", "通过")])
            rc, out = self.run_("summary", "--rid", "r1", "--file", eng)
            self.assertEqual(rc, 4, out)
            self.assertIn("结论级别：%s｜" % lv, out)
            self.assertIn(hint, out)
            rc, out = self.summary(eng, [{"ruleIds": ["R-1"], "text": "命中%s类规则一条" % lv}], ["按规则要求补充材料后转人工处理"])
            self.assertEqual(rc, 0, out)
            self.assertIn("## 结论\n%s｜" % lv, self.final()["summary"])

    def test_release_praises_five_submitted_materials_and_has_a_fixed_next_step(self):
        eng = self.put("e.json", [mk("R-1", "全部未命中", "false", "拦截", reason="不满足 A.b = 1"), mk("R-2", "跳过", "skip", "拦截")])
        os.makedirs(os.path.join(self.ws, "work", "r1"), exist_ok=True)
        shutil.copy(os.path.join(FX, "detail_image_scenario.json"), os.path.join(self.ws, "work", "r1", "input-extract-detail.json"))
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 4, out)
        self.assertIn("NEED_BASIS 结论级别：通过｜", out)
        self.assertIn("4–6 条", out)
        five = [{"text": t} for t in ["营业执照名称与申报企业名称逐字一致，主体信息真实", "营业执照在有效期内，经营范围与申报业务相符", "法定代表人身份证件清晰可读，姓名与工商登记一致", "银行开户凭证的户名与企业名称一致", "项目内容：「按照场务指示」描述具体，任务边界清晰"]]
        rc, out = self.summary(eng, five)
        self.assertEqual(rc, 0, out)
        s = self.final()["summary"]
        self.assertIn("## 结论\n通过｜可正常入驻", s)
        self.assertEqual(len(self.part(s, "## 依据", "## 下一步")), 5)
        self.assertEqual(self.part(s, "## 下一步", "## 说明"), ["1. ✅ 业务可正常开展、正常入驻。"])
        for n in (3, 7):                                                              # 约 5 条：只收 4–6 条
            rc, out = self.summary(eng, (five * 2)[:n])
            self.assertEqual(rc, 1, out)
            self.assertIn("通过的依据应写 4–6 条", out)

    def test_quotes_must_come_from_the_submitted_materials(self):
        eng = self.image_ws()
        ok = [{"ruleIds": ["RULE-BIZ-001"], "text": "任务内容「按照场务指示」属典型影视灵工场景，需持续关注"}]
        rc, out = self.summary(eng, ok, ["补充交付佐证"])
        self.assertEqual(rc, 0, out)
        for basis, nxt in (([{"ruleIds": ["RULE-BIZ-001"], "text": "剧组场景布置：「搭建了一个并不存在的摄影棚」"}], ["补充交付佐证材料"]),
                           (ok, ["请补充：「并不存在的原文」相关说明"])):
            rc, out = self.summary(eng, basis, nxt)
            self.assertEqual(rc, 1, out)
            self.assertIn("引文不是提交资料里的原文", out)

    # ───── v38：summary 防死循环（v37 job_54：一段材料里没有的引文改了 29 次标点，模型调用报错，整单失败）─────

    BAD = [{"ruleIds": ["RULE-BIZ-001"], "text": "上下游合同项目名称为「软件开发人员组织·发票类目：信息技术服务」，需持续关注"}]

    def test_v38_rejected_quote_points_to_the_nearest_original(self):
        eng = self.image_ws()
        rc, out = self.summary(eng, [{"ruleIds": ["RULE-BIZ-001"], "text": "项目内容为「剧组场务协作」，属影视灵工场景"}], ["补充交付佐证材料"])
        self.assertEqual(rc, 1, out)
        self.assertIn("最接近的原文", out)
        self.assertIn("「剧组场务协助」", out)                     # 给出真实原文，让模型逐字抄而不是反复改标点
        self.assertIn("第 1 次被拒", out)

    def test_v38_need_basis_lists_quotable_originals_and_analysis(self):
        eng = self.image_ws()
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 4, out)
        self.assertIn("可放进「」的原文", out)
        self.assertIn("项目内容：剧组场务协助", out)
        self.assertIn("analysis（agent全局分析，仅供参考", out)

    def test_v38_third_bad_draft_is_accepted_leniently_without_fabricated_quotes(self):
        eng = self.image_ws()
        for n in (1, 2):
            rc, out = self.summary(eng, self.BAD, ["补充交付佐证材料"], fresh=False)
            self.assertEqual(rc, 1, out)
            self.assertIn("第 %d 次被拒" % n, out)
        rc, out = self.summary(eng, self.BAD, ["补充交付佐证材料"], fresh=False)
        self.assertEqual(rc, 0, out)                                 # 第三次：不合格条目丢弃，脚本用规则说明补齐依据
        self.assertIn("LENIENT", out)
        s = self.final()["summary"]
        self.assertNotIn("软件开发人员组织", s)                       # 编造的引文不会进摘要
        self.assertIn("典型影视灵工场景放行并关注：", s)
        self.assertIn("补充交付佐证材料", s)                          # 合格的下一步保留
        self.assertFalse(os.path.exists(os.path.join(self.ws, "work", "r1", ".summary-tries.json")))   # 通过后计数清零

    def test_v38_invalid_json_also_ends_after_two_rejections(self):
        """语法错误比内容退回收得更早：同一步骤连续第二次不是合法 JSON 就由脚本收尾（STDIN_LENIENT），不再等第三次。"""
        eng = self.image_ws()
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng, stdin='{"basis": [ "next"')
        self.assertEqual(rc, 1, out)
        self.assertIn("STDIN_JSON_INVALID summary", out)
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng, stdin='{"basis": [ "next"')
        self.assertEqual(rc, 0, out)
        self.assertIn("WARN STDIN_LENIENT", out)
        s = self.final()["summary"]
        self.assertIn("## 依据\n1. 典型影视灵工场景放行并关注：", s)
        self.assertIn("## 下一步\n1. 关于“", s)

    def test_v38_analysis_goes_last_in_attention_and_bad_items_are_only_dropped(self):
        eng = self.image_ws()
        ok = [{"ruleIds": ["RULE-BIZ-001"], "text": "任务内容「按照场务指示」属典型影视灵工场景，需持续关注"}]
        ana = ["交付要求以场务、装卸为主，疑似劳务派遣性质，建议核实用工形式与开票类目是否匹配",
               "这条写了属性 Employer.usage_scenario，应被丢弃",
               "资料里「并不存在的原文」，应被丢弃"]
        rc, out = self.summary(eng, ok, ["补充交付佐证材料"], analysis=ana)
        self.assertEqual(rc, 0, out)                                  # analysis 不合格只丢弃，不退回
        self.assertEqual(out.count("ANALYSIS_DROPPED"), 2, out)
        att = self.part(self.final()["summary"], "## 注意", "## 说明")
        self.assertTrue(att[-1].endswith("agent全局分析（仅供参考）：交付要求以场务、装卸为主，疑似劳务派遣性质，建议核实用工形式与开票类目是否匹配。"), att)
        self.assertNotIn("并不存在的原文", self.final()["summary"])
        rc, out = self.summary(eng, ok, ["补充交付佐证材料"])           # 不写 analysis：“注意”里没有这一条
        self.assertNotIn("agent全局分析", self.final()["summary"])

    def test_v33_field_names_in_quotes_are_rejected_without_a_cascade_error(self):
        """am1：「交付要求」被拒后改写成「dlvrDemd」「projCont」就通过了；且被拒时还另报“规则没出现在依据里”，模型困惑。"""
        eng = self.image_ws()
        rc, out = self.summary(eng, [{"ruleIds": ["RULE-BIZ-001"], "text": "资料中「dlvrDemd」为影视灵工场景，需持续关注"}], ["补充交付佐证材料"])
        self.assertEqual(rc, 1, out)
        self.assertIn("「」里写资料原文，不写字段名：dlvrDemd", out)
        self.assertIn("这条依据已带 RULE-BIZ-001，只改文字即可", out)
        self.assertNotIn("没有出现在任何一条依据里", out)

    # ───── v39：summary 给客户看：不出现字段变量、清单编号、原因码、技术用语 ─────

    def test_v39_basis_and_next_reject_codes_and_jargon(self):
        eng = self.image_ws()
        bad = ["B08 经营范围与任务不符，需要补充说明情况", "项目内容 projCont 没写清楚具体任务和地点",
               "用工场景属性未取得，规则无法判定是否放行", "交付佐证不足（R06），需要补充现场照片", "照片 scene_photo_count 不足两张需要补充"]
        for t in bad:
            rc, out = self.summary(eng, [{"ruleIds": ["RULE-BIZ-001"], "text": t}], ["补充交付佐证材料"])
            self.assertEqual(rc, 1, (t, out))
            self.assertIn("要写给客户看，用业务用语", out)
        rc, out = self.summary(eng, [{"ruleIds": ["RULE-BIZ-001"], "text": "任务内容「按照场务指示」属典型影视灵工场景，需持续关注"}], ["属性缺失请补充"])
        self.assertIn("“属性”改说“信息/事项”", out)
        rc, out = self.summary(eng, [{"ruleIds": ["RULE-BIZ-001"], "text": "任务内容「按照场务指示」属典型影视灵工场景，需持续关注"}], ["补充交付佐证材料"])
        self.assertEqual(rc, 0, out)

    def test_v39_attention_and_analysis_are_rewritten_in_business_terms(self):
        eng = self.image_ws()
        fp = os.path.join(self.ws, "work", "r1", "input-extract-detail.json")
        d = json.load(open(fp, encoding="utf-8"))
        d["notes"] = {"unresolvedProperties": [], "notFoundInDefinition": [], "conflicts": ["leaseAgreementUrl 承租方与 entpName 不一致，Employer.employer_name 待人工确认（R09）"], "unreadMaterials": ["officeVideoUrl｜ReadVideo 两次无证据（R05）"], "toolIssues": []}
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        ok = [{"ruleIds": ["RULE-BIZ-001"], "text": "任务内容「按照场务指示」属典型影视灵工场景，需持续关注"}]
        rc, out = self.summary(eng, ok, ["补充交付佐证材料"], analysis=["疑似 dlvrDemd 与经营范围不符，建议核实"])
        self.assertEqual(rc, 0, out)
        s = self.final()["summary"]
        att = "\n".join(self.part(s, "## 注意"))
        self.assertIn("企业名称", att)
        self.assertIn("交付要求", att)
        for pat in (r"[A-Za-z]+Url", r"entpName|dlvrDemd|Employer\.", r"(?<![A-Za-z0-9])R\d{2}(?![0-9])", r"ReadVideo"):
            self.assertFalse(re.search(pat, att), (pat, att))

    def test_v39_restricted_industry_hiring_temporary_staff_gets_a_reminder(self):
        eng = self.image_ws()
        fp = os.path.join(self.ws, "work", "r1", "input-extract-detail.json")
        d = json.load(open(fp, encoding="utf-8"))
        by = {x["id"]: x for x in d["items"]}
        def put(i, v):
            if i in by:
                by[i]["value"], by[i]["source"] = v, "Y｜请求｜" + v
            else:
                d["items"].append({"id": i, "name": i, "desc": "", "value": v, "source": "Y｜请求｜" + v})
        put("A02", "上海某某金融信息服务有限公司")
        put("A08", "车展期间展台引导、地推发放宣传册")
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng)
        self.assertIn("FLEX_JOB", out)
        ok = [{"ruleIds": ["RULE-BIZ-001"], "text": "任务内容「按照场务指示」属典型影视灵工场景，需持续关注"}]
        rc, out = self.summary(eng, ok, ["补充交付佐证材料"])
        self.assertEqual(rc, 0, out)
        att = "\n".join(self.part(self.final()["summary"], "## 注意"))
        self.assertIn("企业属于金融类行业", att)
        self.assertIn("可以按灵活用工承接", att)
        self.assertNotIn("FUNNEL", att)
        self.assertIn("## 结论\n转人工｜", self.final()["summary"])            # 只提醒，不改结论
        put("A08", "地推拉新办理信用卡")                                         # 推的是金融产品本身：不在例外内
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = self.summary(eng, ok, ["补充交付佐证材料"])
        self.assertNotIn("可以按灵活用工承接", self.final()["summary"])

    def test_v34_attention_section_rewrites_conflicts_for_people(self):
        """“注意”段：notes.conflicts 整理成准入校验口径的话（材料值/工商值分别是什么），再加附件超时/未提供；脚本生成，不经模型。"""
        eng = self.image_ws()
        fp = os.path.join(self.ws, "work", "r1", "input-extract-detail.json")
        d = json.load(open(fp, encoding="utf-8"))
        def item(i, v, src="Y｜x｜y"):
            return {"id": i, "name": i, "desc": "", "value": v, "source": src}
        keep = {x["id"]: x for x in d["items"]}
        for i, v in (("B01", "智元创新（无锡）科技有限公司"), ("J01", "智元创新（无锡）软件有限公司"), ("B08", "一般项目：软件开发；技术服务；智能机器人的研发。（除依法须经批准的项目外，凭营业执照依法自主开展经营活动）"),
                     ("J16", "一般项目：软件开发；技术服务；货物进出口；技术进出口（除依法须经批准的项目外，凭营业执照依法自主开展经营活动）"), ("B10", "人民币壹佰万元"), ("J08", "注册资本500万元；币种人民币")):
            if i in keep:
                keep[i]["value"], keep[i]["source"] = v, "Y｜x｜y"
            else:
                d["items"].append(item(i, v))
        for i in ("B03", "J02", "B06", "J07", "B04", "J09", "B05", "J10", "B07", "J13", "C02", "D01", "D08", "G02"):
            if i not in keep:
                d["items"].append(item(i, None, "N｜R01｜无"))
        d["notes"] = {"unresolvedProperties": [], "notFoundInDefinition": [], "conflicts": ["officeVideoUrl 视频招牌原文「万联易达集团」与申报名称「智元创新（无锡）科技有限公司」不一致（未作为已核实）"],
                      "unreadMaterials": ["officeVideoUrl｜视频读取两次均超时"], "toolIssues": []}
        d["materials"] = {"bizlicUrl": ["可读", "名称栏"], "vatTaxCertUrl": ["未提供", "—"], "upstreamDnstreamAgmtUrl": ["未提供", "—"], "noTaxCertSbUrl": ["不可读", "仅占位文字"]}
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump({"prefilled": [], "modelFilled": [], "needStatus": [], "invalid": {"leaseAgreementUrl": "ATTACHMENT_DOWNLOAD_TIMEOUT", "bizScenePhotoUrls": "ATTACHMENT_UNAVAILABLE"},
                   "base": None, "baseOrigin": "", "derived": [], "autoConflicts": [], "rechecked": {"B08": {"outcome": "confirmed_diff", "first": "x", "second": "x"}}, "stale": []},
                  open(os.path.join(self.ws, "work", "r1", ".detail-state.json"), "w", encoding="utf-8"))
        ok = [{"ruleIds": ["RULE-BIZ-001"], "text": "任务内容「按照场务指示」属典型影视灵工场景，需持续关注"}]
        rc, out = self.summary(eng, ok, ["补充交付佐证"])
        self.assertEqual(rc, 0, out)
        s = self.final()
        self.assertEqual(self.sections(s["summary"]), ["## 结论", "## 依据", "## 下一步", "## 注意"])
        att = self.part(s["summary"], "## 注意")
        text = "\n".join(att)
        self.assertIn("营业执照名称与工商登记不一致", text)
        self.assertIn("营业执照名称与工商登记不一致：材料上为「智元创新（无锡）科技有限公司」，工商登记为「智元创新（无锡）软件有限公司」。请核实并说明原因。", text)
        self.assertIn("营业执照经营范围与工商登记不一致（已回看原件二次确认）：材料上有而工商没有：智能机器人的研发；工商有而材料上没有：货物进出口、技术进出口。", text)
        self.assertIn("注册资本与工商登记不一致：材料上为「人民币壹佰万元」，工商登记为「500万元」", text)
        self.assertIn("办公场所视频：视频招牌原文「万联易达集团」与申报名称", text)
        self.assertIn("未作为已核实结论", text)
        self.assertIn("租赁合同：下载超时，相关核验未进行，请重新提供。", text)
        self.assertIn("业务场景照片：链接失效或不可用", text)
        self.assertIn("以下材料无法读取：无欠税及社保证明（仅占位文字）", text)
        self.assertIn("本次未提供：增值税发票、上下游合同", text)
        self.assertIn("办公场所视频读取失败：视频读取两次均超时", text)
        self.assertNotIn("officeVideoUrl", text)
        self.assertNotIn("Url", text)
        self.assertNotIn("## 说明", s["summary"])

    def test_v34_no_attention_section_when_nothing_to_note(self):
        eng = self.image_ws()
        ok = [{"ruleIds": ["RULE-BIZ-001"], "text": "任务内容「按照场务指示」属典型影视灵工场景，需持续关注"}]
        rc, out = self.summary(eng, ok, ["补充交付佐证"])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("## 注意", self.final()["summary"])

    def test_text_rules_no_ids_no_english_attrs_and_length(self):
        eng = self.image_ws()
        for text, want in (("实体属性 Employer.x 命中", "不得含规则 ID、英文属性名"), ("含规则编号 RULE-BIZ-001 的说明", "不得含规则 ID、英文属性名"),
                           ("【命中】典型影视灵工场景", "不得含规则 ID、英文属性名"), ("短", "4–220 字")):
            rc, out = self.summary(eng, [{"ruleIds": ["RULE-BIZ-001"], "text": text}], ["补充交付佐证材料"])
            self.assertEqual(rc, 1, (text, out))
            self.assertIn(want, out)
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng, stdin="{坏json")
        self.assertNotEqual(rc, 0)
        self.assertIn("不是合法 JSON", out)

    def test_second_consecutive_bad_json_goes_lenient_instead_of_looping(self):
        """job 218：summary 括号写错两次被拒后模型绕过脚本。现在第二次语法失败不再退回，依据/下一步由脚本按规则说明生成。"""
        eng = self.image_ws()
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng, stdin='{"basis":[{"ruleIds":["RULE-BIZ-001"],"text":"x"}},{')
        self.assertEqual(rc, 1, out)
        self.assertIn("STDIN_JSON_INVALID summary", out)
        self.assertIn("连续第 1 次", out)
        self.assertNotIn("STDIN_GIVE_UP", out)
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng, stdin='{"basis":[}')
        self.assertEqual(rc, 0, out)
        self.assertIn("连续第 2 次", out)
        self.assertIn("WARN STDIN_LENIENT", out)
        self.assertIn("## 依据", self.final()["summary"])

    def test_incomplete_engine_result_does_not_render(self):
        eng = self.put("e.json", [mk("R-1", "x", "true", "拦截"), mk("R-1", "重复", "true", "拦截")])
        rc, out = self.summary(eng, [{"ruleIds": ["R-1"], "text": "命中拦截类规则的说明"}])
        self.assertEqual(rc, 3, out)
        self.assertIn("结果不完整", out)

    def test_engine_failed_with_null_list_names_the_missing_input_key(self):
        """am8：code=0 但 ruleCheckList=null + failures（从入参里取不到 Agency.agency_id）。不是“文件里没有数据”，是引擎没跑起来。"""
        eng = self.put("e.json", fixture="response_engine_failed_am8.json")
        for args in (("result", "--file", eng), ("summary", "--rid", "r1", "--file", eng)):
            rc, out = self.run_(*args)
            self.assertEqual(rc, 5, out)
            self.assertIn("ENGINE_FAILED ruleCheckResult=fail  ruleCheckList=null", out)
            self.assertIn("FAILURE hrInst｜取值失败：从入参里取不到 Agency.agency_id", out)
            self.assertIn("MISSING_INPUT_KEY Agency.agency_id", out)                 # 键名来自引擎自己的报错
            self.assertNotIn("文件里没有 data.ruleCheckList", out)
        # 键名不写死：换一个键名照样读出来
        doc = json.load(open(os.path.join(FX, "response_engine_failed_am8.json"), encoding="utf-8"))
        doc["failures"][0]["reason"] = "取值失败：从入参里取不到 Foo.bar_id"
        json.dump(doc, open(os.path.join(self.ws, "e2.json"), "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = self.run_("result", "--file", "e2.json")
        self.assertIn("MISSING_INPUT_KEY Foo.bar_id", out)
        # 没点名缺哪个键：不建议重试
        doc["failures"] = [{"step": "x", "reason": "内部错误"}]
        json.dump(doc, open(os.path.join(self.ws, "e3.json"), "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = self.run_("result", "--file", "e3.json")
        self.assertEqual(rc, 5)
        self.assertNotIn("MISSING_INPUT_KEY", out)
        self.assertIn("不重试", out)
        # 真的没有这个字段：仍是原来的报错
        json.dump({"code": 0, "data": {}}, open(os.path.join(self.ws, "e4.json"), "w", encoding="utf-8"))
        rc, out = self.run_("result", "--file", "e4.json")
        self.assertNotEqual(rc, 5)
        self.assertIn("文件里没有 data.ruleCheckList", out)

    def test_headings_and_ladder_come_from_config_not_code(self):
        cfg = os.path.join(os.path.dirname(SCRIPT), "combine_config.json")
        c = json.load(open(cfg, encoding="utf-8"))
        self.assertEqual([x["level"] for x in c["riskLadder"]], ["拦截", "建议拦截", "转人工", "通过"])
        self.assertEqual(c["summaryHeadings"], {"conclusion": "## 1 · 结论", "basis": "## 2 · 依据", "next": "## 3 · 下一步", "attention": "## 4 · 注意"})


    def test_summary_omits_internal_diagnostics_and_retains_hit_counts(self):
        rules = [mk("R-1", "命中转人工类", "true", "转人工"), mk("R-2", "准入阶段跳过", "skip", "拦截"),
                 mk("R-3", "后续阶段跳过", "skip", "建议拦截", comment="x｜适用阶段：结算"),
                 mk("R-U", "属性缺失未触发", "false", "拦截", reason="A.b 属性不存在"), mk("R-C", "复合", "true", "不足3月拦截，3-6月建议拦截")]
        eng = self.put("e.json", rules)
        rc, out = self.summary(eng, [{"ruleIds": ["R-1"], "text": "命中转人工类规则一条"}], ["补充交付佐证材料"])
        self.assertEqual(rc, 0, out)
        s = self.final()["summary"]
        self.assertIn("## 结论\n转人工｜", s)
        for internal in ("## 说明", "核查完成", "可能影响结论", "riskMeasure", "复合"):
            self.assertNotIn(internal, s)
        with open(os.path.join(self.ws, "work", "r1", "hit-rules.json"), encoding="utf-8") as f:
            counts = json.load(f)["counts"]
        self.assertEqual((counts["total"], counts["hit"], counts["skip"], counts["missAttrAbsent"]), (5, 2, 2, 1))

    def test_blocked_level_has_no_release_caveat(self):
        eng = self.put("e.json", [mk("R-1", "命中拦截类", "true", "拦截"), mk("R-2", "准入阶段跳过", "skip", "拦截")])
        rc, out = self.summary(eng, [{"ruleIds": ["R-1"], "text": "命中拦截类规则一条"}], ["按规则要求改正后重新提交"])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("可能影响结论", self.final()["summary"])

    # ───── v32：hit-rules.json ─────

    def test_result_writes_only_hit_rules_and_summary_reads_only_that_file(self):
        rules = [mk("R-HIT", "命中拦截", "true", "拦截", comment="企业名称含禁用词，不得入驻｜适用阶段：准入"),
                 mk("R-UN", "复合写法", "true", "不足3月拦截，3-6月建议拦截"),
                 mk("R-MISS", "未命中", "false", "拦截", reason="不满足 A.b = 1"),
                 mk("R-U", "缺属性", "false", "拦截", reason="A.b 属性不存在"),
                 mk("R-SK", "跳过", "skip", "拦截", comment="x｜适用阶段：结算")]
        eng = self.put("e.json", rules)
        rc, out = self.run_("result", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 0, out)
        self.assertIn("HITS_FILE work/r1/hit-rules.json  命中 2 条", out)
        self.assertNotIn("R-MISS", out); self.assertNotIn("R-U|", out); self.assertNotIn("R-SK", out)   # 未命中/skip 不列出
        doc = json.load(open(os.path.join(self.ws, "work", "r1", "hit-rules.json"), encoding="utf-8"))
        self.assertEqual([h["ruleId"] for h in doc["hits"]], ["R-HIT", "R-UN"])
        self.assertEqual(doc["hits"][0]["comment"], "企业名称含禁用词，不得入驻｜适用阶段：准入")       # comment 全文
        self.assertEqual((doc["hits"][0]["level"], doc["hits"][0]["atConclusionLevel"]), ("拦截", True))
        self.assertIsNone(doc["hits"][1]["level"])
        self.assertEqual(doc["counts"], {"total": 5, "judged": 4, "hit": 2, "missDetermined": 1, "missAttrAbsent": 1, "skip": 1,
                                         "skipLaterStage": 1, "unknownStatus": 0, "duplicateRuleIds": [], "outOfScope": 0, "outOfScopeHit": 0, "parseError": 0, "parseErrorRuleIds": []})
        self.assertEqual(doc["funnel"]["level"], "拦截")
        self.assertNotIn("R-MISS", json.dumps(doc["hits"], ensure_ascii=False))
        os.remove(os.path.join(self.ws, eng))                                       # 删掉原始返回：summary 只靠 hit-rules.json
        rc, out = self.run_("summary", "--rid", "r1")
        self.assertEqual(rc, 4, out)
        self.assertIn("R-HIT|命中拦截|", out)
        rc, out = self.run_("summary", "--rid", "r1", stdin=json.dumps({"basis": [{"ruleIds": ["R-HIT"], "text": "企业名称含禁用词，命中拦截规则"}],
                                                                         "next": ["更换不含禁用词的企业名称后重新提交"]}, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertIn("## 结论\n拦截｜", self.final()["summary"])
        self.assertNotIn("## 说明", self.final()["summary"])
        # 未命中的规则 ID 仍不能写进依据文字（allRuleIds 只供脚本校验）
        rc, out = self.run_("summary", "--rid", "r1", stdin=json.dumps({"basis": [{"ruleIds": ["R-HIT"], "text": "命中拦截，参见 R-MISS 规则"}],
                                                                         "next": ["更换不含禁用词的企业名称后重新提交"]}, ensure_ascii=False))
        self.assertEqual(rc, 1, out)
        self.assertIn("不得含规则 ID", out)

    def test_summary_without_hits_file_asks_to_run_result_first(self):
        rc, out = self.run_("summary", "--rid", "r9")
        self.assertNotEqual(rc, 0)
        self.assertIn("先运行 combine.py result --rid r9", out)

    def test_engine_failure_writes_no_hits_file(self):
        eng = self.put("e.json", fixture="response_engine_failed_am8.json")
        rc, out = self.run_("result", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 5, out)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "work", "r1", "hit-rules.json")))


    # ───── v37：result 直接给出写草稿的内容；summary 输出最终结果一行；“注意”去重 ─────

    def test_v37_result_prints_need_basis_so_summary_runs_once(self):
        eng = self.image_ws()
        rc, out = self.run_("result", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 0, out)
        self.assertIn("NEED_BASIS 结论级别：", out)
        self.assertIn("草稿格式：", out)
        self.assertIn("写好草稿后运行 combine.py summary --rid r1", out)

    def test_v37_no_conclusion_needs_no_draft(self):
        eng = self.put("e.json", [mk("R-1", "x", "skip", "拦截")])
        rc, out = self.run_("result", "--rid", "r1", "--file", eng)
        self.assertIn("NO_DRAFT", out)
        self.assertNotIn("NEED_BASIS", out)

    def test_v37_summary_prints_final_with_input_notes_and_no_curly_quotes(self):
        eng = self.image_ws()
        w = os.path.join(self.ws, "work", "r1")
        json.dump({"input": {"Employer": {"employer_id": "1"}}}, open(os.path.join(w, "input-combine.json"), "w", encoding="utf-8"))
        json.dump({"unresolvedProperties": ["营业执照到期日｜R10｜不传（规则按“有截止日且已到期”判断）"], "notFoundInDefinition": [], "conflicts": [],
                   "unreadMaterials": [], "toolIssues": []}, open(os.path.join(w, "notes-final.json"), "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = self.summary(eng, [{"ruleIds": ["RULE-BIZ-001"], "text": "任务内容「按照场务指示」属典型影视灵工场景，需持续关注"}], ["补充交付佐证"])
        self.assertEqual(rc, 0, out)
        line = next(l for l in out.splitlines() if l.startswith("FINAL "))
        final = json.loads(line[len("FINAL "):])
        self.assertEqual(sorted(final), ["input", "notes", "summary"])
        self.assertEqual(final["input"], {"Employer": {"employer_id": "1"}})
        self.assertIn("「有截止日且已到期」", final["notes"]["unresolvedProperties"][0])
        self.assertNotIn("“", line)
        self.assertEqual(final, json.load(open(os.path.join(w, "final-output.json"), encoding="utf-8")))
        self.assertEqual(final["summary"], self.final(raw=True)["summary"])
        with open(os.path.join(os.path.dirname(HERE), "references", "结构化输出schema_v28.json"), encoding="utf-8") as f:
            schema = json.load(f)
        self.assertEqual(set(schema["required"]), set(final))
        self.assertNotIn("summary_debug", schema["properties"])
        # 全部跳过时也须覆盖旧产物，只输出同样的三个字段。
        eng = self.put("skip.json", [mk("R-SKIP", "未判断", "skip", "拦截")])
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 0, out)
        final = json.loads(next(l[len("FINAL "):] for l in out.splitlines() if l.startswith("FINAL ")))
        self.assertEqual(set(final), set(schema["required"]))
        self.assertEqual(final["summary"], self.final(raw=True)["summary"])
        self.assertEqual(final, json.load(open(os.path.join(w, "final-output.json"), encoding="utf-8")))

    def test_v37_attention_drops_repeats_of_registry_checks_and_bracket_only_diffs(self):
        eng = self.image_ws()
        fp = os.path.join(self.ws, "work", "r1", "input-extract-detail.json")
        d = json.load(open(fp, encoding="utf-8"))
        d["notes"] = {"unresolvedProperties": [], "notFoundInDefinition": [], "unreadMaterials": [], "toolIssues": []}
        d["notes"]["conflicts"] = [
            "办公场所视频 officeVideoUrl 00:00-00:05，招牌文字为「万联易达集团」，申报名称为「智元创新（无锡）科技有限公司」，两者不同，仅凭招牌不符不能判断场所虚构，未作为已核实",
            "营业执照 bizlicUrl，注册资本：执照原文为「人民币壹佰万元」，工商登记为「500万元」，不裁决真假",
            "营业执照 bizlicUrl、名称、原件识别「智元创新（无锡）科技有限公司」与工商返回待比对",
            "租赁合同 leaseAgreementUrl、承租方「智元创新(无锡)科技有限公司」与执照「智元创新（无锡）科技有限公司」括号形式不同"]
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = self.summary(eng, [{"ruleIds": ["RULE-BIZ-001"], "text": "任务内容「按照场务指示」属典型影视灵工场景，需持续关注"}], ["补充交付佐证"])
        self.assertEqual(rc, 0, out)
        text = "\n".join(self.part(self.final()["summary"], "## 注意"))
        self.assertEqual(text.count("办公场所视频"), 1, text)
        self.assertEqual(text.count("未作为已核实"), 1, text)
        self.assertNotIn("注册资本：执照原文", text)
        self.assertNotIn("待比对", text)
        self.assertNotIn("括号形式", text)


    # ───── 排版：只改格式，文字与原来逐字相同 ─────

    def test_layout_only_changes_format_not_text(self):
        eng = self.image_ws()
        basis = [{"ruleIds": ["RULE-BIZ-001"], "text": "影视灵工场景：「按照场务指示」，平台认可但需持续关注任务是否真实发生"}]
        nxt = ["在项目内容里补写每次任务的具体地点、时间和交付物", "上传剧组现场任务照片作为交付佐证"]
        rc, out = self.summary(eng, basis, nxt, analysis=["建议核实拍摄地是否为申报企业的实际办公地"])
        self.assertEqual(rc, 0, out)
        s = self.final(raw=True)["summary"]
        self.assertTrue(s.startswith("## 1 · 结论\n> 🟡 **转人工｜需转人工核验后决定是否入驻**\n\n## 2 · 依据\n"), s)
        self.assertIn("## 2 · 依据\n- **影视灵工场景：**「按照场务指示」，平台认可但需持续关注任务是否真实发生\n\n", s)
        self.assertIn("## 3 · 下一步\n> - %s\n> - %s" % tuple(nxt), s)
        self.assertIn("\n\n## 4 · 注意\n- ", s)
        self.assertIn("- agent全局分析（仅供参考）：建议核实拍摄地是否为申报企业的实际办公地。", s)
        # 去掉排版记号后与原来的纯文本格式完全一致
        u = unformat(s)
        self.assertIn("## 结论\n转人工｜需转人工核验后决定是否入驻\n\n## 依据\n1. 影视灵工场景：「按照场务指示」", u)
        self.assertIn("## 下一步\n1. %s\n2. %s" % tuple(nxt), u)

    def test_layout_no_conclusion_icon_and_plain_basis(self):
        eng = self.put("e.json", [mk("R-1", "x", "skip", "拦截")])
        rc, out = self.run_("summary", "--rid", "r1", "--file", eng)
        self.assertEqual(rc, 0, out)
        s = self.final(raw=True)["summary"]
        self.assertIn("## 1 · 结论\n> ⚪ **暂无结论｜提交的信息还不足以完成自动核验**", s)
        self.assertIn("## 2 · 依据\n- 提交的信息还不足以完成自动核验", s)      # 没有「要点：」的依据不加粗
        self.assertNotIn("## 4 · 注意", s)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
