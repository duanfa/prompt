"""python3 integration/test_scripts.py
RunSkillScript 的脚本（detail.py / combine.py）回归：用 v25 一次真实运行的请求、工商三接口返回、规则、属性定义，
按 RunSkillScript 的方式运行（python3 -I、空环境、工作区当 cwd、stdin 管道），核对：
  init 预填行数、fill 后无待填、派生行与那次模型手写的一致、combine 的 input 与那次一致、机械校验通过。"""
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "admission-v0-1-1-catalog", "scripts")
FX = os.path.join(HERE, "fixtures", "v25_run")
RID = "ontology_agent_job_43_115-am2"


def run(ws, script, *args, stdin="", _verify=True):
    if _verify and script == "combine.py" and args[:1] == ("build",):
        auto_verify(ws)
    r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, script), *args], cwd=ws, input=stdin,
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}, timeout=30)
    return r.returncode, r.stdout + r.stderr


def read(name):
    return open(os.path.join(FX, name), encoding="utf-8").read()


def auto_verify(ws, runner=None):
    """模拟模型对清单 verify 条目做语义校验：有值判 pass；空值先 fail 再取一次（仍为空），再判 fail。
    只用于与 verify 无关的旧用例，让它们照常走到 build；verify 本身的行为见 VerifyTests。"""
    runner = runner or (lambda script, *args, stdin="": run(ws, script, *args, stdin=stdin, _verify=False))
    out_all = ""
    for _ in range(3):
        rc, out = runner("detail.py", "show", "--rid", RID, "--pending")
        rows = []
        for ln in out.splitlines():
            if not ln.startswith("VERIFY_ITEM "):
                continue
            f = ln[len("VERIFY_ITEM "):].split("|")
            i, empty, last = f[0], "当前值=(空)" in f, "最后校验" in ln
            if not empty:
                rows.append([i, "pass", "回归夹具：值符合校验"])
            elif last:
                rows.append([i, "fail", "回归夹具：再取后仍为空"])
            else:
                rows.append([i, "fail", "回归夹具：当前值为空", None, "R03｜回归夹具：再取仍取不到"])
        if not rows:
            break
        rc, out = runner("detail.py", "verify", "--rid", RID, stdin=json.dumps({"rows": rows}, ensure_ascii=False))
        out_all += out
    return out_all


AUTO_FILL_WHY = "R03｜回归夹具未覆盖此条目（测试自动补齐）"


