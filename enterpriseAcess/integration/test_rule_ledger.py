"""Offline contract tests; no service calls or credentials."""
import copy
import unittest

from rule_ledger import LedgerError, build_ledger, finalize


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.response = {"code": 0, "requestId": "job-1", "data": {"ruleCheckList": [
            {"ruleId": "a", "result": True},
            {"ruleId": "b", "result": "false"},
            {"ruleId": "c", "result": "skip"},
        ]}}
        self.kw = dict(engine_call_id="call-1", request_id="job-1",
                       input_snapshot={"Employer": {"employer_id": "1"}}, complete=True)
        self.ledger = build_ledger(self.response, **self.kw)
        self.draft = {"engineCallId": "call-1",
                      "responseSha256": self.ledger["responseSha256"],
                      "inputSha256": self.ledger["inputSha256"], "groups": [
            {"category": "其他", "result": "true", "text": "条件成立", "ruleIds": ["a"]},
            {"category": "其他", "result": "false", "text": "条件不成立", "ruleIds": ["b"]},
        ]}

    def test_counts_and_one_renderer(self):
        result = finalize(self.response, self.draft, **self.kw)
        self.assertEqual(result["ledger"]["stats"],
                         {"total": 3, "determined": 2, "true": 1, "false": 1, "skip": 1,
                          "falseInsufficient": 0})
        self.assertEqual(set(result), {"ledger", "summary", "validation"})
        self.assertIn("命中：条件成立。未命中：条件不成立", result["summary"])
        self.assertNotIn("【来源：", result["summary"])

    def test_omission_duplicate_unknown_skip_and_direction_are_blocked(self):
        for name, alter in (
            ("missing", lambda d: d["groups"].pop()),
            ("duplicate", lambda d: d["groups"][0]["ruleIds"].append("a")),
            ("unknown", lambda d: d["groups"][0]["ruleIds"].append("x")),
            ("skip", lambda d: d["groups"][0]["ruleIds"].append("c")),
            ("direction", lambda d: d["groups"][0].update(result="false")),
            ("snapshot", lambda d: d.update(engineCallId="old-call")),
            ("hash", lambda d: d.update(responseSha256="old-hash")),
            ("input_hash", lambda d: d.update(inputSha256="other-input")),
            ("category", lambda d: d["groups"][0].update(category="准入资料")),
            ("source_injection", lambda d: d["groups"][0].update(text="描述【来源：x】")),
        ):
            with self.subTest(name=name):
                draft = copy.deepcopy(self.draft)
                alter(draft)
                with self.assertRaises(LedgerError):
                    finalize(self.response, draft, **self.kw)

    def test_invalid_raw_result_is_never_silently_counted(self):
        for state in (0, 1, None, "pass", "TRUE", {}, []):
            with self.subTest(state=state):
                response = copy.deepcopy(self.response)
                response["data"]["ruleCheckList"][0]["result"] = state
                with self.assertRaises(LedgerError):
                    build_ledger(response, **self.kw)

    def test_duplicate_ids_and_transport_failures_are_blocked(self):
        response = copy.deepcopy(self.response)
        response["data"]["ruleCheckList"].append(response["data"]["ruleCheckList"][0])
        with self.assertRaisesRegex(LedgerError, "DUPLICATE_RULE_ID"):
            build_ledger(response, **self.kw)
        for overrides in ({"complete": False}, {"request_id": "other-job"}):
            with self.subTest(overrides=overrides), self.assertRaises(LedgerError):
                build_ledger(self.response, **{**self.kw, **overrides})

    def test_all_skip_and_empty_results(self):
        for rows in ([], [{"ruleId": "c", "result": "skip"}]):
            response = {"code": 0, "requestId": "job-1", "data": {"ruleCheckList": rows}}
            ledger = build_ledger(response, **self.kw)
            draft = {"engineCallId": "call-1", "responseSha256": ledger["responseSha256"],
                     "inputSha256": ledger["inputSha256"],
                     "groups": []}
            self.assertEqual(finalize(response, draft, **self.kw)["summary"],
                             "无已判定（true/false）的规则")


