"""stdin JSON 解析：稳定错误码 + 唯一一种结构修复 + 同一步骤连续失败计数。
detail.py（init/fill/recheck/verify）与 combine.py（build/summary）共用。

背景：job 216 的 fill 在 notes 前少了一个关闭 rows 的 ]，模型连续 29 次改写说明文字，括号始终没补上。
build/summary 的解析失败原来只有一句「stdin 不是合法 JSON」，没有错误码、没有次数，模型同样会无限重试。

约定（主提示词「stdin 语法错误的有限恢复」）：
  - 合法 JSON 原样接收；同一层出现重名键视为损坏（不让后一个静默覆盖前一个）。
  - 只修一种情况：fill 的 rows 数组在下一个顶层键（notes/materials）前少一个 ]。补上后必须全文可解析、
    无重名键、顶层只有契约键、rows 每行都是 [字符串ID, 值|null, 字符串说明]，否则不修。打印 WARN STDIN_ROWS_CLOSED。
  - 结尾多出的 } / ]（v33 起兼容）照旧忽略。
  - 其他任何损坏都拒绝，打印 STDIN_JSON_INVALID（报错位置仅供定位）；不猜、不改任何 value/text。
  - 同一 requestId、同一步骤连续第二次解析失败：同时打印 STDIN_GIVE_UP，模型停止重试、按主提示词收尾。
    计数落盘在 work/<rid>/.stdin-failures.json，该步骤解析成功即清零。
"""
import json
import os
import sys

GIVE_UP_AFTER = 2
FAIL_FILE = ".stdin-failures.json"

# 各步骤 stdin 的顶层契约键（None = 不检查顶层键）
TOP_KEYS = {
    "fill": {"materials", "rows", "notes", "recheck"},
    "recheck": {"rows"},
    "verify": {"rows"},
    "build": {"map", "skip", "set", "fixedUnmapped", "toolIssues", "rules"},
    "summary": {"basis", "next", "notice", "analysis"},
    "init": None,
}

NEXT_TRY = {
    "fill": "按材料拆成小批（每批不超过 20 行）重交，已写入的行不重发",
    "recheck": "每次只交一行复核",
    "verify": "每次只交少量几行",
    "build": "只交这次要改的键（之前的 map/skip/set/rules 已落盘，不用重交）",
    "summary": "只改被点名处的括号或引号",
    "init": "按 init 的 stdin 格式重组请求",
}


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


def _is_triple(r):
    return (isinstance(r, list) and len(r) == 3 and isinstance(r[0], str)
            and (r[1] is None or isinstance(r[1], (str, int, float)) and not isinstance(r[1], bool))
            and isinstance(r[2], str))


def _fill_contract(o):
    if not isinstance(o, dict) or "rows" not in o or not set(o) <= TOP_KEYS["fill"]:
        return False
    if not (isinstance(o["rows"], list) and all(_is_triple(r) for r in o["rows"])):
        return False
    if "notes" in o and not isinstance(o["notes"], dict):
        return False
    if "materials" in o and not isinstance(o["materials"], dict):
        return False
    return True


def _skip_ws_back(raw, i):
    while i >= 0 and raw[i].isspace():
        i -= 1
    return i


def _close_rows(raw, err):
    """job 216：rows 的最后一行 ] 之后直接跟了 ,"notes": / ,"materials":。只在解析器报错正好落在那个冒号上时补一个 ]。"""
    pos = getattr(err, "pos", None)
    if not isinstance(pos, int) or pos >= len(raw) or raw[pos] != ":":
        return None
    j = _skip_ws_back(raw, pos - 1)
    for key in ('"notes"', '"materials"'):
        if raw[max(0, j - len(key) + 1):j + 1] == key:
            k = _skip_ws_back(raw, j - len(key))
            if k < 0 or raw[k] != ",":
                return None
            b = _skip_ws_back(raw, k - 1)
            if b < 0 or raw[b] != "]":
                return None
            fixed = raw[:b + 1] + "]" + raw[b + 1:]
            try:
                obj = strict_loads(fixed)
            except ValueError:
                return None
            return obj if _fill_contract(obj) else None
    return None


def _near(raw, pos):
    if not isinstance(pos, int):
        return ""
    return "；出错位置附近：…%s⟨这里⟩%s…" % (raw[max(0, pos - 30):pos].replace("\n", " "), raw[pos:pos + 10].replace("\n", " "))


