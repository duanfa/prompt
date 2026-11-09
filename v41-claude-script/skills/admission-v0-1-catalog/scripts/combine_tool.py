#!/usr/bin/env python3
"""input-combine.json 参考实现 + 校验器（Agent 没有 Bash，只能 Read/Write/Edit 手写同结构文件；
本工具给平台侧预处理、离线回归和格式样例用）。

  skeleton  由 mcp_list_rule / mcp_list_property 返回 + extract-items-checked.json（+ 可选 input-extract-detail.json）生成 input-combine.json
  validate  校验 extract-detail 与 combine 的一致性（对应审核 A 的机械条款）

清单（extract-items-checked.json）只是抽取的原始数据，不带属性对应关系：条目对到哪个本体属性由 Agent 按语义决定。
本工具只对“固定标识”（A01–A04 请求参数）自带来源；其他键的 条目→属性 对应由 --map 文件（{"实体.属性":["B16"],…}，
多个 ID 表示由多条明细推出，值留空待组装）传入，用于离线回归；不传则只出固定标识。规则引用但没有条目的键进 unfilled，
原因码这里只按键名粗分 R14/R10，真实登记由 Agent 按 catalog skill 第四节判断。

用法:
  python3 combine_tool.py skeleton --rules list_rule.json --props list-properties.json --items extract-items-checked.json \
        [--map key2ids.json] [--extract input-extract-detail.json] --routing requestId=..,domain=..,scene=..,businessKey=.. --out input-combine.json
  python3 combine_tool.py validate --extract input-extract-detail.json --combine input-combine.json [--rules ..] [--props ..] [--items extract-items-checked.json]
"""
import argparse, json, os, re, sys, unicodedata
from collections import OrderedDict

KEY = re.compile(r"\b([A-Z][A-Za-z]+)\.([a-z][a-z_]*)\b")
CONFIG = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "combine_config.json"), encoding="utf-8"))
# v29：不再写死任何属性名（旧版的固定标识键、字符串键、_name 后缀、结果类正则、定义冲突都曾在这里，本体改名就失效）。
# 清单条目 → 属性的对应由 Agent 按含义决定；这里只认清单里的预设条目 ID（A01–A04、A08，清单侧稳定）。
REQUIRED_FILE = "run_process_required.json"
_rp = os.path.join(os.path.dirname(os.path.abspath(__file__)), REQUIRED_FILE)
# 调 mcp_run_process 必带的预设键（四个标识 + 用工场景）及兜底值，单独成文件；没有该文件时退回旧版 combine_config.json 的 fixedIdentifiers/softPresets
_rq = json.load(open(_rp, encoding="utf-8")) if os.path.isfile(_rp) else {}
REQUIRED = _rq["required"] if _rq else [
    {"key": k, "item": item, "soft": item in CONFIG.get("softPresets", []), "why": ""}
    for item, keys in CONFIG.get("fixedIdentifiers", {}).items() for k in keys]
PRESET_IDS = {r["key"]: r["item"] for r in REQUIRED}   # 预设：键 → 标识条目（A01–A04、A08）
FIXED_ITEMS = list(dict.fromkeys(r["item"] for r in REQUIRED)) or CONFIG.get("fixedItems", [])
SOFT_PRESETS = {r["item"] for r in REQUIRED if r.get("soft")}   # 预设里“模型提交了也只忽略、不退回”的条目（用工场景 A08）；四个 ID 不在其中，改映/skip 仍退回
ENUM_FALLBACKS = OrderedDict((r["key"], r["fallback"]) for r in _rq.get("enumFallbacks", []) if r["key"] not in PRESET_IDS)   # 枚举键没取到值时的兜底


