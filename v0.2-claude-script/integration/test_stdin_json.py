"""stdin_json：只改括号的结构修复、诊断与连续失败计数（v44）。

job 216：fill 少了关闭 rows 的 ]，重提 29 次；job 218：summary 把 next 的 ] 写成 },{，两次被拒后绕过脚本。
修复只动字符串外的 ] } , [ {，结果唯一且通过该步骤入参校验才接收；字符串内容一个字都不改。"""
import glob
import importlib.util
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_scripts import FX, RID, SCRIPTS, read, run  # noqa: E402

SPEC = importlib.util.spec_from_file_location("stdin_json", os.path.join(SCRIPTS, "stdin_json.py"))
sj = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sj)

FILL = {"materials": {"bizlicUrl": ["可读", "名称栏｜某某有限公司"]},
        "rows": [["B01", "某某有限公司", "营业执照 p1 名称｜某某有限公司"],
                 ["B02", None, "R03｜类型栏看不清"],
                 ["J34", None, "派生:J01-J16,B01-B08｜由脚本自动比对"]],
        "notes": {"conflicts": ["双方原文不同"], "toolIssues": []}}
SUMMARY = {"basis": [{"ruleIds": ["RULE-DOC-014"], "text": "开户名称与执照名称不一致"}],
           "next": ["请核实开户名称", "请人工核实现场照片"],
           "notice": [{"id": "B12", "condition": "false,不是彩色"}],
           "analysis": ["多份材料名称不一致，建议核实"]}


