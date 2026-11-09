#!/usr/bin/env python3
"""input-combine.json 组装脚本：由 RunSkillScript 运行（python3 -I，只用标准库，工作目录 = 工作区）。

规则（mcp_list_rule）和属性定义（mcp_list_property）是工具落盘的原文文件，明细是 detail.py 写的文件，
「清单条目 → 本体属性」的对应由你按含义决定（v29：没有对照表，属性名随本体随时会变，脚本里不写任何属性名）；脚本只做机械校验。
combine 文件完全由脚本生成，模型不再手写 93 KB 的 JSON，也不会漏抄、改写规则。

  plan     --rid <id> --rules <规则文件> --props <属性文件>   只读：规则引用的键（含 label/comment）+ 预设条目（四个标识、用工场景）+ 全部清单条目，供你按语义决定映射
  names    --rules <规则文件>                               打印规则引用的对象名
  rules    --rules <规则文件> [--grep 词]                     规则摘要：ruleId|label|引用键；--grep 按 condition/label/comment 过滤并给出完整 condition
  props    --props <属性文件> [--obj 对象]                    属性定义摘要：对象(label)：属性(label)…；--obj 给出该对象每个属性的 comment
  result   --rid <id> --file <mcp_run_process 落盘文件>        v32：从引擎原始返回过滤出命中（result=true）的规则，写 work/<id>/hit-rules.json；
                                                              打印计数（未命中/skip 只计数，不列出）、命中规则小表和漏斗结论
                                                              桶：T=命中，F=未命中且依据确定，U=未命中但所需属性未取得（只计数）
  summary  --rid <id>                                         只读 work/<id>/hit-rules.json（不再读引擎原始返回）；stdin: {"basis":[{"ruleIds":["…"],"text":"一句中文"}],"next":["一句中文"]}
                                                              按漏斗级别校验依据/下一步，渲染 summary（没有 stdin 时列出该级别要写的规则并退出 4）
  build    --rid <id> --rules <规则文件> --props <属性文件>   生成 work/<id>/input-combine.json，做机械校验，
                                                              打印 NEED_VALUE（需模型判断的派生属性）、UNMAPPED、input、最终 notes
           stdin: {"map":{"对象.属性":["条目ID"]},"skip":{"R14":[键…],"R13":[键…],"R10":[键…],"R11":[键…]},
                   "fixedUnmapped":{"A02":"原因"},"toolIssues":["…"],"set":{"对象.属性":[值,"派生:ID,ID｜依据"]}}
                   首次 build 必须带 map/skip（没有则只打印 plan 并退出 4）；之后的 build 自动沿用已保存的 work/<id>/key-map.json，只需补改的部分
  validate --rid <id> --rules <规则文件>                     只做机械校验
"""
import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import combine_tool as ct  # noqa: E402
import detail as dt  # noqa: E402

def die(msg, code=1):
    print("ERROR " + msg)
    sys.exit(code)


RULE_OK_CODES = ("0", "200", "None")   # 规则接口两种成功约定都认：code=0 与 HTTP 风格 code=200（trace e974ced3 的 inst-list-rc-rules 返回 200 被误拒）；None = 没有 code 字段


def rules_list(paths):
    """v41：--rules 可给多个文件（mcp_list_rule 落盘 + inst-rc-rule-mcp 落盘），合并成一个列表；机构规则转成 INST-<名称>。"""
    paths = paths if isinstance(paths, (list, tuple)) else [paths]
    for path in paths:
        data = ct.load(path)
        if isinstance(data, dict) and str(data.get("code")).strip() not in RULE_OK_CODES:
            die("规则返回不是成功码：code=%s msg=%s（%s）" % (data.get("code"), data.get("msg"), path))
    rows = ct.load_rules(paths)
    if not rows:
        die("规则文件里没有 data 或 model 数组：%s" % "、".join(paths))
    return rows


def props_list(path):
    data = ct.load(path)
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        die("属性文件里没有 data 数组：%s" % path)
    return rows


def ref_keys(rules):
    out = {}
    for r in rules:
        for k in ct.cond_keys(r["condition"]):
            o, p = k.split(".")
            if p not in out.setdefault(o, []):
                out[o].append(p)
    return out


def stage_tokens(r):
    m = re.search(r"适用阶段[：:]\s*([^｜|]+)", r.get("comment") or "")
    return [x.strip() for x in re.split(r"[、,，/;；\s]+", m.group(1)) if x.strip()] if m else []


def rule_scope(rules, mp):
    """规则范围由模型依据当次规则与资料决定；未明确排除的规则均保留。"""
    sc = mp.get("rules") or {}
    keep_ids, drop_ids = set(sc.get("keep") or []), dict(sc.get("drop") or {})
    kept, dropped = [], []
    for r in rules:
        rid_ = r.get("ruleId")
        if rid_ in drop_ids and rid_ not in keep_ids:
            dropped.append({"ruleId": rid_, "label": r.get("label"),
                            "stage": "、".join(stage_tokens(r)), "reason": "你判定：" + str(drop_ids[rid_])})
        else:
            kept.append(r)
    return kept, dropped


def cmd_names(a):
    rules = rules_list(a.rules)
    names = list(ref_keys(rules))
    print(json.dumps({"name": names}, ensure_ascii=False))


def cmd_rules(a):
    rules = rules_list(a.rules)
    print("共 %d 条规则" % len(rules))
    for r in rules:
        blob = "%s %s %s" % (r.get("condition", ""), r.get("label", ""), r.get("comment", ""))
        if a.grep:
            if a.grep not in blob:
                continue
            print("%s|%s|%s" % (r["ruleId"], r.get("label"), r.get("condition")))
        else:
            print("%s|%s|%s" % (r["ruleId"], r.get("label"), ",".join(ct.cond_keys(r["condition"]))))


def cmd_props(a):
    props = props_list(a.props)
    if a.obj:
        for o in props:
            if o["name"] == a.obj:
                print("%s(%s)：%s" % (o["name"], o.get("label"), o.get("comment") or ""))
                for p in o.get("properties", []):
                    print("  %s|%s|%s|%s" % (p["name"], p.get("label"), p.get("type", ""), p.get("comment") or ""))
        return
    print("共 %d 个对象" % len(props))
    for o in props:
        ps = o.get("properties", [])
        print("%s(%s)[%d]：%s" % (o["name"], o.get("label"), len(ps), "、".join("%s(%s)" % (p["name"], p.get("label")) for p in ps)))


def outer_connectors(expr):
    """表达式最外层（括号 {} 引号之外）出现的 AND/OR 集合"""
    if not isinstance(expr, str):  # 机构规则的 expression 可能是数组/对象：不判连接词，按 U 保守处理
        return {"?"}
    depth, i, found, q = 0, 0, set(), None
    while i < len(expr):
        c = expr[i]
        if q:
            if c == q:
                q = None
        elif c in "\"'":
            q = c
        elif c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        elif depth == 0:
            m = re.match(r"\s(AND|OR)\s", expr[i:i + 6])
            if m:
                found.add(m.group(1))
                i += len(m.group(0)) - 1
        i += 1
    return found


def bucket(r):
    if str(r.get("result")).lower() == "true":
        return "T"
    reason = r.get("reason") or ""
    if "属性不存在" not in reason and "对象不存在" not in reason:
        return "F"
    if outer_connectors(r.get("expression") or "") == {"AND"} and "不满足" in reason:
        return "F"
    return "U"


MISSING_KEY_RE = re.compile(r"取不到\s*([A-Za-z][A-Za-z0-9]*\.[a-z][a-z0-9_]*)")


def need_rule_list(data, path):
    """引擎有时返回 code=0 但 data.ruleCheckList=null、另有 failures（am8：从入参里取不到 Agency.agency_id）。
    这不是“摘要没有数据”，是引擎没跑起来：打印失败原因和它点名缺的入参键，退出 5。键名取自引擎自己的报错，脚本里不写死。"""
    d = data.get("data") if isinstance(data, dict) else None
    if isinstance(d, dict) and isinstance(d.get("ruleCheckList"), list):
        return d
    fails = data.get("failures") if isinstance(data, dict) else None
    skipped = data.get("skipped") if isinstance(data, dict) else None
    if isinstance(d, dict) and (fails or skipped or "ruleCheckList" in d):
        print("ENGINE_FAILED ruleCheckResult=%s  ruleCheckList=%s" % (d.get("ruleCheckResult"), "null" if d.get("ruleCheckList") is None else type(d.get("ruleCheckList")).__name__))
        keys = []
        for f in (fails or []):
            if isinstance(f, dict):
                print("FAILURE %s｜%s" % (f.get("step"), f.get("reason")))
                for k in MISSING_KEY_RE.findall(str(f.get("reason") or "")):
                    if k not in keys:
                        keys.append(k)
        for f in (skipped or []):
            if isinstance(f, dict):
                print("SKIPPED %s｜%s" % (f.get("step"), f.get("reason")))
        for k in keys:
            print("MISSING_INPUT_KEY %s（引擎自己点名要的入参键，定义里没有也要传：在 build 的 map 里写 {\"%s\":{\"ids\":[标识条目],\"force\":true}}，重跑 build、重新过审核 A 后，最多再调一次引擎）" % (k, k))
        if not keys:
            print("没有点名缺哪个入参键：不重试，按 output skill 第四节写“规则引擎执行失败”。")
        sys.exit(5)
    die("文件里没有 data.ruleCheckList：%s" % path)


def stage_of(r):
    m = re.search(r"适用阶段[：:]\s*([^\s｜|]+)", r.get("comment") or "")
    return m.group(1) if m else ""


def comment_parts(r):
    """comment 形如「描述｜适用阶段：X[｜额外说明…]」。返回 (描述, [额外说明…])。"""
    segs = [x.strip() for x in (r.get("comment") or "").split("｜") if x.strip()]
    desc = segs[0] if segs and not re.match(r"适用阶段[：:]", segs[0]) else ""
    extra = [x for x in segs[1:] if not re.match(r"适用阶段[：:]", x)]
    return desc.rstrip("。"), extra


def ladder():
    return ct.CONFIG["riskLadder"]


def level_of(r):
    """riskMeasure 与漏斗某一级逐字相同才算识别；复合写法、空值都不识别（不猜、不拆分）。"""
    rm = (r.get("riskMeasure") or "").strip()
    for i, x in enumerate(ladder()):
        if x["level"] == rm:
            return i
    return None


def analyze(lst):
    """把引擎返回拆成：已判定行（带桶、级别）、skip 行、漏斗结论。序号与 result 命令的小表一致。"""
    rows, skips, other = [], [], []
    for r in lst:
        res = str(r.get("result")).lower()
        if res in ("true", "false"):
            rows.append({"n": len(rows) + 1, "r": r, "bucket": bucket(r), "lv": level_of(r)})
        elif res == "skip":
            skips.append(r)
        else:
            other.append(r)
    hits = [x for x in rows if x["bucket"] == "T"]
    rec = [x for x in hits if x["lv"] is not None]
    unrec = [x for x in hits if x["lv"] is None]
    if not rows:
        lv, why = None, "无已判定（true/false）的规则"
    elif hits and not rec:
        lv, why = None, "命中规则的处置级别（riskMeasure）都不在漏斗五级内"
    elif rec:
        lv, why = min(x["lv"] for x in rec), ""
    else:
        lv, why = len(ladder()) - 1, ""          # 有已判定规则、一条都没命中：最宽一级
    return {"rows": rows, "skips": skips, "other": other, "hits": hits, "rec": rec, "unrec": unrec, "lv": lv, "why": why,
            "cnt": {b: sum(1 for x in rows if x["bucket"] == b) for b in "TFU"}}


HITS_FILE = "hit-rules.json"


def dropped_rules(rid):
    """v39：build 判定与客户准入无关、组装前已抛掉的规则（input-combine.json 的 rulesDropped）。"""
    fp = os.path.join("work", rid, "input-combine.json") if rid else None
    if not fp or not os.path.isfile(fp):
        return {}
    try:
        return {x["ruleId"]: x for x in ct.load(fp).get("rulesDropped") or [] if x.get("ruleId")}
    except Exception:
        return {}


