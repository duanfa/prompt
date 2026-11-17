"""python3 -m unittest integration/test_combine_tool.py  （或直接 python3 integration/test_combine_tool.py）
用 fixtures 里的真实规则/属性定义 + 虚构企业事实，生成并校验 extract-detail / combine 的示例。
设环境变量 WRITE_EXAMPLES=1 把示例写到 references/examples/。"""
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "admission-v0-1-1-catalog", "scripts")
TOOL = os.path.join(SCRIPTS, "combine_tool.py")
FX = os.path.join(HERE, "fixtures")
ITEMS = os.path.join(ROOT, "skills", "admission-v0-1-1-catalog", "extract-items-checked.json")
# 模拟 Agent 按语义做的 键→条目 对应（清单不再带 hintKeys/derivedKeys，工具靠 --map 做离线回归）
MAP = {"Employer.founded_months": ["B16"], "AdmissionDoc.photo_count": ["F01"],
       "Employer.has_independent_employment_status": ["B17", "B18", "B19"],
       # v29：四个标识也是模型按含义映射到 A01–A04，脚本里不再写死任何属性名
       "Employer.employer_id": ["A01"], "Employer.employer_name": ["A02"], "Demand.demand_id": ["A03"],
       "LaborAgency.agency_id": ["A04"]}
EX = os.path.join(ROOT, "references", "examples")

# 虚构企业：只为演示格式，不是真实数据
FILL = {
    "A01": ("123456", "Y｜请求 entpId｜entpId=123456"),
    "A02": ("示例科技有限公司", "Y｜请求 entpName｜entpName=示例科技有限公司"),
    "A03": ("7001", "Y｜请求 rqId｜rqId=7001"),
    "A04": ("9001", "Y｜请求 hrInstId｜hrInstId=9001"),
    "A06": ("20261104", "Y｜请求 taskSubmittedDate｜taskSubmittedDate=2026-11-04（无 apply_date，回退）"),
    "B01": ("示例科技有限公司", "Y｜营业执照 bizlicUrl p1 名称栏｜名称：示例科技有限公司"),
    "B02": ("有限责任公司(自然人独资)", "Y｜营业执照 bizlicUrl p1 类型栏｜类型：有限责任公司(自然人独资)"),
    "B04": ("20260301", "Y｜营业执照 bizlicUrl p1 成立日期栏｜成立日期：2026年03月01日"),
    "B16": ("8", "Y｜派生:B04,A06｜(2026-2026)*12+(11-3)=8；基准日4≥成立日1，不再减1"),
    "B17": ("有限责任公司", "Y｜派生:B02｜类型栏「有限责任公司(自然人独资)」→有限责任公司"),
    "B18": ("false", "Y｜派生:B02,B01｜类型栏「有限责任公司(自然人独资)」、名称均不含分公司"),
    "B19": ("false", "Y｜派生:B02｜类型栏不含合伙"),
    "F01": ("3", "Y｜请求 业务场景照片数组｜数组条数=3"),
}


