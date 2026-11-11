"""python3 integration/test_material_progress.py
v44（job_299-v11-7，26 分钟）：平台只保留最近约 5 张图片，6 张图 + “fill 一次” → 模型循环重读。
detail.py 现在按材料分组打印 BY_MATERIAL / NEXT_MATERIAL，引导“读一份、fill 一份”。本测试核对：
  init 后第一个是营业执照；只 fill 营业执照这一组后，NEXT_MATERIAL 换成下一份材料、不再列营业执照；
  分批 fill 与一次 fill 的明细结果相同（分批不丢行）。"""
import json, os, re, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_scripts as T  # noqa: E402


def next_material(out):
    m = re.search(r"^NEXT_MATERIAL ([^｜\n]+)｜.*?本次 fill 只交这一组：([^｜\n]+)", out, re.M)
    return (m.group(1), m.group(2).split("、")) if m else (None, [])


def pending_ids(out):
    """PENDING 下列 desc 的本批行 + LATER 行里只给 ID 的其余行（v45 起不再一次列全）。"""
    lines = out.split("\nPENDING 待填", 1)[1].splitlines()[1:]
    ids = [ln.split("|")[0] for ln in lines if re.match(r"^[A-Z][0-9A-Z-]*\|", ln)]
    later = next((ln for ln in lines if ln.startswith("LATER ")), "")
    return ids + [i for i in later.split("：", 1)[-1].split("、") if i and later]


class MaterialProgressTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        for f in ("biz_D.txt", "biz_B.txt", "biz_T.txt", "rules.json", "props.json"):
            shutil.copy(os.path.join(T.FX, f), self.ws)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def init(self):
        return T.run(self.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json",
                     stdin=T.read("init_spec.json"))

    def fill(self, rows):
        return T.run(self.ws, "detail.py", "fill", "--rid", T.RID, stdin=json.dumps({"rows": rows}, ensure_ascii=False))

    def detail(self):
        return json.load(open(os.path.join(self.ws, "work", T.RID, "input-extract-detail.json"), encoding="utf-8"))

    def test_init_points_to_one_material_first(self):
        rc, out = self.init()
        self.assertEqual(rc, 0, out)
        self.assertIn("BY_MATERIAL", out)
        g, ids = next_material(out)
        self.assertEqual(g, "营业执照", out)
        self.assertTrue(ids and all(i.startswith("B") for i in ids), ids)
        self.assertIn("is offloaded", out)          # 告诉模型 offloaded 提示不是读取失败

    def test_after_filling_one_group_next_material_moves_on(self):
        rc, out = self.init()
        g, ids = next_material(out)
        rc, out = self.fill([[i, None, "R03｜回归夹具：只交营业执照这一组"] for i in ids])
        self.assertEqual(rc, 0, out)
        g2, ids2 = next_material(out)
        self.assertNotEqual(g2, "营业执照", out)
        self.assertTrue(g2, out)
        self.assertFalse(set(ids) & set(ids2))

    def test_video_group_says_no_read(self):
        rc, out = self.init()
        for _ in range(20):
            g, ids = next_material(out)
            if g is None or "办公场所视频" in g:
                break
            rc, out = self.fill([[i, None, "R03｜回归夹具"] for i in ids])
            self.assertEqual(rc, 0, out)
        if g and "办公场所视频" in g:
            line = next(ln for ln in out.splitlines() if ln.startswith("NEXT_MATERIAL"))
            self.assertIn("不要 Read 视频文件", line)
            self.assertNotIn("is offloaded", line)

    def test_batched_fill_equals_single_fill(self):
        rc, out = self.init()
        pend = pending_ids(out)            # 只交模型该填的行；WAIT 的派生行由脚本自己算
        rows = [[i, None, "R03｜回归夹具"] for i in pend]
        self.fill(rows)
        single = {x["id"]: (x["value"], x["source"]) for x in self.detail()["items"]}
        shutil.rmtree(os.path.join(self.ws, "work"))
        rc, out = self.init()
        for _ in range(20):
            g, ids = next_material(out)
            if not g:
                break
            rc, out = self.fill([r for r in rows if r[0] in ids])
            self.assertEqual(rc, 0, out)

        batched = {x["id"]: (x["value"], x["source"]) for x in self.detail()["items"]}
        self.assertFalse([k for k, v in batched.items() if v[1] == ""], "分批提交后不应还有待填行")
        # 分批时脚本能在依据就绪后先自己派生（如 J34 依赖 B01），只允许这类行不同
        diff = {k: (single[k], batched[k]) for k in single if single[k] != batched[k]}
        self.assertTrue(all(b[1].startswith(("N｜R12｜", "Y｜派生:")) for _, b in diff.values()), diff)


if __name__ == "__main__":
    unittest.main()