def make_hits(path, rid=None):
    """从引擎原始返回生成 hit-rules.json 的内容：只保留命中（result=true）的规则全文，未命中/skip 只留计数。
    引擎没跑起来（ruleCheckList=null + failures）时 need_rule_list 打印 ENGINE_FAILED 并退出 5，不生成文件。
    v39：build 判定与准入无关的规则不计入结论和计数（只记条数）。"""
    data = ct.load(path)
    d = need_rule_list(data, path)
    out_scope = dropped_rules(rid)
    lst = [r for r in d["ruleCheckList"] if r.get("ruleId") not in out_scope]
    excluded = [r for r in d["ruleCheckList"] if r.get("ruleId") in out_scope]
    ids = [r.get("ruleId") for r in lst]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    an = analyze(lst)
    lad = ladder()
    first_stage = ct.CONFIG["stageOrder"][0]
    sk_later = sum(1 for r in an["skips"] if stage_of(r) and stage_of(r) != first_stage)
    hits = []
    for x in an["hits"]:
        r = x["r"]
        hits.append({"ruleId": r.get("ruleId"), "ruleName": r.get("ruleName"),
                     "riskMeasure": (r.get("riskMeasure") or "").strip(),
                     "level": lad[x["lv"]]["level"] if x["lv"] is not None else None,
                     "atConclusionLevel": an["lv"] is not None and x["lv"] == an["lv"],
                     "reason": r.get("reason") or "", "comment": r.get("comment") or "",
                     "stage": stage_of(r), "ruleSource": r.get("ruleSource") or "",
                     "expression": r.get("expression")})
    with open(path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    return {
        "source": {"path": path, "sha256": sha, "ruleCheckResult": d.get("ruleCheckResult"),
                   "allRuleIds": ids},   # 只供脚本校验“文字里不含规则 ID”，不是给模型读的
        "counts": {"total": len(lst), "judged": len(an["rows"]), "hit": an["cnt"]["T"], "missDetermined": an["cnt"]["F"],
                   "missAttrAbsent": an["cnt"]["U"], "skip": len(an["skips"]), "skipLaterStage": sk_later,
                   "unknownStatus": len(an["other"]), "duplicateRuleIds": dup,
                   "outOfScope": len(excluded), "outOfScopeHit": sum(1 for r in excluded if str(r.get("result")).lower() == "true")},
        "funnel": {"order": [x["level"] for x in lad],
                   "level": lad[an["lv"]]["level"] if an["lv"] is not None else None,
                   "title": lad[an["lv"]]["title"] if an["lv"] is not None else None,
                   "why": an["why"]},
        "hits": hits,
    }


def hits_path(rid):
    return os.path.join("work", rid, HITS_FILE)


def save_hits(rid, doc):
    os.makedirs(os.path.join("work", rid), exist_ok=True)
    with open(hits_path(rid), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)


def load_hits(rid):
    fp = hits_path(rid)
    if not os.path.isfile(fp):
        die("没有 %s：先运行 combine.py result --rid %s --file <mcp_run_process 的落盘 path>" % (fp, rid))
    return ct.load(fp)


def cmd_result(a):
    doc = make_hits(a.file, a.rid)
    c, fn = doc["counts"], doc["funnel"]
    if a.rid:
        save_hits(a.rid, doc)
    print("ruleCheckResult=%s  总条数=%d  已判定=%d（命中 T=%d，未命中 F=%d U=%d）  skip=%d%s%s" % (
        doc["source"]["ruleCheckResult"], c["total"], c["judged"], c["hit"], c["missDetermined"], c["missAttrAbsent"], c["skip"],
        ("  未知状态=%d" % c["unknownStatus"]) if c["unknownStatus"] else "",
        ("  重复ruleId=%s" % ",".join(c["duplicateRuleIds"])) if c["duplicateRuleIds"] else ""))
    if c.get("outOfScope"):
        print("OUT_OF_SCOPE %d 条规则在组装前已判定与客户准入无关，不计入结论（其中引擎给出命中 %d 条）" % (c["outOfScope"], c.get("outOfScopeHit", 0)))
    if a.rid:
        print("HITS_FILE %s  命中 %d 条（未命中与 skip 只计数、不写入）" % (hits_path(a.rid), len(doc["hits"])))
    print("命中规则：ruleId|riskMeasure|漏斗级别|ruleName|comment描述(前60字)")
    for h in doc["hits"]:
        print("%s|%s|%s|%s|%s" % (h["ruleId"], h["riskMeasure"] or "（空）", h["level"] or "未识别", h["ruleName"],
                                  comment_parts(h)[0][:60]))
    if not doc["hits"]:
        print("（无命中）")
    print("FUNNEL 顺序：" + " > ".join(fn["order"]))
    if fn["level"] is None:
        print("FUNNEL_LEVEL 无（%s）" % fn["why"])
    else:
        print("FUNNEL_LEVEL %s｜%s" % (fn["level"], fn["title"]))
    print("FUNNEL_HITS " + "；".join("%s:%s" % (lv, ",".join(h["ruleId"] for h in doc["hits"] if h["level"] == lv) or "-") for lv in fn["order"]))
    for h in doc["hits"]:
        if h["level"] is None:
            print("FUNNEL_UNRECOGNIZED %s|%s|riskMeasure=%s" % (h["ruleId"], h["ruleName"], h["riskMeasure"] or "（空）"))
    if c["duplicateRuleIds"] or c["unknownStatus"]:
        print("WARN 重复 ruleId 或未知状态：结果不完整，不给结论，不按片段宣称计数")
    if not a.rid:
        print("下一步：combine.py summary --rid <requestId>（只读 hit-rules.json），按 output skill 第三节写依据/下一步草稿")
    elif c["duplicateRuleIds"] or c["unknownStatus"]:
        print("下一步：结果不完整，按 output skill 第四节写“摘要未完成”")
    elif fn["level"] is None:
        print("NO_DRAFT 暂无结论：不用写草稿，直接运行 combine.py summary --rid %s（不带 stdin）" % a.rid)
    else:              # v37：直接给出写草稿要的内容，省掉一轮“不带 stdin 的 summary”
        print_need_basis(a.rid, doc)
        print("下一步：写好草稿后运行 combine.py summary --rid %s，草稿放 stdin" % a.rid)


def unsent_keys(rid, expression):
    """v36：命中规则的条件里引用、但没有传给引擎的属性（input-combine.json 的 unfilled）。
    v35-am6：RULE-GATE-003 “用工场景为空”命中，其实是申报的交付要求「内部管理系统」没有可用的分类编码、被脚本丢弃，摘要却写成“申报为空”。"""
    fp = os.path.join("work", rid, "input-combine.json")
    if not expression or not os.path.isfile(fp):
        return []
    try:
        unf = ct.load(fp).get("unfilled") or {}
    except Exception:
        return []
    out = []
    for k in ATTR_RE.findall(expression):
        o, _, p = k.partition(".")
        if any(p in ps for ps in (unf.get(o) or {}).values()) and k not in out:
            out.append(k)
    return out


def print_unsent_hint(rid, rules):
    for r in rules:
        ks = unsent_keys(rid, r.get("expression"))
        if ks:
            print("  注意 %s：条件涉及的属性 %s 没有传给引擎（缺值或口径缺失，原因见 unresolvedProperties）。依据/下一步不要写成“申报为空/对方没填”；"
                  "提取明细里确有相关原文时，写成“已提交相关信息，但系统未能自动归类，需人工确认”，明细里没有原文才写“未提供”；文字里不写属性名、编码等技术词。" % (r["ruleId"], "、".join(ks)))


# 各级别“下一步”该写什么（NEED_BASIS 里原样提示；口径来自业务方）
NEXT_HINT = {
    "拦截": "命中了拦截规则：结合提交资料和规则 comment，告诉对方怎么改正。",
    "建议拦截": "有风险点：转人工核验；结合提交资料，告诉对方怎么降低风险点。",
    "转人工": "有嫌疑点或不足点：转人工核验；结合提交资料，告诉对方怎么降低违规嫌疑，或补充哪些佐证消除嫌疑点，或怎么提高不足点。",
}
# v37：结论级别之外的其余命中级别（通过级除外，它没有要处理的事项）按各自口径并入“下一步”
OTHER_HINT = {
    "拦截": "该规则命中拦截级：告诉对方怎么改正；这是结论之外必须一并处理的事项。",
    "建议拦截": "转人工核验，并告诉对方怎么降低这个风险点。",
    "转人工": "转人工核验，并告诉对方怎么降低违规嫌疑，或补充哪些佐证消除嫌疑点，或怎么提高这个不足点。",
}


ATTR_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*\.[a-z][a-z0-9_]*")
QUOTE_RE = re.compile(r"「([^」]{2,})」")
FIELD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\[\d*\])?")
BASIS_LEN, NEXT_LEN = (4, 220), (4, 300)
RELEASE_BASIS = (4, 6)                                   # 通过：夸资料，5 条左右
MAX_NEXT = 8


def evidence_text(rid):
    """提取明细里所有“有值”条目的 value 和 source、以及材料依据：「」引文必须逐字出自这里（提交的资料原文）。"""
    fp = os.path.join("work", rid, "input-extract-detail.json")
    if not os.path.isfile(fp):
        return None
    doc = ct.load(fp)
    parts = []
    for x in doc.get("items", []):
        if (x.get("source") or "").startswith("Y｜"):
            parts += [x.get("value") or "", x["source"]]
    for v in (doc.get("materials") or {}).values():
        if isinstance(v, list) and len(v) > 1:
            parts.append(str(v[1]))
    return "\n".join(parts)


def quote_ok(q, hay):
    """「」里的引文必须逐字出自提交的资料；允许用…省略中间。没有明细文件时不核对（调用方已 WARN）。"""
    if hay is None:
        return True
    parts = [p.strip() for p in re.split(r"…+|\.{3,}", q) if len(p.strip()) >= 2]
    nh = ct.norm_text(hay)               # 传给引擎的值已统一标点/空格，引用统一后的写法也算原文
    return bool(parts) and all(p in hay or ct.norm_text(p) in nh for p in parts)


def jstr(x):
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def check_text(where, text, size, hay, rule_ids):
    """一句话的通用校验，返回错误文字或 None。"""
    if not isinstance(text, str):
        return "%s 的 text 应是字符串" % where
    text = text.strip()
    if not (size[0] <= len(text) <= size[1]) or "\n" in text:
        return "%s 须是 %d–%d 字的一句话，不含换行" % (where, size[0], size[1])
    if "【" in text or "】" in text or ATTR_RE.search(text) or any(len(str(i)) >= 6 and str(i) in text for i in rule_ids if i):
        return "%s 不得含规则 ID、英文属性名或【】：%s" % (where, text[:40])
    fields = [q for q in QUOTE_RE.findall(text) if FIELD_RE.fullmatch(q.strip())]
    if fields:                          # v33：am1 用「dlvrDemd」「projCont」绕过引文校验，摘要里出现英文字段名
        return "%s 的「」里写资料原文，不写字段名：%s（字段名用中文说，如“交付要求”，不加「」）" % (where, "、".join(fields)[:60])
    tech = tech_terms(text)
    if tech:                            # v39：summary 给客户看，不出现字段变量、清单编号、原因码和技术用语
        return "%s 要写给客户看，用业务用语，不出现技术词或代号：%s。%s" % (where, "、".join(tech[:4]), plain_tip(tech))
    bad = [q for q in QUOTE_RE.findall(text) if not quote_ok(q, hay)]
    if bad:
        near = near_quotes(bad[0], hay)
        tip = ("。提交资料里最接近的原文：%s——要么逐字抄其中一段，要么去掉「」改用自己的话、不写具体原文" % " / ".join("「%s」" % x for x in near)
               if near else "。提交资料里找不到相近原文：去掉「」，改用自己的话概括，不写具体原文")
        return "%s 的「」引文不是提交资料里的原文（须逐字引用，可用…省略中间）：%s%s" % (where, "、".join(bad)[:60], tip)
    return None


# v39：给客户看的文字里不允许的代号与技术词（「」里的资料原文不查）
ITEM_ID_RE = re.compile(r"(?<![A-Za-z0-9])[A-J]\d{2}(?![0-9])")
RCODE_RE = re.compile(r"(?<![A-Za-z0-9])R\d{2}(?![0-9])")
CODE_RE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]+_[A-Za-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]*|[A-Z][a-z]+[A-Z][A-Za-z0-9]*)(?![A-Za-z0-9])")
CJK_GAP_RE = re.compile(r"(?<=[\u4e00-\u9fa5「」，。；：、（）])\s+|\s+(?=[\u4e00-\u9fa5「」，。；：、（）])")


def unquoted(text):
    return QUOTE_RE.sub("", text or "")


def tech_terms(text):
    t = unquoted(text)
    pl = ct.CONFIG.get("plainLanguage") or {}
    out = []
    out += ["清单编号" + m for m in ITEM_ID_RE.findall(t)]
    out += ["原因码" + m for m in RCODE_RE.findall(t)]
    out += ["代号" + m for m in CODE_RE.findall(t)]
    out += [w for w in pl.get("jargon", []) if w in t]
    return list(dict.fromkeys(out))


def plain_tip(tech):
    sug = (ct.CONFIG.get("plainLanguage") or {}).get("suggest") or {}
    hints = ["“%s”改说“%s”" % (w, sug[w]) for w in tech if w in sug]
    base = "材料和栏位用中文名（如“营业执照经营范围”“项目内容”），不写编号、英文名和原因码"
    return "；".join(hints[:3] + [base])


def plain(text, rid=None):
    """v39：脚本生成的“注意”、宽松补齐的话术给客户看之前，把代号换成业务用语（「」里的资料原文不动）。"""
    pl = ct.CONFIG.get("plainLanguage") or {}
    names = {}
    fp = os.path.join("work", rid, "input-extract-detail.json") if rid else None
    if fp and os.path.isfile(fp):
        names = {x["id"]: x["name"].replace(".", "") for x in ct.load(fp).get("items", [])}

    def fix(seg):
        seg = zh_names(seg)
        for k in sorted(pl.get("fieldNames") or {}, key=len, reverse=True):
            seg = re.sub(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(k), pl["fieldNames"][k], seg)
        val = r"(?:\s*=\s*[0-9A-Za-z.\-]+(?:[（(][^）)]{0,6}[）)])?)?"
        seg = re.sub(r"工商[:：]?\s*[DBT]\.[A-Za-z_.]+" + val, "工商登记信息", seg)
        seg = re.sub(r"(?<![A-Za-z0-9])[DBT]\.[A-Za-z_.]+" + val, "工商登记信息", seg)
        seg = ATTR_RE.sub("相关信息", seg)
        seg = ITEM_ID_RE.sub(lambda m: names.get(m.group(0), "相关资料"), seg)
        seg = re.sub(r"[｜|]?\s*" + RCODE_RE.pattern + r"\s*[｜|]?", "，", seg)
        seg = re.sub(r"(?<![A-Za-z])ReadVideo(?![A-Za-z])", "视频识别", seg)
        seg = CODE_RE.sub("系统", seg)
        seg = seg.replace("｜", "，")
        return re.sub(r"[，,]{2,}", "，", seg)

    parts = re.split(r"(「[^」]*」)", text or "")
    out = "".join(p if p.startswith("「") else fix(p) for p in parts)
    out = re.sub(r"[（(]\s*[，,]?\s*[）)]", "", out)
    out = CJK_GAP_RE.sub("", out)
    return re.sub(r"[，,]+(?=[。；;）)]|$)", "", out).strip("，, ")


