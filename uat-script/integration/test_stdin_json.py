"""stdin 边界修复必须只补结构，保留全部值；有歧义或其他损坏仍拒绝。"""
import contextlib
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills/admission-v0-1-catalog/scripts/detail.py"
SPEC = importlib.util.spec_from_file_location("stdin_detail", SCRIPT)
detail = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(detail)
sys.path.insert(0, str(SCRIPT.parent))


class StdinJsonTests(unittest.TestCase):
    def read(self, raw):
        out = io.StringIO()
        with patch.object(detail.sys, "stdin", io.StringIO(raw)), contextlib.redirect_stdout(out):
            try:
                value = detail.read_stdin()
            except SystemExit as exc:
                return exc.code, None, out.getvalue()
        return 0, value, out.getvalue()

    def test_valid_json_keeps_quotes_backslashes_and_boundary_text(self):
        obj = {"rows": [["B01", '含"引号"和\\路径', '原件｜字面 ,"notes": 不应解释为结构']],
               "notes": {"conflicts": [], "toolIssues": []}}
        rc, value, out = self.read(json.dumps(obj, ensure_ascii=False))
        self.assertEqual((rc, value, out), (0, obj, ""))

    def test_job216_boundary_preserves_all_rows_materials_and_notes(self):
        obj = {"materials": {"bizlicUrl": ["可读", "名称栏｜某某有限公司"]},
               "rows": [["B01", "某某有限公司", "营业执照 p1 名称｜某某有限公司"],
                        ["J34", None, "派生:J01-J16,B01-B08｜由脚本自动比对"]],
               "notes": {"conflicts": ["双方原文不同"], "toolIssues": []}}
        valid = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        raw = valid.replace(']],"notes":', '],"notes":', 1)
        rc, value, out = self.read(raw)
        self.assertEqual((rc, value), (0, obj))
        self.assertIn("WARN STDIN_ROWS_CLOSED", out)

    def test_whitespace_and_escaped_strings_are_unchanged(self):
        obj = {"rows": [["B01", '原文"引号"', "原文｜含\\反斜杠与换行\n第二行"]],
               "notes": {"conflicts": [], "toolIssues": []}}
        valid = json.dumps(obj, ensure_ascii=True)
        raw = valid.replace(']], "notes":', '] ,\n "notes" :', 1)
        rc, value, out = self.read(raw)
        self.assertEqual((rc, value), (0, obj))
        self.assertIn("STDIN_ROWS_CLOSED", out)

    def test_materials_can_follow_rows(self):
        raw = '{"rows":[["B01","某公司","原件｜某公司"],"materials":{"bizlicUrl":["可读","名称：某公司"]}}'
        rc, value, out = self.read(raw)
        self.assertEqual(rc, 0, out)
        self.assertEqual(value["rows"], [["B01", "某公司", "原件｜某公司"]])
        self.assertIn("STDIN_ROWS_CLOSED", out)

    def test_existing_extra_closing_brace_compatibility(self):
        obj = {"rows": [["B01", "公司", "原件｜公司"]]}
        rc, value, out = self.read(json.dumps(obj) + "}")
        self.assertEqual((rc, value), (0, obj))
        self.assertIn("结尾多了", out)

    def test_other_damage_is_rejected_without_guessing(self):
        cases = {
            "value_missing_comma": '{"rows":[["B01","x" "y"]]}',
            "incomplete_row": '{"rows":[["B01","x"],"notes":{}}',
            "row_id_is_not_string": '{"rows":[[1,"x","原件｜x"],"notes":{}}',
            "unknown_top_level_key": '{"rows":[["B01","x","原件｜x"],"other":{}}',
            "unknown_prefix_key": '{"ctx":{},"rows":[["B01","x","原件｜x"],"notes":{}}',
            "duplicate_key": '{"notes":{},"rows":[["B01","x","原件｜x"],"notes":{}}',
            "duplicate_nested_key": '{"rows":[["B01","x","原件｜x"],"notes":{"conflicts":[],"conflicts":["x"]}}',
            "notes_is_not_object": '{"rows":[["B01","x","原件｜x"],"notes":[]}',
            "truncated": '{"rows":[["B01","x","原件｜x"],"notes":{',
            "two_errors": '{"rows":[["B01","x","原件｜x"],"notes":{}}}',
        }
        for name, raw in cases.items():
            with self.subTest(name=name):
                rc, value, out = self.read(raw)
                self.assertEqual((rc, value), (1, None), out)
                self.assertIn("STDIN_JSON_INVALID", out)
                self.assertIn("连续第二次", out)
                self.assertNotIn("WARN STDIN_ROWS_CLOSED", out)


