"""stdin 边界修复必须只补结构，保留全部值；有歧义或其他损坏仍拒绝。"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "skills/admission-v0-1-catalog/scripts/detail.py"
SPEC = importlib.util.spec_from_file_location("stdin_detail", SCRIPT)
detail = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(detail)


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


if __name__ == "__main__":
    unittest.main()