DOC_PREFIX = {"B": "营业执照"}          # 比对项 label 里没带材料名的才补（C02/D01/D08/G02 的 label 自带）
CLAUSE_TAIL = re.compile(r"[（(]\s*(?:未作为已核实|未裁决)\s*[）)]")


def att_name(field):
    base = re.sub(r"\[\d*\]$", "", field)
    return ct.CONFIG["attachmentNames"].get(base, base)


def zh_names(text):
    """把文本里的附件字段名（bizlicUrl、officeVideoUrl[0]…）换成中文名。"""
    for f in sorted(ct.CONFIG["attachmentNames"], key=len, reverse=True):
        text = re.sub(re.escape(f) + r"(?:\[\d*\])?", ct.CONFIG["attachmentNames"][f], text)
    return text


def clip(v, n=60):
    v = (v or "").strip()
    return v if len(v) <= n else v[:n] + "…"


def scope_items(t):
    t = re.sub(r"[（(]\s*除依法须经批准.*?[）)]\s*$", "", (t or "").strip())
    t = re.sub(r"^\s*(?:一般项目|许可项目)[:：]", "", t).rstrip("。 ")
    return [x.strip() for x in re.split(r"[；;]", t) if x.strip()]


def diff_sentence(o_id, label, kind, orig, biz, outcome, first, second):
    """工商与材料不一致 → 准入校验口径的一句话：写清材料上是什么、工商是什么，不裁决真假，请申请方核实。"""
    name = DOC_PREFIX.get(o_id[0], "") + label
    if kind == "money":                  # 工商 J08 是“注册资本500万元；实收资本…；币种…”的拼接，只取注册资本一项
        biz = (biz or "").split("；")[0].replace("注册资本", "")
    if outcome == "unstable":
        return "%s：回看原件两次识别结果不同（「%s」与「%s」），工商登记为「%s」，需人工核对原件。" % (name, clip(first), clip(second), clip(biz))
    if outcome == "unreadable":
        return "%s：材料上的内容无法确认（首次识别为「%s」），工商登记为「%s」，请重新提供清晰原件。" % (name, clip(first), clip(biz))
    tail = "（已回看原件二次确认）" if outcome == "confirmed_diff" else ""
    if kind == "scope":
        a, b = scope_items(orig), scope_items(biz)
        only_a, only_b = [x for x in a if x not in b], [x for x in b if x not in a]
        parts = []
        if only_a:
            parts.append("材料上有而工商没有：%s" % "、".join(clip(x, 30) for x in only_a[:4]) + ("等" if len(only_a) > 4 else ""))
        if only_b:
            parts.append("工商有而材料上没有：%s" % "、".join(clip(x, 30) for x in only_b[:4]) + ("等" if len(only_b) > 4 else ""))
        if parts:
            return "%s与工商登记不一致%s：%s。请核实并说明原因。" % (name, tail, "；".join(parts))
        return "%s与工商登记表述不同%s：材料上为「%s」，工商登记为「%s」。请核实。" % (name, tail, clip(orig), clip(biz))
    return "%s与工商登记不一致%s：材料上为「%s」，工商登记为「%s」。请核实并说明原因。" % (name, tail, clip(orig), clip(biz))


HEDGE_RE = re.compile(r"[，,；;]?\s*(?:仅作提示|仅凭招牌不符不能判断场所虚构|不裁决真假|请申请方核实)?[，,]?\s*未作为已核实(?:结论)?")


def model_conflict_redundant(c):
    """v37：模型写进 conflicts、但“注意”里已由脚本按比对结果生成的事项，不再重复（v35-am5 把经营范围、注册资本又写了一遍）；
    只差括号全半角/空白的“冲突”（v35-am2 租赁合同承租方）和“待比对”这类没有结论的话也不进“注意”。"""
    if "工商" in c or "待比对" in c:
        return True
    qs = QUOTE_RE.findall(c)
    return len(qs) >= 2 and len({dt.nfkc_name(q) for q in qs}) == 1


def dedupe_names(t):
    """“办公场所视频 办公场所视频 …”“办公场所视频、办公场所视频”这类模型原文里自带中文名、再被换名后的重复，只留一个。"""
    for n in sorted(set(ct.CONFIG["attachmentNames"].values()), key=len, reverse=True):
        t = re.sub(r"(%s)(?:[\s、，,：:]+\1)+" % re.escape(n), r"\1", t)
    return t


def attention_lines(rid):
    """“注意”段（脚本生成，不经模型）：把 notes.conflicts 整理成准入校验口径的话，再加附件超时/未提供。
    ①材料与工商不一致：由比对结果结构化生成（材料值、工商值分别是什么）；②模型写进 conflicts 的其他冲突（如视频招牌与申报名称不同）
    做字段名中文化后保留；③附件：超时/失效、不可读、请求未提供。没有任何事项返回空表（不输出这一段）。"""
    fp = os.path.join("work", rid, "input-extract-detail.json")
    if not os.path.isfile(fp):
        return []
    doc = ct.load(fp)
    st_fp = os.path.join("work", rid, ".detail-state.json")
    st = dt.load_json_file(st_fp) if os.path.isfile(st_fp) else {}
    by = {x["id"]: x for x in doc["items"]}
    rc = st.get("rechecked") or {}
    out = []
    for o, b, label, kind in dt.PAIRS:
        if o not in by or b not in by:
            continue
        r = rc.get(o) or {}
        both = by[o]["source"].startswith("Y｜") and by[b]["source"].startswith("Y｜")
        if both and not dt.same_fact(kind, by[o]["value"], by[b]["value"]):
            out.append(diff_sentence(o, label, kind, by[o]["value"], by[b]["value"], r.get("outcome"), r.get("first"), r.get("second")))
        elif r.get("outcome") in ("unstable", "unreadable") and by[b]["source"].startswith("Y｜"):
            out.append(diff_sentence(o, label, kind, None, by[b]["value"], r["outcome"], r.get("first"), r.get("second")))
    auto = set(st.get("autoConflicts") or []) | {r.get("conflict") for r in rc.values() if r.get("conflict")}
    for c in (doc.get("notes") or {}).get("conflicts", []):
        if c in auto or model_conflict_redundant(c):
            continue
        t = CLAUSE_TAIL.sub("", c).strip().rstrip("。；")
        t = HEDGE_RE.sub("", t).strip().rstrip("，,。；")
        m = re.match(r"^(%s)(?:\[\d*\])?\s+(.+)$" % "|".join(map(re.escape, ct.CONFIG["attachmentNames"])), t)
        t = "%s：%s" % (ct.CONFIG["attachmentNames"][m.group(1)], zh_names(m.group(2))) if m else zh_names(t)
        t = dedupe_names(t)
        if "视频" in t or "办公场所" in t:
            t += "，仅作提示，未作为已核实结论"
        out.append(t + "。")
    # 附件：超时/失效、不可读、请求未提供
    cfg = ct.CONFIG["attachmentIssue"]
    covered, timeout, invalid, unread, absent = set(), [], [], [], []
    for f, code in (st.get("invalid") or {}).items():
        covered.add(f)
        (timeout if "TIMEOUT" in str(code).upper() else invalid).append(att_name(f))
    for f, v in (doc.get("materials") or {}).items():
        base = re.sub(r"\[\d*\]$", "", f)
        if base in covered:
            continue
        if v[0] == "不可读":
            covered.add(base)
            unread.append("%s（%s）" % (att_name(f), clip(v[1], 40)))
        elif v[0] == "未提供":
            covered.add(base)
            absent.append(att_name(f))
    if timeout:
        out.append("%s：%s，相关核验未进行，请重新提供。" % ("、".join(dict.fromkeys(timeout)), cfg["TIMEOUT"]))
    if invalid:
        out.append("%s：%s，相关核验未进行，请重新提供。" % ("、".join(dict.fromkeys(invalid)), cfg["default"]))
    if unread:
        out.append("以下材料无法读取：%s，相关内容未核验。" % "、".join(dict.fromkeys(unread)))
    if absent:
        out.append("本次未提供：%s，相关核验按未提供处理。" % "、".join(dict.fromkeys(absent)))
    for m in (doc.get("notes") or {}).get("unreadMaterials", []):      # 模型补记的（如视频读取失败及实际尝试次数）
        f, _, why = m.partition("｜")
        if re.sub(r"\[\d*\]$", "", f) in covered or m.startswith("@auto:"):
            continue
        out.append("%s读取失败：%s。" % (att_name(f), zh_names(why).rstrip("。")))
    out += flex_job_notes(by)
    return list(dict.fromkeys(plain(x, rid) for x in out))


def flex_job_notes(by):
    """v39：灵工禁入/受限行业里招临时辅助岗位的例外提醒（如金融公司招展会临时工作人员、地推人员）。只提醒，不改结论。"""
    cfg = ct.CONFIG.get("flexJobException") or {}
    if not cfg:
        return []

    def texts(ids):
        return [(i, by[i]["value"]) for i in ids if i in by and by[i]["source"].startswith("Y｜") and isinstance(by[i]["value"], str)]

    ind_text = " ".join(v for _, v in texts(cfg["sources"]["industry"]))
    jobs = texts(cfg["sources"]["job"])
    job_text = " ".join(v for _, v in jobs)
    out = []
    for ind in cfg.get("industries") or []:
        if not any(w in ind_text for w in ind["words"]):
            continue
        if any(w in job_text for w in ind.get("notJobs") or []):
            continue
        hit = next((w for w in cfg["flexJobs"] if w in job_text), None)
        if not hit:
            continue
        src = next(v for _, v in jobs if hit in v)
        k = src.index(hit)
        seg = re.split(r"[，,。；;\n]", src[:k])[-1] + re.split(r"[，,。；;\n]", src[k:])[0]     # 含岗位词的那一小句原文
        out.append(cfg["text"].format(industry=ind["name"], job=clip(seg.strip(), 30)))
    return out


# v42：清单条目的 notice（[{"condition","desc"}]）：哪条 condition 命中由模型在草稿 notice 里按语义判断，
# desc 原样（换成业务用语后）进“注意”，作为依据/下一步的补充；依据/下一步已写过的不重复。
NOTICE_PUNCT = re.compile(r"[\s，,。；;：:、「」“”\"'（）()！!？?]")


# 比较类 condition：和'<清单条目名称>'不一致 / 一致——两侧都有值时由脚本判定（忽略空白和括号全半角），不交给模型
NOTICE_CMP = re.compile(r"^和\s*['‘’“”「」]?(.+?)['‘’“”「」]?\s*(不一致|一致)$")


def notice_candidates(rid):
    """清单里带 notice 的条目与本次明细行：[(清单条目, 明细行, {条目名称: 明细行})]。"""
    fp = os.path.join("work", rid, "input-extract-detail.json")
    if not os.path.isfile(fp):
        return []
    items = dt.load_items()
    by = {x["id"]: x for x in ct.load(fp).get("items", [])}
    by_name = {it["name"]: by[it["id"]] for it in items if it["id"] in by}
    return [(it, by[it["id"]], by_name) for it in items if it.get("notice") and it["id"] in by]


def has_value(row):
    return bool(row) and (row.get("source") or "").startswith("Y｜") and row.get("value") is not None


def notice_compare(cond, row, by_name):
    """比较类 condition 的脚本判定：True/False；不是比较类、对方条目不存在或任一侧没有值时 None（交给模型）。"""
    m = NOTICE_CMP.match(cond.strip())
    if not m or m.group(1) not in by_name:
        return None
    other = by_name[m.group(1)]
    if not (has_value(row) and has_value(other)):
        return None
    same = dt.nfkc_name(str(row["value"])) == dt.nfkc_name(str(other["value"]))
    return same if m.group(2) == "一致" else not same


def notice_literal(it, row, by_name):
    """值与 condition 字面相同（忽略大小写、首尾空白）的条件，或脚本判定成立的比较类条件：仅作预判，没有草稿或草稿没给 notice 时用。"""
    if not has_value(row):
        return []
    v = str(row["value"]).strip().lower()
    return [n["condition"].strip() for n in it["notice"]
            if n["condition"].strip().lower() == v or notice_compare(n["condition"], row, by_name)]


def pick_notices(rid, picks, covered):
    """校验模型选的 notice（picks=None 时用字面预判），返回 (要进“注意”的话, 丢弃说明)。不合格只丢弃、不退回。"""
    cands = {it["id"]: (it, row, by_name) for it, row, by_name in notice_candidates(rid)}
    if not cands:
        return [], []
    dropped = []
    if picks is None:
        picks = [{"id": i, "condition": c} for i, (it, row, by_name) in cands.items() for c in notice_literal(it, row, by_name)]
    elif not isinstance(picks, list):
        return [], ["notice 不是数组，已忽略"]
    else:                                # 比较类条件以脚本判定为准：成立的补上，不成立的去掉
        decided = {(i, n["condition"].strip()): notice_compare(n["condition"], row, by_name)
                   for i, (it, row, by_name) in cands.items() for n in it["notice"]}
        for p in picks:
            if isinstance(p, dict) and decided.get((str(p.get("id", "")).strip(), str(p.get("condition", "")).strip())) is False:
                dropped.append("%s「%s」脚本比对两侧一致/不一致结论相反，已去掉" % (p["id"], p["condition"]))
        picks = [p for p in picks if not (isinstance(p, dict) and decided.get(
            (str(p.get("id", "")).strip(), str(p.get("condition", "")).strip())) is False)]
        picks += [{"id": i, "condition": c} for (i, c), ok in decided.items() if ok]
    seen_text = NOTICE_PUNCT.sub("", " ".join(covered))
    out, seen = [], set()
    for k, p in enumerate(picks, 1):
        if not (isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("condition"), str)):
            dropped.append('notice[%d] 格式应为 {"id":"条目ID","condition":"清单里的条件原文"}' % k)
            continue
        i, c = p["id"].strip(), p["condition"].strip()
        if i not in cands:
            dropped.append("notice[%d] 的 %s 不是带 notice 的条目" % (k, i))
            continue
        n = next((x for x in cands[i][0]["notice"] if x["condition"].strip() == c), None)
        if n is None:
            dropped.append("notice[%d] 的条件「%s」不在 %s 的 notice 里（须逐字抄清单里的 condition）" % (k, c, i))
            continue
        if (i, c) in seen:
            continue
        seen.add((i, c))
        t = plain(n["desc"], rid).strip().rstrip("。；;")
        key = NOTICE_PUNCT.sub("", t)
        if key and key in seen_text:
            dropped.append("notice[%d] %s「%s」依据/下一步已写过，不重复" % (k, i, t))
            continue
        if t + "。" not in out:          # 成对条目（如 B02/J06）desc 相同，只留一条
            out.append(t + "。")
    return out, dropped