def fill_fixture(ws, runner=None):
    """按 v25 那次模型的填写记录 fill；清单后来新增、夹具里没有答案的行，再用 null + R03 补一轮。
    这样清单加条目不会让与它无关的用例失败（夹具只记录那次真实运行，不随清单逐条补）。
    清单 derive 声明的行由脚本派生，不在待填里，不会被这里补成 null。返回 (rc, 输出)。"""
    runner = runner or (lambda script, *args, stdin="": run(ws, script, *args, stdin=stdin))
    rc, out = runner("detail.py", "fill", "--rid", RID, stdin=read("fill_spec.json"))
    if rc != 0:
        return rc, out
    fp = os.path.join(ws, "work", RID, "input-extract-detail.json")
    with open(os.path.join(os.path.dirname(SCRIPTS), "extract-items-checked.json"), encoding="utf-8") as f:
        derived = {x["id"] for x in json.load(f) if x.get("derive")}
    with open(fp, encoding="utf-8") as f:
        pend = [x["id"] for x in json.load(f)["items"] if x["source"] == "" and x["id"] not in derived]
    if pend:
        rc, out2 = runner("detail.py", "fill", "--rid", RID, stdin=json.dumps({"rows": [[i, None, AUTO_FILL_WHY] for i in pend]}, ensure_ascii=False))
        out += out2
    if rc == 0:
        out += auto_verify(ws, runner)
    return rc, out


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
        catalog = json.load(open(os.path.join(os.path.dirname(SCRIPTS), "extract-items-checked.json"), encoding="utf-8"))
        self.assertEqual(list(items), [x["id"] for x in catalog])   # v42：条数和顺序以清单为准，不在测试里写死（清单加条目不改这里）
        pending = [i for i in items if items[i]["source"] == ""]
        self.assertTrue(pending, out)                    # 还有要模型读材料填的行
        self.assertEqual(items["J33"]["value"], "false")   # 规则关键词表逐词核对
        self.assertEqual(items["A06"]["value"], "2026-11-05")
        self.assertIn("基准日回退", d["notes"]["toolIssues"][0])
        self.assertEqual(items["E10"]["source"][:6], "N｜R01｜")        # URL 失效的视频整组 N R01
        self.assertIn("ATTACHMENT_DOWNLOAD_TIMEOUT", items["E01"]["source"])
        self.assertEqual(items["C02"]["source"][:6], "N｜R01｜")
        rc, out = run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rules.json", "--props", "props.json")
        self.assertEqual(rc, 2, out)                      # 还有待填行时拒绝组装
        rc, out = fill_fixture(self.ws)
        self.assertEqual(rc, 0, out)
        d = self.detail()
        items = {i["id"]: i for i in d["items"]}
        self.assertTrue(all(i["source"] for i in items.values()))
        # v42：夹具里有答案的行（v25 那次真实运行），fill 后与夹具一致；不再断言整张清单的 Y/N 条数
        for i, v, _ in json.loads(read("fill_spec.json"))["rows"]:
            self.assertEqual(items[i]["value"], v if v is None or isinstance(v, str) else json.dumps(v, ensure_ascii=False), i)
        self.assertEqual(items["G12"]["source"], "N｜R12｜缺 G11")    # 清单 derive：G11 夹具里没有 → 补成 null → G12 跟着 R12
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
        want["Employer"]["usage_scenario"] = "内部管理系统开发调试"                 # 2026-11-09 预设：用工场景必填，同机构 ID 一样取 projCont 原文
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
        fill_fixture(self.ws)
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
        fill_fixture(self.ws)
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
        for name, want in (("engine_run_am4.json", "已判定=10（命中 T=2，未命中 F=8 U=0）  skip=180"), ("engine_run_am3.json", "已判定=17（命中 T=2，未命中 F=15 U=0）  skip=173")):
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
        fp = os.path.join(self.ws, "work", RID, "input-extract-detail.json")
        if r.returncode != 0 or not os.path.isfile(fp):     # v42：清单 derive 声明有误时 init 直接失败，没有明细
            return r.stdout + r.stderr, {}
        d = json.load(open(fp, encoding="utf-8"))
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
        self.assertEqual(len(tax), 21)                         # 清单后来加了单位/纳税人名称三条（H17-1、H23-1、H29-1）
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
        out, it = self._renumbered_catalog(mutate)
        self.assertIn("B05 在清单里不存在", out)
        self.assertIn("B22 的 derive.from 引用了不存在的条目 B05", out)   # v42：清单 derive 引用断了 → init 失败，不悄悄留空
        self.assertEqual(it, {})

    def test_v35_current_catalog_matches_all_anchors(self):
        sys.path.insert(0, SCRIPTS)
        try:
            import importlib
            dt = importlib.import_module("detail")
            self.assertEqual(dt.check_anchors(dt.load_items()), [])
        finally:
            sys.path.remove(SCRIPTS)

    # ───── v42：清单 derive 声明的通用派生（加条目不用改脚本，夹具不全也不连锁失败） ─────

    def _flow_with_catalog(self, mutate):
        """复制 catalog skill、改清单后跑 init → fill（夹具 + 自动补齐）→ finish；返回 (init 输出, fill/finish 输出, 明细 items)。"""
        cat = os.path.join(self.ws, "cat")
        shutil.copytree(os.path.dirname(SCRIPTS), cat, ignore=shutil.ignore_patterns("__pycache__", "*.zip"))
        jp = os.path.join(cat, "extract-items-checked.json")
        with open(jp, encoding="utf-8") as f:
            items = json.load(f)
        mutate(items)
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False)

        def runc(script, *args, stdin=""):
            r = subprocess.run([sys.executable, "-I", os.path.join(cat, "scripts", script), *args], cwd=self.ws, input=stdin,
                               capture_output=True, text=True, env={"LANG": "C.UTF-8"}, timeout=30)
            return r.returncode, r.stdout + r.stderr
        rc, init_out = runc("detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json", stdin=read("init_spec.json"))
        if rc != 0:
            return init_out, "", {}
        derived = {x["id"] for x in items if x.get("derive")}
        rc, out = runc("detail.py", "fill", "--rid", RID, stdin=read("fill_spec.json"))
        pend = [x["id"] for x in self.detail()["items"] if x["source"] == "" and x["id"] not in derived]
        if pend:
            rc, o2 = runc("detail.py", "fill", "--rid", RID, stdin=json.dumps({"rows": [[i, None, AUTO_FILL_WHY] for i in pend]}, ensure_ascii=False))
            out += o2
        out += auto_verify(self.ws, runc)
        rc, o3 = runc("detail.py", "finish", "--rid", RID)
        return init_out, out + o3, self.items()

    def test_v42_g12_seal_name_is_derived_from_g11(self):
        """G12 按清单声明 same_name(G11, A02)，忽略末尾「合同专用章」等字样；G11 改了 G12 跟着重算。"""
        self.ready()
        rc, out = self.force([["G11", "上海修匀软件开发有限责任公司合同专用章", "租赁合同 leaseAgreementUrl p3 承租方盖章处｜上海修匀软件开发有限责任公司合同专用章"]])
        self.assertEqual(rc, 0, out)
        g12 = self.items()["G12"]
        self.assertEqual(g12["value"], "true", g12)
        self.assertIn("去掉末尾「合同专用章」后逐字一致", g12["source"])
        rc, out = self.force([["G11", "上海某某物业管理有限公司", "租赁合同 leaseAgreementUrl p3 承租方盖章处｜上海某某物业管理有限公司"]])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.items()["G12"]["value"], "false")

    def test_v42_new_catalog_item_with_derive_needs_no_script_change(self):
        """清单新增一条声明了 derive 的条目、一条普通条目：前者脚本自动派生、不进 PENDING；后者进 PENDING；全流程照常 PASS。"""
        def mutate(items):
            pos = next(n for n, x in enumerate(items) if x["id"] == "G12") + 1
            items.insert(pos, {"id": "G90", "group": "租赁合同", "name": "租赁合同.承租方与企业名称一致", "desc": "",
                               "derive": {"op": "same_name", "from": ["G02", "A02"]}})
            items.insert(pos + 1, {"id": "G91", "group": "租赁合同", "name": "租赁合同.出租方名称", "desc": "合同原文"})
        init_out, out, it = self._flow_with_catalog(mutate)
        self.assertIn("WAIT", init_out)
        self.assertIn("G90←G02,A02", init_out)
        self.assertNotIn("\nG90|", init_out)                        # 派生行不让模型读
        self.assertIn("\nG91|", init_out)                           # 普通新条目照常列给模型
        self.assertIn("PASS", out)
        self.assertTrue(it["G90"]["source"].startswith("Y｜派生:G02,A02｜"), it["G90"])
        self.assertEqual(it["G91"]["source"], "N｜" + AUTO_FILL_WHY)

    def test_v42_threshold_comes_from_the_catalog(self):
        """快到期阈值写在清单 withinDays 里：改清单即可，不改脚本。"""
        def mutate(items):
            next(x for x in items if x["id"] == "G07")["derive"]["withinDays"] = 100000
        _, out, it = self._flow_with_catalog(mutate)
        self.assertIn("PASS", out)
        self.assertEqual(it["G07"]["value"], "true", it["G07"])
        self.assertIn("阈值 100000 天", it["G07"]["source"])

    def test_v42_bad_derive_spec_fails_init_loudly(self):
        def mutate(items):
            next(x for x in items if x["id"] == "G12")["derive"] = {"op": "fuzzy_match", "from": ["G11", "A02"]}
            next(x for x in items if x["id"] == "G07")["derive"] = {"op": "days_to_expiry", "from": ["G10"]}
            next(x for x in items if x["id"] == "B15")["derive"] = {"op": "same_name", "from": ["B01", "Z99"]}
        init_out, _, it = self._flow_with_catalog(mutate)
        self.assertEqual(it, {})
        for want in ("G12 的 derive.op 须为", "G07 的 days_to_expiry 须给正整数 withinDays", "B15 的 derive.from 引用了不存在的条目 Z99"):
            self.assertIn(want, init_out)

    def test_v42_current_catalog_derive_specs_are_valid(self):
        sys.path.insert(0, SCRIPTS)
        try:
            import importlib
            dt = importlib.import_module("detail")
            self.assertEqual(dt.check_derive_specs(dt.load_items()), [])
        finally:
            sys.path.remove(SCRIPTS)

    # ───── v29：派生行随依据重算；工商与原件识别不一致 → 回看原件二次识别 ─────

    def ready(self):
        self.init()
        rc, out = fill_fixture(self.ws)
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
        self.assertIn("VERIFY_ITEM B01|", out)                            # 值改了（误识别），复核后还要按 verify 语义校验
        self.assertNotIn("PASS", out)
        self.assertIn("PASS", auto_verify(self.ws))
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

    def test_v01_empty_gate_hint_for_enum_key(self):
        """v0.1.1：v01-2 有 54 单因用工场景 skip 被“为空即拦截”规则命中；plan 对该键打印 EMPTY_GATE。"""
        self.ready()
        self.enum_ws()
        rp = os.path.join(self.ws, "rules.json")
        rules = json.load(open(rp, encoding="utf-8"))
        rules["data"].append({"ruleId": "RULE-GATE-X", "label": "租期状态为空", "comment": "x", "condition": "Employer.lease_status IS EMPTY", "riskMeasure": "拦截"})
        json.dump(rules, open(rp, "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = run(self.ws, "combine.py", "plan", "--rid", RID, "--rules", "rules.json", "--props", "props.json")
        self.assertIn("EMPTY_GATE RULE-GATE-X（租期状态为空，处置 拦截）在该键为空时命中", out)
        line = next(l for l in out.splitlines() if "EMPTY_GATE RULE-GATE-X" in l)
        self.assertNotIn("acct_kind", line)
        self.assertEqual(out.count("EMPTY_GATE RULE-GATE-X"), 1)

    def test_v41_enum_value_must_be_an_option(self):
        """v41：没有 enum 时从 comment 选项里选；布尔、原文整句不是选项，不传。"""
        self.ready()
        self.enum_ws()
        spec = json.loads(read("map_spec.json"))
        spec["map"]["Employer.lease_status"] = ["G05"]            # G05 是布尔（在租期内）——am8 里模型就是这样传了 true
        spec["map"]["Employer.acct_kind"] = ["D02"]               # D02 是原件原文「基本存款账户」：脚本不按关键词归一，由模型按语义用 set 选项
        spec["set"] = {"Employer.acct_kind": ["基本户", "派生:D02｜账户性质栏「基本存款账户」，语义即基本户"]}
        rc, out = self.build(json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)                              # uat：ENUM_DROPPED 只提醒、按 R10 进 unfilled，不拦门禁
        self.assertNotIn("CHECK ENUM_CHOICE", out)
        self.assertIn("GATE: READY", out)
        self.assertIn("ENUM_DROPPED 1 个枚举属性的取值不是可选项", out)
        self.assertIn("Employer.lease_status｜", out)
        inp = json.loads(out.split("INPUT ", 1)[1].split("\n", 1)[0])
        self.assertEqual(inp["Employer"]["acct_kind"], "基本户")
        self.assertNotIn("lease_status", inp["Employer"])
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
        bad = {"set": {"Employer.acct_kind": ["专用存款账户", "派生:D02,D04｜原文"]}}                 # set 给的值同样要过校验（同义表也对不上）
        rc, out = self.build(json.dumps(bad, ensure_ascii=False))
        self.assertIn("ENUM_DROPPED", out)
        self.assertIn("取值「专用存款账户」", out)

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
        for v in ("personal", "专用存款账户", "基本存款账户"):         # 有 enum 时规则编码、原文都不算；脚本不按关键词/同义表归一
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
        """本体把企业名称改回 employer_name：只改 run_process_required.json，不改代码。"""
        cat = os.path.join(self.ws, "cat")
        shutil.copytree(os.path.dirname(SCRIPTS), cat, ignore=shutil.ignore_patterns("__pycache__", "*.zip"))
        cfg = os.path.join(cat, "scripts", "run_process_required.json")
        c = json.load(open(cfg, encoding="utf-8"))
        next(r for r in c["required"] if r["item"] == "A02")["key"] = "Employer.brand_new_name"
        json.dump(c, open(cfg, "w", encoding="utf-8"), ensure_ascii=False)

        def runc(script, *args, stdin=""):
            r = subprocess.run([sys.executable, "-I", os.path.join(cat, "scripts", script), *args], cwd=self.ws, input=stdin, capture_output=True, text=True,
                               env={"LANG": "C.UTF-8"}, timeout=30)
            return r.returncode, r.stdout + r.stderr
        rc, out = runc("detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json", stdin=read("init_spec.json"))
        self.assertEqual(rc, 0, out)
        fill_fixture(self.ws, runc)
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

    def test_job216_missing_rows_bracket_is_saved_once_without_changing_evidence(self):
        self.init()
        raw = '{"rows":[["B01","某某有限公司","营业执照 bizlicUrl p1 名称栏｜某某有限公司"],"notes":{"conflicts":["保留原始冲突证据"],"toolIssues":[]}}'
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=raw)
        self.assertEqual(rc, 0, out)
        self.assertIn("STDIN_ROWS_CLOSED", out)
        row = self.detail_row("B01")
        self.assertEqual(row["value"], "某某有限公司")
        self.assertEqual(row["source"], "Y｜营业执照 bizlicUrl p1 名称栏｜某某有限公司")
        self.assertIn("保留原始冲突证据", self.detail()["notes"]["conflicts"])
        before = self.detail()
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID,
                      stdin='{"rows":[["B01","不应写入" "缺逗号"]]}')
        self.assertEqual(rc, 1, out)
        self.assertIn("STDIN_JSON_INVALID", out)
        self.assertEqual(self.detail(), before)

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
        rc, out = fill_fixture(self.ws)
        self.assertIn("PASS", out)
        return out


    def test_v39_new_items_are_derived(self):
        self.ready()
        it = self.items()
        self.assertNotIn("D03", it)
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


