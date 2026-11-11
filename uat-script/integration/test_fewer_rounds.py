"""python3 integration/test_fewer_rounds.py
v45（job_299-v11-9，12 分钟）：再减少模型轮数与上下文。
  1. build 抄错规则文件路径（mcp_list_rule_16120743 → …1610743）报文件不存在：build/validate 可省略 --rules/--props，路径不存在时沿用 plan 记下的。
  2. fill 每次重印全部 87 行待填：PENDING 只列本次这一份的 desc，其余在 LATER 行只给 ID。
  3. 每份材料后单独一轮 recheck：fill 可带 recheck 字段一起交（不需要复核的项忽略、不算错）。
  4. 视频/请求参数/工商各占一轮：不用看图的组并进第一批。"""
import json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_scripts as T  # noqa: E402
import test_material_progress as M  # noqa: E402

RID = T.RID


class FewerRoundsTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        for f in ("biz_D.txt", "biz_B.txt", "biz_T.txt", "rules.json", "props.json"):
            shutil.copy(os.path.join(T.FX, f), self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def init(self):
        return T.run(self.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json",
                     stdin=T.read("init_spec.json"))

    def items(self):
        with open(os.path.join(self.ws, "work", RID, "input-extract-detail.json"), encoding="utf-8") as f:
            return {x["id"]: x for x in json.load(f)["items"]}

    def state(self):
        with open(os.path.join(self.ws, "work", RID, ".detail-state.json"), encoding="utf-8") as f:
            return json.load(f)

    # ── 1 ──
    def test_build_reuses_plan_paths_when_omitted_or_mistyped(self):
        self.init()
        rc, out = T.fill_fixture(self.ws)
        self.assertEqual(rc, 0, out)
        rc, out = T.run(self.ws, "combine.py", "plan", "--rid", RID, "--rules", "rules.json", "--props", "props.json")
        self.assertEqual(rc, 0, out)
        spec = T.read("map_spec.json")
        rc, ok = T.run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rules.json", "--props", "props.json", stdin=spec)
        self.assertEqual(rc, 0, ok)
        rc, typo = T.run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rule.json", "--props", "props.json", stdin=spec)
        self.assertEqual(rc, 0, typo)
        self.assertIn("PATH_FIXED", typo)
        rc, bare = T.run(self.ws, "combine.py", "build", "--rid", RID, stdin=spec)
        self.assertEqual(rc, 0, bare)
        line = lambda o: next(ln for ln in o.splitlines() if ln.startswith("INPUT "))
        self.assertEqual(line(ok), line(typo))
        self.assertEqual(line(ok), line(bare))

    def test_build_without_plan_and_without_paths_explains(self):
        self.init()
        rc, out = T.run(self.ws, "combine.py", "build", "--rid", RID, stdin="{}", _verify=False)
        self.assertNotEqual(rc, 0)
        self.assertIn("先运行 combine.py plan", out)

    # ── 2 & 4 ──
    def test_first_batch_includes_no_read_groups_and_output_is_trimmed(self):
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        g, ids = M.next_material(out)
        self.assertTrue(g.startswith("营业执照"), g)
        for extra in ("请求参数", "工商"):
            self.assertIn(extra, g)
        self.assertIn("LATER ", out)
        pend_desc = [ln for ln in out.split("\nPENDING 待填", 1)[1].splitlines()[1:] if "|" in ln and not ln.startswith("LATER")]
        self.assertEqual(sorted(ln.split("|")[0] for ln in pend_desc), sorted(ids))
        rc, full = T.run(self.ws, "detail.py", "show", "--rid", RID, "--pending")
        self.assertNotIn("LATER ", full)                     # show --pending 仍给完整清单

    # ── 3 ──
    def test_recheck_rows_can_ride_along_with_fill(self):
        self.init()
        T.run(self.ws, "detail.py", "fill", "--rid", RID, stdin=T.read("fill_spec.json"))
        it = self.items()
        name = it["B01"]["value"]
        rows = [["B01", name, "营业执照 bizlicUrl p1 名称栏｜逐字：" + "/".join(name)],
                ["B03", it["B03"]["value"], "营业执照 bizlicUrl p1｜不需要复核也不算错"]]
        rc, out = T.run(self.ws, "detail.py", "fill", "--rid", RID,
                        stdin=json.dumps({"rows": [], "recheck": rows}, ensure_ascii=False))
        self.assertEqual(rc, 0, out)
        self.assertIn("复核结果：B01", out)
        self.assertIn("RECHECK_IGNORED", out)
        self.assertIn("B01", self.state()["rechecked"])
        self.assertNotIn("STDIN_UNKNOWN_KEY", out)

    def test_bad_recheck_row_in_fill_is_rejected_like_recheck(self):
        self.init()
        T.run(self.ws, "detail.py", "fill", "--rid", RID, stdin=T.read("fill_spec.json"))
        rc, out = T.run(self.ws, "detail.py", "fill", "--rid", RID,
                        stdin=json.dumps({"rows": [], "recheck": [["B01", "某名称", "没有逐字拆写"]]}, ensure_ascii=False))
        self.assertEqual(rc, 1, out)
        self.assertIn("REJECT recheck：", out)
        self.assertNotIn("B01", self.state()["rechecked"])


if __name__ == "__main__":
    unittest.main()