def dumps(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


class RepairTests(unittest.TestCase):
    def ok(self, raw, step, want):
        obj, warn, err = sj.load(raw, sj.VALIDATORS[step])
        self.assertEqual(obj, want, err)
        return warn

    def bad(self, raw, step):
        obj, warn, err = sj.load(raw, sj.VALIDATORS[step])
        self.assertIsNone(obj, warn)
        return err

    def test_valid_json_untouched(self):
        o = {"rows": [["B01", '含"引号"和\\路径', '原件｜字面 ,"notes": ]] 不是结构']], "notes": {"conflicts": []}}
        self.assertIsNone(self.ok(json.dumps(o, ensure_ascii=False), "fill", o))

    def test_job216_rows_not_closed(self):
        raw = dumps(FILL).replace(']],"notes"', '],"notes"')
        self.assertIn("补「]」", self.ok(raw, "fill", FILL))

    def test_job218_next_closed_with_brace(self):
        raw = dumps(SUMMARY).replace('照片"],"notice"', '照片"},{"notice"')
        self.assertIn("改成「],」", self.ok(raw, "summary", SUMMARY))

    def test_other_single_bracket_slips(self):
        s = dumps(FILL)
        cases = {
            "row ] missing mid": s.replace('司"],["B02"', '司",["B02"'),
            "final } missing": s[:-1],
            "extra ] after rows": s.replace(']],"notes"', ']]],"notes"'),
            "rows ] written as }": s.replace(']],"notes"', ']},"notes"'),
            "comma missing between rows": s.replace('司"],["B02"', '司"]["B02"'),
            "pretty printed": json.dumps(FILL, ensure_ascii=False, indent=1).replace("]\n ],\n \"notes\"", "]\n ,\n \"notes\""),
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.assertNotEqual(raw, s)
                self.ok(raw, "fill", FILL)

    def test_ascii_quote_is_diagnosed_not_guessed(self):
        raw = dumps(FILL).replace("名称｜某某有限公司", '名称｜"某某"有限公司')
        err = self.bad(raw, "fill")
        self.assertIn("B01 行", err)
        self.assertIn("ASCII 双引号", err)

    def test_structure_that_fails_validation_is_rejected(self):
        cases = {
            "row of two": '{"rows":[["B01","x"],"notes":{}}',
            "row id not string": '{"rows":[[1,"x","原件｜x"],"notes":{}}',
            "unknown top key": '{"rows":[["B01","x","原件｜x"],"other":{}}',
            "duplicate key": '{"notes":{},"rows":[["B01","x","原件｜x"]],"notes":{}}',
            "truncated": '{"rows":[["B01","x","原件｜x"],"notes":{',
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.bad(raw, "fill")

    def test_build_and_recheck_validators(self):
        b = {"map": {"Employer.x": ["B01"]}, "skip": {"R10": ["Employer.y"]}, "set": {"Employer.z": [True, "派生:B01｜依据"]}}
        self.ok(dumps(b).replace(']},"skip"', '}},"skip"'), "build", b)
        r = {"rows": [["B05", "长期", "营业执照｜营业期限：长期"]]}
        self.ok(dumps(r)[:-1], "recheck", r)

    def test_repairs_never_change_string_content(self):
        """随机删/改一个结构符号：要么拒绝，要么恢复成原对象，绝不产生别的结果。"""
        rnd = random.Random(44)
        s = dumps(FILL)
        spans = sj.string_spans(s)
        inside = {k for a, b in spans for k in range(a, b + 1)}
        pos = [i for i, c in enumerate(s) if c in "[]{}," and i not in inside]
        for _ in range(60):
            i = rnd.choice(pos)
            raw = s[:i] + rnd.choice(["", "]", "}", ","]) + s[i + 1:]
            if raw == s:
                continue
            obj, _, _ = sj.load(raw, sj.validate_fill)
            if obj is not None:
                for row, want in zip(obj["rows"], FILL["rows"]):
                    self.assertEqual(row, want, raw)
                self.assertEqual(obj, FILL, raw)


class ScriptFlowTests(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        for f in ("biz_D.txt", "biz_B.txt", "biz_T.txt", "rules.json", "props.json"):
            shutil.copy(os.path.join(FX, f), self.ws)
        rc, out = run(self.ws, "detail.py", "init", "--biz", "biz_D.txt", "biz_B.txt", "biz_T.txt", "--rules", "rules.json",
                      stdin=read("init_spec.json"))
        self.assertEqual(rc, 0, out)

    def tearDown(self):
        shutil.rmtree(self.ws, ignore_errors=True)

    def fill(self, raw):
        return run(self.ws, "detail.py", "fill", "--rid", RID, stdin=raw)

    def test_fill_with_unclosed_rows_is_written(self):
        spec = json.loads(read("fill_spec.json"))
        raw = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
        k = raw.index('"rows":[') + len('"rows":')
        end = json.JSONDecoder().raw_decode(raw, k)[1]          # rows 数组的结尾
        broken = raw[:end - 1] + raw[end:]
        self.assertNotEqual(broken, raw)
        rc, out = self.fill(broken)
        self.assertIn("WARN STDIN_REPAIRED", out)
        self.assertNotIn("STDIN_JSON_INVALID", out)
        with open(os.path.join(self.ws, "work", RID, "input-extract-detail.json"), encoding="utf-8") as f:
            items = {x["id"]: x for x in json.load(f)["items"]}
        for i, v, _ in spec["rows"][:5]:
            if v is not None and i in items:
                self.assertEqual(items[i]["value"], v)

    def test_consecutive_failures_escalate_then_reset(self):
        bad = '{"rows":[["B01","某"公司","营业执照｜某公司"]]}'
        rc1, o1 = self.fill(bad)
        rc2, o2 = self.fill(bad)
        rc3, o3 = self.fill(bad)
        self.assertEqual((rc1, rc2, rc3), (1, 1, 1))
        self.assertIn("连续第 1 次", o1)
        self.assertIn("分批", o2)
        self.assertIn("STDIN_GIVE_UP", o3)
        self.fill('{"rows":[]}')                                   # 解析成功即清零
        rc, o = self.fill(bad)
        self.assertIn("连续第 1 次", o)

    def test_build_reports_stdin_json_invalid(self):
        rc, out = run(self.ws, "combine.py", "build", "--rid", RID, "--rules", "rules.json", "--props", "props.json",
                      stdin='{"map":{"Employer.x":["B01"]},"skip":"R10"}}')
        self.assertEqual(rc, 1)
        self.assertIn("STDIN_JSON_INVALID build", out)


TRACES = sorted(glob.glob(os.path.expanduser("~/Downloads/ontology_agent_job_21[68]_v01-10-6*.json")))


@unittest.skipUnless(TRACES, "本机没有 job 216/218 的原始导出")
class RealTraceReplay(unittest.TestCase):
    def test_every_logged_json_failure_is_repaired(self):
        n = 0
        for p in TRACES:
            with open(p, encoding="utf-8") as f:
                obs = json.load(f)["observations"]
            for o in obs:
                if o["name"] != "RunSkillScript" or "不是合法 JSON" not in str(o.get("output")):
                    continue
                x = json.loads(o["input"])
                obj, warn, err = sj.load(x["stdin"], sj.VALIDATORS[x["args"][0]])
                self.assertIsNotNone(obj, "%s %s" % (os.path.basename(p), err))
                n += 1
        self.assertEqual(n, 31)      # 216 fill 29 次 + 218 summary 2 次


if __name__ == "__main__":
    unittest.main()
