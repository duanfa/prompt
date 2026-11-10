"""按当次定义显式提交映射；脚本不决定业务合格、分类或状态。"""
import json
import os
import unittest
try:
    from . import test_scripts as fx
except ImportError:
    import test_scripts as fx


class ModelMappingTests(unittest.TestCase):
    def setUp(self):
        self.f = fx.ScriptTests()
        self.f.setUp()
        self.f.ready()
        rc, out = self.f.force([
            ["C07", "true", "身份证正面｜画面为彩色"],
            ["C08", "false", "身份证正面｜未见公章印迹"],
            ["C10", "true", "身份证正面｜头像为卡通形象，右上角有「测试专用」水印"],
        ])
        self.assertEqual(rc, 0, out)
        self.files()

    def tearDown(self):
        self.f.tearDown()

    def files(self, obj="AdmissionDoc", prop="id_card_image_ok", label="身份证影像合格", stage="准入", condition=None, comment=None):
        self.key = obj + "." + prop
        self.obj, self.prop = obj, prop
        props = {"data": [{"name": obj, "label": "本次核验对象", "properties": [
            {"name": prop, "label": label, "comment": comment}]}]}
        rules = {"data": [{"ruleId": "CURRENT-RULE", "label": "本次材料核验", "comment": "适用阶段：" + stage,
                           "condition": condition or self.key + " = false"}]}
        for name, data in (("current-props.json", props), ("current-rules.json", rules)):
            with open(os.path.join(self.f.ws, name), "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)

    def build(self, spec=None):
        return fx.run(self.f.ws, "combine.py", "build", "--rid", fx.RID,
                      "--rules", "current-rules.json", "--props", "current-props.json",
                      stdin=json.dumps(spec, ensure_ascii=False) if spec is not None else "")

    def model_spec(self):
        return {"map": {self.key: ["C07", "C08", "C10"]},
                "set": {self.key: [False, "派生:C07,C08,C10｜虽为彩色，但头像为卡通形象且有测试水印，有伪造嫌疑"]}}

    def test_no_business_mapping_is_chosen_automatically(self):
        rc, out = self.build()
        self.assertEqual(rc, 4, out)
        self.assertIn("NO_MAP", out)
        self.assertIn(self.key, out)
        self.assertNotIn("INPUT ", out)
        rc, out = self.build({"skip": {"R10": [self.key]}})
        self.assertEqual(rc, 0, out)
        self.assertNotIn(self.prop, self.f.inp(out).get(self.obj, {}))

    def test_model_forgery_judgment_reaches_input_for_renamed_property(self):
        self.files(obj="IdentityReview", prop="media_acceptable", label="持证人证件材料符合要求")
        rc, out = self.build(self.model_spec())
        self.assertEqual(rc, 0, out)
        self.assertIs(self.f.inp(out)[self.obj][self.prop], False)
        self.assertIn("validate: OK", out)
        with open(os.path.join(self.f.ws, "work", fx.RID, "input-combine.json"), encoding="utf-8") as handle:
            prop = json.load(handle)["entities"][self.obj]["properties"][self.prop]
        self.assertEqual(prop["extractIds"], ["C07", "C08", "C10"])
        self.assertIn("伪造嫌疑", prop["value_source"])

    def test_composite_value_is_kept_until_withdrawn(self):
        """v43：set 落盘，之后的 build 不重提也沿用（trace 173 重写 stdin 时丢了分类）；写 null 撤回。"""
        rc, out = self.build(self.model_spec())
        self.assertEqual(rc, 0, out)
        value = self.f.inp(out)[self.obj][self.prop]
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        self.assertIn("SET_KEPT", out)
        self.assertEqual(self.f.inp(out)[self.obj][self.prop], value)
        rc, out = self.build({"set": {self.key: None}})
        self.assertEqual(rc, 0, out)
        self.assertIn("NEED_VALUE", out)
        self.assertNotIn(self.prop, self.f.inp(out).get(self.obj, {}))

    def test_kept_set_is_dropped_when_evidence_changes(self):
        rc, out = self.build(self.model_spec())
        self.assertEqual(rc, 0, out)
        rc, out = self.f.force([["C10", None, "R06｜防伪及头像细节无法确认"]])
        self.assertEqual(rc, 0, out)
        rc, out = self.build()
        self.assertIn("SET_STALE", out)
        self.assertNotIn(self.prop, self.f.inp(out).get(self.obj, {}))

    def test_set_alone_supplies_the_mapping(self):
        """v43（trace 173）：只交 set 不交 map，依据条目就是映射，不能静默记 R10。"""
        spec = self.model_spec()
        spec.pop("map", None)
        rc, out = self.build(spec)
        self.assertEqual(rc, 0, out)
        self.assertIn("MAP_SYNCED", out)
        self.assertIn(self.prop, self.f.inp(out)[self.obj])

    def test_single_evidence_can_have_model_supplied_enum_value(self):
        self.files(obj="Review", prop="subject_kind", label="主体类别",
                   condition="Review.subject_kind = company", comment="枚举：company 为公司")
        spec = {"map": {self.key: ["B02"]}, "set": {self.key: ["company", "派生:B02｜类型栏为有限责任公司，按本次定义归为公司"]}}
        rc, out = self.build(spec)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.f.inp(out)[self.obj][self.prop], "company")

    def test_model_value_with_missing_evidence_stays_unfilled(self):
        rc, out = self.f.force([["C10", None, "R06｜防伪及头像细节无法确认"]])
        self.assertEqual(rc, 0, out)
        rc, out = self.build(self.model_spec())
        self.assertEqual(rc, 0, out)
        self.assertNotIn(self.prop, self.f.inp(out).get(self.obj, {}))
        self.assertIn("模型取值缺少依据", out)

    def test_source_must_list_the_mapped_evidence(self):
        spec = self.model_spec()
        spec["set"][self.key][1] = "派生:C07｜画面为彩色"
        rc, out = self.build(spec)
        self.assertNotEqual(rc, 0, out)
        self.assertIn("来源条目必须与 map 一致", out)

    def test_later_stage_rules_require_explicit_exclusion(self):
        self.files(stage="签约")
        rc, out = self.build(self.model_spec())
        self.assertEqual(rc, 0, out)
        self.assertIs(self.f.inp(out)[self.obj][self.prop], False)
        spec = self.model_spec()
        spec["rules"] = {"drop": {"CURRENT-RULE": "本次只审核准入资料，该规则由签约环节执行"}}
        rc, out = self.build(spec)
        self.assertEqual(rc, 0, out)
        self.assertNotIn(self.prop, self.f.inp(out).get(self.obj, {}))
        self.assertIn("已抛掉 1 条", out)


if __name__ == "__main__":
    unittest.main()