SCRIPTS = SCRIPT.parent
FX = Path(__file__).resolve().parent / "fixtures"


def run(ws, script, *args, stdin=""):
    import subprocess
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *args], cwd=ws, input=stdin,
                       capture_output=True, text=True, env={"LANG": "C.UTF-8"}, timeout=30)
    return r.returncode, r.stdout + r.stderr


class ConsecutiveFailureTests(unittest.TestCase):
    """build/summary/fill 的语法失败都给稳定错误码；同一步骤连续第二次停止重试（summary 改为脚本生成），成功一次即清零。"""

    def setUp(self):
        import shutil, tempfile
        self.ws = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ws, True)
        for n in ("rules.json", "props.json"):
            shutil.copy(FX / "v25_run" / n, Path(self.ws) / n)
        (Path(self.ws) / "work" / "r1").mkdir(parents=True)

    def build(self, stdin):
        return run(self.ws, "combine.py", "build", "--rid", "r1", "--rules", "rules.json", "--props", "props.json", stdin=stdin)

    def test_build_bad_json_has_code_and_second_time_gives_up(self):
        rc, out = self.build('{"map":{"A.b":["A01"]}')
        self.assertEqual(rc, 1, out)
        self.assertIn("STDIN_JSON_INVALID build", out)
        self.assertIn("连续第 1 次", out)
        self.assertIn("连续第二次语法失败即停止重试", out)
        self.assertNotIn("STDIN_GIVE_UP", out)
        rc, out = self.build('{"map":{"A.b":["A01"]]}')           # 换一种写错法也算同一步骤的连续失败
        self.assertEqual(rc, 1, out)
        self.assertIn("连续第 2 次", out)
        self.assertIn("STDIN_GIVE_UP build", out)
        self.assertIn("不调用 mcp_run_process", out)

    def test_build_success_resets_the_counter(self):
        self.build("{坏")
        rc, out = self.build('{"toolIssues":[]}')                  # 合法：解析通过即清零（后续业务报错与计数无关）
        self.assertNotIn("STDIN_JSON_INVALID", out)
        rc, out = self.build("{坏")
        self.assertIn("连续第 1 次", out)
        self.assertNotIn("STDIN_GIVE_UP", out)

    def test_build_duplicate_key_and_non_object_are_rejected(self):
        rc, out = self.build('{"map":{"A.b":["A01"]},"map":{}}')
        self.assertIn("STDIN_JSON_INVALID", out)
        self.assertIn("「map」出现了两次", out)
        rc, out = self.build('[1,2]')
        self.assertIn("STDIN_JSON_INVALID", out)
        self.assertIn("连续第 2 次", out)

    def test_fill_and_recheck_count_separately(self):
        import stdin_json as sj
        cwd = os.getcwd()
        os.chdir(self.ws)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(sj.read("{坏", "fill", "r1")[1], 1)
                self.assertEqual(sj.read("{坏", "recheck", "r1")[1], 1)
                self.assertEqual(sj.read("{坏", "fill", "r1")[1], 2)
            self.assertIn("STDIN_GIVE_UP fill", out.getvalue())
            self.assertNotIn("STDIN_GIVE_UP recheck", out.getvalue())
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