def parse(raw, step):
    """返回 (obj, warn, err)。obj 为 None 时 err 是给模型看的具体原因。"""
    try:
        obj = strict_loads(raw)
        return obj, None, None
    except DuplicateKey as exc:
        return None, None, "同一层里键「%s」出现了两次，合并成一个后重交" % exc
    except ValueError as exc:
        err = exc
    try:                                 # v33：结尾多了 } 或 ]，其余内容完整
        obj, end = json.JSONDecoder(object_pairs_hook=_pairs).raw_decode(raw.lstrip())
        rest = raw.lstrip()[end:].strip()
        if isinstance(obj, dict) and rest and set(rest) <= set("}]"):
            return obj, "stdin 结尾多了「%s」，已忽略；内容按原样接收，不要因此改动 value/text" % rest, None
    except ValueError:
        pass
    if step == "fill":
        obj = _close_rows(raw, err)
        if obj is not None:
            return obj, "STDIN_ROWS_CLOSED rows 数组在下一个键前少了一个「]」，已补上；所有 value/text 原样接收，本次继续执行，不要重交", None
    return None, None, "%s%s" % (err, _near(raw, getattr(err, "pos", None)))


def check_top(obj, step):
    """顶层不是对象 → 返回原因（按语法失败计）；契约外的键只提醒、照旧忽略（兼容旧提交）。"""
    if not isinstance(obj, dict):
        return "stdin 顶层应为 JSON 对象 {…}", None
    keys = TOP_KEYS.get(step)
    extra = sorted(set(obj) - keys) if keys else []
    if extra:
        return None, "STDIN_UNKNOWN_KEY 顶层键 %s 不在 %s 的格式里，已忽略（允许：%s）；拼错了就改正后重交" % (
            "、".join(extra), step, "、".join(sorted(keys)))
    return None, None


# ---------- 连续失败计数 ----------

def _fail_path(rid):
    return os.path.join("work", rid, FAIL_FILE)


def _load_counts(rid):
    try:
        with open(_fail_path(rid), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def bump(rid, step):
    if not rid or not os.path.isdir(os.path.join("work", rid)):
        return 1
    d = _load_counts(rid)
    d[step] = int(d.get(step, 0)) + 1
    with open(_fail_path(rid), "w", encoding="utf-8") as f:
        json.dump(d, f)
    return d[step]


def clear(rid, step):
    if not rid or not os.path.isdir(os.path.join("work", rid)):
        return
    d = _load_counts(rid)
    if d.pop(step, None) is not None:
        with open(_fail_path(rid), "w", encoding="utf-8") as f:
            json.dump(d, f)


def fail(step, rid, reason, raw=""):
    """打印 STDIN_JSON_INVALID（连续第二次再加 STDIN_GIVE_UP），返回连续失败次数。调用方负责退出。"""
    n = bump(rid, step)
    stop = ("连续第二次语法失败时脚本不再退回，依据/下一步按规则说明自动生成" if step == "summary"
            else "同一步骤连续第二次语法失败即停止重试")
    print("STDIN_JSON_INVALID %s 的 stdin 不是合法 JSON（同一步骤连续第 %d 次）：%s。本次未写入任何内容。"
          "只改出错的结构符号（[ ] { } , 或字符串里的 ASCII 双引号改「」），不要改动 value/text 的原文；"
          "下一次%s。%s。" % (step, n, reason, NEXT_TRY.get(step, "只改出错处"), stop))
    if n >= GIVE_UP_AFTER and step != "summary":
        print("STDIN_GIVE_UP %s 的 stdin 已连续 %d 次不是合法 JSON：停止重试，不再改写重交；"
              "按主提示词「stdin 语法错误的有限恢复」提交审核未完成（引用上面 STDIN_JSON_INVALID 原话），不调用 mcp_run_process。" % (step, n))
    return n


def read(raw, step, rid=None):
    """成功：打印 WARN 并返回 (obj, 0)。失败：打印错误码，返回 (None, 连续次数)。"""
    obj, warn, err = parse(raw, step)
    extra = None
    if obj is not None:
        err, extra = check_top(obj, step)
        if err:
            obj = None
    if obj is None:
        return None, fail(step, rid, err, raw)
    clear(rid, step)
    for w in (warn, extra):
        if w:
            print("WARN " + w)
    return obj, 0


def read_or_exit(raw, step, rid=None, code=1):
    obj, _ = read(raw, step, rid)
    if obj is None:
        sys.exit(code)
    return obj