class InsufficientBasisTests(unittest.TestCase):
    """false with reason 属性/对象不存在 was not evaluated; never render as "checked"."""

    def setUp(self):
        self.response = {"code": 0, "requestId": "job-2", "data": {"ruleCheckList": [
            {"ruleId": "a", "result": True, "reason": ""},
            {"ruleId": "b", "result": "false", "reason": "不满足 X.y = 1"},
            {"ruleId": "d", "result": "false",
             "reason": "AdmissionDoc.doc_type 属性不存在 或 不满足 AdmissionDoc.valid = false"},
            {"ruleId": "s", "result": "false", "reason": "StageGate对象不存在"},
            {"ruleId": "k", "result": "skip", "reason": "x"},
        ]}}
        self.kw = dict(engine_call_id="call-2", request_id="job-2",
                       input_snapshot={"Employer": {"employer_id": "1"}}, complete=True)
        self.ledger = build_ledger(self.response, **self.kw)

    def draft(self, **over):
        d = {"engineCallId": "call-2", "responseSha256": self.ledger["responseSha256"],
             "inputSha256": self.ledger["inputSha256"], "groups": [
            {"category": "其他", "result": "true", "text": "条件成立", "ruleIds": ["a"]},
            {"category": "其他", "result": "false", "text": "条件不成立", "ruleIds": ["b"]},
            {"category": "其他", "result": "false", "basis": "insufficient",
             "text": "资料类型缺失，条件未求值", "ruleIds": ["d", "s"]}]}
        d.update(over)
        return d

    def test_flags_and_counts(self):
        st = self.ledger["stats"]
        self.assertEqual((st["determined"], st["true"], st["false"], st["falseInsufficient"]),
                         (4, 1, 3, 2))
        flags = {r["ruleId"]: r["insufficient"] for r in self.ledger["rules"]}
        self.assertEqual(flags, {"a": False, "b": False, "d": True, "s": True, "k": False})

    def test_renders_not_triggered_label_and_header(self):
        out = finalize(self.response, self.draft(), **self.kw)
        self.assertIn("其中2条因所需属性未取得而未触发、未据此核实", out["summary"])
        self.assertIn("未触发（所需属性未取得，未据此核实）：资料类型缺失", out["summary"])
        self.assertEqual(set(out), {"ledger", "summary", "validation"})
        self.assertNotIn("【来源：", out["summary"])

    def test_wrong_basis_is_blocked(self):
        d = self.draft()
        d["groups"][1]["ruleIds"].append("d")      # insufficient rule hidden among determined
        d["groups"][2]["ruleIds"].remove("d")
        with self.assertRaises(LedgerError) as cm:
            finalize(self.response, d, **self.kw)
        self.assertIn("WRONG_BASIS", str(cm.exception))
        d2 = self.draft()
        d2["groups"][1]["basis"] = "insufficient"  # determined rule mislabelled
        with self.assertRaises(LedgerError):
            finalize(self.response, d2, **self.kw)
        d3 = self.draft()
        d3["groups"][0]["basis"] = "insufficient"  # true can never be insufficient
        with self.assertRaises(LedgerError):
            finalize(self.response, d3, **self.kw)

    def test_unknown_basis_value_is_blocked(self):
        d = self.draft()
        d["groups"][1]["basis"] = "maybe"
        with self.assertRaises(LedgerError):
            finalize(self.response, d, **self.kw)


class AndOrAwareInsufficientTests(unittest.TestCase):
    """v26: a false AND with a conjunct reported 不满足 was evaluated, even if another conjunct is absent.
    Cases are the real v25 run (ontology_agent_job_43_115-am2)."""

    def flag(self, expression, reason):
        from rule_ledger import is_insufficient
        return is_insufficient("false", reason, expression)

    def test_and_with_failed_conjunct_is_determined(self):
        # RULE-IND-SEN-002: business_scope_sensitive=false was supplied, employment_scene_sensitive was not
        self.assertFalse(self.flag(
            "Employer.business_scope_sensitive = true AND Employer.employment_scene_sensitive = false",
            "不满足 Employer.business_scope_sensitive = true 或 Employer.employment_scene_sensitive 属性不存在"))
        # RULE-DOC-017: doc_type is never supplied, account_name_matches=true was
        self.assertFalse(self.flag(
            "AdmissionDoc.doc_type = bank_account AND AdmissionDoc.account_name_matches = false",
            "AdmissionDoc.doc_type 属性不存在 或 不满足 AdmissionDoc.account_name_matches = false"))
        # RULE-IND-PRO-001: object absent on one side
        self.assertFalse(self.flag(
            "Employer.name_blacklist_hit = true AND BusinessCheck.task_category = professional_practice",
            "不满足 Employer.name_blacklist_hit = true 或 BusinessCheck对象不存在"))

    def test_and_with_only_missing_parts_is_insufficient(self):
        self.assertTrue(self.flag("A.x = 1 AND B.y = 2", "A.x 属性不存在 或 B对象不存在"))

    def test_or_single_mixed_and_missing_expression_are_insufficient(self):
        self.assertTrue(self.flag("A.x = 1 OR B.y = 2", "不满足 A.x = 1 或 B.y 属性不存在"))
        self.assertTrue(self.flag("A.x = 1", "A.x 属性不存在"))
        self.assertTrue(self.flag("A.x = 1 OR (B.y = 2 AND C.z = 3)", "不满足 A.x = 1 或 C对象不存在"))
        self.assertTrue(self.flag(None, "A.x 属性不存在 或 不满足 B.y = 2"))   # old callers: conservative

    def test_and_inside_brackets_and_quotes_is_not_top_level(self):
        # the OR hides in a set / quoted literal; top level is AND only
        self.assertFalse(self.flag('A.x IN {a, b} AND B.y CONTAINS "x OR y"',
                                   "不满足 A.x IN {a, b} 或 B对象不存在"))

    def test_true_and_clean_false_are_never_insufficient(self):
        from rule_ledger import is_insufficient
        self.assertFalse(is_insufficient("true", "属性不存在", "A.x = 1"))
        self.assertFalse(self.flag("A.x = 1 OR B.y = 2", "不满足 A.x = 1 或 不满足 B.y = 2"))


if __name__ == "__main__":
    unittest.main()