def print_notice_hint(rid):
    cands = notice_candidates(rid)
    if not cands:
        return
    print("NOTICE 以下条目配置了“注意”提醒（id|名称|本次值|依据/原因｜可选条件 condition=>告知内容）。按语义判断本次哪条 condition 成立"
          "（condition 有时是值、有时是文字描述），成立的写进草稿 notice；依据或下一步已经说过同一件事的不要选，"
          "notice 只作依据/下一步的补充；analysis 也不要重复。脚本把 desc 原样放进“注意”，你不用写这句话：")
    for it, row, by_name in cands:
        src = (row.get("source") or "（待填）")
        pre = notice_literal(it, row, by_name)
        print("  %s|%s|%s|%s｜%s%s" % (it["id"], it["name"], row.get("value"), clip(src, 80),
                                     "；".join("%s=>%s" % (n["condition"], n["desc"]) for n in it["notice"]),
                                     "（字面预判：%s）" % "、".join(pre) if pre else ""))
    print('  草稿 notice 写法：[{"id":"条目ID","condition":"清单里的 condition 原文"}]；都不成立写 []。不写 notice 字段时脚本按字面预判。'
          "形如“和'某条目'不一致”的比较类条件由脚本比对两侧值自动判定，不用你选。")


def need_basis_ctx(doc):
    """结论级别、该级别命中、其余级别命中（通过级除外）。summary 与 result 共用。"""
    lad, fn, hits = ladder(), doc["funnel"], doc["hits"]
    levels = [x["level"] for x in lad]
    lv = levels.index(fn["level"]) if fn["level"] in levels else None
    L = lad[lv] if lv is not None else None
    release = lv is not None and lv == len(lad) - 1
    at_level = [h for h in hits if L and h["level"] == L["level"]]
    rec = [h for h in hits if h["level"] is not None]
    other_lv = [h for h in rec if L and h["level"] != L["level"] and h["level"] != lad[-1]["level"]]
    return lv, L, release, at_level, other_lv


def print_need_basis(rid, doc):
    lv, L, release, at_level, other_lv = need_basis_ctx(doc)
    print("NEED_BASIS 结论级别：%s｜%s" % (L["level"], L["title"]))
    if release:
        print("通过：没有命中需拦截/转人工的规则。依据写 %d–%d 条（约 5 条）：围绕已提交的资料，列举哪些资料真实、合规（每条指明哪份资料、哪个栏位，只写提取明细里有原文证据的）；下一步由脚本固定，不用写。" % RELEASE_BASIS)
    else:
        print("命中该级别的规则（依据必须逐条覆盖，围绕 comment 举证；ruleId|ruleName|reason|comment 全文）：")
        for r in at_level:
            print("%s|%s|%s|%s" % (r["ruleId"], r.get("ruleName"), (r.get("reason") or "")[:100], r.get("comment") or ""))
        print_unsent_hint(rid, at_level)
        print("下一步：%s" % NEXT_HINT[L["level"]])
    if other_lv and not release:
        print("其余命中级别的规则（不是结论级别，不写进依据；每条必须在“下一步”里有一条带 ruleIds 的事项，告诉对方怎么处理或注意什么；ruleId|级别|ruleName|reason|comment 全文）：")
        for r in other_lv:
            print("%s|%s|%s|%s|%s" % (r["ruleId"], r["level"], r.get("ruleName"), (r.get("reason") or "")[:100], r.get("comment") or ""))
        print_unsent_hint(rid, other_lv)
        for lvn in dict.fromkeys(h["level"] for h in other_lv):
            print("  %s级的口径：%s" % (lvn, OTHER_HINT[lvn]))
    fp_ = os.path.join("work", rid, "input-extract-detail.json")
    if os.path.isfile(fp_) and flex_job_notes({x["id"]: x for x in ct.load(fp_)["items"]}):
        print("FLEX_JOB 企业属灵工受限行业，但本次招聘的是临时辅助岗位：脚本已在“注意”里写了例外提醒。命中行业类规则时，下一步可建议对方补充岗位说明（工作内容、地点、时长，说明不涉及本行业业务），供人工核实；不要在依据里否定规则结论，也不要在 analysis 里重复。")
    print_notice_hint(rid)
    q = quotable(rid)
    if q:
        print("可放进「」的原文（逐字抄，可用…省略中间；不在这里、也不在明细里的内容不要加「」）：")
        for name, v in q:
            print("  %s：%s" % (name, clip(v, 120)))
    print("analysis（agent全局分析，仅供参考，0–%d 条，每条 %d–%d 字一句话）：结合本次全部资料，写规则没有覆盖或没能判定、但审核人应该留意的问题或建议，"
          "如项目内容/交付要求暗示的业务模式与经营范围、开票类目不符，材料之间日期/主体/金额对不上，关键材料缺失导致多条规则跳过，"
          "附件类型与字段要求不符等；只写提取明细里有依据的现象，用“疑似/建议核实”表述，不下违规结论，不写规则ID/属性名；没有就不写。"
          "这一项不合格只会被丢弃，不会退回。" % ((MAX_ANALYSIS,) + ANALYSIS_LEN))
    print('草稿格式：{"basis":[{"ruleIds":["…"],"text":"一句中文"}],"next":["一句中文",{"ruleIds":["其余级别规则ID"],"text":"一句中文"}],"notice":[{"id":"条目ID","condition":"条件原文"}],"analysis":["一句中文"]}（next 里只有覆盖其余级别规则的事项需要带 ruleIds；通过级只写 basis，ruleIds 可省；文字不含规则ID/英文属性名/【】，引用资料原文放「」里逐字）')
    print("草稿被拒 %d 次后，下一次提交由脚本丢弃不合格的条目并用规则说明补齐，不再退回。" % LENIENT_AFTER)


# v38：summary 防死循环。v37 job_54 把一段材料里没有的「引文」改了 29 次标点，最后模型调用报错，整单 UPSTREAM_TASK_FAILED。
# 草稿被拒 LENIENT_AFTER 次后，下一次提交进入宽松模式：不合格的条目直接丢弃（不再退回），缺的依据/下一步由脚本用规则说明补齐，保证结束。
LENIENT_AFTER = 2
TRIES_FILE = ".summary-tries.json"
ANALYSIS_LEN, MAX_ANALYSIS = (6, 200), 3
QUOTE_SRC = (("A07", "交付要求"), ("A08", "项目内容"), ("A10", "开票类目"), ("B08", "经营范围"))


def tries_path(rid):
    return os.path.join("work", rid, TRIES_FILE)


def load_tries(rid):
    fp = tries_path(rid)
    return int((ct.load(fp) or {}).get("rejected", 0)) if os.path.isfile(fp) else 0


def save_tries(rid, n):
    os.makedirs(os.path.join("work", rid), exist_ok=True)
    with open(tries_path(rid), "w", encoding="utf-8") as f:
        json.dump({"rejected": n}, f)


def quotable(rid):
    """可直接放进「」的请求/执照原文（明细里为 Y 的），NEED_BASIS 和引文报错时给模型照抄。"""
    fp = os.path.join("work", rid, "input-extract-detail.json")
    if not os.path.isfile(fp):
        return []
    by = {x["id"]: x for x in ct.load(fp)["items"]}
    out = []
    for i, name in QUOTE_SRC:
        x = by.get(i)
        if x and (x.get("source") or "").startswith("Y｜") and x.get("value"):
            out.append((name, x["value"]))
    return out


def near_quotes(q, hay, n=3):
    """被拒引文最接近的原文片段（按共有字符数），报错时附上，让模型改成逐字抄写而不是反复改标点。"""
    segs = {x.strip() for x in re.split(r"[\n｜；;。]", hay or "") if 4 <= len(x.strip()) <= 120}
    qs = set(q)
    best = sorted(segs, key=lambda x: (-len(qs & set(x)), len(x)))[:n]
    return [clip(x, 40) for x in best if qs & set(x)]


def why_plain(why):
    return ((ct.CONFIG.get("plainLanguage") or {}).get("whyText") or {}).get(why, why)


def fallback_basis(r):
    desc, _ = comment_parts(r)
    return plain("%s%s" % (r.get("ruleName") or "审核要求", "：" + desc if desc else "未满足"))


def fallback_next(r, other=False):
    desc, _ = comment_parts(r)
    head = "另请处理“%s”" % r.get("ruleName") if other else "关于“%s”" % r.get("ruleName")
    desc = desc or "请按审核要求处理"
    return plain("%s：%s，请补充或更正相关资料后重新提交%s" % (head, desc, "" if "人工" in desc else "，我们将安排人工核验"))


def check_analysis(items, hay, ids, rid=None):
    """全局分析（仅供参考）：只丢弃不合格的条目，从不退回，避免新的死循环。v39：先把代号换成业务用语再校验。"""
    ok, dropped = [], []
    if not isinstance(items, list):
        return ok, ["analysis 不是数组，已忽略"] if items is not None else []
    for k, t in enumerate(items[:MAX_ANALYSIS], 1):
        t = plain(t, rid) if isinstance(t, str) else t
        e = check_text("analysis[%d]" % k, t, ANALYSIS_LEN, hay, ids)
        if e:
            dropped.append(e)
        else:
            ok.append(t.strip().rstrip("。；;"))
    if len(items) > MAX_ANALYSIS:
        dropped.append("analysis 最多 %d 条，其余 %d 条已忽略" % (MAX_ANALYSIS, len(items) - MAX_ANALYSIS))
    return ok, dropped


def bold_head(t):
    """依据写成「要点：说明」时把要点加粗（要点 2–18 字、不含引文和标点），文字不动；没有要点的原样。"""
    m = re.match(r"^([^：:「」，,。；]{2,18})([：:])(.+)$", t)
    return "**%s%s**%s" % (m.group(1), m.group(2), m.group(3)) if m else t


