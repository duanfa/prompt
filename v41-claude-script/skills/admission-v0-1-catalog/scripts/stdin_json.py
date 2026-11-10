"""stdin JSON 的结构修复与连续失败计数（detail.py fill/recheck、combine.py build/summary 共用）。

背景：job 216 的 fill 少了一个关闭 rows 的 ]，模型改了 29 次说明文字也没补上括号；job 218 的 summary 把
next 数组的 ] 写成 },{，两次被拒后模型绕过脚本直接提交。两次都只是括号写错，原文本身没问题。

修复原则：
  1. 只改字符串外的结构符号（] } [ { ,），字符串内容一个字也不动；
  2. 先试单处修改（在任一位置补/删/互换一个 ] 或 }），再在报错位置附近的符号串里试两处以内的修改；
  3. 改完必须能解析、没有重复键、通过该子命令的入参校验，并且所有候选里只有唯一一种结果，才接收；
  4. 否则拒绝，并给出具体诊断（哪一行、哪个字符串里疑似有 ASCII 双引号等），不猜。

连续失败计数落盘在 work/<rid>/.stdin-failures.json，按步骤（fill/recheck/build/summary）分别计；该步骤解析成功即清零。
"""
import json
import os
import re

STRUCT = "]}"
RUN_ALPHABET = "]},{["
MAX_FULL_SCAN = 200_000      # 超过这个长度只在报错位置附近找
NEAR_RUNS = 6                # 两处修改只在报错位置前后这么多个符号串里找
GIVE_UP_AFTER = 3            # 同一步骤连续第 3 次解析失败：停止重试
FAIL_FILE = ".stdin-failures.json"


class DuplicateKey(ValueError):
    pass