class ArgsGuardTests(unittest.TestCase):
    """模型把整条命令（含大量换行、逗号拼路径、init 多写 --rid）塞进 args 一项：脚本拆开照常执行；真错给可修正提示。"""

    def setUp(self):
        self.ws = tempfile.mkdtemp()
        for f in ("biz_D.txt", "biz_B.txt", "biz_T.txt", "rules.json", "props.json"):
            shutil.copy(os.path.join(FX, f), self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def items(self):
        return json.load(open(os.path.join(self.ws, "work", RID, "input-extract-detail.json"), encoding="utf-8"))["items"]

    def test_packed_init_runs_like_the_split_call(self):
        rc, out = run(self.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json",
                      stdin=read("init_spec.json"))
        self.assertEqual(rc, 0, out)
        want = self.items()
        shutil.rmtree(os.path.join(self.ws, "work"))
        packed = "\n" * 200 + "init --rid %s --biz biz_D.txt,biz_B.txt,biz_T.txt --rules rules.json" % RID + "\n" * 200
        rc, out = run(self.ws, "detail.py", packed, stdin=read("init_spec.json"))
        self.assertEqual(rc, 0, out)
        self.assertIn("WARN ARGS_REPACKED", out)
        self.assertNotIn("工商文件读不了", out)
        self.assertEqual(self.items(), want)

    def test_init_rid_must_match_ctx(self):
        rc, out = run(self.ws, "detail.py", "init", "--rid", "other", "--biz", "biz_D.txt", stdin=read("init_spec.json"))
        self.assertEqual(rc, 2, out)
        self.assertIn("init 不需要 --rid", out)

    def test_bad_args_print_a_fixable_hint(self):
        for script, args in (("detail.py", ["inti", "--biz", "a"]), ("detail.py", ["fill"]),
                             ("combine.py", ["build", "--rid"])):
            rc, out = run(self.ws, script, *args)
            self.assertEqual(rc, 2, out)
            self.assertIn("ERROR INVALID_SCRIPT_ARGS", out)
            self.assertIn("HINT 用法", out)
            self.assertIn("不要再试", out)


class V42FixTests(unittest.TestCase):
    """v42（v01-10-4 两组结果分析后）：枚举只认原值（不做同义归一）、ENUM_CHOICE 拦一次、上下游协议公司名称原文、完税证明按内容归组、租赁合同双方盖章分拆。"""

    def setUp(self):
        sys.path.insert(0, SCRIPTS)
        import importlib
        self.cb = importlib.import_module("combine")
        self.st = ScriptTests("test_v30_non_enum_properties_are_not_checked")
        self.st.setUp()

    def tearDown(self):
        self.st.tearDown()

    def test_enum_value_is_never_normalized_by_keywords(self):
        """枚举只接受与选项（编码或中文）完全一致的值。原文→选项是语义判断，由模型用 set 提交，脚本不按关键词/同义表归一：
        「公司不从事集资」「为客户提供理财产品推广服务」「营业期限至2030年到期」「即将到期」都曾被关键词归一误判。"""
        self.assertFalse(hasattr(self.cb, "enum_alias_pick"))
        st = {"enum": [{"active": "存续"}, {"expired": "已届满"}, {"revoked": "已注销"}]}
        cat = {"enum": [{"fundraising": "集资"}, {"wealth": "理财"}, {"general": "一般"}]}
        for pd, v in ((cat, "公司不从事集资"), (cat, "为客户提供理财产品推广服务"), (st, "营业期限至2030年到期"),
                      (st, "即将到期"), (st, "注销"), (st, "未注销"), (st, "在营(开业)"), (st, "已届满（营业期限）")):
            got, why = self.cb.enum_check("X.y", pd, v, [])
            self.assertEqual(got, v, v)                                  # 原值不变
            self.assertIn("不在 enum 里，不传", why or "", v)            # 进 ENUM_DROPPED / unfilled，不进 input

    def test_enum_check_accepts_only_exact_code_or_label(self):
        pd = {"enum": [{"active": "存续"}, {"expired": "已届满"}, {"revoked": "已注销"}]}
        self.assertEqual(self.cb.enum_check("AdmissionDoc.business_license_status", pd, "已注销", []), ("revoked", None))
        self.assertEqual(self.cb.enum_check("AdmissionDoc.business_license_status", pd, " revoked ", []), ("revoked", None))
        pd = {"comment": "枚举 BankAccountNature：基本户、非基本户"}
        self.assertEqual(self.cb.enum_check("AdmissionDoc.bank_account_nature", pd, "基本户", []), ("基本户", None))
        self.assertIsNotNone(self.cb.enum_check("AdmissionDoc.bank_account_nature", pd, "基本存款账户", [])[1])

    def test_contract_company_name_is_raw_and_match_is_derived(self):
        spec = json.loads(read("init_spec.json"))
        spec["request"]["upstreamDnstreamAgmtUrl"] = "http://x/10-upstreamDnstreamAgmtUrl.pdf"
        rc, out = run(self.st.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json",
                      stdin=json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertIn("\nH1-15|", out)                             # uat 清单没有 H1-14 名称原文条目：是否一致交给模型按协议读
        self.assertNotIn("H1-15←", out)
        rc, out = run(self.st.ws, "detail.py", "fill", "--rid", RID, stdin=json.dumps(
            {"rows": [["H1-15", "true", "上下游合同 upstreamDnstreamAgmtUrl p1 甲方栏｜甲方：上海修匀软件开发有限责任公司"]]}, ensure_ascii=False))
        it = {i["id"]: i for i in self.st.detail()["items"]}
        self.assertEqual(it["H1-15"]["value"], "true", it["H1-15"])
        self.assertTrue(it["H1-15"]["source"].startswith("Y｜上下游合同"), it["H1-15"])

    def test_lease_seal_split_rows_are_listed_for_model(self):
        init_out, _, _ = self.st._flow_with_catalog(lambda items: None)
        for i in ("G09", "G11"):                                   # uat 清单：双方盖章 G09、承租方章名 G11 由模型读
            self.assertIn("\n%s|" % i, init_out)

    def test_tax_group_not_absent_when_only_vat_field_has_file(self):
        spec = json.loads(read("init_spec.json"))
        spec["request"].pop("noTaxCertSbUrl")                       # 只有 vatTaxCertUrl（实测里面常是《税收完税证明》）
        rc, out = run(self.st.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json",
                      stdin=json.dumps(spec, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        items = {i["id"]: i for i in self.st.detail()["items"]}
        tax = [i for i in items.values() if i["name"].startswith("完税证明")]
        self.assertTrue(tax)
        self.assertTrue(all(i["source"] == "" for i in tax), [i["source"] for i in tax])   # 留给模型按标题读，不整组判未提供
        spec["request"].pop("vatTaxCertUrl")
        rc, out = run(self.st.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json",
                      stdin=json.dumps(spec, ensure_ascii=False))
        items = {i["id"]: i for i in self.st.detail()["items"]}
        self.assertTrue(all(i["source"].startswith("N｜R01｜") for i in items.values() if i["name"].startswith("完税证明")))


class VerifyTests(unittest.TestCase):
    """清单 verify：全部值取完后按语义校验，不符合再取一次；未校验不能 finish/build。"""
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        for f in ("biz_D.txt", "biz_B.txt", "biz_T.txt", "rules.json", "props.json"):
            shutil.copy(os.path.join(FX, f), self.ws)
        run(self.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json", stdin=read("init_spec.json"))
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=read("fill_spec.json"))
        fp = os.path.join(self.ws, "work", RID, "input-extract-detail.json")
        with open(os.path.join(os.path.dirname(SCRIPTS), "extract-items-checked.json"), encoding="utf-8") as f:
            derived = {x["id"] for x in json.load(f) if x.get("derive")}
        with open(fp, encoding="utf-8") as f:
            pend = [x["id"] for x in json.load(f)["items"] if x["source"] == "" and x["id"] not in derived]
        rc, self.fill_out = run(self.ws, "detail.py", "fill", "--rid", RID, stdin=json.dumps({"rows": [[i, None, AUTO_FILL_WHY] for i in pend]}, ensure_ascii=False))

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def verify(self, rows):
        return run(self.ws, "detail.py", "verify", "--rid", RID, stdin=json.dumps({"rows": rows}, ensure_ascii=False))

    def items(self):
        with open(os.path.join(self.ws, "work", RID, "input-extract-detail.json"), encoding="utf-8") as f:
            return {x["id"]: x for x in json.load(f)["items"]}

    def test_verify_items_listed_after_all_values_and_gate_blocks(self):
        self.assertIn("VERIFY_ITEM B01|", self.fill_out)
        self.assertNotIn("PASS", self.fill_out)
        rc, out = run(self.ws, "detail.py", "finish", "--rid", RID)
        self.assertEqual(rc, 3, out)
        rc, out = run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rules.json", "--props", "props.json", _verify=False)
        self.assertEqual(rc, 2, out)
        self.assertIn("VERIFY", out)

    def test_pass_all_then_finish_passes(self):
        rc, out = self.verify([[i, "pass", "栏位原文有值，符合不为空"] for i in ("B01", "B02", "B04", "B05")])
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS", out)
        rc, out = run(self.ws, "detail.py", "finish", "--rid", RID)
        self.assertEqual(rc, 0, out)
        rc, out = self.verify([["B01", "pass", "再交一次"]])
        self.assertEqual(rc, 1, out)
        self.assertIn("已校验过", out)

    def test_fail_reextracts_once_then_needs_reverify(self):
        self.verify([[i, "pass", "栏位原文有值，符合不为空"] for i in ("B01", "B02", "B05")])
        rc, out = self.verify([["B04", "fail", "取成了发证日期，不是成立日期栏", "2024-12-03", "营业执照 bizlicUrl p1 成立日期栏｜成立日期 2024年12月03日"]])
        self.assertEqual(rc, 0, out)
        self.assertIn("VERIFY_ITEM B04|", out)
        self.assertIn("最后校验", out)
        it = self.items()["B04"]
        self.assertEqual(it["value"], "2024-12-03")
        self.assertIn("已再取一次", it["source"])
        rc, out = self.verify([["B04", "fail", "还是不对", "2024-12-04", "营业执照｜x"]])     # 只能再取一次
        self.assertEqual(rc, 1, out)
        rc, out = self.verify([["B04", "fail", "再取后仍不是成立日期栏"]])
        self.assertEqual(rc, 0, out)
        it = self.items()["B04"]
        self.assertIsNone(it["value"])
        self.assertTrue(it["source"].startswith("N｜R06｜两次取值均不符合校验"), it["source"])
        self.assertIn("PASS", out)

    def test_empty_value_cannot_pass_non_empty_rule(self):
        run(self.ws, "detail.py", "fill", "--rid", RID, "--force", stdin=json.dumps({"rows": [["B02", None, "R03｜类型栏被印章遮挡"]]}, ensure_ascii=False))
        rc, out = self.verify([["B02", "pass", "看过了没问题"]])
        self.assertEqual(rc, 1, out)
        self.assertIn("不能判 pass", out)
        rc, out = self.verify([["B02", "fail", "类型栏为空，回看原件", "有限责任公司（自然人独资）", "营业执照 bizlicUrl p1 类型栏｜类型 有限责任公司（自然人独资）"]])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.items()["B02"]["value"], "有限责任公司（自然人独资）")

    def test_changing_a_verified_value_reopens_verify(self):
        self.verify([[i, "pass", "栏位原文有值，符合不为空"] for i in ("B01", "B02", "B04", "B05")])
        rc, out = run(self.ws, "detail.py", "fill", "--rid", RID, "--force", stdin=json.dumps({"rows": [["B05", "长期", "营业执照 bizlicUrl p1 营业期限栏｜营业期限 长期"]]}, ensure_ascii=False))
        self.assertIn("VERIFY_ITEM B05|", out)
        self.assertNotIn("VERIFY_ITEM B01|", out)

    def test_bad_catalog_verify_spec_fails_init(self):
        sys.path.insert(0, SCRIPTS)
        try:
            import importlib
            dt = importlib.import_module("detail")
            self.assertEqual(dt.check_verify_specs(dt.load_items()), [])
            self.assertTrue(dt.check_verify_specs([{"id": "X1", "verify": ""}]))
        finally:
            sys.path.remove(SCRIPTS)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
