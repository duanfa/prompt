"""python3 integration/test_scripts.py
RunSkillScript 的脚本（detail.py / combine.py）回归：用 v25 一次真实运行的请求、工商三接口返回、规则、属性定义，
按 RunSkillScript 的方式运行（python3 -I、空环境、工作区当 cwd、stdin 管道），核对：
  init 预填行数、fill 后无待填、派生行与那次模型手写的一致、combine 的 input 与那次一致、机械校验通过。"""
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "admission-v41-claude-catalog", "scripts")
FX = os.path.join(HERE, "fixtures", "v25_run")
RID = "ontology_agent_job_43_115-am2"


def run(ws, script, *args, stdin=""):
    r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, script), *args], cwd=ws, input=stdin,
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, timeout=30)
    return r.returncode, r.stdout + r.stderr


def read(name):
    return open(os.path.join(FX, name), encoding="utf-8").read()


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        for f in ("biz_D.txt", "biz_B.txt", "biz_T.txt", "rules.json", "props.json"):
            shutil.copy(os.path.join(FX, f), self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def init(self):
        return run(self.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json", stdin=read("init_spec.json"))

    def detail_row(self, i):
        return next(x for x in self.detail()["items"] if x["id"] == i)

    def detail(self):
        return json.load(open(os.path.join(self.ws, "work", RID, "input-extract-detail.json"), encoding="utf-8"))

    def test_capital_conflict_between_d_and_b_makes_j08_r09(self):
        """v36：D.capital=500万元 对 B.registerCapital=100（单位万）时，J08 不再取 D 的值（v35-am6）。"""
        fp = os.path.join(self.ws, "biz_D.txt")
        s = open(fp, encoding="utf-8").read().replace('"capital": "300.000000"', '"capital": "500万元"')
        open(fp, "w", encoding="utf-8").write(s)
        fp = os.path.join(self.ws, "biz_B.txt")
        s = open(fp, encoding="utf-8").read().replace('"registerCapital": "300"', '"registerCapital": "100"')
        open(fp, "w", encoding="utf-8").write(s)
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        j08 = next(x for x in self.detail()["items"] if x["id"] == "J08")
        self.assertIsNone(j08["value"])
        self.assertTrue(j08["source"].startswith("N｜R09｜"), j08["source"])
        self.assertTrue(any("注册资本来源冲突" in c for c in self.detail()["notes"]["conflicts"]))

    def test_capital_same_value_different_units_is_not_a_conflict(self):
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        j08 = next(x for x in self.detail()["items"] if x["id"] == "J08")
        self.assertTrue(j08["source"].startswith("Y｜"), j08["source"])


    def test_full_flow_matches_the_real_run(self):
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        d = self.detail()
        items = {i["id"]: i for i in d["items"]}
        self.assertEqual(len(items), 163)            # v39：清单删去 I 组与 D03，新增 B24–B26、C13/C14、G09/G10
        pending = [i for i in items if items[i]["source"] == ""]
        self.assertEqual(len(pending), 85, out)          # 模型只需要读材料填这些（其中 15 行随后由脚本派生；v39 +G09/G10 +B24–B26 −D03）
        self.assertEqual(items["J33"]["value"], "false")   # 规则关键词表逐词核对
        self.assertEqual(items["A06"]["value"], "2026-11-05")
        self.assertIn("基准日回退", d["notes"]["toolIssues"][0])
        self.assertEqual(items["E10"]["source"][:6], "N｜R01｜")        # URL 失效的视频整组 N R01
        self.assertIn("ATTACHMENT_DOWNLOAD_TIMEOUT", items["E01"]["source"])
        self.assertEqual(items["C02"]["source"][:6], "N｜R01｜")
        rc, out = run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rules.json", "--props", "props.json")
        self.assertEqual(rc, 2, out)                      # 还有待填行时拒绝组装
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=read("fill_spec.json"))
        self.assertEqual(rc, 0, out)
        d = self.detail()
        items = {i["id"]: i for i in d["items"]}
        self.assertTrue(all(i["source"] for i in items.values()))
        ys = sum(1 for i in items.values() if i["source"].startswith("Y｜"))
        self.assertEqual((ys, 163 - ys), (94, 69))   # v39：B24/B25/B26 由 B04/B05/B08 派生、G10 为原文，D03 删去
        self.assertEqual(items["B16"]["value"], "23")
        self.assertEqual(items["B15"]["value"], "true")
        self.assertEqual(items["J34"]["value"], "无不一致")
        rc, out = run(self.ws, "detail.py", "finish", "--rid", RID)
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS", out)
        rc, out = run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rules.json", "--props", "props.json", stdin=read("map_spec.json"))
        self.assertEqual(rc, 0, out)
        self.assertIn("validate: OK", out)
        self.assertIn("keys: N=154 M=9 L=0 K=145", out)              # v39：32 条结算/签约/处置/复核治理规则与准入无关，先抛掉              # v39：D03 删去，account_type_allowed 无条目对应
        cb = json.load(open(os.path.join(self.ws, "work", RID, "input-combine.json"), encoding="utf-8"))
        want = json.loads(read("expected_input.json"))
        want["Employer"]["enterprise_name"] = want["Employer"]["employer_name"]   # v30 预设：企业名称总是传 Employer.enterprise_name；v25 的 employer_name 是模型按规则另映的，仍在
        want["AdmissionDoc"].pop("account_type_allowed")                          # v39：清单删去 D03「账户性质允许」，这个键不再有条目支撑
        self.assertEqual(cb["input"], want)                                       # 其余与那次真实运行的 input 逐项一致
        self.assertTrue(all(p["value"] is not None for e in cb["entities"].values() for p in e["properties"].values()))
        self.assertLess(os.path.getsize(os.path.join(self.ws, "work", RID, "input-combine.json")), 30000)
        notes = json.load(open(os.path.join(self.ws, "work", RID, "notes-final.json"), encoding="utf-8"))
        self.assertTrue(any("R14" in x and "结果类" in x for x in notes["unresolvedProperties"]))
        self.assertTrue(any("subject_type" in x for x in notes["toolIssues"]))
        self.assertTrue(any(x.startswith("officeVideoUrl｜") for x in notes["unreadMaterials"]))

    def test_fill_rejects_bad_rows_and_prefilled_ids(self):
        self.init()
        bad = {"rows": [["A01", "x", "请求｜x"], ["B01", None, "没看清"], ["B02", "有限责任公司", "无分隔"], ["ZZ9", "x", "a｜b"]]}
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=json.dumps(bad, ensure_ascii=False))
        self.assertEqual(rc, 1)
        for want in ("A01 已由脚本预填", "B01 取不到时", "ZZ9 不在清单"):
            self.assertIn(want, out)
        self.assertIn("SKIP A01", out)                                   # v37：预填行重交不算错
        self.assertNotIn("REJECT A01", out)
        self.assertIn("AUTOFIX", out)                                    # v37：漏了「｜」用该条所属材料作来源
        self.assertEqual(self.detail_row("B02")["source"], "Y｜营业执照 bizlicUrl｜无分隔")
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin="{not json")
        self.assertNotEqual(rc, 0)
        self.assertIn("不是合法 JSON", out)

    def test_new_rule_keys_are_reported_and_keys_still_close(self):
        self.init()
        run(self.ws, "detail.py", "fill", "--rid", RID, stdin=read("fill_spec.json"))
        # 规则新增两个引用：一个定义里有、映射表里没有（应报 UNMAPPED）；一个定义里没有（应进 notFoundInDefinition）；键数仍闭合
        with open(os.path.join(self.ws, "rules.json"), encoding="utf-8") as f:
            rules = json.load(f)
        rules["data"].append({"ruleId": "RULE-NEW-001", "label": "新规则1", "comment": "x", "condition": "AdmissionDoc.doc_id IS EMPTY"})
        rules["data"].append({"ruleId": "RULE-NEW-002", "label": "新规则2", "comment": "x", "condition": "Employer.brand_new_key = true"})
        with open(os.path.join(self.ws, "rules.json"), "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False)
        rc, out = run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rules.json", "--props", "props.json", stdin=read("map_spec.json"))
        self.assertEqual(rc, 0, out)
        self.assertIn("UNDECIDED 1 个规则引用键", out)
        self.assertIn("AdmissionDoc.doc_id", out)
        self.assertIn("keys: N=156 M=9 L=1 K=146", out)
        self.assertIn("validate: OK", out)
    def build(self, stdin=""):
        return run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rules.json", "--props", "props.json", stdin=stdin)

    def test_derived_attribute_needs_value_then_accepts_set(self):
        """多条明细共同推出的属性：先 NEED_VALUE（保持 unfilled），模型用 set 提交后进 entities 和 input。映射由模型按含义提交，不查对照表。"""
        self.init()
        run(self.ws, "detail.py", "fill", "--rid", RID, stdin=read("fill_spec.json"))
        spec = json.loads(read("map_spec.json"))
        spec["map"]["Employer.has_independent_employment_status"] = ["B17", "B18", "B19"]
        rc, out = self.build(json.dumps(spec, ensure_ascii=False))       # 同一个键既在 map 又在 skip：自相矛盾，直接报错而不是悄悄选一个
        self.assertNotEqual(rc, 0)
        self.assertIn("既在 map 又在 skip", out)
        spec["skip"]["R10"].remove("Employer.has_independent_employment_status")
        rc, out = self.build(json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertIn("NEED_VALUE", out)
        self.assertIn("Employer.has_independent_employment_status", out)
        self.assertNotIn('"has_independent_employment_status"', out.split("INPUT ")[1].split("\nNOTES")[0])
        sets = {"set": {"Employer.has_independent_employment_status": [True, "派生:B17,B18,B19｜有限责任公司，非分公司、非合伙"]}}
        rc, out = self.build(json.dumps(sets, ensure_ascii=False))             # 映射已保存，这次只补 set
        self.assertEqual(rc, 0, out)
        self.assertNotIn("NEED_VALUE", out)
        self.assertIn('"has_independent_employment_status":true', out)
        self.assertIn("validate: OK", out)
        bad = {"set": {"Employer.has_independent_employment_status": [True, "没有派生前缀"]}}
        rc, out = self.build(json.dumps(bad, ensure_ascii=False))
        self.assertNotEqual(rc, 0)

    # ───── v28：对应 v27 三次 trace（am3/am4/am5）暴露的问题 ─────

    def test_init_rejects_rules_file_passed_as_biz(self):
        """am4：--biz 误传规则文件，v27 静默接受，工商只填 14 条"""
        rc, out = run(self.ws, "detail.py", "init", "--biz", "rules.json", "--rules", "rules.json", stdin=read("init_spec.json"))
        self.assertNotEqual(rc, 0)
        self.assertIn("规则/属性文件，不是工商返回", out)

    def test_init_accepts_comma_joined_biz_paths(self):
        """am3/am5：三个路径用逗号拼成一项，v27 报“文件读不了”，J 组全部 N R07"""
        rc, out = run(self.ws, "detail.py", "init", "--biz", "biz_D.txt,biz_B.txt,biz_T.txt", "--rules", "rules.json", stdin=read("init_spec.json"))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("读不了", out)
        self.assertIn("工商接口读到：B、D、T", out)

    def test_fill_strips_yn_prefix_and_keeps_good_rows(self):
        """am4 被拒 4 次、am5 被拒 7 次：模型写 N｜R10｜… 而校验要 R10｜…"""
        self.init()
        spec = {"rows": [["B09", None, "N｜R10｜无完整敏感行业分类口径，本流程不填"], ["B02", "有限责任公司", "Y｜营业执照 bizlicUrl p1 类型栏｜有限责任公司"],
                         ["B23", None, "没看清"]]}
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 1)
        self.assertNotIn("REJECT B09", out)
        self.assertNotIn("REJECT B02", out)
        self.assertIn("REJECT B23", out)
        self.assertIn("如「R10｜无业务判断口径」", out)
        self.assertIn("其余 2 行已写入", out)
        by = {x["id"]: x for x in self.detail()["items"]}
        self.assertEqual(by["B09"]["source"], "N｜R10｜无完整敏感行业分类口径，本流程不填")
        self.assertEqual(by["B02"]["source"], "Y｜营业执照 bizlicUrl p1 类型栏｜有限责任公司")

    def test_show_marks_null_and_status(self):
        self.init()
        rc, out = run(self.ws, "detail.py", "show", "--rid", RID)
        self.assertEqual(rc, 0)
        self.assertNotIn("|None|", out)
        self.assertIn("|(空)|", out)

    def test_digest_commands_and_result_buckets(self):
        rc, out = run(self.ws, "combine.py", "rules", "--rules", "rules.json")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"共 \d+ 条规则")
        rc, out = run(self.ws, "combine.py", "rules", "--rules", "rules.json", "--grep", "founded_months")
        self.assertIn("Employer.founded_months", out)
        rc, out = run(self.ws, "combine.py", "props", "--props", "props.json")
        self.assertIn("Employer(", out)
        # 真实引擎返回（v27 am4：199 条 = 2 true + 8 false + 189 skip；am3：17 条 true/false）
        fxd = os.path.join(HERE, "fixtures", "v27_trace_am3_am4")
        for name, want in (("engine_run_am4.json", "已判定=10（命中 T=2，未命中 F=8 U=0）  skip=189"), ("engine_run_am3.json", "已判定=17（命中 T=2，未命中 F=15 U=0）  skip=182")):
            shutil.copy(os.path.join(fxd, name), self.ws)
            rc, out = run(self.ws, "combine.py", "result", "--file", name)
            self.assertEqual(rc, 0, out)
            self.assertIn(want, out)
            self.assertNotIn("Request reference", out)  # 网关页脚不影响解析
        # 非 AND 连接/属性不存在 → U 桶
        u = {"data": {"ruleCheckResult": "fail", "ruleCheckList": [
            {"ruleId": "X1", "ruleName": "n", "result": "false", "expression": "A.a = 1 OR A.b = 2", "reason": "A.a 属性不存在 或 不满足 A.b = 2"},
            {"ruleId": "X2", "ruleName": "n", "result": "false", "expression": "A.a = 1 AND A.b = 2", "reason": "A.a 属性不存在 或 不满足 A.b = 2"},
            {"ruleId": "X3", "ruleName": "n", "result": "false", "expression": "A.a = 1 AND A.b = 2", "reason": "A.a 属性不存在"},
            {"ruleId": "X4", "ruleName": "n", "result": "false", "expression": ["A.a = 1"], "reason": "A.a 属性不存在"}]}}
        open(os.path.join(self.ws, "u.json"), "w", encoding="utf-8").write(json.dumps(u, ensure_ascii=False) + "\nRequest reference: wc-1")
        rc, out = run(self.ws, "combine.py", "result", "--file", "u.json")
        self.assertIn("命中 T=0，未命中 F=1 U=3", out)
        self.assertNotIn("X2", out)                     # v32：未命中只计数，不列出

    # ───── v35：补充材料不再按 H 编号写死，清单插入/改号后仍按名称归组 ─────

    def _renumbered_catalog(self, mutate):
        """复制 catalog skill 到临时目录，改清单后用那份 detail.py 跑 init；返回 (输出, 明细 items)。"""
        cat = os.path.join(self.ws, "cat")
        shutil.copytree(os.path.dirname(SCRIPTS), cat, ignore=shutil.ignore_patterns("__pycache__"))
        jp = os.path.join(cat, "extract-items-checked.json")
        items = json.load(open(jp, encoding="utf-8"))
        mutate(items)
        json.dump(items, open(jp, "w", encoding="utf-8"), ensure_ascii=False)
        spec = json.loads(read("init_spec.json"))
        for k in ("noTaxCertSbUrl", "vatTaxCertUrl", "onlinePresenceUrl"):
            spec["request"].pop(k, None)
        r = subprocess.run([sys.executable, "-I", os.path.join(cat, "scripts", "detail.py"), "init", "--biz", "biz_D.txt", "biz_B.txt",
                            "biz_T.txt", "--rules", "rules.json"], cwd=self.ws, input=json.dumps(spec, ensure_ascii=False),
                           capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, timeout=30)
        d = json.load(open(os.path.join(self.ws, "work", RID, "input-extract-detail.json"), encoding="utf-8"))
        return r.stdout + r.stderr, {i["id"]: i for i in d["items"]}

    def test_v35_supplement_groups_follow_names_not_h_numbers(self):
        """三类证明（社保/完税/无欠税）是同一个请求参数：没提供时按名称整组 N R01；官网两条换了编号也要对得上。"""
        def mutate(items):
            ren = {"H34": "H90", "H35": "H91"}                 # 官网两条换成与原来 H22/H23 毫无关系的编号
            for it in items:
                it["id"] = ren.get(it["id"], it["id"])
        out, it = self._renumbered_catalog(mutate)
        self.assertNotIn("WARN 清单与脚本", out)
        tax = [i for i in it.values() if i["name"].startswith(("社保证明", "完税证明", "无欠税证明"))]
        self.assertEqual(len(tax), 18)
        for i in tax:
            self.assertTrue(i["source"].startswith("N｜R01｜"), i)
        for k in ("H90", "H91"):
            self.assertTrue(it[k]["source"].startswith("N｜R01｜") and "onlinePresenceUrl" in it[k]["source"], it[k])
        self.assertTrue(all(i["source"].startswith("N｜R01｜") for i in it.values() if i["name"].startswith(("增值税专用发票", "上下游合同"))))

    def test_v35_inserted_item_in_supplement_is_grouped_by_name(self):
        """清单在补充材料里再插一条「无欠税证明…」：自动并入该组，不需要改脚本。"""
        def mutate(items):
            pos = next(n for n, x in enumerate(items) if x["id"] == "H33") + 1
            items.insert(pos, {"id": "H99", "group": "补充材料", "name": "无欠税证明开具机关", "desc": "原文"})
        out, it = self._renumbered_catalog(mutate)
        self.assertTrue(it["H99"]["source"].startswith("N｜R01｜"), it["H99"])

    def test_v35_warns_when_script_referenced_id_no_longer_matches(self):
        def mutate(items):
            for x in items:
                if x["id"] == "B05":
                    x["id"] = "B99"
        out, _ = self._renumbered_catalog(mutate)
        self.assertIn("B05 在清单里不存在", out)

    def test_v35_current_catalog_matches_all_anchors(self):
        sys.path.insert(0, SCRIPTS)
        try:
            import importlib
            dt = importlib.import_module("detail")
            self.assertEqual(dt.check_anchors(dt.load_items()), [])
        finally:
            sys.path.remove(SCRIPTS)

    # ───── v29：派生行随依据重算；工商与原件识别不一致 → 回看原件二次识别 ─────

    def ready(self):
        self.init()
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=read("fill_spec.json"))
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS", out)

    def force(self, rows):
        return run(self.ws, "detail.py", "fill", "--rid", RID, "--force", stdin=json.dumps({"rows": rows}, ensure_ascii=False))

    def recheck(self, rows):
        return run(self.ws, "detail.py", "recheck", "--rid", RID, stdin=json.dumps({"rows": rows}, ensure_ascii=False))

    def items(self):
        return {i["id"]: i for i in self.detail()["items"]}

    MISREAD = "上海修匀软件开发有限公同"          # 形近字：「责任」被识成「公同」之类的误识别
    B01_SRC = "营业执照 bizlicUrl p1 名称栏｜名称 "

    def misread(self, value=None):
        """模拟首次识别把名称读错：B01 与依赖 B01 的 H17/H23 一并提交（真实流程里它们同一次 fill 提交）。"""
        v = value or self.MISREAD
        return self.force([["B01", v, self.B01_SRC + v],
                           ["H17", "false", "派生:H16,B01｜社保证明单位名称与 B01 不同"],
                           ["H23", "false", "派生:H22,B01｜完税证明纳税人名称与 B01 不同"]])

    def test_v29_derived_rows_follow_their_sources(self):
        """v28 缺陷：fill --force 改了源字段，已写好的派生行（B15/B16/J34）不会变，删值后还留着旧结果。"""
        self.ready()
        rc, out = self.force([["B04", "2024-12-06", "营业执照 bizlicUrl p1 成立日期栏｜成立日期 2024年12月06日"]])
        it = self.items()
        self.assertEqual(it["B16"]["value"], "22")                       # 基准日 11-05 的日 < 06 → 再减 1（v28 仍是 23）
        self.assertIn("成立日期", it["J34"]["value"])
        self.assertTrue(it["J34"]["value"].startswith("不一致："))
        self.assertTrue(any("工商与执照不一致" in c for c in self.detail()["notes"]["conflicts"]))
        self.assertIn("RECHECK", out)
        self.assertNotIn("PASS", out)
        self.force([["B04", "2024-12-03", "营业执照 bizlicUrl p1 成立日期栏｜成立日期 2024年12月03日"]])
        it = self.items()
        self.assertEqual((it["B16"]["value"], it["J34"]["value"]), ("23", "无不一致"))
        self.assertFalse(any("工商与执照不一致" in c for c in self.detail()["notes"]["conflicts"]))   # 旧冲突不残留
        # 审核 A 退回要求删值：依赖它的派生行必须变 N R12，且不能带着旧结果往下走
        rc, out = self.force([["B04", None, "R06｜日期栏看不清，审核 A 要求删除"]])
        it = self.items()
        self.assertEqual(it["B16"]["source"], "N｜R12｜缺 B04")
        self.assertIsNone(it["B16"]["value"])
        self.assertTrue(it["J34"]["source"].startswith("N｜R12｜"))

    def test_v29_name_change_flows_into_B15_and_J34(self):
        self.ready()
        self.misread()
        it = self.items()
        self.assertEqual(it["B15"]["value"], "false")                    # v28 仍是 true
        self.assertIn("名称", it["J34"]["value"])

    def test_v29_mismatch_blocks_build_until_rechecked(self):
        self.ready()
        rc, out = self.misread()
        self.assertIn("RECHECK", out)
        self.assertIn("RECHECK_ITEM B01|名称|首次识别=" + self.MISREAD, out)
        self.assertNotIn("PASS", out)
        rc, out = run(self.ws, "detail.py", "compare", "--rid", RID)
        self.assertEqual(rc, 3, out)
        rc, out = run(self.ws, "detail.py", "finish", "--rid", RID)
        self.assertEqual(rc, 3, out)
        rc, out = run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rules.json", "--props", "props.json")
        self.assertEqual(rc, 2, out)
        self.assertIn("复核门禁", out)

    def test_v29_recheck_confirms_difference_keeps_original_value(self):
        self.ready()
        self.misread()
        rc, out = self.recheck([["B01", self.MISREAD, self.B01_SRC + self.MISREAD]])
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS", out)
        it = self.items()
        self.assertEqual(it["B01"]["value"], self.MISREAD)                # 保留原件识别值，不用工商值覆盖
        self.assertNotIn("STALE", out)                                    # 值没变，H17/H23 仍有效
        self.assertIn("复核：二次识别", it["B01"]["source"])
        self.assertIn("确认不一致", it["B01"]["source"])
        self.assertIn("【已二次识别确认】", it["J34"]["value"])
        self.assertIn("复核记录：B01=确认不一致", it["J34"]["source"])
        conflicts = self.detail()["notes"]["conflicts"]
        self.assertTrue(any("工商与执照不一致" in c and "已二次识别确认" in c for c in conflicts), conflicts)
        rc, out = self.build(read("map_spec.json"))
        self.assertEqual(rc, 0, out)
        self.assertIn("validate: OK", out)
        rc, out = self.recheck([["B01", self.MISREAD, self.B01_SRC + self.MISREAD]])      # 每项只复核一次
        self.assertEqual(rc, 1)
        self.assertIn("已经复核过一次", out)

    def test_v29_recheck_corrects_a_first_misread(self):
        self.ready()
        right = self.items()["B01"]["value"]
        self.misread()
        rc, out = self.recheck([["B01", right, self.B01_SRC + right]])
        self.assertEqual(rc, 0, out)
        it = self.items()
        self.assertEqual(it["B01"]["value"], right)
        self.assertIn("首次识别为「%s」有误" % self.MISREAD, it["B01"]["source"])
        self.assertEqual((it["J34"]["value"], it["B15"]["value"]), ("无不一致", "true"))
        conflicts = self.detail()["notes"]["conflicts"]
        self.assertFalse(any("工商与执照不一致" in c or "原件识别与工商不一致" in c for c in conflicts), conflicts)

    def test_v29_recheck_two_readings_disagree_or_unreadable_gives_N(self):
        self.ready()
        self.misread()
        third = "上海修匀软件开发有限责任公同"
        rc, out = self.recheck([["B01", third, self.B01_SRC + third]])
        self.assertEqual(rc, 0, out)
        it = self.items()
        self.assertIsNone(it["B01"]["value"])
        self.assertTrue(it["B01"]["source"].startswith("N｜R06｜两次识别不一致"))
        self.assertTrue(it["J34"]["source"].startswith("N｜R12｜缺 B01"))
        self.assertTrue(any("两次识别不一致" in c for c in self.detail()["notes"]["conflicts"]))
        self.assertTrue(any(x.startswith("营业执照.名称｜R06") for x in self.detail()["notes"]["unresolvedProperties"]))
        # 二次复核仍看不清
        self.ready_again()
        self.misread()
        rc, out = self.recheck([["B01", None, "R03｜名称栏被印章遮挡，二次仍无法确认"]])
        self.assertEqual(rc, 0, out)
        it = self.items()
        self.assertTrue(it["B01"]["source"].startswith("N｜R03｜首次识别为"))
        self.assertTrue(any("无法确认" in c for c in self.detail()["notes"]["conflicts"]))

    def ready_again(self):
        shutil.rmtree(os.path.join(self.ws, "work"), ignore_errors=True)
        self.ready()

    def test_v29_recheck_rejects_unneeded_or_bad_rows(self):
        self.ready()
        rc, out = self.recheck([["B03", "91310120MAE7HU839Y", "营业执照 p1 信用代码栏｜统一社会信用代码 91310120MAE7HU839Y"]])
        self.assertEqual(rc, 1)
        self.assertIn("无需复核", out)
        rc, out = self.recheck([["J01", "x", "a｜b"], ["B01", "x"]])
        self.assertIn("不在比对清单", out)
        self.assertIn("行格式应为", out)

    def test_v29_id_card_name_is_compared_with_registered_legal_person(self):
        """身份证姓名 C02 与工商法定代表人 J07 比对；不进 J34，只进 conflicts。"""
        self.ready()
        rc, out = self.force([["C02", "郭朋", "法人身份证 idCardUrl p1 姓名栏｜姓名 郭朋"]])
        self.assertIn("RECHECK_ITEM C02|", out)
        self.assertEqual(self.items()["J34"]["value"], "无不一致")
        rc, out = self.recheck([["C02", "郭朋", "法人身份证 idCardUrl p1 姓名栏｜姓名 郭朋"]])
        self.assertEqual(rc, 0, out)
        self.assertTrue(any("原件识别与工商不一致" in c and "C02=郭朋" in c and "已二次识别确认" in c for c in self.detail()["notes"]["conflicts"]))

    def test_v29_editing_a_rechecked_row_reopens_the_comparison(self):
        self.ready()
        self.misread()
        self.recheck([["B01", self.MISREAD, self.B01_SRC + self.MISREAD]])
        other = "上海修匀软件开发有限责仼公司"
        rc, out = self.misread(other)
        self.assertIn("RECHECK_ITEM B01|", out)                            # 值变了，之前的复核结论作废

    def test_v29_model_written_derived_rows_become_stale_when_their_basis_changes(self):
        """H17/H23 是模型自己写的「派生:H16,B01」行，脚本不能代算：依据 B01 变了就要求模型重判。"""
        self.ready()
        rc, out = self.force([["B01", self.MISREAD, self.B01_SRC + self.MISREAD]])      # 只改 B01，不重判 H17/H23
        self.assertIn("STALE", out)
        for i in ("H17", "H23"):
            self.assertIn(i, out.split("STALE", 1)[1].split("\n")[0])
        rc, out = self.force([["H17", "false", "派生:H16,B01｜社保证明单位名称与 B01 不同"],
                              ["H23", "false", "派生:H22,B01｜完税证明纳税人名称与 B01 不同"]])
        self.assertNotIn("STALE", out)

    # ───── v29：映射由模型按语义决定，脚本不写死任何属性名（am7：本体把 employer_name 改成 enterprise_name 后 v28 整条链路断了）─────

    def test_v29_no_map_prints_plan_and_exits_4(self):
        self.ready()
        rc, out = self.build()
        self.assertEqual(rc, 4, out)
        self.assertIn("PLAN", out)
        self.assertIn("NO_MAP", out)
        self.assertIn("A02｜企业名称 entpName", out)
        self.assertIn("Employer.founded_months｜", out)                       # 规则引用的键带 label
        self.assertIn("B16｜营业执照.成立月数", out)                              # 清单条目
        self.assertFalse(os.path.exists(os.path.join(self.ws, "work", RID, "input-combine.json")))
        rc, out = run(self.ws, "combine.py", "plan", "--rid", RID, "--rules", "rules.json", "--props", "props.json")
        self.assertEqual(rc, 0, out)
        self.assertIn("标识候选", out)

    def renamed(self):
        """把本体里的两个属性改名，规则、定义、模型提交的映射同步改名，模拟 am7。"""
        for f, pairs in (("rules.json", (("employer_name", "enterprise_name"), ("founded_months", "established_months"))),
                         ("props.json", (("employer_name", "enterprise_name"), ("founded_months", "established_months")))):
            fp = os.path.join(self.ws, f)
            t = open(fp, encoding="utf-8").read()
            for a, b in pairs:
                t = t.replace(a, b)
            open(fp, "w", encoding="utf-8").write(t)
        t = read("map_spec.json")
        for a, b in (("employer_name", "enterprise_name"), ("founded_months", "established_months")):
            t = t.replace(a, b)
        return t

    def test_v29_renamed_ontology_properties_still_assemble(self):
        """v28 在 am7 的失败：定义返回 enterprise_name，脚本仍强制要求 employer_name；映射表里没有 established_months。"""
        self.ready()
        spec = self.renamed()
        rc, out = self.build(spec)
        self.assertEqual(rc, 0, out)
        self.assertIn("validate: OK", out)
        inp = json.loads(out.split("INPUT ", 1)[1].split("\n", 1)[0])
        self.assertEqual(inp["Employer"]["enterprise_name"], "上海修匀软件开发有限责任公司")
        self.assertEqual(inp["Employer"]["established_months"], 23)
        self.assertNotIn("employer_name", inp["Employer"])
        self.assertNotIn("founded_months", inp["Employer"])
        self.assertEqual(inp["Employer"]["employer_id"], "2114985936972623872001")     # 标识仍是字符串

    def test_v29_undecided_and_ignored_keys_are_reported(self):
        self.ready()
        spec = json.loads(read("map_spec.json"))
        spec["skip"]["R14"] = [k for k in spec["skip"]["R14"] if k != "Employer.conclusion_changed" and not k.endswith("admission_conclusion")][:-1]
        dropped = [k for k in json.loads(read("map_spec.json"))["skip"]["R14"] if k not in spec["skip"]["R14"]]
        spec["map"]["Employer.not_referenced_anywhere"] = ["B01"]
        rc, out = self.build(json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertIn("UNDECIDED", out)
        for k in dropped:
            self.assertIn(k, out)
        self.assertIn("IGNORED", out)
        self.assertIn("Employer.not_referenced_anywhere", out)
        self.assertNotIn("not_referenced_anywhere", out.split("INPUT ", 1)[1].split("\n", 1)[0])

    def test_v29_map_entries_are_validated(self):
        self.ready()
        rc, out = self.build(json.dumps({"map": {"Employer.founded_months": ["ZZ9"]}}))
        self.assertNotEqual(rc, 0)
        self.assertIn("清单里没有的条目 ZZ9", out)
        rc, out = self.build(json.dumps({"map": {"founded_months": ["B16"]}}))
        self.assertNotEqual(rc, 0)
        self.assertIn("对象.属性", out)
        rc, out = self.build(json.dumps({"skip": {"R99": ["Employer.x"]}}))
        self.assertNotEqual(rc, 0)
        rc, out = self.build(json.dumps({"map": {"Employer.founded_months": "B16"}}))
        self.assertNotEqual(rc, 0)

    def test_v29_saved_map_is_reused_and_edits_flow_through(self):
        self.ready()
        rc, out = self.build(read("map_spec.json"))
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.ws, "work", RID, "key-map.json")))
        rc, out = self.force([["B04", "2024-12-06", "营业执照 bizlicUrl p1 成立日期栏｜成立日期 2024年12月06日"]])
        self.assertIn("RECHECK", out)
        rc, out = self.recheck([["B04", "2024-12-06", "营业执照 bizlicUrl p1 成立日期栏｜成立日期 2024年12月06日"]])
        self.assertEqual(rc, 0, out)
        rc, out = self.build()                                                        # 不再提交映射，沿用已保存的
        self.assertEqual(rc, 0, out)
        self.assertIn('"founded_months":22', out)                                     # 基准日 11-05 的日 < 06 → 再减 1
        rc, out = self.build(json.dumps({"map": {"Employer.founded_months": None}}))   # 值为 null = 删除该映射
        self.assertEqual(rc, 0, out)
        self.assertNotIn("founded_months", out.split("INPUT ", 1)[1].split("\n", 1)[0])

    # ───── v30（am8）/v41：枚举属性只能从选项里选（有 enum 用 enum，没有用 comment）；引擎点名要的入参键可补传 ─────

    def enum_ws(self):
        """在 v25 夹具上加一个“枚举”属性和引用它的规则：Employer.lease_status，规则里只出现编码 expired。"""
        rp, pp = os.path.join(self.ws, "rules.json"), os.path.join(self.ws, "props.json")
        rules = json.JSONDecoder().raw_decode(open(rp, encoding="utf-8").read().lstrip())[0]
        rules["data"].append({"ruleId": "RULE-ENUM-1", "label": "租期已过", "comment": "x", "condition": "Employer.lease_status = expired"})
        rules["data"].append({"ruleId": "RULE-ENUM-2", "label": "账户类型", "comment": "x", "condition": "Employer.acct_kind IN {other, personal}"})
        json.dump(rules, open(rp, "w", encoding="utf-8"), ensure_ascii=False)
        props = json.JSONDecoder().raw_decode(open(pp, encoding="utf-8").read().lstrip())[0]
        emp = next(o for o in props["data"] if o["name"] == "Employer")
        emp["properties"].append({"name": "lease_status", "label": "房租合同租期状态", "comment": "枚举 LeaseStatus：在租期内、已过租期"})
        emp["properties"].append({"name": "acct_kind", "label": "账户类型", "comment": "枚举 AcctKind：基本户、一般户、其他账户"})
        json.dump(props, open(pp, "w", encoding="utf-8"), ensure_ascii=False)

    def test_v41_enum_value_must_be_an_option(self):
        """v41：没有 enum 时从 comment 选项里选；布尔、原文整句不是选项，不传。"""
        self.ready()
        self.enum_ws()
        spec = json.loads(read("map_spec.json"))
        spec["map"]["Employer.lease_status"] = ["G05"]            # G05 是布尔（在租期内）——am8 里模型就是这样传了 true
        spec["map"]["Employer.acct_kind"] = ["D02"]               # D02 是原件原文「基本存款账户」，不是 comment 选项
        rc, out = self.build(json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertIn("ENUM_DROPPED 2 个枚举属性的取值不是可选项", out)
        self.assertIn("Employer.lease_status｜枚举键只能选一个选项，取值「True」不是选项；可选：在租期内、已过租期", out)
        self.assertIn("Employer.acct_kind｜取值「基本存款账户」不在 comment 列出的选项里，不传；可选：基本户、一般户、其他账户", out)
        inp = json.loads(out.split("INPUT ", 1)[1].split("\n", 1)[0])
        self.assertNotIn("lease_status", inp["Employer"])
        self.assertNotIn("acct_kind", inp["Employer"])
        self.assertIn("validate: OK", out)                        # 键数仍闭合：被丢弃的键进 unfilled
        notes = json.loads(out.split("NOTES ", 1)[1].split("\n", 1)[0])
        self.assertTrue(any("lease_status" in x and "R10" in x for x in notes["unresolvedProperties"]), notes["unresolvedProperties"])

    def test_v41_enum_comment_option_or_rule_code_passes(self):
        self.ready()
        self.enum_ws()
        spec = json.loads(read("map_spec.json"))
        spec["map"]["Employer.lease_status"] = ["G05", "G10"]      # 多条共同推出：模型用 set 选项
        spec["map"]["Employer.acct_kind"] = ["D02", "D04"]
        rc, out = self.build(json.dumps(spec, ensure_ascii=False))
        self.assertIn("NEED_VALUE", out)
        sets = {"set": {"Employer.lease_status": ["expired", "派生:G05,G10｜已过租期｜置信度约90%｜租期止于基准日前"],     # 规则编码：兼容旧本体
                        "Employer.acct_kind": ["基本户", "派生:D02,D04｜基本户｜置信度约95%｜开户许可证写基本存款账户"]}}  # comment 选项
        rc, out = self.build(json.dumps(sets, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("ENUM_DROPPED", out)
        inp = json.loads(out.split("INPUT ", 1)[1].split("\n", 1)[0])
        self.assertEqual((inp["Employer"]["lease_status"], inp["Employer"]["acct_kind"]), ("expired", "基本户"))
        bad = {"set": {"Employer.acct_kind": ["基本存款账户", "派生:D02,D04｜原文"]}}                 # set 给的值同样要过校验
        rc, out = self.build(json.dumps(bad, ensure_ascii=False))
        self.assertIn("ENUM_DROPPED", out)
        self.assertIn("取值「基本存款账户」", out)

    def test_v41_enum_field_takes_priority_and_label_becomes_code(self):
        """v41：定义带 enum 时只认 enum；交中文选项自动换成编码；规则编码不在 enum 里时 plan 提示。"""
        self.ready()
        self.enum_ws()
        pp = os.path.join(self.ws, "props.json")
        props = json.load(open(pp, encoding="utf-8"))
        emp = next(o for o in props["data"] if o["name"] == "Employer")
        acct = next(p for p in emp["properties"] if p["name"] == "acct_kind")
        acct["enum"] = [{"basic": "基本户"}, {"general": "一般户"}, {"other": "其他账户"}]
        with open(pp, "w", encoding="utf-8") as f:
            json.dump(props, f, ensure_ascii=False)
        rc, out = run(self.ws, "combine.py", "plan", "--rid", RID, "--rules", "rules.json", "--props", "props.json")
        self.assertIn("ENUM 选项（来自 enum）：basic=基本户、general=一般户、other=其他账户", out)
        self.assertIn("ENUM_RULE_MISMATCH 规则条件比较的编码 personal 不在 enum 里", out)
        self.assertIn("ENUM 选项（来自 comment）：在租期内、已过租期", out)
        self.assertIn("ENUM_KEYS", out)
        spec = json.loads(read("map_spec.json"))
        spec["map"]["Employer.acct_kind"] = ["D02", "D04"]
        spec["set"] = {"Employer.acct_kind": ["其他账户", "派生:D02,D04｜其他账户｜置信度约70%｜账户性质栏写专用存款账户"]}
        rc, out = self.build(json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        inp = json.loads(out.split("INPUT ", 1)[1].split("\n", 1)[0])
        self.assertEqual(inp["Employer"]["acct_kind"], "other")
        for v in ("personal", "基本存款账户"):                       # 有 enum 时规则编码、原文都不算
            rc, out = self.build(json.dumps({"set": {"Employer.acct_kind": [v, "派生:D02,D04｜x"]}}, ensure_ascii=False))
            self.assertIn("取值「%s」不在 enum 里，不传；可选：basic=基本户、general=一般户、other=其他账户" % v, out)

    def test_v30_non_enum_properties_are_not_checked(self):
        """只有 comment 以「枚举」开头的属性才校验，布尔/数值/日期/文本不受影响（v25 真实数据的 input 回归已覆盖）。"""
        self.ready()
        rc, out = self.build(read("map_spec.json"))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("ENUM_DROPPED", out)

    def inp(self, out):
        return json.loads(out.split("INPUT ", 1)[1].split("\n", 1)[0])

    def test_v30_engine_named_key_can_be_added_with_force(self):
        """引擎点名要的、不在预设里的入参键：按它的报错补一条 force 映射，重建后进入 input（预设的四个标识不需要这一步）。"""
        self.ready()
        rc, out = self.build(read("map_spec.json"))
        self.assertNotIn("Foo", self.inp(out))
        rc, out = self.build(json.dumps({"map": {"Foo.bar_id": {"ids": ["A04"], "force": True}}}))   # 只补这一条，其余沿用已保存的映射
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.inp(out)["Foo"], {"bar_id": "2080184341491822592"})
        self.assertIn("固定标识 Foo.bar_id 本次属性定义未返回", out.split("NOTES ", 1)[1])
        self.assertIn("validate: OK", out)

    # ───── v30：四个标识预设（entpId/entpName/rqId/hrInstId），配置驱动 ─────

    def test_v30_preset_identifiers_are_passed_without_any_mapping(self):
        """用户预设：entpId→Employer.employer_id；entpName→Employer.enterprise_name；rqId→Demand.demand_id；hrInstId→LaborAgency.agency_id 与 Agency.agency_id。"""
        self.ready()
        spec = json.loads(read("map_spec.json"))
        spec["map"].pop("Employer.employer_name")                        # 模型什么标识都不映射
        rc, out = self.build(json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        inp = self.inp(out)
        self.assertEqual(inp["Employer"]["employer_id"], "2114985936972623872001")
        self.assertEqual(inp["Employer"]["enterprise_name"], self.items()["A02"]["value"])
        self.assertEqual(inp["Demand"]["demand_id"], "2899")
        self.assertEqual(inp["LaborAgency"]["agency_id"], "2080184341491822592")
        self.assertEqual(inp["Agency"]["agency_id"], "2080184341491822592")          # 引擎的 hrInst 步骤要它（am8）
        for o, k in (("Employer", "employer_id"), ("Employer", "enterprise_name"), ("Demand", "demand_id"), ("LaborAgency", "agency_id"), ("Agency", "agency_id")):
            self.assertIsInstance(inp[o][k], str)
        self.assertIn("PRESET_UNDEFINED", out)                                          # v25 的定义里没有 enterprise_name / Agency：仍照传，只打印
        self.assertIn("Employer.enterprise_name", out.split("PRESET_UNDEFINED", 1)[1].split("\n", 1)[0])
        self.assertNotIn("PRESET_UNDEFINED", out.split("NOTES ", 1)[1])                  # 不进 notes
        self.assertIn("validate: OK", out)

    def test_v30_preset_identifiers_cannot_be_swapped_or_skipped(self):
        """四个 ID 不可互换。"""
        self.ready()
        rc, out = self.build(json.dumps({"map": {"Employer.employer_id": ["A03"]}}))
        self.assertNotEqual(rc, 0)
        self.assertIn("预设的标识键，只能对应 A01，不能改映到 A03", out)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "work", RID, "key-map.json")))      # 被拒的提交不落盘，不毒化以后的 build
        rc, out = self.build(json.dumps({"map": {"Demand.demand_id": ["A04"]}}))
        self.assertNotEqual(rc, 0)
        self.assertIn("不可互换", out)
        rc, out = self.build(json.dumps({"skip": {"R10": ["Demand.demand_id"]}}))
        self.assertNotEqual(rc, 0)
        self.assertIn("不能 skip", out)
        rc, out = self.build(read("map_spec.json"))                                              # 前面三次都被拒，现在正常提交仍然成功
        self.assertEqual(rc, 0, out)
        rc, out = self.build(json.dumps({"map": {"Employer.employer_id": ["A01"]}}))             # 映成同一个条目：无害
        self.assertEqual(rc, 0, out)

    def test_v30_preset_follows_the_config_not_the_code(self):
        """本体把企业名称改回 employer_name：只改 combine_config.json，不改代码。"""
        cat = os.path.join(self.ws, "cat")
        shutil.copytree(os.path.dirname(SCRIPTS), cat, ignore=shutil.ignore_patterns("__pycache__", "*.zip"))
        cfg = os.path.join(cat, "scripts", "combine_config.json")
        c = json.load(open(cfg, encoding="utf-8"))
        c["fixedIdentifiers"]["A02"] = ["Employer.brand_new_name"]
        json.dump(c, open(cfg, "w", encoding="utf-8"), ensure_ascii=False)

        def runc(script, *args, stdin=""):
            r = subprocess.run([sys.executable, "-I", os.path.join(cat, "scripts", script), *args], cwd=self.ws, input=stdin, capture_output=True, text=True,
                               env={"LANG": "C.UTF-8"}, timeout=30)
            return r.returncode, r.stdout + r.stderr
        rc, out = runc("detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json", stdin=read("init_spec.json"))
        self.assertEqual(rc, 0, out)
        runc("detail.py", "fill", "--rid", RID, stdin=read("fill_spec.json"))
        rc, out = runc("combine.py", "build", "--rid", RID, "--rules", "rules.json", "--props", "props.json", stdin=read("map_spec.json"))
        self.assertEqual(rc, 0, out)
        emp = self.inp(out)["Employer"]
        self.assertIn("brand_new_name", emp)
        self.assertNotIn("enterprise_name", emp)

    def test_v30_preset_with_no_request_value_is_simply_omitted(self):
        """请求没给 rqId（A03 为 N）：不传 Demand.demand_id，也不报错、不进 unfilled。"""
        self.ready()
        rc, out = self.force([["A03", None, "R01｜请求没有需求 ID"]])
        rc, out = self.build(read("map_spec.json"))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("demand_id", self.inp(out).get("Demand", {}))
        self.assertIn("validate: OK", out)
        cb = json.load(open(os.path.join(self.ws, "work", RID, "input-combine.json"), encoding="utf-8"))
        self.assertNotIn("demand_id", cb["unfilled"].get("Demand", {}).get("R01", []))      # demand_id 若被规则引用才进 unfilled；这里规则没引用它

    # ───── v33：v32 真实运行（trace c5b30fc5 = am1、c8f64c2c = am2）暴露的问题 ─────

    def type_ws(self):
        """给规则加 am1 里被传错类型的三类键：布尔键、日期比较键、长期营业期限。"""
        rp, pp = os.path.join(self.ws, "rules.json"), os.path.join(self.ws, "props.json")
        rules = json.load(open(rp, encoding="utf-8"))
        rules["data"] += [
            {"ruleId": "RULE-T-1", "label": "主营可查询", "comment": "x", "condition": "Employer.main_business_queryable = false"},
            {"ruleId": "RULE-T-2", "label": "同业", "comment": "x", "condition": "Employer.peer_platform_merchant = true AND Employer.founded_months >= 1"},
            {"ruleId": "RULE-T-3", "label": "执照到期", "comment": "x",
             "condition": "AdmissionDoc.business_license_expiry_date IS NOT NULL AND AdmissionDoc.business_license_expiry_date <= Employer.admission_submitted_at"}]
        json.dump(rules, open(rp, "w", encoding="utf-8"), ensure_ascii=False)
        props = json.JSONDecoder().raw_decode(open(pp, encoding="utf-8").read().lstrip())[0]
        emp = next(o for o in props["data"] if o["name"] == "Employer")
        doc = next(o for o in props["data"] if o["name"] == "AdmissionDoc")
        emp["properties"] += [{"name": "main_business_queryable", "label": "主营业务可查询", "comment": None},
                              {"name": "peer_platform_merchant", "label": "是否同属互联网灵活用工平台", "comment": None},
                              {"name": "admission_submitted_at", "label": "入网申请提交时间", "comment": None}]
        doc["properties"] += [{"name": "business_license_expiry_date", "label": "营业执照到期日", "comment": None}]
        json.dump(props, open(pp, "w", encoding="utf-8"), ensure_ascii=False)

    def test_v33_text_is_not_passed_to_boolean_keys(self):
        """am1：main_business_queryable ← J16 经营范围全文、peer_platform_merchant ← 视频招牌文字，都进了 input。"""
        self.ready()
        self.type_ws()
        spec = json.loads(read("map_spec.json"))
        spec["map"].update({"Employer.main_business_queryable": ["B08"], "Employer.peer_platform_merchant": ["A07"],
                            "Employer.admission_submitted_at": ["A06"], "AdmissionDoc.business_license_expiry_date": ["B05"]})
        rc, out = self.build(json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertIn("TYPE_DROPPED", out)
        inp = self.inp(out)
        self.assertNotIn("main_business_queryable", inp["Employer"])
        self.assertNotIn("peer_platform_merchant", inp["Employer"])
        self.assertIn("Employer.main_business_queryable｜规则只拿它和 true/false 比较", out)
        self.assertIn("validate: OK", out)                          # 丢弃的键进 unfilled，键数仍闭合
        self.assertEqual(inp["Employer"]["admission_submitted_at"], "20261105")    # 日期比较两侧统一 yyyyMMdd
        self.assertIn("COMPARE_SUMMARY 12 项", out)

    def test_v33_long_term_expiry_is_not_passed_as_a_date(self):
        self.ready()
        self.type_ws()
        self.force([["B05", "2023年11月28日 至 长期", "营业执照 bizlicUrl p1 营业期限栏｜2023年11月28日 至 长期"]])
        spec = json.loads(read("map_spec.json"))
        spec["map"].update({"Employer.admission_submitted_at": ["A06"], "AdmissionDoc.business_license_expiry_date": ["B05"]})
        rc, out = self.build(json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("business_license_expiry_date", self.inp(out).get("AdmissionDoc", {}))
        self.assertIn("长期/无截止日", out)
        self.force([["B05", "2023年11月28日 至 2043年11月27日", "营业执照 bizlicUrl p1 营业期限栏｜2023年11月28日 至 2043年11月27日"]])
        self.recheck([["B05", "2023年11月28日 至 2043年11月27日", "营业执照 bizlicUrl p1 营业期限栏｜2023年11月28日 至 2043年11月27日"]])
        rc, out = self.build()
        self.assertEqual(self.inp(out)["AdmissionDoc"]["business_license_expiry_date"], "20431127")   # 到期日取截止日

    def test_v33_fill_autofixes_missing_bar_when_source_is_recognizable(self):
        """am1/am2 首次 fill 各被拒 18–19 行，多为「营业执照 bizlicUrl 为…」这种漏了「｜」的判断行。"""
        self.init()
        rows = [["B12", "false", "营业执照 bizlicUrl 为JPEG图片，非彩色扫描件"],
                ["B14", "true", "营业执照 bizlicUrl p1 各栏位文字清晰可辨"],
                ["B13", "false", "执照两张图均为灰度图像"]]
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=json.dumps({"rows": rows}, ensure_ascii=False))
        self.assertIn("AUTOFIX", out)
        self.assertNotIn("REJECT B13", out)                                       # v37：认不出来源就用该条所属材料
        self.assertEqual(self.detail_row("B13")["source"], "Y｜营业执照 bizlicUrl｜执照两张图均为灰度图像")
        items = {i["id"]: i for i in self.detail()["items"]}
        self.assertEqual(items["B12"]["source"], "Y｜营业执照 bizlicUrl｜为JPEG图片，非彩色扫描件")
        self.assertEqual(items["B14"]["source"], "Y｜营业执照 bizlicUrl p1｜各栏位文字清晰可辨")

    def test_v33_id_card_number_is_rejected(self):
        self.init()
        spec = {"materials": {"bizlicUrl": ["可读", "身份证正面：姓名张三，公民身份号码11010519491231002X"]},
                "rows": [["B06", "张三", "营业执照 bizlicUrl p1 法定代表人栏｜张三，号码11010519491231002X"],
                         ["D10", "1103023209000218647", "开户凭证 bankPermitUrl p1 账号栏｜1103023209000218647"]]}
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=json.dumps(spec, ensure_ascii=False))
        self.assertIn("REJECT B06 含身份证号码", out)
        self.assertIn("materials.bizlicUrl 的依据含身份证号码", out)
        self.assertNotIn("REJECT D10", out)                          # 19 位银行账号不误判

    def test_v33_stdin_with_extra_closing_brace_is_accepted(self):
        """am2：recheck 的 stdin 结尾多了一个 }，报错只提双引号，模型删掉原文括号重提，被判“两次识别不一致”。"""
        self.init()
        raw = json.dumps({"rows": [["B01", "某某公司", "营业执照 bizlicUrl p1 名称栏｜某某公司"]]}, ensure_ascii=False) + "}"
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=raw)
        self.assertIn("WARN stdin 结尾多了「}」", out)
        self.assertEqual({i["id"]: i for i in self.detail()["items"]}["B01"]["value"], "某某公司")
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin='{"rows":[["B01","x" "y"]]}')
        self.assertIn("出错位置附近", out)
        self.assertIn("不要改动 value/text 的原文", out)

    def test_v33_recheck_ignores_punctuation_differences(self):
        self.ready()
        self.force([["B08", "一般项目：软件开发；技术服务。（除依法须经批准的项目外，凭营业执照依法自主开展经营活动）",
                     "营业执照 bizlicUrl p1 经营范围栏｜一般项目：软件开发；技术服务。"]])
        rc, out = run(self.ws, "detail.py", "compare", "--rid", RID)
        self.assertIn("RECHECK_ITEM B08", out)
        rc, out = self.recheck([["B08", "一般项目：软件开发；技术服务。除依法须经批准的项目外，凭营业执照依法自主开展经营活动",
                                 "营业执照 bizlicUrl p1 经营范围栏｜二次识别同首次"]])
        self.assertIn("B08 经营范围：确认不一致", out)

    def test_v33_registered_capital_is_compared(self):
        """执照「人民币壹佰万元」vs 工商「500万元」（am1/am2 都没发现）；工商没写单位时不比较（v25 数据为「300.000000」）。"""
        self.ready()
        d = self.detail()
        items = {i["id"]: i for i in d["items"]}
        self.assertNotIn("B10", "".join(d["notes"]["conflicts"]))
        self.force([["J08", "注册资本500万元；币种人民币", "工商:B.registerCapital｜B.registerCapital=500万元"],
                    ["B10", "人民币壹佰万元", "营业执照 bizlicUrl p1 注册资本栏｜人民币壹佰万元"]])
        rc, out = run(self.ws, "detail.py", "compare", "--rid", RID)
        self.assertIn("B10|注册资本|不一致", out)

    def test_v33_id_card_fields_are_known_attachments(self):
        """v32：legalIdCard*Url 不在已知附件里 → 被当“未知附件” → 视频/补充材料整组都不会自动置 N（am2 没视频，E01–E10 仍要模型手填）。"""
        spec = json.loads(read("init_spec.json"))
        spec["request"]["legalIdCardFrontUrl"] = "http://x/08-legalIdCardFrontUrl.jpg"
        spec["request"]["legalIdCardBackUrl"] = "http://x/09-legalIdCardBackUrl.jpg"
        spec["request"].pop("vatTaxCertUrl")
        spec["warnings"] = []
        spec["request"]["officeVideoUrl"] = None
        rc, out = run(self.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json", stdin=json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        items = {i["id"]: i for i in self.detail()["items"]}
        self.assertEqual(items["E05"]["source"][:6], "N｜R01｜")
        self.assertEqual(items["H01"]["source"][:6], "N｜R01｜")
        self.assertEqual(items["H11"]["source"][:6], "N｜R01｜")
        self.assertEqual(items["C02"]["source"], "")                  # 身份证提供了：留给模型读
        self.assertIn("legalIdCardFrontUrl", out.split("MATERIALS", 1)[1].split("\n", 1)[0])


    # ───── 模型显式映射：夹具提供模型选择，脚本只组装和校验 ─────

    def build_v37(self, stdin="", props=None):
        """当前本体（v35-am1 的 PLAN 与 response-1105 的规则条件）下组装。"""
        V37 = os.path.join(HERE, "fixtures", "v37")
        shutil.copy(os.path.join(V37, "rules_v35.json"), self.ws)
        if props is None:
            shutil.copy(os.path.join(V37, "props_v35.json"), self.ws)
        else:
            json.dump(props, open(os.path.join(self.ws, "props_v35.json"), "w", encoding="utf-8"), ensure_ascii=False)
        # 测试夹具模拟模型显式提交，运行时不再提供业务属性默认表。
        spec = {"map": {"Employer.established_months": ["B16"],
                        "AdmissionDoc.scene_photo_count": ["F01"],
                        "AdmissionDoc.bank_account_name_consistent": ["D04"],
                        "AdmissionDoc.lease_contract_both_sealed": ["G09"]},
                "rules": {"drop": {"RULE-STAGE-002": "本用例只审核准入资料，签约齐全由签约环节核验",
                                   "RULE-STAGE-003": "本用例只审核准入资料，结算齐全由结算环节核验"}}}
        extra = json.loads(stdin) if stdin else {}
        for field in ("map", "set", "skip"):
            spec.setdefault(field, {}).update(extra.get(field) or {})
        for keys in spec["skip"].values():
            for key in keys:
                spec["map"].pop(key, None)
        for rid in (extra.get("rules") or {}).get("keep", []):
            spec["rules"]["drop"].pop(rid, None)
        spec["rules"].setdefault("keep", []).extend((extra.get("rules") or {}).get("keep", []))
        spec["rules"]["drop"].update((extra.get("rules") or {}).get("drop", {}))
        for field in ("fixedUnmapped", "toolIssues"):
            if field in extra:
                spec[field] = extra[field]
        return run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rules_v35.json", "--props", "props_v35.json", stdin=json.dumps(spec, ensure_ascii=False))








    # ───── v38：管理员信息与客户登记表（I 组）由脚本预填；用工场景取登记表说明，为空回退项目内容 ─────

    def ready_with(self, extra):
        spec = json.loads(read("init_spec.json"))
        spec["request"].update(extra)
        rc, out = run(self.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json", stdin=json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=read("fill_spec.json"))
        self.assertIn("PASS", out)
        return out


    def test_v39_new_items_are_derived(self):
        self.ready()
        it = self.items()
        self.assertNotIn("D03", it)
        self.assertEqual(it["B24"]["value"], it["B04"]["value"])            # 与 B04 同义，原样带出
        self.assertEqual(it["B25"]["value"], it["B05"]["value"])
        self.assertEqual(it["B26"]["value"], "false")                       # 经营范围不含劳务/灵活用工字样
        self.assertEqual(it["G05"]["value"], "true")                        # G04 开始 + G10 结束
        self.force([["B08", "劳务派遣；人力资源服务", "营业执照 bizlicUrl p1 经营范围栏｜劳务派遣；人力资源服务"]])
        self.assertEqual(self.items()["B26"]["value"], "true")

    def test_v39_lease_both_sealed_comes_from_G09(self):
        self.ready()
        self.force([["G09", "false", "租赁合同 leaseAgreementUrl p3 签章处｜仅出租方盖章，承租方签章处空白"]])
        rc, out = self.build_v37()
        self.assertIs(self.inp(out)["AdmissionDoc"]["lease_contract_both_sealed"], False)

    # ───── v41：inst-rc-rule-mcp 机构风控规则与 mcp_list_rule 一起传给脚本，引用的键照传 ─────

    INST = {"model": [{"companyName": "Employer.employer_name CONTAINS [修匀]"},
                      {"projectName": "Project.project_name CONTAINS [修匀]"}]}

    def inst_file(self):
        with open(os.path.join(self.ws, "inst.json"), "w", encoding="utf-8") as f:
            json.dump(self.INST, f, ensure_ascii=False)

    def test_v41_inst_rules_keys_are_passed_to_run_process(self):
        self.ready()
        self.inst_file()
        rules = ["--rules", "rules.json", "inst.json"]
        rc, out = run(self.ws, "combine.py", "plan", "--rid", RID, *rules, "--props", "props.json")
        self.assertEqual(rc, 0, out)
        self.assertIn("INST_KEYS 机构风控规则（inst-rc-rule-mcp）引用 2 个键：Employer.employer_name、Project.project_name", out)
        self.assertIn("Project.project_name｜projectName｜机构风控规则（inst-rc-rule-mcp）引用，本体定义未返回", out)   # 定义没有 Project：照样列出
        self.assertNotIn("规则引用但本次定义没有（自动记 notFoundInDefinition，不用处理）：Project.project_name", out)
        spec = json.loads(read("map_spec.json"))
        spec["map"]["Employer.employer_name"] = ["A02"]
        spec["map"]["Project.project_name"] = ["A08"]
        rc, out = run(self.ws, "combine.py", "build", "--rid", RID, *rules, "--props", "props.json", stdin=json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertIn("validate: OK", out)
        inp = json.loads(out.split("INPUT ", 1)[1].split("\n", 1)[0])
        self.assertEqual(inp["Employer"]["employer_name"], "上海修匀软件开发有限责任公司")
        self.assertEqual(inp["Project"]["project_name"], "内部管理系统开发调试")
        cb = json.load(open(os.path.join(self.ws, "work", RID, "input-combine.json"), encoding="utf-8"))
        self.assertEqual(cb["notFoundInDefinition"], [])
        self.assertIn("INST-companyName", [r["ruleId"] for r in cb["entities"]["Employer"]["properties"]["employer_name"]["rules"]])
        self.assertEqual([r["ruleId"] for r in cb["entities"]["Project"]["properties"]["project_name"]["rules"]], ["INST-projectName"])

    def test_v41_inst_keyword_feeds_name_hit(self):
        """机构规则的 [修匀] 写法也进企业名称关键词表（J33）。"""
        self.inst_file()
        rc, out = run(self.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json", "inst.json", stdin=read("init_spec.json"))
        self.assertEqual(rc, 0, out)
        j33 = self.items()["J33"]
        self.assertEqual(j33["value"], "true")
        self.assertIn("修匀", j33["source"])

    # ───── v41：71/80 号失败——伪造嫌疑类依据的断言字样，fill 回 PASS、build 回 CHECK，循环到超时 ─────

    def test_v41_assertions_stripped_even_without_source_bar_or_with_dun_hao(self):
        self.ready()
        rc, out = self.force([["B23", "false", "逐项看过：证号格式合规，地址为国内真实地址，未见卡通头像或明显AI生成痕迹"],   # 80 号：没写「｜」
                              ["F06", "false", "业务场景照片3张｜逐项看过：光影自然、人物姿态自然、屏幕内容合理、无AI生成痕迹、显示正常"]])  # 「、」分句
        self.assertEqual(rc, 0, out)
        it = self.items()
        self.assertEqual(it["B23"]["source"], "Y｜营业执照 bizlicUrl｜未见卡通头像或明显AI生成痕迹")
        self.assertNotIn("正常", it["F06"]["source"])
        self.assertIn("无AI生成痕迹", it["F06"]["source"])
        rc, out = self.build_v37()
        self.assertNotIn("CHECK B23", out)
        self.assertNotIn("CHECK F06", out)

    def test_v41_assertion_only_evidence_is_rejected_then_falls_back_to_r06(self):
        self.ready()
        before = self.items()["D12"]["source"]
        row = [["D12", "false", "开户许可证 bankPermitUrl p1｜账号格式合规"]]
        for n in (1, 2):
            rc, out = self.force(row)
            self.assertEqual(rc, 1, out)
            self.assertIn("REJECT D12 的依据每一句都带断言字样「合规」（「账号格式合规」）", out)
            self.assertEqual(self.items()["D12"]["source"], before)                  # 不写入
        rc, out = self.force(row)
        self.assertEqual(rc, 0, out)
        self.assertIn("ASSERT_FALLBACK", out)
        d12 = self.items()["D12"]
        self.assertIsNone(d12["value"])
        self.assertTrue(d12["source"].startswith("N｜R06｜依据连续 3 次"), d12["source"])
        rc, out = self.build_v37()
        self.assertNotIn("CHECK D12", out)

    # ───── v39：组装前先抛掉与客户准入无关的规则，它们条件里的字段不进 input-combine.json ─────

    def test_v39_rules_unrelated_to_admission_are_dropped_before_assembly(self):
        self.ready()
        rc, out = self.build_v37()
        self.assertEqual(rc, 0, out)
        self.assertIn("RULE_SCOPE 规则共 76 条：与客户准入相关、参与组装 74 条；判定与准入无关、已抛掉 2 条", out)
        self.assertIn("- RULE-STAGE-002｜", out)                      # 签约阶段资料齐全：只属签约，键没有准入资料对应
        self.assertIn("- RULE-STAGE-003｜", out)
        self.assertNotIn("- RULE-DOC-014｜", out)                     # 签约阶段，但开户名称一致由准入资料取得：保留
        self.assertNotIn("- RULE-INST-004｜", out)                    # 处置阶段，但规则名提“禁入”：保留
        cb = json.load(open(os.path.join(self.ws, "work", RID, "input-combine.json"), encoding="utf-8"))
        flat = json.dumps(cb["refKeys"]) + json.dumps(cb["unfilled"])
        self.assertNotIn("sign_stage_complete", flat)
        self.assertNotIn("settlement_stage_complete", flat)
        self.assertEqual({d["ruleId"] for d in cb["rulesDropped"]}, {"RULE-STAGE-002", "RULE-STAGE-003"})
        notes = json.loads(out.split("NOTES ", 1)[1].split("\n", 1)[0])
        self.assertFalse(any("sign_stage_complete" in x for x in notes["unresolvedProperties"]))
        # 模型改判：留下一条、再抛掉一条
        rc, out = self.build_v37(json.dumps({"rules": {"keep": ["RULE-STAGE-002"], "drop": {"RULE-INST-005": "规则版本管理，与客户资料无关"}}}, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertIn("- RULE-INST-005｜", out)
        self.assertNotIn("- RULE-STAGE-002｜", out)
        self.assertIn("validate: OK", out)
        rc, out = self.build_v37(json.dumps({"rules": {"drop": {"RULE-ADM-001": "x"}}}))
        self.assertIn("要写明与准入无关的原因", out)

    def test_v39_dropped_rules_do_not_count_in_the_conclusion(self):
        self.ready()
        self.build_v37()
        eng = {"code": 0, "data": {"ruleCheckResult": "x", "ruleCheckList": [
            {"ruleId": "RULE-STAGE-002", "ruleName": "签约阶段资料未齐不得签约", "result": "true", "riskMeasure": "拦截", "comment": "x｜适用阶段：签约", "expression": "AdmissionDoc.sign_stage_complete = false"},
            {"ruleId": "RULE-ADM-005", "ruleName": "成立不足3月", "result": "false", "riskMeasure": "拦截", "comment": "x｜适用阶段：准入", "expression": "Employer.established_months < 3", "reason": "不满足"}]}}
        json.dump(eng, open(os.path.join(self.ws, "eng.json"), "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = run(self.ws, "combine.py", "result", "--rid", RID, "--file", "eng.json")
        self.assertIn("OUT_OF_SCOPE 1 条规则在组装前已判定与客户准入无关，不计入结论（其中引擎给出命中 1 条）", out)
        self.assertIn("FUNNEL_LEVEL 通过｜", out)





    def test_v37_fill_trims_assertions_in_forgery_rows(self):
        self.ready()
        rc, out = self.force([["B23", "false", "营业执照 bizlicUrl p1 逐项核查｜信用代码18位；印章版式正常；整体真实合规；未见卡通头像"]])
        self.assertIn("TRIMMED", out)
        self.assertEqual(self.detail_row("B23")["source"], "Y｜营业执照 bizlicUrl p1 逐项核查｜信用代码18位；未见卡通头像")
        rc, out = self.force([["B23", "false", "营业执照 bizlicUrl p1｜真实合规"]])     # v41：去掉后没内容就当场退回，不写入、不留给 build 的 CHECK
        self.assertEqual(rc, 1, out)
        self.assertIn("REJECT B23", out)
        rc, out = self.build_v37()
        self.assertNotIn("CHECK B23", out)

    def test_v37_prefilled_resubmission_is_not_an_error(self):
        self.init()
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=json.dumps({"rows": [["F01", "3", "业务场景照片｜共3张"]]}, ensure_ascii=False))
        self.assertIn("SKIP F01", out)
        self.assertNotIn("REJECT", out)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