def _pairs(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise DuplicateKey(k)
        obj[k] = v
    return obj


def strict_loads(raw):
    return json.loads(raw, object_pairs_hook=_pairs)


def string_spans(raw):
    """[(开引号下标, 闭引号下标)]；字符串没闭合时最后一段到文本末尾。"""
    spans, i, n = [], 0, len(raw)
    while i < n:
        if raw[i] == '"':
            j = i + 1
            while j < n and raw[j] != '"':
                j += 2 if raw[j] == "\\" else 1
            spans.append((i, min(j, n - 1)))
            i = j + 1
        else:
            i += 1
    return spans


def _outside_mask(raw, spans):
    """out[i] = 第 i 个字符在字符串外（引号本身算字符串内）。"""
    out = [True] * len(raw)
    for s, e in spans:
        for k in range(s, e + 1):
            out[k] = False
    return out


def _runs(raw, out):
    """字符串外、连续的结构符号串（忽略空白），返回 [(起, 止)]，止为开区间。"""
    runs, i, n = [], 0, len(raw)
    while i < n:
        if out[i] and raw[i] in "[]{},":
            j = i
            while j < n and out[j] and (raw[j] in "[]{}," or raw[j].isspace()):
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def _single_edits(raw, out, opens, closes, lo, hi):
    n = len(raw)
    for p in range(lo, min(hi, n) + 1):
        # 在 p 前插入：p 不能落在字符串内部（可以紧贴引号外侧）
        if (p == 0 or out[p - 1] or p - 1 in closes) and (p == n or out[p] or p in opens):
            for c in STRUCT:
                yield "在第 %d 个字符处补「%s」" % (p, c), raw[:p] + c + raw[p:]
        if p < n and out[p] and raw[p] in STRUCT:
            yield "删掉第 %d 个字符「%s」" % (p, raw[p]), raw[:p] + raw[p + 1:]
            other = "}" if raw[p] == "]" else "]"
            yield "第 %d 个字符「%s」改成「%s」" % (p, raw[p], other), raw[:p] + other + raw[p + 1:]


def _run_variants(seg, depth=2):
    """符号串 seg 在两处以内的增删改（字母表 ] } , { [），保留空白位置无关。"""
    core = "".join(c for c in seg if not c.isspace())
    seen, frontier = {core}, {core}
    for _ in range(depth):
        nxt = set()
        for s in frontier:
            for i in range(len(s) + 1):
                for c in RUN_ALPHABET:
                    nxt.add(s[:i] + c + s[i:])
                if i < len(s):
                    nxt.add(s[:i] + s[i + 1:])
                    for c in RUN_ALPHABET:
                        nxt.add(s[:i] + c + s[i + 1:])
        nxt -= seen
        seen |= nxt
        frontier = nxt
    seen.discard(core)
    return sorted(seen)


def _try(text, validate):
    try:
        obj = strict_loads(text)
    except ValueError:
        return None
    try:
        return obj if validate(obj) else None
    except Exception:            # 校验函数遇到意外结构一律视为不通过
        return None


def _unique(cands):
    """cands: [(说明, obj)] → 去重后唯一的一个，或 None（没有/有歧义）。"""
    by = {}
    for why, obj in cands:
        by.setdefault(json.dumps(obj, ensure_ascii=False, sort_keys=True), (why, obj))
    return list(by.values())


def repair(raw, err, validate):
    """返回 (obj, 说明) 或 (None, 'ambiguous'|None)。"""
    pos = getattr(err, "pos", None)
    if not isinstance(pos, int):
        return None, None
    spans = string_spans(raw)
    out = _outside_mask(raw, spans)
    opens, closes = {a for a, _ in spans}, {b for _, b in spans}
    lo, hi = (0, len(raw)) if len(raw) <= MAX_FULL_SCAN else (max(0, pos - 2000), pos + 50)
    found = []
    for why, text in _single_edits(raw, out, opens, closes, lo, hi):
        obj = _try(text, validate)
        if obj is not None:
            found.append((why, obj))
    uniq = _unique(found)
    if len(uniq) == 1:
        return uniq[0][1], uniq[0][0]
    if len(uniq) > 1:
        return None, "ambiguous"
    runs = _runs(raw, out)
    idx = [k for k, (s, e) in enumerate(runs) if s <= pos + 1]
    near = runs[max(0, (idx[-1] if idx else 0) - NEAR_RUNS + 1):(idx[-1] + 2 if idx else 2)]
    for s, e in near:
        seg = raw[s:e]
        for v in _run_variants(seg):
            obj = _try(raw[:s] + v + raw[e:], validate)
            if obj is not None:
                found.append(("第 %d 个字符处的「%s」改成「%s」" % (s, seg.strip(), v), obj))
    uniq = _unique(found)
    if len(uniq) == 1:
        return uniq[0][1], uniq[0][0]
    return None, ("ambiguous" if uniq else None)


ROW_ID_RE = re.compile(r'\[\s*"([A-Z][A-Za-z0-9-]{0,8})"\s*,')


def diagnose(raw, err):
    """解析失败、又修不了时给的具体提示。"""
    pos = getattr(err, "pos", None)
    if not isinstance(pos, int):
        return str(err)
    tips = []
    spans = string_spans(raw)
    # 字符串结束后紧跟的不是 , : ] }，这个“结束引号”多半是原文里的 ASCII 双引号
    for s, e in spans:
        if e >= pos + 1:
            break
        k = e + 1
        while k < len(raw) and raw[k].isspace():
            k += 1
        if k < len(raw) and raw[k] not in ",:]}":
            rid = ROW_ID_RE.findall(raw[:s])
            tips.append("%s字符串「%s」后面紧跟着「%s」：原文里疑似有 ASCII 双引号，把这处引号改成「」" %
                        ("%s 行的" % rid[-1] if rid else "", raw[s + 1:e][-20:], raw[k:k + 10]))
    near = raw[max(0, pos - 40):pos].replace("\n", " ") + "⟨这里⟩" + raw[pos:pos + 15].replace("\n", " ")
    rid = ROW_ID_RE.findall(raw[:pos])
    head = "%s（%s附近：…%s…）" % (err, "%s 行" % rid[-1] if rid else "出错位置", near)
    if tips:
        return head + "。" + tips[-1]
    return head + "。数一下这一处前后的 [ ] { } 是否成对"


def load(raw, validate):
    """解析 stdin。返回 (obj, warn 或 None, 错误说明 或 None)。"""
    try:
        obj = strict_loads(raw)
        return obj, None, None
    except DuplicateKey as exc:
        return None, None, "同一层里键「%s」出现了两次，合并成一个后重交" % exc
    except ValueError as exc:
        err = exc
    try:                        # 结尾多了 } 或 ]（v33 起就兼容）
        dec = json.JSONDecoder(object_pairs_hook=_pairs)
        obj, end = dec.raw_decode(raw.lstrip())
        rest = raw.lstrip()[end:].strip()
        if rest and set(rest) <= set(STRUCT) and _try(json.dumps(obj), validate) is not None:
            return obj, "结尾多了「%s」，已忽略" % rest, None
    except ValueError:
        pass
    obj, why = repair(raw, err, validate)
    if obj is not None:
        return obj, why, None
    msg = diagnose(raw, err)
    if why == "ambiguous":
        msg += "（括号有多种补法，脚本不替你选）"
    return None, None, msg


# ---------- 各步骤的入参校验（只看结构，不看业务） ----------

def _is_triple(r):
    return (isinstance(r, list) and len(r) == 3 and isinstance(r[0], str)
            and (r[1] is None or isinstance(r[1], (str, int, float, bool))) and isinstance(r[2], str))


def validate_fill(o):
    if not isinstance(o, dict) or not o or not set(o) <= {"materials", "rows", "notes"}:
        return False
    if "rows" in o and not (isinstance(o["rows"], list) and all(_is_triple(r) for r in o["rows"])):
        return False
    m = o.get("materials", {})
    if not isinstance(m, dict) or not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in m.values()):
        return False
    n = o.get("notes", {})
    return isinstance(n, dict) and all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in n.values())