def run(*a):
    r = subprocess.run([sys.executable, TOOL, *a], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def build_extract():
    t = json.load(open(ITEMS, encoding="utf-8"))
    out = []
    for it in t:
        v, s = FILL.get(it["id"], (None, None))
        if s is None:
            s = "N｜R01｜示例中请求未提供该字段（演示用占位原因）"
        out.append({"id": it["id"], "name": it["name"], "desc": it["desc"], "value": v, "source": s})  # v24：明细只有 id/name/desc/value/source
    return out


def write_extract(path, items):
    with open(path, "w", encoding="utf-8") as f:
        f.write('{\n"contract":"admission-noshell-v0-1-1",\n"schema":"input-extract-detail/3",\n')
        f.write('"routing":{"requestId":"123","domain":"demo","scene":"admission","businessKey":"123456"},\n')
        f.write('"materials":{"bizlicUrl":["可读","名称栏：示例科技有限公司"]},\n"items":[\n')
        f.write(",\n".join(json.dumps(i, ensure_ascii=False, separators=(",", ":")) for i in items))
        f.write('\n],\n"notes":{"unresolvedProperties":[],"notFoundInDefinition":[],"conflicts":[],"unreadMaterials":[],"toolIssues":[]}\n}\n')


class T(unittest.TestCase):
    def test_roundtrip(self):
        d = tempfile.mkdtemp()
        ex, cb = os.path.join(d, "ex.json"), os.path.join(d, "cb.json")
        write_extract(ex, build_extract())
        mp = os.path.join(d, "map.json")
        json.dump(MAP, open(mp, "w", encoding="utf-8"), ensure_ascii=False)
        json.load(open(ex, encoding="utf-8"))
        rc, out = run("skeleton", "--rules", FX + "/list_rule_1103.json", "--props", FX + "/list-properties.json", "--items", ITEMS, "--map", mp,
                      "--extract", ex, "--routing", "requestId=123,domain=demo,scene=admission,businessKey=123456", "--out", cb)
        self.assertEqual(rc, 0, out)
        c = json.load(open(cb, encoding="utf-8"))
        inp = c["input"]
        self.assertEqual(inp["Employer"]["founded_months"], 8)          # 数值型
        prop = c["entities"]["Employer"]["properties"]["has_independent_employment_status"]  # v24：派生属性，工具只留骨架
        self.assertIsNone(prop["value"])
        self.assertEqual(prop["extractIds"], ["B17", "B18", "B19"])
        prop["value"] = True            # 模拟 Agent 按规则语义由多条明细组装
        prop["value_source"] = "派生:B17,B18,B19｜有限责任公司，B18、B19 均为 false"
        c["input"]["Employer"]["has_independent_employment_status"] = True
        json.dump(c, open(cb, "w", encoding="utf-8"), ensure_ascii=False)
        self.assertEqual(inp["Employer"]["employer_id"], "123456")      # ID 保持字符串
        self.assertEqual(inp["AdmissionDoc"]["photo_count"], 3)
        self.assertEqual(inp["LaborAgency"]["agency_id"], "9001")
        self.assertNotIn("Agency", inp)                                  # 没映射、定义也没有的键不会凭空出现（v28 写死 Agency.agency_id）
        self.assertNotIn("subject_type", inp["Employer"])                # 没映射的键不进 input
        # v26：null 的键不进 entities，只进 unfilled；refKeys 与 condition 引用一致且按实体闭合
        self.assertNotIn("subject_type", c["entities"]["Employer"]["properties"])
        self.assertIn("subject_type", c["unfilled"]["Employer"]["R10"])  # 离线 skeleton 没有 skip，未映射一律 R10
        self.assertIn("founded_months", c["refKeys"]["Employer"])
        self.assertTrue(all(p["value"] is not None for e in c["entities"].values() for n, p in e["properties"].items()
                            if n != "has_independent_employment_status"))
        self.assertIn("task_category", c["unfilled"]["BusinessCheck"]["R10"])
        rc, out = run("validate", "--extract", ex, "--combine", cb, "--rules", FX + "/list_rule_1103.json", "--items", ITEMS)
        self.assertEqual(rc, 0, out)
        # v26：回归 v25 真实运行暴露的问题——null 行留在 entities、unfilled 登记无规则引用的键，必须被发现
        c2 = json.loads(json.dumps(c))
        c2["entities"]["Employer"]["properties"]["zz_null"] = {"value": None, "value_source": "", "label": "x", "comment": None, "extractIds": [], "rules": []}
        c2["unfilled"].setdefault("AdmissionDoc", {}).setdefault("R14", []).append("doc_id")   # 没有任何规则引用
        cb2 = os.path.join(d, "cb2.json")
        json.dump(c2, open(cb2, "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = run("validate", "--extract", ex, "--combine", cb2, "--rules", FX + "/list_rule_1103.json", "--items", ITEMS)
        self.assertEqual(rc, 1, out)
        self.assertIn("entities 含 null 属性 Employer.zz_null", out)
        self.assertIn("unfilled AdmissionDoc.doc_id", out)
        c3 = json.loads(json.dumps(c))
        del c3["refKeys"]
        cb3 = os.path.join(d, "cb3.json")
        json.dump(c3, open(cb3, "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = run("validate", "--extract", ex, "--combine", cb3)
        self.assertEqual(rc, 1, out)
        self.assertIn("缺 refKeys", out)
        # 篡改: input 与 entities 不一致必须被发现
        c["input"]["Employer"]["founded_months"] = 9
        json.dump(c, open(cb, "w", encoding="utf-8"), ensure_ascii=False)
        rc, out = run("validate", "--extract", ex, "--combine", cb)
        self.assertEqual(rc, 1, out)
        if "--write-examples" in sys.argv or os.environ.get("WRITE_EXAMPLES"):
            os.makedirs(EX, exist_ok=True)
            write_extract(EX + "/input-extract-detail.example.json", build_extract())
            out = EX + "/input-combine.example.json"
            run("skeleton", "--rules", FX + "/list_rule_1103.json", "--props", FX + "/list-properties.json", "--items", ITEMS, "--map", mp,
                "--extract", EX + "/input-extract-detail.example.json", "--routing", "requestId=123,domain=demo,scene=admission,businessKey=123456",
                "--out", out)
            # 示例要是“组装完成”的样子：把派生属性补上值，再按同一格式渲染
            import importlib.util
            spec = importlib.util.spec_from_file_location("combine_tool", TOOL)
            ct = importlib.util.module_from_spec(spec); spec.loader.exec_module(ct)
            ex_c = json.load(open(out, encoding="utf-8"))
            ex_p = ex_c["entities"]["Employer"]["properties"]["has_independent_employment_status"]
            ex_p["value"], ex_p["value_source"] = True, "派生:B17,B18,B19｜有限责任公司，B18、B19 均为 false"
            ex_c["input"]["Employer"]["has_independent_employment_status"] = True
            open(out, "w", encoding="utf-8").write(ct.render_combine(ex_c))

if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