def cmd_summary(a):
    """按漏斗级别渲染 summary（结论 / 依据 / 下一步，有事项时加注意段）。
    结论由脚本按引擎结果生成；依据和下一步由你写、脚本校验：
      拦截 / 建议拦截 / 转人工：依据围绕该级别命中规则的 comment 举证（每条命中规则至少出现一次），下一步结合提交资料写；
      通过：没有命中需处置的规则，依据写 4–6 条夸已提交资料真实合规，下一步由脚本固定；
      无结论（没有已判定规则/命中级别都不识别）：脚本直接渲染，不用写草稿。"""
    if a.file:                                   # 兼容：给了原始返回就先重新生成 hit-rules.json
        save_hits(a.rid, make_hits(a.file, a.rid))
    doc = load_hits(a.rid)
    c, fn, hits = doc["counts"], doc["funnel"], doc["hits"]
    if c["duplicateRuleIds"] or c["unknownStatus"]:
        die("引擎结果不完整（重复 ruleId=%s，未知状态=%d）：不渲染摘要；按 output skill 第四节写“摘要未完成”" % (",".join(c["duplicateRuleIds"]) or "无", c["unknownStatus"]), 3)
    cfg, lad, H = ct.CONFIG, ladder(), ct.CONFIG["summaryHeadings"]
    levels = [x["level"] for x in lad]
    lv = levels.index(fn["level"]) if fn["level"] in levels else None
    L = lad[lv] if lv is not None else None
    release = lv is not None and lv == len(lad) - 1
    at_level = [h for h in hits if L and h["level"] == L["level"]]
    rec = [h for h in hits if h["level"] is not None]
    allowed = {r["ruleId"] for r in at_level}
    other_lv = [h for h in rec if L and h["level"] != L["level"] and h["level"] != lad[-1]["level"]]    # 结论之外、需要处理的命中
    other_ids = {h["ruleId"] for h in other_lv}
    ids = doc["source"].get("allRuleIds") or [h["ruleId"] for h in hits]
    basis, nxt, analysis, lenient_log = [], [], [], []
    rejected = load_tries(a.rid)
    lenient = rejected >= LENIENT_AFTER

    def reject(msgs):
        """草稿被拒：计数落盘，提示还剩几次进入宽松模式。"""
        for e in msgs:
            print("ERR " + e)
        n = rejected + 1
        save_tries(a.rid, n)
        left = LENIENT_AFTER - n
        print("summary: %d errors（第 %d 次被拒）" % (len(msgs), n))
        if left > 0:
            print("NOTE 再被拒 %d 次后，下一次提交由脚本直接丢弃不合格的条目、用规则说明补齐缺的依据/下一步，不再退回。只改被点名的条目，不要重写其余内容。" % left)
        else:
            print("NOTE 下一次提交进入宽松模式：不合格的条目直接丢弃、缺的由脚本补齐。改一次被点名的条目后再提交即可，不要反复改标点。")
        sys.exit(1)

    if lv is None:
        basis = ["%s，需人工核验后给出结论。" % why_plain(fn["why"])]
        nxt = [cfg["noConclusion"]["first"]]
    else:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        if not raw.strip():
            print_need_basis(a.rid, doc)
            sys.exit(4)
        try:
            draft = json.loads(raw)
        except ValueError as exc:
            if not lenient:
                reject(["stdin 不是合法 JSON（%s）。字符串里的双引号请改写成「」。" % exc])
            draft = {}
            lenient_log.append("草稿不是合法 JSON，依据/下一步全部由脚本按规则说明生成")
        if not isinstance(draft, dict) or not isinstance(draft.get("basis"), list):
            if not lenient:
                reject(['草稿应为 {"basis":[{"ruleIds":[…],"text":"…"}],"next":["…"],"analysis":["…"]}'])
            draft = draft if isinstance(draft, dict) else {}
            draft["basis"] = draft.get("basis") if isinstance(draft.get("basis"), list) else []
        hay, errs, seen, tried = evidence_text(a.rid), [], set(), set()
        if hay is None:
            print("WARN 没有找到 work/%s/input-extract-detail.json，「」引文无法核对提交资料原文（不影响其余校验）" % a.rid)
        for k, it in enumerate(draft["basis"], 1):
            if not isinstance(it, dict):
                errs.append("basis[%d] 格式应为 {\"ruleIds\":[…],\"text\":\"…\"}" % k)
                continue
            rids = it.get("ruleIds") or []
            if not isinstance(rids, list) or not all(isinstance(i, str) for i in rids) or (not rids and not release):
                errs.append("basis[%d] 须带 ruleIds（命中规则的 ID 数组）" % k)
                continue
            bad = [i for i in rids if i not in allowed] if not release else []
            if bad:
                errs.append("basis[%d] 的 ruleId 不是命中“%s”级别的规则（依据只写该级别的命中规则）：%s" % (k, L["level"], ",".join(bad)))
                continue
            e = check_text("basis[%d]" % k, it.get("text"), BASIS_LEN, hay, ids)
            if e:                       # v33：这条依据的 ruleIds 已经写了，只是文字被拒，不再另报“规则没出现在依据里”
                errs.append(e + "（这条依据已带 %s，只改文字即可）" % ",".join(rids) if rids else e)
                tried.update(rids)
                continue
            seen.update(rids)
            basis.append(it["text"].strip().rstrip("。；"))
        if release:
            if not (RELEASE_BASIS[0] <= len(draft["basis"]) <= RELEASE_BASIS[1]):
                errs.append("通过的依据应写 %d–%d 条（约 5 条），现在 %d 条" % (RELEASE_BASIS[0], RELEASE_BASIS[1], len(draft["basis"])))
            nxt = [cfg["release"]["next"]]
        else:
            miss = sorted(allowed - seen - tried)
            if miss:
                errs.append("这些命中“%s”级别的规则没有出现在任何一条依据里：%s" % (L["level"], ",".join(miss)))
            items = draft.get("next")
            n_seen, n_tried, n_plain = set(), set(), 0
            if lenient and isinstance(items, list):
                items = items[:MAX_NEXT + len(other_lv)]
            if not isinstance(items, list) or not (1 <= len(items) <= MAX_NEXT + len(other_lv)):
                errs.append("next 应是 1–%d 条的数组（每条一句话；覆盖其余级别规则的事项写成 {\"ruleIds\":[…],\"text\":\"…\"}）" % (MAX_NEXT + len(other_lv)))
            else:
                for k, t in enumerate(items, 1):
                    rids2 = []
                    if isinstance(t, dict):
                        rids2 = t.get("ruleIds") or []
                        if not isinstance(rids2, list) or not all(isinstance(i, str) for i in rids2) or not rids2:
                            errs.append("next[%d] 带 ruleIds 时应是非空的命中规则 ID 数组" % k)
                            continue
                        bad = [i for i in rids2 if i not in other_ids and i not in allowed]
                        if bad:
                            errs.append("next[%d] 的 ruleId 不是本次命中的结论级别或其余级别的规则：%s" % (k, ",".join(bad)))
                            continue
                        t = t.get("text")
                    e = check_text("next[%d]" % k, t, NEXT_LEN, hay, ids)
                    if e:
                        errs.append(e + ("（这条已带 %s，只改文字即可）" % ",".join(rids2) if rids2 else ""))
                        n_tried.update(rids2)
                    else:
                        nxt.append(t.strip())
                        n_seen.update(rids2)
                        if not any(i in other_ids for i in rids2):
                            n_plain += 1
                miss2 = sorted(other_ids - n_seen - n_tried)
                if miss2:
                    errs.append("这些其余级别的命中规则没有出现在任何一条下一步里（每条规则至少要有一条带 ruleIds 的事项，告诉对方怎么处理或注意什么）：%s" % ",".join(miss2))
                if n_plain > MAX_NEXT:
                    errs.append("结论级别的下一步最多 %d 条" % MAX_NEXT)
        analysis, a_dropped = check_analysis(draft.get("analysis"), hay, ids, a.rid)
        for e in a_dropped:
            print("ANALYSIS_DROPPED " + e)
        if errs and not lenient:
            reject(errs)
        if errs:                         # v38 宽松模式：不合格的条目已在上面跳过，这里只补齐缺的部分，不再退回
            lenient_log += errs
            if release:
                basis = basis[:RELEASE_BASIS[1]] or [cfg["release"].get("basisFallback", "已提交资料经规则校验，未命中需拦截或转人工的规则")]
            else:
                byid = {h["ruleId"]: h for h in hits}
                for rid_ in sorted(allowed - seen):
                    basis.append(fallback_basis(byid[rid_]))
                if not nxt:
                    nxt = [fallback_next(h) for h in at_level][:MAX_NEXT]
                for rid_ in sorted(other_ids - n_seen):
                    nxt.append(fallback_next(byid[rid_], other=True))
                nxt = nxt[:MAX_NEXT + len(other_lv)]
        if lenient_log:
            for e in lenient_log:
                print("LENIENT 已丢弃/已补齐：" + e)

    sty = cfg.get("summaryStyle") or {}

    def block(head, items, kind):
        """只改排版、不改文字：conclusion=引用块+图标+加粗；basis=列表，「要点：」加粗；next=引用块里的列表；其余=列表。"""
        if kind == "conclusion":
            icon = (sty.get("levelIcons") or {}).get(L["level"] if L else "", "")
            return "\n".join([head] + ["> %s**%s**" % (icon + " " if icon else "", t) for t in items])
        if kind == "basis":
            items = [bold_head(t) for t in items]
        prefix = "> - " if kind == "next" else "- "
        return "\n".join([head] + [prefix + t for t in items])

    concl = "%s｜%s" % (L["level"], L["title"]) if L else "暂无结论｜%s" % why_plain(fn["why"])
    att = attention_lines(a.rid)
    picks = draft.get("notice") if lv is not None and isinstance(draft, dict) and "notice" in draft else None
    notices, n_dropped = pick_notices(a.rid, picks, basis + nxt)
    for e in n_dropped:
        print("NOTICE_DROPPED " + e)
    att = list(dict.fromkeys(att + notices))
    if analysis:                         # v38：模型的全局分析作为“注意”的最后一条，明确标注仅供参考
        att.append("%s：%s。" % (cfg.get("analysisLabel", "agent全局分析（仅供参考）"), "；".join(analysis)))
    if os.path.isfile(tries_path(a.rid)):
        os.remove(tries_path(a.rid))
    parts = [block(H["conclusion"], [concl], "conclusion"), block(H["basis"], basis, "basis"), block(H["next"], nxt, "next")]
    if att:
        parts.append(block(H["attention"], att, "attention"))
    summ = "\n\n".join(parts)
    os.makedirs(os.path.join("work", a.rid), exist_ok=True)
    if lv is not None:
        with open(os.path.join("work", a.rid, "summary-draft.json"), "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False, indent=1)
    with open(os.path.join("work", a.rid, "summary-final.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summ}, f, ensure_ascii=False, indent=1)
    print("OK 结论 %s；依据 %d 条；下一步 %d 条；注意提醒 %d 条" % (L["level"] if L else "无", len(basis), len(nxt), len(notices)))
    print("SUMMARY " + jstr(summ))
    final = final_output(a.rid, summ)
    if final is not None:
        print("FINAL " + jstr(final))


CURLY = str.maketrans({"“": "「", "”": "」", "‘": "「", "’": "」"})


def no_curly(x):
    """v37：结果里的弯引号统一成「」。v35-am2/am3 抄写 notes 时把“”改成了直引号 "，没转义，最终 JSON 不合法。"""
    if isinstance(x, str):
        return x.translate(CURLY)
    if isinstance(x, list):
        return [no_curly(v) for v in x]
    if isinstance(x, dict):
        return {k: no_curly(v) for k, v in x.items()}
    return x


def final_output(rid, summ):
    """最终结果（input、notes、summary）由脚本拼好，打印成一行 FINAL，模型原样作为 GenerateStructuredOutput 的参数。
    input 取最近一次 build 的 input-combine.json（就是调引擎时传的 INPUT），notes 取 notes-final.json。"""
    cf, nf = os.path.join("work", rid, "input-combine.json"), os.path.join("work", rid, "notes-final.json")
    if not (os.path.isfile(cf) and os.path.isfile(nf)):
        print("WARN 没有 input-combine.json 或 notes-final.json，不输出 FINAL：input、notes 用最近一次 build 的 INPUT、NOTES 行")
        return None
    final = {"input": ct.load(cf)["input"], "notes": no_curly(ct.load(nf)), "summary": no_curly(summ)}
    with open(os.path.join("work", rid, "final-output.json"), "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=1)
    return final


def enum_literals(key, rules):
    """规则条件里与该键比较过的字面值（= / != / IN {…}）。枚举属性的合法取值只能是这些编码，不能是中文标签。"""
    lits = set()
    for r in rules:
        c = r["condition"]
        for m in re.finditer(re.escape(key) + r"\s*(?:=|!=)\s*\"?([A-Za-z0-9_\-]+)\"?", c):
            lits.add(m.group(1))
        for m in re.finditer(re.escape(key) + r"\s+(?:NOT\s+)?IN\s*\{([^}]*)\}", c):
            for t in m.group(1).split(","):
                if t.strip().strip("\"' "):
                    lits.add(t.strip().strip("\"' "))
    return lits


ENUM_SPLIT = re.compile(r"[、,，/；;|｜]+")
ENUM_CODE_KEYS = ("code", "value", "key", "name", "id")
ENUM_LABEL_KEYS = ("label", "desc", "text", "title", "cn")


def enum_options(pd):
    """v41：枚举属性的可选项。定义里有 enum 就从 enum 取 (编码, 中文)；没有 enum、comment 是「枚举 X：甲、乙、丙」就从 comment 取 (None, 选项)。
    enum 的写法不固定，下面几种都认：[{"finance":"金融类"}…]、[{"code":"finance","label":"金融类"}…]、["finance"…]、{"finance":"金融类"}。
    返回 (来源, [(编码或None, 中文或None)])；不是枚举返回 (None, [])。"""
    pd = pd or {}
    en = pd.get("enum")
    opts = []
    if isinstance(en, dict):
        opts = [(str(k), None if v is None else str(v)) for k, v in en.items()]
    elif isinstance(en, list):
        for x in en:
            if isinstance(x, (str, int, float)) and not isinstance(x, bool):
                opts.append((str(x), None))
            elif isinstance(x, dict):
                ck = next((k for k in ENUM_CODE_KEYS if k in x), None)
                lk = next((k for k in ENUM_LABEL_KEYS if k in x), None)
                if ck:
                    opts.append((str(x[ck]), None if lk is None else str(x[lk])))
                elif len(x) == 1:
                    k, v = next(iter(x.items()))
                    opts.append((str(k), None if v is None else str(v)))
    if opts:
        return "enum", opts
    c = pd.get("comment") or ""
    m = re.search(r"枚举[^：:]*[：:](.+)", c, re.S)
    if m:
        labels = [t.strip(" 。.\n") for t in ENUM_SPLIT.split(m.group(1)) if t.strip(" 。.\n")]
        if labels:
            return "comment", [(None, t) for t in labels]
    return None, []


def enum_text(opts):
    return "、".join("%s=%s" % (c, l) if c and l else (c or l) for c, l in opts)


def enum_rule_mismatch(key, pd, rules):
    """enum 给了编码时，规则条件里比较的编码不在 enum 里（例如 enum 是 finance、规则写 financial），规则永远不会命中。"""
    src, opts = enum_options(pd)
    if src != "enum":
        return []
    codes = {c for c, _ in opts}
    return sorted(x for x in enum_literals(key, rules) if x not in codes)


def enum_check(key, pd, value, rules):
    """v41：规则引用的枚举键只能从选项里选一个。有 enum：传 enum 的编码（给了中文选项就换成对应编码）；
    没有 enum：传 comment 里的一个选项（规则条件里出现过的编码也接受，兼容旧本体）。返回 (值, 不传的原因或 None)。"""
    src, opts = enum_options(pd)
    if not src:
        return value, None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return value, "枚举键只能选一个选项，取值「%s」不是选项；可选：%s" % (short(str(value), 30), enum_text(opts))
    v = str(value).strip()
    if src == "enum":
        for c, l in opts:
            if v == c:
                return c, None
        for c, l in opts:
            if l and v == l:
                return c, None
        return value, "取值「%s」不在 enum 里，不传；可选：%s" % (short(v, 30), enum_text(opts))
    if any(v == l for _, l in opts) or v in enum_literals(key, rules):
        return v, None
    return value, "取值「%s」不在 comment 列出的选项里，不传；可选：%s" % (short(v, 30), enum_text(opts))


def key_uses(key, rules):
    """规则条件里该键每次出现的（前文, 后文）片段。"""
    pat = re.compile(r"(?<![\w.])" + re.escape(key) + r"(?!\w)")
    out = []
    for r in rules:
        c = r["condition"]
        for m in pat.finditer(c):
            out.append((c[max(0, m.start() - 60):m.start()], c[m.end():m.end() + 60]))
    return out


BOOL_TAIL = re.compile(r"^\s*(?:=|!=)\s*(?:true|false)(?![\w.])", re.I)
NULL_TAIL = re.compile(r"^\s+IS\s+(?:NOT\s+)?(?:NULL|EMPTY)\b", re.I)
KEY_CMP_TAIL = re.compile(r"^\s*(?:<=|>=|<|>)\s*[A-Z][A-Za-z0-9]*\.[a-z][a-z0-9_]*")
KEY_CMP_HEAD = re.compile(r"[A-Z][A-Za-z0-9]*\.[a-z][a-z0-9_]*\s*(?:<=|>=|<|>)\s*$")
LONG_TERM = ("长期", "永久", "无固定期限", "不约定期限")
EQ_KEY_TAIL = re.compile(r"^\s*(?:!=|=)\s*([A-Z][A-Za-z0-9]*\.[a-z][a-z0-9_]*)(?![\w.])")
EQ_KEY_HEAD = re.compile(r"(?<![\w.])([A-Z][A-Za-z0-9]*\.[a-z][a-z0-9_]*)\s*(?:!=|(?<![<>!=])=)\s*$")


def eq_peers(key, rules):
    """规则里与该键做 = / != 比较的另一个属性键（如 X.party_b_name != Employer.enterprise_name → Employer.enterprise_name）。"""
    out = []
    for h, t in key_uses(key, rules):
        for m in (EQ_KEY_TAIL.match(t), EQ_KEY_HEAD.search(h)):
            if m and m.group(1) != key and m.group(1) not in out:
                out.append(m.group(1))
    return out


def type_fix(key, pd, value, rules):
    """v33：按规则怎么用这个键核对取值类型（am1 把经营范围全文传给布尔键 main_business_queryable、把视频招牌文字传给
    peer_platform_merchant、把附件盘点传给 *_stage_complete）。返回 (值, 不传的原因或 None)。
    - 布尔键（规则里只和 true/false 比较，或只判空）：取值必须是布尔；
    - 数值键（规则里只和数字比较）：取值必须是数字；
    - 日期键（和另一个属性比大小，或 label 含“日期/到期”）：统一成 8 位 yyyyMMdd；“长期/永久”不造日期、不传。"""
    uses = key_uses(key, rules)
    if not uses or value is None:
        return value, None
    if value in ("true", "false"):
        value = value == "true"
    tails = [t for _, t in uses]
    if isinstance(value, bool) and eq_peers(key, rules) and "名" in ((pd or {}).get("label") or ""):
        return value, "规则拿它和另一个属性（%s）比较名称，取值「%s」是判断结果不是名称，不传（改映射到名称原文条目，不要映射到“…是否一致/是否匹配”条目）" % (
            "、".join(eq_peers(key, rules)), value)
    if any(BOOL_TAIL.match(t) for t in tails) and all(BOOL_TAIL.match(t) or NULL_TAIL.match(t) for t in tails):
        if isinstance(value, bool):
            return value, None
        return value, "规则只拿它和 true/false 比较，取值「%s」不是布尔，不传（映射的条目含义对不上：布尔键只能映射到值为 true/false 的条目，或用 set 给布尔）" % short(str(value), 30)
    if ct.numeric_key(key, rules):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value, None
        return value, "规则只拿它和数字比较，取值「%s」不是数字，不传" % short(str(value), 30)
    label = (pd or {}).get("label") or ""
    is_date = any(KEY_CMP_TAIL.match(t) for t in tails) or any(KEY_CMP_HEAD.search(h) for h, _ in uses) or \
        any(w in label for w in ("日期", "到期", "失效时间", "提交时间"))
    if is_date and isinstance(value, str):
        if any(w in value for w in LONG_TERM):
            return value, "取值「%s」为长期/无截止日，日期键不造日期，不传（规则按「有截止日且已到期」判断，不传即不触发）" % short(value, 30)
        ds = dt.dates_in(value)
        if not ds:
            return value, "日期键的取值「%s」读不出日期，不传" % short(value, 30)
        d = ds[-1] if any(w in label for w in ("到期", "截止", "失效")) else ds[0]
        return d.strftime("%Y%m%d"), None
    return value, None


FIX_ITEMS = ct.FIXED_ITEMS            # 请求里的预设条目 A01–A04 + A08 项目内容（清单条目 ID，稳定；属性名随本体变，不写死）
MAP_FILE = "key-map.json"
PRESET_UNDEFINED = []                 # 本次属性定义里没有、仍按预设照传的标识键（只打印，不进 notes）
FALLBACK_FILLED = []                  # 本次按 run_process_required.json 兜底传入的枚举键 (键, 值)


def row_code(row):
    m = re.match(r"N｜(R\d\d)｜", row["source"])
    return m.group(1) if m else None


def map_path(rid):
    return os.path.join("work", rid, MAP_FILE)


def norm_entry(k, v):
    """映射项 → (ids, force)。ids 是清单条目 ID 列表；force 仅对固定标识有意义：定义没返回该键也照传。"""
    if isinstance(v, list):
        ids, force = v, False
    elif isinstance(v, dict):
        ids, force = v.get("ids"), bool(v.get("force"))
    else:
        ids, force = None, False
    if not (isinstance(ids, list) and ids and all(isinstance(x, str) for x in ids)):
        die("map.%s 应为条目 ID 数组（如 [\"B16\"]；多条共同推出写多个）或 {\"ids\":[…],\"force\":true}" % k)
    return ids, force


def load_map(rid):
    fp = map_path(rid)
    if os.path.isfile(fp):
        m = ct.load(fp)
    else:
        m = {}
    for f, d in (("map", {}), ("skip", {}), ("fixedUnmapped", {}), ("toolIssues", [])):
        m.setdefault(f, d)
    return m


def merge_map(m, spec):
    """模型这次提交的映射并入已保存的映射：map 同键覆盖（值 null 表示删除）；skip 按原因码并入；一个键只在 map 或 skip 里出现一次。"""
    if not spec:
        return m
    keyre = re.compile(r"[A-Za-z][A-Za-z0-9]*\.[a-z][a-z0-9_]*")
    both = sorted(set(k for k, v in (spec.get("map") or {}).items() if v is not None) &
                  set(str(k) for ks in (spec.get("skip") or {}).values() if isinstance(ks, list) for k in ks))
    if both:
        die("这次提交里同一个键既在 map 又在 skip（%s）：一个键只能选一种处理，请决定后重交" % "、".join(both[:6]))
    for k, v in (spec.get("map") or {}).items():
        if not keyre.fullmatch(k):
            die("map 的键应为「对象.属性」，收到 %r" % k)
        if v is None:
            m["map"].pop(k, None)
            continue
        norm_entry(k, v)
        m["map"][k] = v
        for c in m["skip"]:
            m["skip"][c] = [x for x in m["skip"][c] if x != k]
    for c, keys in (spec.get("skip") or {}).items():
        if not re.fullmatch(r"R(0[1-9]|1[0-5])", c) or not isinstance(keys, list):
            die("skip 应为 {\"R10\":[键…],\"R14\":[键…]}，原因码取 R01–R15；收到 %r" % c)
        for k in keys:
            if not keyre.fullmatch(str(k)):
                die("skip.%s 里的键应为「对象.属性」，收到 %r" % (c, k))
            m["map"].pop(k, None)
            for c2 in m["skip"]:
                m["skip"][c2] = [x for x in m["skip"][c2] if x != k]
            m["skip"].setdefault(c, []).append(k)
    for f in ("fixedUnmapped",):
        for i, why in (spec.get(f) or {}).items():
            if i not in FIX_ITEMS or not isinstance(why, str) or len(why) < 4:
                die("fixedUnmapped 只能写 %s 里的条目，原因至少 4 个字：%r" % ("/".join(FIX_ITEMS), i))
            m[f][i] = why
    sc = spec.get("rules")
    if sc is not None:                   # v39：规则是否与准入有关，模型可改判
        if not isinstance(sc, dict) or not isinstance(sc.get("keep", []), list) or not isinstance(sc.get("drop", {}), dict):
            die('rules 应为 {"keep":[规则ID…],"drop":{"规则ID":"原因"}}')
        cur = m.setdefault("rules", {"keep": [], "drop": {}})
        for i in sc.get("keep") or []:
            cur["drop"].pop(i, None)
            if i not in cur["keep"]:
                cur["keep"].append(i)
        for i, why in (sc.get("drop") or {}).items():
            if not isinstance(why, str) or len(why.strip()) < 4:
                die("rules.drop.%s 要写明与准入无关的原因（至少 4 个字）" % i)
            cur["keep"] = [x for x in cur["keep"] if x != i]
            cur["drop"][i] = why.strip()
    for t in spec.get("toolIssues") or []:
        if isinstance(t, str) and t not in m["toolIssues"]:
            m["toolIssues"].append(t)
    m["skip"] = {c: list(dict.fromkeys(v)) for c, v in m["skip"].items() if v}
    return m


def short(x, n):
    x = x or ""
    return x if len(x) <= n else x[:n] + "…"






def inst_def(k, ref):
    """机构规则键的临时定义：label 取规则名称（companyName 等），comment 写明来源。"""
    names = [r["ruleId"][len(ct.INST_PREFIX):] for r in ref.get(k, []) if r["ruleId"].startswith(ct.INST_PREFIX)]
    return {"name": k.split(".")[1], "label": "、".join(names) or k,
            "comment": "机构风控规则（inst-rc-rule-mcp）引用，本体定义未返回；条件：%s" % "；".join(r["condition"] for r in ref.get(k, []))}


def empty_gates(key, rules):
    """条件里含「键 IS EMPTY / IS NULL」（不含 NOT）的规则：该键不传就会命中。"""
    pat = re.compile(re.escape(key) + r"\s+IS\s+(?:EMPTY|NULL)\b", re.I)
    return [r for r in rules if pat.search(r.get("condition") or "")]


def cmd_plan(a):
    """只读：列出本次规则引用的属性（含定义的 label/comment）和清单条目，供你按语义决定「哪个条目 → 哪个属性」。
    映射不是对照表：属性名随本体随时会变，只看本次定义返回的 label/comment 与条目 name/desc 的含义。"""
    rules, props = rules_list(a.rules), props_list(a.props)
    rules, _ = rule_scope(rules, load_map(a.rid))
    defs = {o["name"]: o for o in props}
    rk = ref_keys(rules)
    ref = ct.rule_index(rules)
    detail_fp = os.path.join("work", a.rid, "input-extract-detail.json")
    if not os.path.isfile(detail_fp):
        die("没有 %s，先运行 detail.py init" % detail_fp)
    doc = ct.load(detail_fp)
    saved = load_map(a.rid)
    print("PLAN 本次规则引用 %d 个键（%d 个对象）。按含义决定每个键怎么处理，用 build 的 stdin 提交：" % (sum(len(v) for v in rk.values()), len(rk)))
    print('  {"map":{"对象.属性":["条目ID"]},   // 一个条目；多条共同推出写多个 ID（之后按 NEED_VALUE 用 set 给值）')
    print('   "skip":{"R14":[键…],"R13":[键…],"R10":[键…],"R11":[键…]},   // 不填的键：R14 结果类（结论/处置/是否放行/汇总信号）、R13 外部来源（三方核查/结算/个人/流水）、R10 无业务判断口径、R11 定义含义与规则用法冲突')
    print('   "fixedUnmapped":{"A02":"原因"},   // 四个标识条目没有可映射的属性时才写')
    print('   "toolIssues":["…"]}                // R11 冲突等需要记入 notes.toolIssues 的说明')
    print("规则：只映射「规则引用的键」（四个标识和用工场景已预设，不用管）；条目没有证据（值为 N）也可映射，会自动按该条目的 N 原因码登记；不确定就 skip，不猜。")
    print("-- 规则引用的键（对象.属性｜label｜comment｜引用规则数｜示例条件）--")
    undefined, enum_keys = [], []
    for o, ps in rk.items():
        dp = {p["name"]: p for p in defs.get(o, {}).get("properties", [])}
        for p in ps:
            k = "%s.%s" % (o, p)
            tag = "（已映射 %s）" % saved["map"][k] if k in saved["map"] else ("（已 skip）" if any(k in v for v in saved["skip"].values()) else "")
            if p not in dp:
                undefined.append(k)
                if k not in ct.inst_keys(rules):
                    continue
                dp[p] = inst_def(k, ref)
            r0 = (ref.get(k) or [{}])[0].get("condition", "")
            print("%s｜%s｜%s｜%d｜%s%s" % (k, dp[p].get("label") or "", short(dp[p].get("comment"), 60), len(ref.get(k, [])), short(r0, 70), tag))
            for g in empty_gates(k, rules):
                print("  EMPTY_GATE %s（%s，处置 %s）在该键为空时命中：skip 会直接触发这条规则。有可读证据就按含义提交值（枚举按选择题选一项），确实无依据才 skip，并在依据/下一步里说明缺什么" % (g["ruleId"], g.get("label") or "", (g.get("riskMeasure") or "").strip() or "未写"))
            src, opts = enum_options(dp[p])
            if src:
                enum_keys.append(k)
                print("  ENUM 选项（来自 %s）：%s" % (src, enum_text(opts)))
                miss = enum_rule_mismatch(k, dp[p], rules)
                if miss:
                    print("  ENUM_RULE_MISMATCH 规则条件比较的编码 %s 不在 enum 里，选 enum 编码后这条规则也不会命中，记入 toolIssues" % "、".join(miss))
    if enum_keys:
        print("ENUM_KEYS %d 个规则引用的枚举键：%s。每个都是选择题：逐项估计各选项与证据相符的把握，最高一项超过 50%% 就用 set 提交该选项（有 enum 交 enum 元素的 key，如 [{\"pass\":\"通过\"}] 交 pass），并在依据里写「选项｜置信度约N%%｜理由」；都不超过 50%% 就留空：value 为 null、skip R10、不传。" % (len(enum_keys), "、".join(enum_keys)))
    inst = ct.inst_keys(rules)
    if inst:
        print("INST_KEYS 机构风控规则（inst-rc-rule-mcp）引用 %d 个键：%s。这些是调用 mcp_run_process 的必填输入，与 mcp_list_rule 引用键一起组装。本体定义里没有也要按规则含义用 map 映到有证据的清单条目；缺项时 build/validate 报 INST_REQUIRED_MISSING，不得调用引擎，不得编造值。" % (len(inst), "、".join(inst)))
        undefined = [k for k in undefined if k not in inst]
    if undefined:
        print("-- 规则引用但本次定义没有（自动记 notFoundInDefinition，不用处理）：%s" % "、".join(undefined))
    print("-- 预设条目（四个标识 + 用工场景取项目内容）：不用你映射，build 自动传入；四个 ID 不可互换，预设键不能改映、skip 或 set（预设在 run_process_required.json）--")
    by = {x["id"]: x for x in doc["items"]}
    for i in FIX_ITEMS:
        keys = [k for k, it in ct.PRESET_IDS.items() if it == i]
        print("%s｜%s｜%s｜预设→%s" % (i, by[i]["name"], short(by[i]["value"], 30) if by[i]["source"].startswith("Y｜") else "（空）", "、".join(keys) or "（无）"))
    cand = []
    for o in props:
        for p in o.get("properties", []):
            lb = p.get("label") or ""
            if re.search(r"(ID|编号|名称)", lb) and re.search(r"(企业|客户|需求|机构|代理)", (o.get("label") or "") + lb):
                cand.append("%s.%s｜%s｜%s" % (o["name"], p["name"], lb, o.get("label") or ""))
    if cand:
        print("-- 标识候选（预设之外，定义里还有哪些像标识的属性；只在含义确实相同时才用 map 再映到同一个条目，同值同传；一般不用管）--")
        for c in cand[:40]:
            print(c)
    print("-- 清单条目（id｜name｜值或状态）--")
    for x in doc["items"]:
        v = x["value"] if x["source"].startswith("Y｜") else "N " + (row_code(x) or "")
        print("%s｜%s｜%s" % (x["id"], x["name"], short(v, 28)))
    print("-- 条目的 desc 里若写着「Xxx.yyy」，那是历史提示，不是映射依据；以本次定义的 label/comment 为准 --")


def build(rid, rules, props, sets, spec_in):
    detail_fp = os.path.join("work", rid, "input-extract-detail.json")
    if not os.path.isfile(detail_fp):
        die("没有 %s，先运行 detail.py init" % detail_fp)
    doc = ct.load(detail_fp)
    rows = {x["id"]: x for x in doc["items"]}
    pend = [i for i, x in rows.items() if x["source"] == ""]
    if pend:
        die("明细还有 %d 行待填（%s…），先 detail.py fill / finish" % (len(pend), ",".join(pend[:6])), 2)
    st_fp = os.path.join("work", rid, ".detail-state.json")
    if os.path.isfile(st_fp):          # v29：工商与原件识别不一致必须先二次识别；模型写的派生行依据变了必须先重判
        probs = dt.gate_problems(doc, dt.load_json_file(st_fp))
        if probs:
            die("明细未通过复核门禁，不能组装：" + "；".join(probs) + "。先运行 detail.py compare / recheck", 2)
    saved_before = os.path.isfile(map_path(rid))
    mp = merge_map(load_map(rid), spec_in)
    all_rules = rules
    rules, rules_dropped = rule_scope(rules, mp)      # v39：与客户准入无关的规则先抛掉，它们条件里的字段不进 input-combine.json
    defs = {o["name"]: o for o in props}
    rk = ref_keys(rules)
    ref = ct.rule_index(rules)
    refset = [("%s.%s" % (o, p)) for o, ps in rk.items() for p in ps]
    if not saved_before and not (spec_in and (spec_in.get("map") or spec_in.get("skip") or spec_in.get("fixedUnmapped") or spec_in.get("rules"))):
        return None                    # 没有本次映射：调用方打印 plan，不替模型选择属性
    for k, v in mp["map"].items():
        for i in norm_entry(k, v)[0]:
            if i not in rows:
                die("map.%s 引用了清单里没有的条目 %s" % (k, i))
    skipmap = {k: c for c, ks in mp["skip"].items() for k in ks}
    entries = {k: norm_entry(k, v) for k, v in mp["map"].items()}
    for k, item in ct.PRESET_IDS.items():     # 预设（四个标识 + 用工场景）：自动传入，不可改映、不可 skip（四个 ID 不可互换）
        if item in ct.SOFT_PRESETS:           # 用工场景：值固定取请求原文，模型的 map/skip/set 一律不采用，只提示、不退回（免得多跑一轮）
            touched = [w for w, hit in (("skip", k in skipmap), ("map", k in entries and entries[k][0] != [item]), ("set", k in sets)) if hit]
            skipmap.pop(k, None)
            sets.pop(k, None)
            if touched:
                print("PRESET_OVERRIDE_IGNORED %s 是预设键，固定取 %s 原文，忽略你提交的 %s；以后不用提交它" % (k, item, "/".join(touched)))
            entries[k] = ([item], True)
            continue
        if k in skipmap:
            die("%s 是预设的标识键（%s → %s），不能 skip" % (k, item, k))
        if k in entries and entries[k][0] != [item]:
            die("%s 是预设的标识键，只能对应 %s，不能改映到 %s：企业 ID、需求 ID、机构 ID 不可互换" % (k, item, "、".join(entries[k][0])))
        entries[k] = ([item], True)
    with open(map_path(rid), "w", encoding="utf-8") as f:     # 全部校验通过后才落盘：被拒的提交不能留在 key-map.json 里毒化以后的 build
        json.dump(mp, f, ensure_ascii=False, indent=1)
    fixed_keys = [k for k, (ids, _) in entries.items() if len(ids) == 1 and ids[0] in FIX_ITEMS]

    ents, unfilled, notfound, need_value, undecided, notes_unfilled = {}, {}, [], [], [], []
    ignored, fixed_unmapped, tool_issues = [], dict(mp["fixedUnmapped"]), list(mp["toolIssues"])
    enum_dropped, type_dropped = [], []
    del PRESET_UNDEFINED[:]
    order_keys = list(dict.fromkeys(fixed_keys + refset))

    def add_unfilled(k, code):
        o, p = k.split(".")
        unfilled.setdefault(o, {}).setdefault(code, []).append(p)

    inst = set(ct.inst_keys(rules))
    for k in order_keys:
        o, p = k.split(".")
        pd = next((x for x in defs.get(o, {}).get("properties", []) if x["name"] == p), None)
        if pd is None and k in inst:       # v41：机构风控规则引用的键，本体定义没有也照传
            pd = inst_def(k, ref)
            defs.setdefault(o, {"name": o, "label": o, "comment": "机构风控规则引用（本体定义未返回）", "properties": []})
        is_ref, is_fixed = k in refset, k in fixed_keys
        ids, force = entries.get(k, (None, False))
        if pd is None:
            if is_ref:
                notfound.append(k)
            if is_fixed and force:       # 模型确认本体就是这个键、只是定义没返回：照传（固定标识）并记录
                pd = {"name": p, "label": "（定义未返回，按固定标识保留）", "comment": None}
                defs.setdefault(o, {"name": o, "label": o, "comment": None, "properties": []})
                if k in ct.PRESET_IDS:
                    PRESET_UNDEFINED.append(k)
                else:
                    t_ = "固定标识 %s 本次属性定义未返回，按你的确认（force）照传" % k
                    if t_ not in tool_issues:
                        tool_issues.append(t_)
            else:
                if is_fixed and not is_ref:
                    fixed_unmapped.setdefault(ids[0], "你映射的键 %s 在本次属性定义里不存在" % k)
                continue
        if k in skipmap:
            add_unfilled(k, skipmap[k])
            notes_unfilled.append((k, skipmap[k], None))
            continue
        if not ids:
            undecided.append((k, pd.get("label")))
            add_unfilled(k, "R10")
            notes_unfilled.append((k, "R10", None))
            continue
        main = rows[ids[0]]
        if k in sets:  # 模型按本次属性含义提交的取值，单条或多条依据均可
            value, vsrc = sets[k]
            cited = vsrc.split("｜", 1)[0].removeprefix("派生:").split(",")
            if set(cited) != set(ids):
                die("set.%s 的来源条目必须与 map 一致：map=%s，来源=%s" % (k, ids, cited))
            missing = [i for i in ids if not rows[i]["source"].startswith("Y｜") or rows[i]["value"] is None]
            if missing:
                add_unfilled(k, "R12")
                notes_unfilled.append((k, "R12", "模型取值缺少依据：%s" % "、".join(missing)))
                continue
            if value is None:
                add_unfilled(k, "R10")
                notes_unfilled.append((k, "R10", "模型未给出可确认的取值"))
                continue
        elif len(ids) > 1:
            need_value.append((k, ids))
            add_unfilled(k, "R10")
            notes_unfilled.append((k, "R10", "派生属性待模型判断"))
            continue
        else:
            if not main["source"].startswith("Y｜"):
                if is_ref:
                    add_unfilled(k, row_code(main) or "R10")  # 原因已在 unresolvedProperties 的 N 行里
                continue                                        # 非规则引用的标识（如请求没给 rqId）：不传，也不进 unfilled
            value = ct.typed(k, main["value"], rules, as_str=is_fixed)
            vsrc = "%s｜%s" % (main["id"], main["source"])
        value = ct.norm_text(value)      # 传给引擎前统一：中文/全角标点 → 英文，去空格（明细文件保持原文）
        before_fix = value
        value, bad = type_fix(k, pd, value, rules) if not is_fixed else (value, None)
        if not bad and isinstance(before_fix, str) and value != before_fix:
            vsrc += "；按规则用法统一为 yyyyMMdd"
        if bad:
            add_unfilled(k, "R10")
            notes_unfilled.append((k, "R10", bad))
            type_dropped.append((k, bad))
            continue
        value, bad = enum_check(k, pd, value, rules) if not is_fixed else (value, None)
        if bad:                          # am8：把「有限责任公司」「基本户」「true」传给枚举键，规则按编码比较，等于传了错值
            add_unfilled(k, "R10")
            notes_unfilled.append((k, "R10", bad))
            enum_dropped.append((k, bad))
            continue
        e = ents.setdefault(o, {"label": defs[o].get("label"), "comment": defs[o].get("comment"), "props": {}})
        e["props"][p] = {"value": value, "value_source": vsrc, "label": pd["label"], "comment": pd.get("comment"),
                         "extractIds": ids, "rules": ref.get(k, [])}
    for k in list(mp["map"]) + [k for ks in mp["skip"].values() for k in ks]:
        if k not in order_keys:
            ignored.append(k)            # 既不是规则引用的键、也不是标识：不进 input
    covered = {e2["extractIds"][0] for e in ents.values() for e2 in e["props"].values() if len(e2["extractIds"]) == 1}
    for i in FIX_ITEMS:
        if rows[i]["source"].startswith("Y｜") and i not in covered and i in fixed_unmapped:
            tool_issues.append("固定标识 %s（%s）未映射到任何属性：%s" % (i, rows[i]["name"], fixed_unmapped[i]))
    fixed_unmapped = {i: w for i, w in fixed_unmapped.items() if i not in covered}

    # 必填预设键（run_process_required.json 的 required）：请求条目无值时不传、不兜底，只记 notes.toolIssues
    del FALLBACK_FILLED[:]
    for k, item in ct.PRESET_IDS.items():
        o, p = k.split(".")
        if p not in ents.get(o, {}).get("props", {}):
            tool_issues.append("必填键 %s 的条目 %s（%s）无值，未传给 mcp_run_process" % (k, item, rows[item]["name"]))
    # 枚举键兜底（enumFallbacks）：本次规则引用、定义里有选项、却没取到值的键，传配置的选项；不是选项就不传
    for k, fb in ct.ENUM_FALLBACKS.items():
        o, p = k.split(".")
        pd = next((x for x in defs.get(o, {}).get("properties", []) if x["name"] == p), None)
        if k not in refset or pd is None or not enum_options(pd)[0] or p in ents.get(o, {}).get("props", {}):
            continue
        value, bad = enum_check(k, pd, fb, rules)
        if bad:
            tool_issues.append("枚举键 %s 的兜底值不可用（%s），未传" % (k, bad))
            continue
        for code, ps in list(unfilled.get(o, {}).items()):
            if p in ps:
                ps.remove(p)
                if not ps:
                    del unfilled[o][code]
        if o in unfilled and not unfilled[o]:
            del unfilled[o]
        notes_unfilled[:] = [x for x in notes_unfilled if x[0] != k]
        e = ents.setdefault(o, {"label": defs[o].get("label"), "comment": defs[o].get("comment"), "props": {}})
        e["props"][p] = {"value": value, "value_source": "兜底｜%s｜本次未取到值" % ct.REQUIRED_FILE, "label": pd.get("label"),
                         "comment": pd.get("comment"), "extractIds": [], "rules": ref.get(k, [])}
        FALLBACK_FILLED.append((k, value))
        tool_issues.append("枚举键 %s 本次未取到值，按 %s 兜底传入 %s" % (k, ct.REQUIRED_FILE, json.dumps(value, ensure_ascii=False)))

    names = list(defs)
    ents_sorted = {o: ents[o] for o in names if o in ents}
    inp = {o: {p: d["value"] for p, d in e["props"].items()} for o, e in ents_sorted.items()}
    cb = {"routing": doc["routing"], "refKeys": rk, "rulesDropped": rules_dropped,
          "entities": {o: {"label": e["label"], "comment": e["comment"], "properties": e["props"]} for o, e in ents_sorted.items()},
          "unfilled": {o: unfilled[o] for o in sorted(unfilled, key=lambda x: names.index(x) if x in names else 999)},
          "notFoundInDefinition": notfound, "fixedUnmapped": fixed_unmapped, "input": inp}
    out_fp = os.path.join("work", rid, "input-combine.json")
    with open(out_fp, "w", encoding="utf-8") as f:
        f.write(ct.render_combine(cb))

    # 最终 notes：明细里的 N 行 + 没有明细 N 行支撑的 unfilled 键（按实体+原因码合并；R14 只合并一条）
    reasons = ct.CONFIG["reasonByCode"]
    notes = json.loads(json.dumps(doc["notes"]))
    lines = list(notes["unresolvedProperties"])
    grouped, r14 = {}, 0
    for k, code, why in notes_unfilled:
        o, p = k.split(".")
        if code == "R14":
            r14 += 1
            continue
        grouped.setdefault((o, code, why or reasons.get(code, "本流程不填")), []).append(p)
    for (o, code, why), ps in grouped.items():
        lines.append("%s.[%s]｜%s｜%s" % (o, ",".join(ps), code, why))
    if r14:
        lines.append("结果类属性（共 %d 个，由引擎产出）｜R14｜%s" % (r14, reasons["R14"]))
    notes["unresolvedProperties"] = lines
    notes["notFoundInDefinition"] = notfound
    for t in tool_issues:
        if t not in notes["toolIssues"]:
            notes["toolIssues"].append(t)
    nf = os.path.join("work", rid, "notes-final.json")
    with open(nf, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=1)
    return cb, notes, need_value, undecided, ignored, enum_dropped, type_dropped, out_fp, (len(all_rules), rules_dropped)


def run_validate(rid, rules_path):
    import argparse as ap
    import contextlib
    import io
    ns = ap.Namespace(extract=os.path.join("work", rid, "input-extract-detail.json"),
                      combine=os.path.join("work", rid, "input-combine.json"), rules=rules_path,
                      items=os.path.join(dt.CAT, "extract-items-checked.json"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ct.cmd_validate(ns)
    return rc, buf.getvalue().strip().splitlines()


def cmd_build(a):
    rules, props = rules_list(a.rules), props_list(a.props)
    sets, raw = {}, ""
    if not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            try:
                spec = json.loads(raw)
            except ValueError as exc:
                die("stdin 不是合法 JSON（%s）" % exc)
            for k, v in (spec.get("set") or {}).items():
                if not (isinstance(v, list) and len(v) == 2 and isinstance(v[1], str) and v[1].startswith("派生:") and "｜" in v[1]):
                    die("set.%s 应为 [值, \"派生:ID,ID｜依据\"]" % k)
                sets[k] = v
    res = build(a.rid, rules, props, sets, spec if not sys.stdin.isatty() and raw.strip() else None)
    if res is None:
        cmd_plan(a)
        print("NO_MAP 还没有映射：按上面的 PLAN 决定后，用 build 的 stdin 提交 map / skip（见 PLAN 开头的格式）")
        sys.exit(4)
    cb, notes, need, undecided, ignored, enum_dropped, type_dropped, out_fp, (n_rules, rules_dropped) = res
    rules, _ = rule_scope(rules, load_map(a.rid))
    rc, lines = run_validate(a.rid, a.rules)
    print("RULE_SCOPE 规则共 %d 条：与客户准入相关、参与组装 %d 条；判定与准入无关、已抛掉 %d 条（它们条件里的字段不进 input-combine.json，引擎即使命中也不计入结论）%s" % (
        n_rules, n_rules - len(rules_dropped), len(rules_dropped), "：" if rules_dropped else ""))
    for d in rules_dropped[:80]:
        print("- %s｜%s｜%s" % (d["ruleId"], d["label"], d["reason"]))
    if rules_dropped:
        print('  看一眼：确实与准入有关的，在 build 的 stdin 里写 {"rules":{"keep":["规则ID"]}} 留下；保留的规则里明显与客户准入无关的（如只针对结算、出款、复核留痕），写 {"rules":{"drop":{"规则ID":"原因"}}} 抛掉。拿不准就保留。')
    n_ent = sum(len(e["properties"]) for e in cb["entities"].values())
    n_unf = sum(len(v) for u in cb["unfilled"].values() for v in u.values())
    print("OK %s  refKeys=%d 有值=%d unfilled=%d notFound=%d" % (out_fp, sum(len(v) for v in cb["refKeys"].values()), n_ent, n_unf, len(cb["notFoundInDefinition"])))
    for ln in lines:
        if ln.startswith(("keys:", "ERR", "validate:")):
            print(ln)
    print(compare_summary(a.rid))
    checks = review_checks(a.rid)
    for c in checks:
        print("CHECK " + c)
    if need:
        by = {x["id"]: x for x in ct.load(os.path.join("work", a.rid, "input-extract-detail.json"))["items"]}
        print("NEED_VALUE 以下派生属性需要你按本次属性 label/comment 和规则含义判断后用 set 提交（推不出就不提交，保持 unfilled）：")
        rl = ct.rule_index(rules)
        for k, ids in need:
            print("- %s  依据条目：%s" % (k, "；".join("%s=%s" % (i, by[i]["value"] if by[i]["source"].startswith("Y｜") else "N") for i in ids)))
            for r in rl.get(k, [])[:3]:
                print("    %s %s" % (r["ruleId"], r["condition"][:200]))
    if undecided:
        print("UNDECIDED %d 个规则引用键你既没映射也没 skip，已按 R10 记入 unfilled。逐个看含义：结果类（结论/处置/是否放行/汇总信号）改放 skip.R14，外部来源（三方核查/结算/个人/流水）放 skip.R13，能由某个清单条目取到的放 map；确实无口径的可保持 R10：" % len(undecided))
        for k, lb in undecided[:60]:
            print("- %s｜%s" % (k, lb or ""))
    if PRESET_UNDEFINED:
        print("PRESET_UNDEFINED 预设的标识键本次属性定义里没有，仍按预设传入（引擎自己的流程可能要它）：%s。若本体已把它改名，改 run_process_required.json，不要改提示词。" % "、".join(PRESET_UNDEFINED))
    if FALLBACK_FILLED:
        print("FALLBACK_FILLED 枚举键本次未取到值，已按 run_process_required.json 兜底传入（已记 notes.toolIssues，不用处理，不写进摘要依据）：%s" % "、".join(
            "%s=%s" % (k, json.dumps(v, ensure_ascii=False)) for k, v in FALLBACK_FILLED))
    if enum_dropped:
        print("ENUM_DROPPED %d 个枚举属性的取值不是可选项，已按 R10 记入 unfilled、不进 input（有 enum 从 enum 选编码，没有 enum 从 comment 选一项；用 set 重交，置信度低于 50%% 就 skip R10）：" % len(enum_dropped))
        for k, why in enum_dropped[:20]:
            print("- %s｜%s" % (k, why))
    if type_dropped:
        print("TYPE_DROPPED %d 个键的取值类型与规则用法不符，已按 R10 记入 unfilled、不进 input（多半是映射错了条目：回到 PLAN 看 label 含义，改映射或改 skip；不要把文字塞给布尔/数字/日期键）：" % len(type_dropped))
        for k, why in type_dropped[:20]:
            print("- %s｜%s" % (k, why))
    if ignored:
        print("IGNORED %d 个你提交的键不是规则引用的键也不是标识，不进 input：%s" % (len(ignored), ",".join(ignored[:20])))
    missing_inst = ct.missing_inst_keys(rules, cb["input"])
    if missing_inst:
        print("INST_REQUIRED_MISSING 机构自定义规则的必填输入尚未齐全：%s。补齐有证据的 map/set 后重新 build；来源确实缺失则按审核未完成处理，不调用 mcp_run_process。" % "、".join(missing_inst))
        print("NOTES " + json.dumps(no_curly(notes), ensure_ascii=False, separators=(",", ":")))
        sys.exit(1)
    print("INPUT " + json.dumps(cb["input"], ensure_ascii=False, separators=(",", ":")))
    print("NOTES " + json.dumps(no_curly(notes), ensure_ascii=False, separators=(",", ":")))
    sys.exit(1 if checks or any(ln.startswith("ERR") for ln in lines) else 0)


ASSERT_WORDS = ("真实", "合规", "正常", "可信", "无异常", "没有异常")


def review_checks(rid):
    """v37：原来自审 A 里能机械核对的两项改由脚本做（v35 五次自审全部“通过”，没拦下任何问题，却每次多花一轮）。
    ①“是否有伪造嫌疑”类条目的 source 不得含真实/合规/正常/可信/无异常这类断言；②E05（明确物理造假证据）只能是 true/false/空。"""
    doc = ct.load(os.path.join("work", rid, "input-extract-detail.json"))
    out = []
    for x in doc["items"]:
        src = x["source"].split("｜", 1)[-1]
        if "伪造嫌疑" in x["name"] and x["source"].startswith("Y｜"):
            bad = [w for w in ASSERT_WORDS if w in src]
            if bad:
                out.append("%s（%s）的依据含断言字样「%s」：只写逐项看了什么、看到的具体现象；用 detail.py fill --force 改写后重跑 build" % (x["id"], x["name"], "、".join(bad)))
        if x["id"] == "E05" and x["source"].startswith("Y｜") and x["value"] not in ("true", "false"):
            out.append("E05 的值只能是 true/false（或取不到写 null + R06），现在是「%s」" % short(x["value"], 30))
    return out


def compare_summary(rid):
    """v33：工商与原件比对的一行汇总，自审第⑤项直接引用这一行（am1 自审没跑 compare 却写了“compare 输出”）。"""
    doc = ct.load(os.path.join("work", rid, "input-extract-detail.json"))
    st_fp = os.path.join("work", rid, ".detail-state.json")
    st = dt.load_json_file(st_fp) if os.path.isfile(st_fp) else {}
    rc = st.get("rechecked") or {}
    cnt, diff = {"same": 0, "diff": 0, "na": 0}, []
    for o, b, l, k, status in dt.pair_rows(doc):
        cnt[status] += 1
        if status == "diff" or o in rc:
            diff.append("%s%s=%s" % (o, l, dt.OUTCOME_LABEL.get(rc.get(o, {}).get("outcome"), "未复核")))
    return "COMPARE_SUMMARY %d 项：一致 %d，不一致 %d，无法比较 %d；复核：%s；待复核 %d" % (
        len(dt.PAIRS), cnt["same"], cnt["diff"], cnt["na"], "、".join(diff) or "无", len(dt.recheck_pending(doc, st)))


def cmd_validate(a):
    rc, lines = run_validate(a.rid, a.rules)
    print("\n".join(lines))
    sys.exit(rc)


# ---- 参数防呆（RunSkillScript 不是 shell，模型偶尔把整条命令连同大量换行塞进 args 的一项） ----
def _packed(x):
    return x != x.strip() or any(ord(ch) < 32 for ch in x) or re.search(r"\s-{1,2}[A-Za-z]", x) is not None


def repair_argv(argv, script, usage):
    """把塞进一项的整条命令拆回逐项（按空白拆；本流程的路径都是 tool-results/… 无空格），打印 WARN 后照常执行。"""
    if not any(_packed(x) for x in argv):
        return argv
    import shlex
    out = []
    for x in argv:
        if _packed(x):
            try:
                out.extend(shlex.split(x))
            except ValueError:
                out.extend(x.split())
        else:
            out.append(x)
    print("WARN ARGS_REPACKED args 把整条命令或换行塞进了一项，脚本已拆成 %d 项照常执行：%s。"
          "下次调用请 args 一词一项。用法：%s" % (len(out), " ".join(out)[:300], usage))
    return out


class ArgParser(argparse.ArgumentParser):
    """参数错误时给出能照着改的提示（exit 2），不让模型只看到 argparse 原话。"""
    usage_hint = ""

    def error(self, message):
        print("ERROR INVALID_SCRIPT_ARGS " + " ".join(message.split())[:300])
        print("HINT 用法：" + self.usage_hint)
        print("HINT args 一词一项、不带换行；按提示改一次后重跑。同一参数错误第二次出现就不要再试，"
              "把原话记入 toolIssues，按“技能配置异常”处理")
        sys.exit(2)

USAGE = 'build/plan --rid <requestId> --rules <规则文件>... --props <属性文件>；validate --rid <requestId> --rules <文件>...；names/rules --rules <文件>...；props --props <文件>；result --file <文件>；summary --rid <requestId>；例 args=["build","--rid","<requestId>","--rules","规则文件1","机构规则文件","--props","属性文件"]'


def main():
    ArgParser.usage_hint = USAGE
    ap = ArgParser()
    sp = ap.add_subparsers(dest="cmd", required=True, parser_class=ArgParser)
    n = sp.add_parser("names")
    n.add_argument("--rules", required=True, nargs="+")
    b = sp.add_parser("build")
    b.add_argument("--rid", required=True)
    b.add_argument("--rules", required=True, nargs="+")
    b.add_argument("--props", required=True)
    pl = sp.add_parser("plan")
    pl.add_argument("--rid", required=True)
    pl.add_argument("--rules", required=True, nargs="+")
    pl.add_argument("--props", required=True)
    ru = sp.add_parser("rules")
    ru.add_argument("--rules", required=True, nargs="+")
    ru.add_argument("--grep")
    pr = sp.add_parser("props")
    pr.add_argument("--props", required=True)
    pr.add_argument("--obj")
    rs = sp.add_parser("result")
    rs.add_argument("--rid")
    rs.add_argument("--file", required=True)
    sm = sp.add_parser("summary")
    sm.add_argument("--rid", required=True)
    sm.add_argument("--file")
    v = sp.add_parser("validate")
    v.add_argument("--rid", required=True)
    v.add_argument("--rules", required=True, nargs="+")
    a = ap.parse_args(repair_argv(sys.argv[1:], "combine.py", USAGE))
    for k in ("biz", "rules"):  # 多文件参数：逗号拼接也拆开（路径不含逗号）
        if isinstance(getattr(a, k, None), list):
            setattr(a, k, [x.strip() for f in getattr(a, k) for x in f.split(",") if x.strip()])
    {"names": cmd_names, "build": cmd_build, "plan": cmd_plan, "validate": cmd_validate, "rules": cmd_rules, "props": cmd_props, "result": cmd_result, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    main()