def validate_recheck(o):
    return (isinstance(o, dict) and set(o) == {"rows"} and isinstance(o["rows"], list)
            and all(_is_triple(r) for r in o["rows"]))


BUILD_KEYS = {"map": dict, "skip": dict, "set": dict, "fixedUnmapped": dict, "toolIssues": list,
              "rules": dict, "categoryReview": dict}


def validate_build(o):
    if not isinstance(o, dict) or not o or not set(o) <= set(BUILD_KEYS):
        return False
    if not all(isinstance(o[k], BUILD_KEYS[k]) for k in o):
        return False
    if not all(v is None or (isinstance(v, list) and all(isinstance(x, str) for x in v)) for v in o.get("map", {}).values()):
        return False
    if not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in o.get("skip", {}).values()):
        return False
    if not all(v is None or (isinstance(v, list) and len(v) == 2 and isinstance(v[1], str)) for v in o.get("set", {}).values()):
        return False
    return all(isinstance(x, str) for x in o.get("toolIssues", []))


def _rule_item(x):
    return (isinstance(x, dict) and set(x) <= {"ruleIds", "text"} and isinstance(x.get("text"), str)
            and isinstance(x.get("ruleIds", []), list) and all(isinstance(i, str) for i in x.get("ruleIds", [])))


def validate_summary(o):
    if not isinstance(o, dict) or not set(o) <= {"basis", "next", "notice", "analysis"} or not isinstance(o.get("basis"), list):
        return False
    if not all(_rule_item(x) for x in o["basis"]):
        return False
    if not all(isinstance(x, str) or _rule_item(x) for x in o.get("next", [])) or not isinstance(o.get("next", []), list):
        return False
    nt = o.get("notice", [])
    if not isinstance(nt, list) or not all(isinstance(x, dict) and all(isinstance(v, str) for v in x.values()) for x in nt):
        return False
    an = o.get("analysis", [])
    return isinstance(an, list) and all(isinstance(x, str) for x in an)


VALIDATORS = {"fill": validate_fill, "recheck": validate_recheck, "build": validate_build, "summary": validate_summary}


# ---------- 连续失败计数 ----------

def _fail_path(rid):
    return os.path.join("work", rid, FAIL_FILE)


def bump(rid, step):
    """记一次失败，返回该步骤连续失败次数。rid 不可用时按 1 次算。"""
    if not rid:
        return 1
    fp = _fail_path(rid)
    try:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d[step] = int(d.get(step, 0)) + 1
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    return d[step]


def clear(rid, step):
    if not rid:
        return
    fp = _fail_path(rid)
    try:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return
    if d.pop(step, None) is not None:
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(d, f)


NEXT_TRY = {
    "fill": "改成分批提交：按材料拆开，每批不超过 20 行，已成功写入的行不重发",
    "recheck": "每次只提交一行复核",
    "build": "只提交这次要改的键（之前提交的 map/skip/set 已落盘，不用重交）",
    "summary": "只改被点名处的括号；再失败脚本进入宽松模式",
}


def read(raw, step, rid):
    """供各脚本调用：成功返回 obj（并打印 WARN）；失败打印 STDIN_JSON_INVALID / STDIN_GIVE_UP 并返回 None 与次数。"""
    obj, warn, err = load(raw, VALIDATORS[step])
    if obj is not None:
        clear(rid, step)
        if warn:
            print("WARN STDIN_REPAIRED %s。只动了括号，所有 value/text 原样接收，本次继续执行，不要重跑" % warn)
        return obj, 0
    n = bump(rid, step)
    if n >= GIVE_UP_AFTER and step != "summary":
        print("STDIN_GIVE_UP %s 的 stdin 已连续 %d 次不是合法 JSON：%s。本次未写入。停止重试，"
              "按主提示词“stdin 语法错误的有限恢复”提交审核未完成，不调用规则引擎。" % (step, n, err))
    else:
        print("STDIN_JSON_INVALID %s 的 stdin 不是合法 JSON（连续第 %d 次）：%s。本次未写入。只改结构符号，不要改动 value/text 的原文%s。" %
              (step, n, err, "；下一次" + NEXT_TRY[step] if n >= 2 or step == "fill" and len(raw) > 6000 else ""))
    return None, n