def jl(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def load(p):
    """读 JSON 文件；工具落盘的返回可能在 JSON 后带网关页脚（Request reference: …），只取第一个 JSON 值。"""
    with open(p, encoding="utf-8") as f:
        text = f.read()
    return json.JSONDecoder().raw_decode(text.lstrip())[0]


def cond_keys(cond):
    """条件里的 对象.属性（去掉双引号字面量，免得把字面值当属性）"""
    return list(dict.fromkeys("%s.%s" % t for t in KEY.findall(re.sub(r'"[^"]*"', '""', cond))))


INST_PREFIX = "INST-"
INST_STAGE = "机构风控规则（inst-rc-rule-mcp）｜适用阶段：准入"


def inst_rules(doc):
    """v41：inst-rc-rule-mcp 返回 {"model":[{"companyName":"Employer.employer_name CONTAINS [修匀]"},…]}（也认外面再包一层 data）。
    每一项转成一条规则：ruleId=INST-<名称>，condition=表达式原文。返回 [] 表示不是机构规则文件。"""
    d = doc.get("data") if isinstance(doc, dict) and isinstance(doc.get("data"), dict) else doc
    model = d.get("model") if isinstance(d, dict) else None
    out = []
    for x in model if isinstance(model, list) else []:
        for name, expr in (x.items() if isinstance(x, dict) else []):
            if isinstance(expr, str) and expr.strip():
                out.append({"ruleId": INST_PREFIX + str(name), "label": "机构风控规则 %s" % name, "comment": INST_STAGE,
                            "condition": expr.strip(), "source": "inst"})
    return out


def load_rules(paths):
    """--rules 可给多个文件：mcp_list_rule 的 {data:[…]} 与 inst-rc-rule-mcp 的 {model:[…]}，合并成一个规则列表。"""
    rows = []
    for path in paths if isinstance(paths, (list, tuple)) else [paths]:
        doc = load(path)
        inst = inst_rules(doc)
        if inst:
            rows.extend(inst)
            continue
        data = doc.get("data") if isinstance(doc, dict) else doc
        rows.extend(data if isinstance(data, list) else [])
    return rows


def inst_keys(rules):
    """机构规则引用的必填 对象.属性：与本体规则合并组装，本体定义没有也要传。"""
    return list(dict.fromkeys(k for r in rules if r.get("source") == "inst" for k in cond_keys(r["condition"])))


def missing_inst_keys(rules, inp):
    """机构规则的输入依赖不能以 skip / 定义未返回代替；false 和 0 是有效值。"""
    missing = []
    for key in inst_keys(rules):
        obj, prop = key.split(".")
        value = inp.get(obj, {}).get(prop)
        if value is None or (isinstance(value, str) and not value.strip()) or value == [] or value == {}:
            missing.append(key)
    return missing


def rule_index(rules):
    ref = {}
    for r in rules["data"] if isinstance(rules, dict) and "data" in rules else rules:
        for m in cond_keys(r["condition"]):
            ref.setdefault(m, []).append({"ruleId": r["ruleId"], "label": r["label"], "comment": r.get("comment"), "condition": r["condition"]})
    return ref


def numeric_key(key, rules):
    """条件里该键只与数字字面量比较 → 数值型"""
    pat = re.compile(re.escape(key) + r"\s*(<=|>=|<|>|=|!=)\s*-?\d+(\.\d+)?(?![\w.])")
    anyuse = [r for r in rules if re.search(re.escape(key) + r"\b", r["condition"])]
    return bool(anyuse) and all(pat.search(r["condition"]) for r in anyuse)


# 传给引擎的取值统一文字口径（2026-11-09）：引擎逐字比较名称，「（个人独资）」与「(个人独资)」、多一个空格都会判不一致。
# combine build 组装 input 时对所有字符串取值做最后一遍：全角/中文标点 → 英文标点（NFKC + 下表），去掉首尾和中间的空白、零宽字符；
# 只保留两个英文字母/数字之间的一个空格（如 "ABC Technology"、"2025-12-31 00:00:00"），否则英文名称、时间会粘连。
# input-extract-detail.json 保持原文不改：工商预填、派生行（J08「；」、J10「截止 」、J34「不一致：」）脚本还要按原样解析，摘要引文也要逐字核对。
PUNCT_MAP = str.maketrans({"【": "[", "】": "]", "〔": "(", "〕": ")", "〈": "<", "〉": ">", "《": "<", "》": ">",
                           "“": '"', "”": '"', "‘": "'", "’": "'", "「": '"', "」": '"', "『": '"', "』": '"',
                           "。": ".", "、": ",", "—": "-", "–": "-", "―": "-", "‐": "-", "‑": "-", "－": "-", "～": "~", "…": "..."})
ZERO_WIDTH_RE = re.compile(r"[​-‏⁠﻿]")
INNER_SPACE_RE = re.compile(r"\s+")


def _keep_space(t, m):
    a, b = m.start() - 1, m.end()
    return a >= 0 and b < len(t) and t[a].isascii() and t[a].isalnum() and t[b].isascii() and t[b].isalnum()


def norm_text(v):
    if not isinstance(v, str):
        return v
    t = unicodedata.normalize("NFKC", ZERO_WIDTH_RE.sub("", v)).translate(PUNCT_MAP).strip()
    return INNER_SPACE_RE.sub(lambda m: " " if _keep_space(t, m) else "", t)


def typed(key, s, rules, as_str=False):
    """as_str：标识类（映射自 A01–A04）保持字符串。其余只看规则怎么用它：只与数字比较 → 数值；true/false → 布尔。"""
    if s is None:
        return None
    if as_str:
        return s
    if s in ("true", "false"):
        return s == "true"
    if re.fullmatch(r"-?\d+(\.\d+)?", s) and numeric_key(key, rules):
        return float(s) if "." in s else int(s)
    return s


def split_source(src):
    """Y｜来源｜证据  /  N｜Rxx｜原因"""
    p = (src or "").split("｜")
    return p[0] if p else "", p




def render_combine(cb):
    """把 combine 字典渲染成“每个属性一行”的紧凑格式（与 facts skill 的示例一致，便于 Edit）。"""
    lines = ['{\n"contract":"admission-noshell-v0-1",\n"schema":"input-combine/3",\n"routing":%s,\n"refKeys":%s,\n"rulesDropped":%s,\n"entities":{' % (jl(cb["routing"]), jl(cb["refKeys"]), jl(cb.get("rulesDropped", [])))]
    el = []
    for o, e in cb["entities"].items():
        pl = ",\n".join("%s:%s" % (jl(p), jl(d)) for p, d in e["properties"].items())
        el.append('%s:{"label":%s,"comment":%s,"properties":{\n%s\n}}' % (jl(o), jl(e["label"]), jl(e["comment"]), pl))
    lines.append(",\n".join(el) + '\n},\n"unfilled":{')
    lines.append(",\n".join("%s:%s" % (jl(o), jl(u)) for o, u in cb["unfilled"].items()))
    lines.append('},\n"notFoundInDefinition":%s,\n"fixedUnmapped":%s,\n"input":{' % (jl(cb["notFoundInDefinition"]), jl(cb.get("fixedUnmapped", {}))))
    lines.append(",\n".join("%s:%s" % (jl(o), jl(v)) for o, v in cb["input"].items()) + "\n}\n}\n")
    return "\n".join(lines)


def cmd_skeleton(a):
    rules = load_rules(a.rules)
    defs = {o["name"]: o for o in load(a.props)["data"]}
    known = {i["id"] for i in load(a.items)}  # 人工核对清单：list of {id,group,name,desc}
    extract = {i["id"]: i for i in load(a.extract)["items"]} if a.extract else {}
    ref = rule_index(rules)
    key2items = OrderedDict((k, list(v)) for k, v in (load(a.map).items() if a.map else []))
    FIXED = [k for k, v in key2items.items() if len(v) == 1 and v[0] in FIXED_ITEMS]   # 映射到标识条目的键（不写死属性名）
    bad = sorted({x for v in key2items.values() for x in v} - known)
    if bad:
        sys.exit("--map 引用了清单里没有的条目: %s" % bad)
    plabel = lambda k: defs.get(k.split(".")[0], {}).get("properties", [])
    ents, unfilled, notfound = OrderedDict(), OrderedDict(), []
    want = [k for k in key2items if k in ref or k in FIXED]
    for k in dict.fromkeys(want):
        o, p = k.split(".")
        pd = next((x for x in plabel(k) if x["name"] == p), None)
        if pd is None:
            notfound.append(k)
            continue
        ids = key2items.get(k, [])
        prim = extract.get(ids[0]) if ids else None
        val, vs = None, ""
        if len(ids) > 1:  # 由多条明细推出：值由 Agent 按规则语义组装，工具只留空骨架
            vs = "派生:%s｜待按规则语义组装" % ",".join(ids)
        elif prim is not None:
            vs = "%s｜%s" % (prim["id"], prim.get("source") or "")
            if prim.get("value") is not None:
                val = typed(k, prim["value"], rules)
        if val is None and len(ids) <= 1:  # v26：null 的键不进 entities，只在 unfilled 登记（原因码取主条目 N 码 / 定义矛盾码）
            m = re.match(r"N｜(R(?:0[1-9]|1[0-5]))｜", (prim or {}).get("source") or "")
            code = m.group(1) if m else "R10"
            unfilled.setdefault(o, OrderedDict()).setdefault(code, []).append(p)
            continue
        e = ents.setdefault(o, {"label": defs[o]["label"], "comment": defs[o].get("comment"), "props": OrderedDict()})
        e["props"][p] = OrderedDict([("value", val), ("value_source", vs), ("label", pd["label"]), ("comment", pd.get("comment")),
                                     ("extractIds", ids), ("rules", ref.get(k, []))])
    for k, rs in ref.items():
        if k in key2items:
            continue
        o, p = k.split(".")
        pd = next((x for x in plabel(k) if x["name"] == p), None)
        code = "R10"
        if pd is None:
            notfound.append(k)
            continue
        unfilled.setdefault(o, OrderedDict()).setdefault(code, []).append(p)
    inp = OrderedDict()
    for o, e in ents.items():
        for p, d in e["props"].items():
            if d["value"] is not None:
                inp.setdefault(o, OrderedDict())[p] = d["value"]
    routing = dict(x.split("=", 1) for x in a.routing.split(",")) if a.routing else {"requestId": "", "domain": "", "scene": "", "businessKey": ""}
    refkeys = OrderedDict()
    for k in ref:  # 规则返回顺序下的首次出现顺序，按实体分组
        refkeys.setdefault(k.split(".")[0], []).append(k.split(".")[1])
    cb = OrderedDict([("routing", routing), ("refKeys", refkeys),
                      ("entities", OrderedDict((o, OrderedDict([("label", e["label"]), ("comment", e["comment"]), ("properties", e["props"])]))
                                               for o, e in ents.items())),
                      ("unfilled", unfilled), ("notFoundInDefinition", notfound), ("input", inp)])
    open(a.out, "w", encoding="utf-8").write(render_combine(cb))
    n = sum(len(e["props"]) for e in ents.values())
    print("combine: %d entities, %d properties, %d unfilled keys, %d valued, %d notFound" % (len(ents), n, sum(len(l) for u in unfilled.values() for l in u.values()), sum(len(v) for v in inp.values()), len(notfound)))


def cmd_validate(a):
    errs = []
    ex, cb = load(a.extract), load(a.combine)
    items = ex["items"]
    ids = [i["id"] for i in items]
    if len(ids) != len(set(ids)):
        errs.append("extract: id 重复")
    if a.items:
        tmpl = [i["id"] for i in load(a.items)]
        if ids != tmpl[:len(ids)] or len(ids) != len(tmpl):
            errs.append("extract: 条目顺序或数量与清单不一致（应 %d 条，实 %d 条）" % (len(tmpl), len(ids)))
        miss = [i for i in tmpl if i not in ids]
        if miss:
            errs.append("extract: 缺少清单条目 %s" % miss)
    for i in items:
        for f in ("id", "name", "desc", "value", "source"):
            if f not in i:
                errs.append("extract %s: 缺字段 %s" % (i.get("id"), f))
        v, s = i.get("value"), i.get("source") or ""
        if v is not None and not isinstance(v, str):
            errs.append("extract %s: value 必须是字符串或 null" % i["id"])
        if v is not None and not s.startswith("Y｜"):
            errs.append("extract %s: 有值时 source 必须以 'Y｜来源｜证据' 开头" % i["id"])
        if v is None and not re.match(r"N｜R(0[1-9]|1[0-5])｜.{4,}", s):
            errs.append("extract %s: 无值时 source 必须是 'N｜Rxx｜具体原因'" % i["id"])
    byid = {i["id"]: i for i in items}
    flat = {}
    for o, e in cb["entities"].items():
        for p, d in e["properties"].items():
            flat["%s.%s" % (o, p)] = d
            if d["value"] is None:  # v26：entities 只放有值的属性；null 的键只进 unfilled（v25 实测 129 个 null 行，combine 93 KB）
                errs.append("entities 含 null 属性 %s.%s（应删除并登记到 unfilled）" % (o, p))
            if d["value_source"].startswith("派生:"):  # 派生属性（多条明细推出）：只要求依据条目存在，不要求等于主条目
                missing = [x for x in d["extractIds"] if x not in byid]
                if missing:
                    errs.append("combine %s.%s: 派生依据条目不存在 %s" % (o, p, missing))
                if d["value"] is None and p in cb["input"].get(o, {}):
                    errs.append("input 含 null 键 %s.%s" % (o, p))
                continue
            if d["value"] is not None:
                if not d["value_source"].startswith(tuple(x + "｜" for x in d["extractIds"])) and d["extractIds"]:
                    errs.append("combine %s.%s: value_source 应以主条目 ID 开头" % (o, p))
                prim = byid.get(d["extractIds"][0]) if d["extractIds"] else None
                if d["extractIds"] and (prim is None or prim.get("value") is None):
                    errs.append("combine %s.%s: 有值但主条目 %s 在 extract 中无值" % (o, p, d["extractIds"][0]))
                elif prim is not None:
                    pv = prim["value"]
                    ok = str(d["value"]).lower() == pv.lower() if isinstance(d["value"], bool) else str(d["value"]) in (pv, norm_text(pv))
                    if not ok and isinstance(d["value"], str) and re.fullmatch(r"\d{8}", d["value"]):     # v33：日期键统一为 yyyyMMdd
                        ok = d["value"] in ["%04d%02d%02d" % tuple(map(int, g)) for g in re.findall(r"(\d{4})\D{0,2}(\d{1,2})\D{0,2}(\d{1,2})", pv)]
                    if not ok:
                        errs.append("combine %s.%s: value=%r 与 extract %s 的 %r 不一致" % (o, p, d["value"], prim["id"], pv))
            elif d["extractIds"]:
                prim = byid.get(d["extractIds"][0])
                if prim is not None and prim.get("value") is not None and "｜N｜R" not in d["value_source"]:  # 组装时按定义矛盾等原因置 null 须在 value_source 写 N｜Rxx
                    errs.append("combine %s.%s: extract 主条目 %s 有值但 combine 为 null（未在 value_source 写 N｜Rxx 原因）" % (o, p, prim["id"]))
            if d["value"] is None and p in cb["input"].get(o, {}):
                errs.append("input 含 null 键 %s.%s" % (o, p))
    exp = {}
    for k, d in flat.items():
        if d["value"] is not None:
            o, p = k.split(".")
            exp.setdefault(o, {})[p] = d["value"]
    if exp != cb["input"]:
        errs.append("input 与 entities 非空 value 不相等: 期望 %s 实际 %s" % (jl(exp), jl(cb["input"])))
    # v29：四个标识（清单条目 A01–A04）有值就必须映射到某个属性并进入 input；没有可映射的属性时必须在 fixedUnmapped 里写明原因。
    # v28 在这里写死 Employer.employer_name：本体改名后定义不返回它，build 跳过它，校验器却仍强制要求，模型怎么 set 都过不了（am7）。
    fx = cb.get("fixedUnmapped") or {}
    cover = {d["extractIds"][0] for d in flat.values() if len(d.get("extractIds") or []) == 1}
    for fid in FIXED_ITEMS:
        it = byid.get(fid)
        if it and it.get("value") is not None and fid not in cover and fid not in fx:
            errs.append("标识条目 %s（%s）有值，但没有映射到任何属性，也没有在 fixedUnmapped 写明原因" % (fid, it.get("name")))
    for o, u in cb.get("unfilled", {}).items():
        for code, ps in u.items():
            if not re.fullmatch(r"R(0[1-9]|1[0-5])", code):
                errs.append("unfilled %s: 非法原因码 %s" % (o, code))
            for p in ps:
                if "%s.%s" % (o, p) in flat:
                    errs.append("键同时出现在 entities 与 unfilled: %s.%s" % (o, p))
    rk = cb.get("refKeys")
    if not isinstance(rk, dict):
        errs.append("combine 缺 refKeys（本次 condition 引用的 对象.属性，按实体分组）")
        rk = {}
    rkset = {"%s.%s" % (o, p) for o, ps in rk.items() for p in ps}
    if rkset:
        for o, u in cb.get("unfilled", {}).items():
            for code, ps in u.items():
                for p in ps:
                    if "%s.%s" % (o, p) not in rkset:
                        errs.append("unfilled %s.%s 不在 refKeys 里" % (o, p))
        for o, ps in rk.items():  # 按实体闭合 n = m + l + k
            nf_o = {k for k in cb.get("notFoundInDefinition", []) if k.startswith(o + ".")}
            n = len(ps)
            m = sum(1 for p in ps if "%s.%s" % (o, p) in flat)
            l = sum(1 for p in ps if "%s.%s" % (o, p) in nf_o)
            k_ = sum(len(set(u) & set(ps)) for u in [sum(cb.get("unfilled", {}).get(o, {}).values(), [])])
            if n != m + l + k_:
                errs.append("refKeys %s: n=%d ≠ m+l+k=%d+%d+%d" % (o, n, m, l, k_))
    if a.rules:
        dropped = {d.get("ruleId") for d in cb.get("rulesDropped") or []}      # v39：与准入无关、组装前已抛掉的规则不参与闭合
        rules = [r for r in load_rules(a.rules) if r.get("ruleId") not in dropped]
        ref = rule_index(rules)
        for key in missing_inst_keys(rules, cb["input"]):
            errs.append("INST_REQUIRED_MISSING %s：机构自定义规则引用的必填属性未进入 input；按本次规则含义映射有证据的清单条目，不能以 skip 或定义未返回代替" % key)
        # unfilled / notFoundInDefinition 卫生检查（v25）：N = M + L + K，每个键恰好一个去向
        refkeys = set(k for r in rules for k in cond_keys(r["condition"]))
        if rkset and rkset != refkeys:
            errs.append("refKeys 与规则 condition 引用不一致: 多 %s 缺 %s" % (sorted(rkset - refkeys)[:8], sorted(refkeys - rkset)[:8]))
        ent = set(flat)
        nf = set(cb.get("notFoundInDefinition", []))
        uf = {}
        for o, u in cb.get("unfilled", {}).items():
            for code, ps in u.items():
                for p in ps:
                    uf.setdefault("%s.%s" % (o, p), []).append(code)
        for k, codes in sorted(uf.items()):
            if len(codes) > 1:
                errs.append("unfilled %s: 同一个键出现在多个原因码 %s" % (k, sorted(codes)))
            if k not in refkeys:
                errs.append("unfilled %s: 没有任何规则 condition 引用它，不应登记" % k)
        miss = sorted(k for k in refkeys if k not in ent and k not in uf and k not in nf)
        if miss:
            errs.append("规则引用键既不在 entities、unfilled，也不在 notFoundInDefinition（%d 个）: %s" % (len(miss), miss[:12]))
        N, M, L, K = len(refkeys), len(refkeys & ent), len(refkeys & nf), len(refkeys & set(uf))
        print("keys: N=%d M=%d L=%d K=%d (M+L+K=%d)" % (N, M, L, K, M + L + K))
        if N != M + L + K:
            errs.append("键数不闭合: N=%d ≠ M+L+K=%d" % (N, M + L + K))
        for k, d in flat.items():
            have = [r["ruleId"] for r in d["rules"]]
            want = [r["ruleId"] for r in ref.get(k, [])]
            if have != want:
                errs.append("combine %s: rules 与 list_rule 不符 (缺 %s 多 %s)" % (k, sorted(set(want) - set(have)), sorted(set(have) - set(want))))
            if d["value"] is not None and isinstance(d["value"], str) and re.fullmatch(r"-?\d+(\.\d+)?", d["value"]) and numeric_key(k, rules):
                errs.append("combine %s: 与数字比较的键应为数值而非字符串" % k)
            if isinstance(d["value"], (int, float)) and not isinstance(d["value"], bool) and not numeric_key(k, rules):
                errs.append("combine %s: 非数值比较键不应为数字" % k)
    for e in errs:
        print("ERR", e)
    print("validate:", "OK" if not errs else "%d errors" % len(errs))
    return 1 if errs else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("skeleton")
    for n in ("rules", "props", "items", "out"):
        s.add_argument("--" + n, required=True)
    s.add_argument("--extract"); s.add_argument("--routing"); s.add_argument("--map")
    v = sp.add_parser("validate")
    v.add_argument("--extract", required=True); v.add_argument("--combine", required=True)
    v.add_argument("--rules"); v.add_argument("--items")
    a = ap.parse_args()
    sys.exit(cmd_skeleton(a) if a.cmd == "skeleton" else cmd_validate(a))
