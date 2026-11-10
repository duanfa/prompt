#!/usr/bin/env python3
"""提取明细脚本：由 RunSkillScript 运行（python3 -I，只用标准库，工作目录 = 工作区，参数只能是工作区内相对路径）。

模型不再手写全部明细行（清单条数以 extract-items-checked.json 为准）。脚本做三件事：
  init    读请求（stdin）、工商三接口返回文件、规则文件，预填「请求参数 / 工商 / 请求里根本没有的材料」这些
          不需要看图的行，并打印还要模型读材料后填写的行（id|name|desc）
  fill    合并模型读材料得到的行、材料状态和 notes（stdin JSON）
  finish  算派生行（成立月数、名称比较、有效期、快到期……）、生成 notes、检查还有没有待填行

文件 work/<requestId>/input-extract-detail.json 的格式与 v26 完全一致（id/name/desc/value/source 五字段），
由脚本用 json 序列化，所以不会再出现“未转义双引号导致非法 JSON”。

用法（args 一词一项）:
  init   --biz <工商返回文件>... [--rules <规则返回文件>]      stdin: {"ctx":{requestId,domain,scene},"request":{…},"warnings":[…],"taskSubmittedDate":"yyyy-mm-dd"}
  fill   --rid <requestId>                                      stdin: {"materials":{字段:[状态,依据]},"rows":[[id,value|null,text]],"notes":{"conflicts":[],"toolIssues":[]}}
  finish --rid <requestId>
  show   --rid <requestId> [--pending]
  compare --rid <requestId>                                     工商与原件识别（执照/身份证/开户凭证/租赁合同）逐项比对，列出待复核项
  recheck --rid <requestId>                                     stdin: {"rows":[[原件条目ID,二次识别值|null,text]]}  回看原件二次识别后提交，每项只能复核一次
rows 里 value 有值时 text 写「来源｜证据」，value 为 null 时 text 写「Rxx｜具体原因」。
"""
import argparse
import json
import unicodedata
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import stdin_json as sj  # noqa: E402
CAT = os.path.realpath(os.path.join(HERE, ".."))
CONTRACT = "admission-noshell-v0-2"
RELEASE_MARKER = "RELEASE_ATTACHMENTS"
RID_OK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
N_RE = re.compile(r"R(0[1-9]|1[0-5])｜.{4,}", re.S)
PREFIX_RE = re.compile(r"^[YN]\s*[｜|]\s*")
# v33：有值行漏写「｜」时，若开头是「材料名 xxxUrl [pN]」这种来源，自动在来源后补「｜」（am1/am2 首次 fill 各被拒 18–19 行）
SRC_FIX_RE = re.compile(r"^(?P<src>(?:[\u4e00-\u9fa5（）()/]{2,12}\s*)?[A-Za-z]+Url(?:\[\d+\])?"
                        r"(?:\s*(?:、|和|与|,|，)\s*[A-Za-z]+Url(?:\[\d+\])?)*(?:\s*p\d+(?:[-–]\d+)?)?)(?:\s+|[，,：:])(?P<ev>\S.*)$", re.S)
ID18_RE = re.compile(r"(?<![0-9A-Za-z])(\d{17}[\dXx])(?![0-9A-Za-z])")

# 请求里已知的附件字段 → 清单分组。组里所有字段都没有（且请求里没有未知附件字段）才由脚本写 N R01。
GROUPS = {
    "营业执照": ["bizlicUrl"],
    "法人身份证": ["legalIdCardFrontUrl", "legalIdCardBackUrl"],     # v33：原为 []，身份证 URL 被当成“未知附件”，所有整组判定都失效
    "开户凭证": ["bankPermitUrl"],
    "办公场所视频": ["officeVideoUrl"],
    "业务场景照片": ["bizScenePhotoUrls"],
    "租赁合同": ["leaseAgreementUrl"],
}
# 补充材料里能按请求字段整段判定“没提供”的子组。v35：不再写死 H 编号，按清单里条目名称的开头归组
# （清单在补充材料里插入/调整条目、整体后移编号都不影响）；(名称开头, 请求附件字段, 说明)
SUPPLEMENT_PREFIX = [(("增值税专用发票",), ["vatTaxCertUrl"], "增值税专用发票"),
                     (("上下游合同",), ["upstreamDnstreamAgmtUrl"], "上下游合同"),
                     (("社保证明", "完税证明", "无欠税证明"), ["noTaxCertSbUrl"], "社保/完税/无欠税证明")]   # 三类证明是同一个请求参数
ONLINE_PREFIX = "官网/公众号"                                  # 官网类条目：名称含「可打开」「关联」各一条
# v42：名称比较、是否在期间内、距到期天数、同栏原样带出 不再按编号写死，改由清单条目的 derive 字段声明（见 DERIVE_OPS）
# v35：脚本里仍按编号引用的条目（A–G、J 组），用名称关键词核对；清单改了编号/名称导致对不上时 init 打印 WARN，而不是悄悄写错行
ANCHORS = {
    "A01": "entpId", "A02": "entpName", "A03": "rqId", "A04": "hrInstId", "A05": "requestId", "A06": "基准日",
    "A07": "交付要求", "A08": "项目内容", "A09": "项目简介", "A10": "开票类目", "A11": "官网", "A12": "附件盘点", "A13": "岗位名称",
    "B01": "名称", "B02": "类型", "B03": "信用代码", "B04": "成立日期", "B05": "营业期限", "B06": "法定代表人", "B07": "地址",
    "B08": "经营范围", "B10": "注册资本", "B11": "有效期", "B16": "成立月数", "B17": "主体类型", "B18": "分公司",
    "B19": "合伙", "B26": "灵工平台",
    "C02": "姓名", "D01": "户名", "D02": "账户性质", "D08": "法定代表人",
    "F01": "张数", "G02": "承租方",
    "J01": "企业名称", "J02": "信用代码", "J03": "组织机构代码", "J04": "注册号", "J05": "登记状态", "J06": "企业类型",
    "J07": "法定代表人", "J08": "注册资本", "J09": "成立日期", "J10": "经营期限", "J11": "核准日期", "J12": "登记机关",
    "J13": "注册地址", "J14": "经营地址", "J15": "区域", "J16": "经营范围", "J17": "行业", "J18": "曾用名", "J19": "吊销",
    "J20": "注销", "J21": "从业人数", "J22": "简称", "J23": "上市", "J24": "高新", "J25": "高管人员", "J26": "科技企业",
    "J27": "更新时间", "J28": "接口调用状态", "J30": "主营业务", "J31": "人力资源", "J32": "境外", "J33": "关键词",
    "J34": "不一致", "J35": "期限", "J36": "吊销", "J37": "高管命中",
}


def check_anchors(items):
    """脚本按编号引用的条目，名称里必须含对应关键词；返回对不上的说明列表（空 = 正常）。"""
    byid = {i["id"]: i for i in items}
    bad = []
    for k, kw in ANCHORS.items():
        if k not in byid:
            bad.append("%s 在清单里不存在" % k)
        elif kw.lower() not in byid[k]["name"].lower():
            bad.append("%s 现名「%s」不含「%s」" % (k, byid[k]["name"], kw))
    return bad


# ───────────────────────── 清单声明的派生（v42） ─────────────────────────
# 清单条目可带 "derive": {"op": <工具名>, "from": [依据条目ID, ...], 其它参数}；
# 脚本只按声明执行通用计算，比什么、阈值多少都写在清单里，新增同类条目不用改脚本。
#   same_name       from=[A, B]          A、B 两个名称逐字比较（忽略空白、括号全半角）；可选 ignoreSuffix=[...] 先去掉 A 末尾的这些字样
#   in_period       from=[开始, 结束]     基准日是否落在 [开始, 结束]；可选 label（写进依据，如「租期」）
#   days_to_expiry  from=[截止]           截止日距基准日的天数是否 ≤ withinDays（必填）；“长期/永久”→ false；已过期不派生，留给模型
#   copy            from=[源]             与源条目同一栏位，原样带出
DERIVE_OPS = {"same_name": 2, "in_period": 2, "days_to_expiry": 1, "copy": 1}
DERIVE_ID_RE = r"[A-Z][A-Z0-9-]*"


def check_derive_specs(items):
    """清单里 derive 声明的问题列表（空 = 正常）。声明写错时 init 直接失败，不悄悄跳过。"""
    ids = {i["id"] for i in items}
    bad = []
    for it in items:
        d = it.get("derive")
        if d is None:
            continue
        i = it["id"]
        if not isinstance(d, dict) or d.get("op") not in DERIVE_OPS:
            bad.append("%s 的 derive.op 须为 %s 之一" % (i, "/".join(DERIVE_OPS)))
            continue
        src = d.get("from")
        if not (isinstance(src, list) and len(src) == DERIVE_OPS[d["op"]] and all(isinstance(x, str) for x in src)):
            bad.append("%s 的 derive.from 须为 %d 个条目 ID" % (i, DERIVE_OPS[d["op"]]))
            continue
        for x in src:
            if x not in ids:
                bad.append("%s 的 derive.from 引用了不存在的条目 %s" % (i, x))
            elif x == i:
                bad.append("%s 的 derive.from 不能引用自己" % i)
            elif not re.fullmatch(DERIVE_ID_RE, x):
                bad.append("%s 的 derive.from 条目 ID「%s」格式不支持" % (i, x))
        if d["op"] == "days_to_expiry" and not (isinstance(d.get("withinDays"), int) and d["withinDays"] > 0):
            bad.append("%s 的 days_to_expiry 须给正整数 withinDays（阈值天数）" % i)
        if "ignoreSuffix" in d and not (isinstance(d["ignoreSuffix"], list) and all(isinstance(x, str) and x for x in d["ignoreSuffix"])):
            bad.append("%s 的 derive.ignoreSuffix 须为非空字符串列表" % i)
    return bad


def check_notice_specs(items):
    """v42：清单条目可带 "notice": [{"condition": "命中条件（值或文字描述）", "desc": "告知用户的话"}]。
    哪条 condition 命中由模型在 summary 草稿里按语义判断，desc 原样进 summary 的“注意”（依据/下一步已写过的不重复）。"""
    bad = []
    for it in items:
        ns = it.get("notice")
        if ns is None:
            continue
        if not (isinstance(ns, list) and ns):
            bad.append("%s 的 notice 须为非空数组" % it["id"])
            continue
        conds = []
        for k, n in enumerate(ns, 1):
            if not (isinstance(n, dict) and isinstance(n.get("condition"), str) and n["condition"].strip()
                    and isinstance(n.get("desc"), str) and n["desc"].strip()):
                bad.append("%s 的 notice[%d] 须为 {\"condition\":非空字符串,\"desc\":非空字符串}" % (it["id"], k))
            else:
                conds.append(n["condition"].strip())
        if len(conds) != len(set(conds)):
            bad.append("%s 的 notice 里 condition 有重复" % it["id"])
    return bad


def short_name(item):
    return item["name"].rsplit(".", 1)[-1]


def run_derive_spec(i, d, need, Y, base, by):
    """执行一条清单声明的派生。依据未就绪时不动；依据为 N 时 need() 已写 N R12。"""
    op, src = d["op"], d["from"]
    if op in ("in_period", "days_to_expiry") and not base:
        return
    t = need(i, *src)
    if not t:
        return
    if op == "same_name":
        a, b = s(t[0]), s(t[1])
        cut = next((x for x in sorted(d.get("ignoreSuffix") or [], key=len, reverse=True) if nfkc_name(a).endswith(nfkc_name(x))), None)
        left = nfkc_name(a)[:-len(nfkc_name(cut))] if cut else nfkc_name(a)
        same = left == nfkc_name(b)
        Y(i, "true" if same else "false", "派生:%s,%s｜%s=%s；%s=%s；%s%s" % (
            src[0], src[1], src[0], a, src[1], b, ("去掉末尾「%s」后" % cut) if cut else "",
            "逐字一致（仅忽略空白和括号全半角）" if same else "不一致"))
    elif op == "in_period":
        s0, e0 = parse_date(t[0]), parse_date(t[1])
        if s0 and e0:
            label = d.get("label") or "期间"
            inside = s0 <= base <= e0
            Y(i, "true" if inside else "false", "派生:%s,%s,A06｜%s %s 至 %s；基准日 %s%s%s内" % (
                src[0], src[1], label, s0.isoformat(), e0.isoformat(), base.isoformat(), "在" if inside else "不在", label))
    elif op == "days_to_expiry":
        n, label = d["withinDays"], d.get("label") or "截止"
        if any(w in s(t[0]) for w in ("长期", "永久")):
            Y(i, "false", "派生:%s,A06｜%s为「%s」，无截止日，不存在 %d 天内到期情形" % (src[0], short_name(by[src[0]]), t[0], n))
            return
        ds = dates_in(s(t[0]))
        if ds and ds[-1] >= base:
            days = (ds[-1] - base).days
            Y(i, "true" if days <= n else "false", "派生:%s,A06｜%s %s；基准日 %s；距到期 %d 天；阈值 %d 天" % (
                src[0], label, ds[-1].isoformat(), base.isoformat(), days, n))
    elif op == "copy":
        Y(i, t[0], "派生:%s｜与 %s 同一栏位，原样带出：%s" % (src[0], src[0], t[0]))


def derive_specs(items):
    return {it["id"]: it["derive"] for it in items if it.get("derive")}


def supplement_ids(items, prefixes):
    return [i["id"] for i in items if i["group"] == "补充材料" and i["name"].startswith(prefixes)]


def online_ids(items):
    """官网/公众号两条：(是否可打开, 是否与公司有关联)；找不到的为 None。"""
    c = [i for i in items if i["group"] == "补充材料" and i["name"].startswith(ONLINE_PREFIX)]
    opn = next((i["id"] for i in c if "可打开" in i["name"]), None)
    rel = next((i["id"] for i in c if "关联" in i["name"]), None)
    return opn, rel


KNOWN_ATTACH = {"bizlicUrl", "bankPermitUrl", "officeVideoUrl", "bizScenePhotoUrls", "leaseAgreementUrl",
                "vatTaxCertUrl", "noTaxCertSbUrl", "upstreamDnstreamAgmtUrl", "legalIdCardFrontUrl", "legalIdCardBackUrl"}
MATERIAL_ORDER = ["leaseAgreementUrl", "bankPermitUrl", "vatTaxCertUrl", "noTaxCertSbUrl", "upstreamDnstreamAgmtUrl",
                  "bizScenePhotoUrls", "bizlicUrl", "legalIdCardFrontUrl", "legalIdCardBackUrl", "officeVideoUrl", "onlinePresenceUrl"]
FILE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".bmp")
PROVINCES = ("北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建", "江西",
             "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "内蒙古", "广西",
             "西藏", "宁夏", "新疆")
REQ_POSITION_KEYS = ("positionName", "jobName", "posName", "postName", "position")
# v39：营业执照经营范围里出现这些字样 → B26「是否灵工平台企业」为 true（口径取自清单 B26 的 desc）
FLEX_PLATFORM_WORDS = ("人力外包", "灵活用工", "劳务派遣", "劳务外包", "劳务服务", "劳务中介", "劳务输出")


def die(msg, code=1):
    print("ERROR " + msg)
    sys.exit(code)


def load_json_file(path):
    with open(path, encoding="utf-8") as f:
        return json.JSONDecoder().raw_decode(f.read().lstrip())[0]


def read_stdin(step=None, rid=None):
    """step=fill/recheck 时走 stdin_json：只改括号的结构修复 + 连续失败计数（job 216 少一个 ] 重提 29 次）。"""
    raw = sys.stdin.read()
    if not raw.strip():
        die("stdin 为空")
    if step:
        obj, _ = sj.read(raw, step, rid)
        if obj is None:
            sys.exit(1)
        return obj
    try:
        return json.loads(raw)
    except ValueError as exc:
        err = exc
    try:                                # v33：am2 在结尾多写了一个 }，报错却只提双引号，模型删了原文里的括号重提，导致复核误判
        obj, end = json.JSONDecoder().raw_decode(raw.lstrip())
        rest = raw.lstrip()[end:].strip()
        if isinstance(obj, dict) and rest and set(rest) <= set("}]"):
            print("WARN stdin 结尾多了「%s」，已忽略；内容按原样接收，不要因此改动 value/text" % rest)
            return obj
    except ValueError:
        pass
    die("STDIN_JSON_INVALID stdin 不是合法 JSON：%s。本次未写入。只改结构符号，不要改动 value/text 的原文。" % sj.diagnose(raw, err))


def id_numbers(text):
    """文本里像居民身份证号的 18 位串（校验位正确、出生日期合法）。银行账号等长度不同或校验不过，不会误判。"""
    out = []
    for m in ID18_RE.finditer(text or ""):
        n = m.group(1).upper()
        w = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
        if "10X98765432"[sum(int(c) * k for c, k in zip(n[:17], w)) % 11] != n[17]:
            continue
        try:
            date(int(n[6:10]), int(n[10:12]), int(n[12:14]))
        except ValueError:
            continue
        out.append(n)
    return out


def default_source(item):
    """v37：有值行漏了「｜」、开头又认不出来源时，用这一条所属的材料作来源（v35 五次 fill 共被拒约 20 行，都是判断类短句）。"""
    g, name = item.get("group"), item.get("name") or ""
    if g == "请求参数":
        return "请求"
    if g == "工商":
        return "工商接口"
    if g in GROUPS:
        return "%s %s" % (g, "/".join(GROUPS[g]))
    if name.startswith(ONLINE_PREFIX):
        return "官网/公众号 onlinePresenceUrl"
    for prefixes, fields, label in SUPPLEMENT_PREFIX:
        if name.startswith(prefixes):
            return "%s %s" % (label, "/".join(fields))
    return None


ASSERT_WORDS = ("真实", "合规", "正常", "可信", "无异常", "没有异常")


def strip_assertions(text):
    """v37：“是否有伪造嫌疑”类条目只写逐项看了什么，不下真实/合规/正常/可信/无异常这类断言。
    原来靠自审 A 发现后再 fill --force 改写（多一轮）；现在写入时去掉含断言的分句，其余照留。
    v0.2：「、」也算分句（71 号“证号格式合规、国内真实地址、无卡通头像”整段一句）；去掉后没有内容就原样返回，由 fill 退回。"""
    head, sep, ev = text.partition("｜")
    if not sep:
        return text, False
    parts = [x for x in re.split(r"(?<=[，,；;。、])", ev) if x.strip()]
    keep = [x for x in parts if not any(w in x for w in ASSERT_WORDS)]
    if len(keep) == len(parts) or not "".join(keep).strip("，,；;。 "):
        return text, False
    return "%s｜%s" % (head, "".join(keep).rstrip("，,；;、 ")), True


ASSERT_MAX_REJECT = 2


def assertion_words(text):
    ev = text.partition("｜")[2] or text
    return [w for w in ASSERT_WORDS if w in ev]


def fix_source(text):
    """有值行的 text 没有「｜」：开头是可识别的来源（材料名 + xxxUrl + 页码）就补上「｜」，否则返回 None。"""
    m = SRC_FIX_RE.match(text)
    return "%s｜%s" % (m.group("src").strip(), m.group("ev").strip()) if m else None


def empty(v):
    return v is None or v == "" or v == [] or v == {}


def s(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def nfkc_name(x):
    return re.sub(r"\s+", "", (x or "")).replace("（", "(").replace("）", ")")


def parse_date(text):
    m = re.search(r"(\d{4})\D{0,2}(\d{1,2})\D{0,2}(\d{1,2})", text or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def dates_in(text):
    return [d for d in (date(int(a), int(b), int(c)) for a, b, c in re.findall(r"(\d{4})\D{0,2}(\d{1,2})\D{0,2}(\d{1,2})", text or "")
                        if 1 <= int(b) <= 12 and 1 <= int(c) <= 31)]


def months_between(founded, base):
    n = (base.year - founded.year) * 12 + (base.month - founded.month)
    return n - 1 if base.day < founded.day else n


# ───────────────────────── 状态文件 ─────────────────────────

def paths(rid):
    if not RID_OK.fullmatch(rid or ""):
        die("requestId 含非法字符: %r" % rid)
    d = os.path.join("work", rid)
    return d, os.path.join(d, "input-extract-detail.json"), os.path.join(d, ".detail-state.json")


def load_items():
    return json.load(open(os.path.join(CAT, "extract-items-checked.json"), encoding="utf-8"))


def write_detail(rid, doc):
    d, fp, _ = paths(rid)
    os.makedirs(d, exist_ok=True)
    head = '{\n"contract":%s,\n"schema":"input-extract-detail/3",\n"routing":%s,\n"materials":%s,\n"items":[\n' % (
        json.dumps(doc["contract"]), json.dumps(doc["routing"], ensure_ascii=False, separators=(",", ":")),
        json.dumps(doc["materials"], ensure_ascii=False, separators=(",", ":")))
    rows = ",\n".join(json.dumps({k: it[k] for k in ("id", "name", "desc", "value", "source")}, ensure_ascii=False, separators=(",", ":"))
                      for it in doc["items"])
    tail = '\n],\n"notes":%s\n}\n' % json.dumps(doc["notes"], ensure_ascii=False, separators=(",", ":"))
    with open(fp, "w", encoding="utf-8") as f:
        f.write(head + rows + tail)


def load_detail(rid):
    _, fp, sp = paths(rid)
    if not os.path.isfile(fp) or not os.path.isfile(sp):
        die("work/%s 下没有明细文件，先运行 init" % rid)
    st = load_json_file(sp)
    for k, d in (("derived", []), ("autoConflicts", []), ("rechecked", {}), ("stale", [])):
        st.setdefault(k, d)
    return load_json_file(fp), st


def save_state(rid, st):
    _, _, sp = paths(rid)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)


# ───────────────────────── 工商三接口 ─────────────────────────

def detect_iface(doc):
    rec = (doc.get("model") or [{}])
    rec = rec[0] if isinstance(rec, list) and rec and isinstance(rec[0], dict) else {}
    if "basic" in rec or "person" in rec:
        return "T"
    if "entityName" in rec or "registerCode" in rec:
        return "B"
    if "companyName" in rec or "creditNo" in rec:
        return "D"
    return None


def load_biz(files, uscc):
    """→ {iface: {"ok":bool,"rec":dict,"status":str}}"""
    out = {}
    for fp in files:
        try:
            doc = load_json_file(fp)
        except (OSError, ValueError) as exc:
            print("WARN 工商文件读不了 %s: %s" % (fp, exc))
            continue
        if not isinstance(doc, dict):
            continue
        iface = detect_iface(doc)
        recs = doc.get("model") if isinstance(doc.get("model"), list) else []
        rec = None
        for r in recs:
            if isinstance(r, dict) and uscc and uscc in json.dumps(r, ensure_ascii=False):
                rec = r
                break
        if rec is None and recs and isinstance(recs[0], dict):
            rec = recs[0]
        status = "succeed=%s errMsg=%s" % (str(doc.get("succeed")).lower(), doc.get("errMsg") or doc.get("message") or "")
        if iface is None:
            if isinstance(doc.get("data"), list):
                die("--biz 传入的 %s 是规则/属性文件，不是工商返回。--biz 只放三个工商工具的落盘文件（enterprise-get-company-detail、databao-company-basic-info-check-v2、databao-company-details-check-v2）" % fp)
            print("WARN %s 不是工商三接口的返回格式，已忽略" % fp)
            continue
        out[iface] = {"ok": bool(rec) and doc.get("succeed") is not False, "rec": rec or {}, "status": status.strip(), "doc": doc}
    return out


def getp(rec, path):
    cur = rec
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


class Biz:
    def __init__(self, biz):
        self.biz = biz

    def get(self, key):
        iface, path = key.split(".", 1)
        b = self.biz.get(iface)
        if not b or not b["ok"]:
            return None
        v = getp(b["rec"], path)
        return None if empty(v) else v

    def evidence(self, keys, label):
        parts, miss = [], []
        for k in keys:
            v = self.get(k)
            if v is None:
                miss.append(k)
            else:
                sv = s(v)
                if len(sv) > 100:
                    sv = sv[:100] + "…（共%d字）" % len(sv)
                parts.append("%s=%s" % (k, sv))
        return parts, miss

    def failed(self):
        return [("%s 接口无有效返回（%s）" % (i, b["status"])) for i, b in self.biz.items() if not b["ok"]] + \
               [("%s 接口未返回" % i) for i in "DBT" if i not in self.biz]


def first(bz, *keys):
    for k in keys:
        v = bz.get(k)
        if v is not None:
            return s(v)
    return None


def capital_conflict(bz):
    """D.capital（带单位文字）与 B.registerCapital（接口定义单位：万）折成元后相差 1 元以上，返回冲突说明；否则 None。
    T.basic.regcap 单位未明示，只列出、不参与判定。"""
    d, b = bz.get("D.capital"), bz.get("B.registerCapital")
    if d is None or b is None:
        return None
    dv = money_yuan(s(d))
    try:
        bv = float(re.sub(r"[^\d.]", "", s(b)) or "nan") * 10 ** 4 if re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", s(b)) else money_yuan(s(b))
    except ValueError:
        bv = None
    if dv is None or bv is None or bv != bv or abs(dv - bv) < 1:
        return None
    t = bz.get("T.basic.regcap")
    return "三接口注册资本不一致，不裁决：D.capital=%s；B.registerCapital=%s（单位万）%s" % (s(d), s(b), ("；T.basic.regcap=%s（单位未明示）" % s(t)) if t is not None else "")


def d10(v):
    return None if v is None else v[:10]


def j_specs():
    def join(bz, pairs, sep="；"):
        out = []
        for label, keys in pairs:
            v = first(bz, *keys)
            if v is not None:
                out.append("%s%s" % (label, v) if label else v)
        return sep.join(out) or None

    def ipo(bz):
        v = bz.get("B.isIPO")
        return None if v is None else {"1": "是", "2": "否"}.get(str(v), str(v))

    def hitech(bz):
        v = bz.get("B.isHitech")
        return None if v is None else {"1": "是", "0": "否"}.get(str(v), str(v))

    def person(bz):
        ps = bz.get("T.person")
        if not isinstance(ps, list):
            return None
        seen, out = set(), []
        for p in ps:
            if not isinstance(p, dict):
                continue
            key = (p.get("pername"), p.get("position"))
            if key in seen:
                continue
            seen.add(key)
            out.append("%s(%s)" % (p.get("pername") or "", p.get("position") or ""))
        return "；".join(out) or None

    def industry(bz):
        n, c = first(bz, "B.industryName", "D.industry"), bz.get("B.industryCode")
        return None if n is None and c is None else "%s(%s)" % (n or "", c or "")

    def period(bz):
        a = d10(first(bz, "D.operationStartdate", "B.businessStartTime", "T.basic.opfrom"))
        b = d10(first(bz, "D.operationEnddate", "B.businessEndTime", "T.basic.opto"))
        if a is None and b is None:
            return None
        return "%s 起，%s" % (a or "起始未返回", ("截止 " + b) if b else "截止日未返回")

    def region(bz):
        p, c, d = first(bz, "D.province", "B.province"), first(bz, "D.city", "B.city"), first(bz, "D.district")
        v = "/".join(x for x in (p, c, d) if x)
        return v or first(bz, "B.districtCode")

    return [
        ("J01", ["D.companyName", "B.entityName", "T.basic.entname"], lambda bz: first(bz, "D.companyName", "B.entityName", "T.basic.entname")),
        ("J02", ["D.creditNo", "B.creditCode", "T.basic.creditcode"], lambda bz: first(bz, "D.creditNo", "B.creditCode", "T.basic.creditcode")),
        ("J03", ["D.orgCode", "B.organizationCode", "T.basic.orgcodes"], lambda bz: first(bz, "D.orgCode", "B.organizationCode", "T.basic.orgcodes")),
        ("J04", ["D.companyCode", "B.registerCode", "T.basic.regno"], lambda bz: first(bz, "D.companyCode", "B.registerCode", "T.basic.regno")),
        ("J05", ["D.companyStatus", "B.entityStatus", "T.basic.entstatus"], lambda bz: first(bz, "D.companyStatus", "T.basic.entstatus", "B.entityStatus")),
        ("J06", ["D.companyType", "B.entityType", "B.entType", "B.tagName", "T.basic.enttype", "T.basic.entitytype"],
         lambda bz: first(bz, "D.companyType", "B.entityType", "T.basic.enttype")),
        ("J07", ["D.legalPerson", "D.legalPersonType", "B.legalPerson", "B.legalPersonType", "T.basic.frname"],
         lambda bz: first(bz, "D.legalPerson", "B.legalPerson", "T.basic.frname")),
        ("J08", ["D.capital", "D.realCapital", "B.registerCapital", "B.actualCapital", "B.currency", "T.basic.regcap", "T.basic.regcapcur"],
         lambda bz: join(bz, [("注册资本", ["D.capital", "B.registerCapital", "T.basic.regcap"]), ("实收资本", ["D.realCapital", "B.actualCapital"]),
                              ("币种", ["B.currency", "T.basic.regcapcur"])])),
        ("J09", ["D.establishDate", "B.registerDate", "T.basic.esdate"], lambda bz: d10(first(bz, "D.establishDate", "B.registerDate", "T.basic.esdate"))),
        ("J10", ["D.operationStartdate", "D.operationEnddate", "B.businessStartTime", "B.businessEndTime", "T.basic.opfrom", "T.basic.opto"], period),
        ("J11", ["B.checkDate", "T.basic.apprdate", "T.basic.ancheyear"], lambda bz: first(bz, "B.checkDate", "T.basic.apprdate", "T.basic.ancheyear")),
        ("J12", ["D.authority", "B.registerDepartment", "T.basic.regorg", "T.basic.regorgprovince", "T.basic.regorgcity", "T.basic.regorgdistrict"],
         lambda bz: first(bz, "D.authority", "B.registerDepartment", "T.basic.regorg")),
        ("J13", ["D.companyAddress", "B.address", "T.basic.dom", "T.basic.postalcode"], lambda bz: first(bz, "D.companyAddress", "B.address", "T.basic.dom")),
        ("J14", ["B.businessAddress"], lambda bz: first(bz, "B.businessAddress")),
        ("J15", ["D.province", "D.city", "D.district", "D.provinceCode", "D.cityCode", "D.districtCode", "B.province", "B.city", "B.districtCode"], region),
        ("J16", ["D.businessScope", "B.businessScope", "T.basic.zsopscope"], lambda bz: first(bz, "D.businessScope", "B.businessScope", "T.basic.zsopscope")),
        ("J17", ["D.industry", "B.industryName", "B.industryCode"], industry),
        ("J18", ["D.historyNames", "B.historyName", "T.basic.entname_old"], lambda bz: first(bz, "D.historyNames", "B.historyName", "T.basic.entname_old")),
        ("J19", ["B.revokeDate", "B.revokeReason", "T.basic.revdate", "T.basic.revoke_reason"],
         lambda bz: join(bz, [("吊销日期", ["B.revokeDate", "T.basic.revdate"]), ("原因", ["B.revokeReason", "T.basic.revoke_reason"])])),
        ("J20", ["B.cancelDate", "B.cancelReason", "T.basic.candate", "T.basic.cancel_reason"],
         lambda bz: join(bz, [("注销日期", ["B.cancelDate", "T.basic.candate"]), ("原因", ["B.cancelReason", "T.basic.cancel_reason"])])),
        ("J21", ["B.employeeCnt"], lambda bz: first(bz, "B.employeeCnt")),
        ("J22", ["B.shortName"], lambda bz: first(bz, "B.shortName")),
        ("J23", ["B.isIPO"], ipo),
        ("J24", ["B.isHitech"], hitech),
        ("J25", ["T.person"], person),
        ("J26", ["T.techEnt"], lambda bz: s(bz.get("T.techEnt"))),
        ("J27", ["D.lastUpdatedTime"], lambda bz: first(bz, "D.lastUpdatedTime")),
    ]


NAME_KW_RE = re.compile(r'Employer\.(?:employer_name|enterprise_name)\s+CONTAINS\s+(?:"([^"]+)"|\[([^\]]+)\])')


def keywords_from_rules(rules_paths):
    """规则里「企业名称 CONTAINS 关键词」的词表。v0.2：可给多个文件（含 inst-rc-rule-mcp 的 {"model":[…]}），也认 [修匀] / [甲,乙] 写法。"""
    words = []
    for path in rules_paths or []:
        try:
            data = load_json_file(path)
        except (OSError, ValueError, SystemExit):
            continue
        d = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), (list, dict)) else data
        conds = []
        if isinstance(d, dict) and isinstance(d.get("model"), list):
            conds = [v for x in d["model"] if isinstance(x, dict) for v in x.values() if isinstance(v, str)]
        elif isinstance(d, list):
            conds = [r.get("condition", "") for r in d if isinstance(r, dict)]
        for c in conds:
            for m in NAME_KW_RE.finditer(c):
                for w in (m.group(1),) if m.group(1) else re.split(r"[,，、]", m.group(2)):
                    w = w.strip().strip("\"' ")
                    if w and w not in words:
                        words.append(w)
    return words


# ───────────────────────── 预填 ─────────────────────────

def req_get(req, key):
    v = req.get(key)
    return None if empty(v) else v


def cmd_init(a):
    spec = read_stdin()
    ctx, req = spec.get("ctx") or {}, spec.get("request") or {}
    for k in ("requestId", "domain", "scene"):
        if not ctx.get(k):
            die("ctx.%s 缺失" % k)
    if not isinstance(req, dict):
        die("request 必须是对象")
    rid = ctx["requestId"]
    if a.rid and a.rid != rid:  # init 的 requestId 以 stdin ctx 为准；--rid 只是兼容多写
        die("init --rid=%s 与 stdin ctx.requestId=%s 不一致；init 不需要 --rid，删掉它" % (a.rid, rid), 2)
    warnings = spec.get("warnings") or []
    items = load_items()
    for msg in check_anchors(items):
        print("WARN 清单与脚本按编号引用的条目对不上：%s。脚本里的编号需要同步调整，否则该行可能被写错" % msg)
    bad = check_derive_specs(items)
    if bad:
        die("清单 derive 声明有误（extract-items-checked.json）：" + "；".join(bad))
    bad = check_notice_specs(items)
    if bad:
        die("清单 notice 声明有误（extract-items-checked.json）：" + "；".join(bad))
    row = {i["id"]: {"id": i["id"], "name": i["name"], "desc": i["desc"], "value": None, "source": ""} for i in items}
    order = [i["id"] for i in items]
    pre, issues = set(), []

    def Y(i, v, src):
        row[i]["value"], row[i]["source"] = s(v), "Y｜" + src
        pre.add(i)

    def N(i, code, why):
        row[i]["value"], row[i]["source"] = None, "N｜%s｜%s" % (code, why)
        pre.add(i)

    # A 组：请求与网关上下文
    for i, key in (("A01", "entpId"), ("A02", "entpName"), ("A03", "rqId"), ("A04", "hrInstId"), ("A07", "dlvrDemd"),
                   ("A08", "projCont"), ("A09", "project_intro")):
        v = req_get(req, key)
        if v is None:
            N(i, "R01", "请求未提供 %s 字段" % key)
        else:
            Y(i, v, "请求 %s｜%s=%s" % (key, key, s(v)))
    Y("A05", "%s / %s / %s" % (ctx["requestId"], ctx["domain"], ctx["scene"]),
      "网关上下文｜requestId=%s；domain=%s；scene=%s" % (ctx["requestId"], ctx["domain"], ctx["scene"]))
    apply = req_get(req, "apply_date") or req_get(req, "applyDate")
    tsd = spec.get("taskSubmittedDate")
    if apply:
        Y("A06", apply, "请求 apply_date｜apply_date=%s" % apply)
        base, base_origin = parse_date(str(apply)), "apply_date"
    elif tsd:
        Y("A06", tsd, "网关 taskSubmittedDate｜taskSubmittedDate=%s" % tsd)
        base, base_origin = parse_date(str(tsd)), "taskSubmittedDate"
        issues.append("基准日回退：请求未提供 apply_date，使用 taskSubmittedDate=%s 作为基准日" % tsd)
    else:
        N("A06", "R01", "请求未提供 apply_date，网关也未给 taskSubmittedDate")
        base, base_origin = None, ""
    cate = req_get(req, "invoiceCate")
    if cate is None:
        N("A10", "R01", "请求未提供 invoiceCate 字段")
    else:
        cl = cate if isinstance(cate, list) else [cate]
        names = [c.get("name") if isinstance(c, dict) else str(c) for c in cl]
        ev = "；".join("invoiceCate[%d].name=%s%s" % (n, (c.get("name") if isinstance(c, dict) else c),
                                                      ("；code=%s" % c.get("code")) if isinstance(c, dict) and c.get("code") else "")
                       for n, c in enumerate(cl))
        Y("A10", "、".join(x for x in names if x), "请求 invoiceCate｜" + ev)
    online = req_get(req, "onlinePresenceUrl")
    if online is None:
        N("A11", "R01", "请求未提供 onlinePresenceUrl 字段")
    else:
        Y("A11", online, "请求 onlinePresenceUrl｜onlinePresenceUrl=%s" % online)
    pos = next((k for k in REQ_POSITION_KEYS if req_get(req, k)), None)
    if pos:
        Y("A13", req[pos], "请求 %s｜%s=%s" % (pos, pos, req[pos]))
    else:
        N("A13", "R01", "请求未提供岗位名称字段，当前阶段无")

    # 材料状态：能由请求直接判定的先写；有附件的字段留给模型填「可读/不可读 + 栏位原文」
    invalid = {}
    for w in warnings:
        for f in w.get("inputFields") or []:
            invalid[f.split("[")[0]] = w.get("code") or "ATTACHMENT_UNAVAILABLE"
    materials, need_status = {}, []
    present_attach = set()
    for f in MATERIAL_ORDER:
        v = req.get(f)
        if f == "onlinePresenceUrl":
            if empty(v):
                materials[f] = ["未提供", "—"]
            elif isinstance(v, str) and v.lower().split("?")[0].endswith(FILE_EXT):
                need_status.append(f)
            else:
                materials[f] = ["仅URL", v]
            continue
        if empty(v):
            materials[f] = ["未提供", ("网关附件可用性说明：URL 失效或不可用（%s），已置空" % invalid[f]) if f in invalid else "—"]
            continue
        present_attach.add(f)
        if f == "bizScenePhotoUrls" and isinstance(v, list):
            for n, x in enumerate(v):
                if not empty(x):
                    need_status.append("%s[%d]" % (f, n))
        else:
            need_status.append(f)
    unknown = sorted(k for k, v in req.items() if k not in KNOWN_ATTACH and k != "onlinePresenceUrl" and isinstance(v, str)
                     and v.lower().startswith(("http://", "https://")) and v.lower().split("?")[0].endswith(FILE_EXT))
    for u in unknown:
        need_status.append(u)

    def group_absent(fields):
        return not unknown and all(empty(req.get(f)) for f in fields)

    def reason_absent(fields, label):
        bad = [f for f in fields if f in invalid]
        if bad:
            return "R01", "%s URL 失效（%s），网关已置空，无%s可读" % ("、".join(bad), invalid[bad[0]], label)
        return "R01", "请求未提供%s附件字段" % label

    for g, fields in GROUPS.items():
        if group_absent(fields):
            code, why = reason_absent(fields, g) if fields else ("R01", "请求没有法人身份证附件字段")
            for it in items:
                if it["group"] == g:
                    N(it["id"], code, why)
    for prefixes, fields, label in SUPPLEMENT_PREFIX:
        if group_absent(fields):
            code, why = reason_absent(fields, label)
            for i in supplement_ids(items, prefixes):
                N(i, code, why)
    o_open, o_rel = online_ids(items)
    if o_open is None or o_rel is None:
        print("WARN 清单里没找到「%s…可打开 / …关联」两条，官网条目不自动判定（交给模型按 desc 取）" % ONLINE_PREFIX)
    elif online is not None and "onlinePresenceUrl" not in need_status:
        N(o_open, "R04", "仅有 URL %s，未验证是否可打开" % online)
        N(o_rel, "R04", "仅有 URL，未验证内容，无法判断与公司关联")
    elif online is None:
        N(o_open, "R01", "请求未提供 onlinePresenceUrl 字段")
        N(o_rel, "R01", "请求未提供 onlinePresenceUrl 字段")
    photos = req.get("bizScenePhotoUrls")
    if isinstance(photos, list) and any(not empty(x) for x in photos):
        n = sum(1 for x in photos if not empty(x))
        Y("F01", str(n), "请求 bizScenePhotoUrls｜数组含 %d 张图片" % n)

    # J 组：工商三接口
    biz_files = [x for f in (a.biz or []) for x in f.split(",") if x.strip()]  # 逗号拼接也兼容
    uscc = req_get(req, "uscc") or req_get(req, "creditCode")
    bz = Biz(load_biz(biz_files, uscc))
    if not bz.biz:
        print("WARN 没有读到任何工商返回文件，J 组全部写 N R07")
    else:
        got = sorted(bz.biz)
        miss = [k for k in ("D", "B", "T") if k not in got]
        print("工商接口读到：%s%s" % ("、".join(got), ("；缺：" + "、".join(miss)) if miss else ""))
    for i, keys, fn in j_specs():
        parts, miss = bz.evidence(keys, "")
        v = fn(bz) if parts else None
        if v is None:
            why = "；".join("%s 为空" % k for k in miss) or "无数据"
            extra = bz.failed()
            if extra:
                why += "；" + "；".join(extra)
            N(i, "R07", why)
        else:
            src_key = next(k for k in keys if bz.get(k) is not None)
            Y(i, v, "工商:%s｜%s" % (src_key, "；".join(parts)))
    cap_conf = capital_conflict(bz)      # v36：D.capital 与 B.registerCapital 单位明确、数值不同时，J08 不再只取第一个来源（v35-am6：D=500万元、B=100万、T=100.0，被当成“执照100万≠工商500万”）
    if cap_conf:
        N("J08", "R09", cap_conf)
    st = [("%s.succeed=%s errMsg=%s" % (i, str(b["doc"].get("succeed")).lower(), b["doc"].get("errMsg") or b["doc"].get("message") or ""))
          for i, b in sorted(bz.biz.items())]
    Y("J28", "三接口均成功" if len(bz.biz) == 3 and all(b["ok"] for b in bz.biz.values()) else "；".join(bz.failed()) or "无返回",
      "工商:D/B/T｜" + "；".join(st)) if bz.biz else N("J28", "R07", "没有任何工商返回")
    N("J30", "R10", "主营业务是否可查询可验证需业务判断，本流程无完整口径")
    N("J31", "R10", "是否为人力资源或劳务公司需业务判断，本流程无完整口径")
    N("J37", "R10", "董监高是否命中风控名单需外部名单核查，本流程无此来源")
    words = keywords_from_rules(a.rules)
    name = row["A02"]["value"]
    if words and name:
        hit = [w for w in words if w in name]
        Y("J33", "true" if hit else "false", "派生:A02｜规则给出企业名称关键词表（%s）；A02=%s，%s" % (
            "、".join(words), name, ("命中：" + "、".join(hit)) if hit else "逐词核对均未命中"))
    else:
        N("J33", "R10", "规则未给出企业名称关键词词表或缺申报企业名称")

    doc = {"contract": CONTRACT, "routing": {"requestId": rid, "domain": ctx["domain"], "scene": ctx["scene"],
                                              "businessKey": row["A01"]["value"] or ""},
           "materials": materials, "items": [row[i] for i in order],
           "notes": {"unresolvedProperties": [], "notFoundInDefinition": [], "conflicts": [], "unreadMaterials": [], "toolIssues": issues}}
    state = {"prefilled": sorted(pre), "modelFilled": [], "needStatus": need_status, "invalid": invalid,
             "base": base.isoformat() if base else None, "baseOrigin": base_origin,
             "derived": [], "autoConflicts": [], "rechecked": {}, "stale": []}
    write_detail(rid, doc)
    save_state(rid, state)
    derive(doc, state)
    write_detail(rid, doc)
    save_state(rid, state)
    report(rid, doc, state, header=True)


# ───────────────────────── 工商与原件识别的比对 / 复核（v29） ─────────────────────────

# (原件条目, 工商条目, 说明, 比较类型)。前 J34_PAIRS 对就是 J34 的逐项对比；其余只进 conflicts，不进 J34。
# 这些条目是否进入 input 取决于本次映射（由 Agent 按含义决定）：映射了，复核更正后的值会随重新组装进入 input；没映射，只影响明细和 notes。
PAIRS = [
    ("B01", "J01", "名称", "name"),
    ("B03", "J02", "信用代码", "code"),
    ("B06", "J07", "法定代表人", "legal"),
    ("B04", "J09", "成立日期", "date"),
    ("B05", "J10", "营业期限", "period"),
    ("B07", "J13", "地址", "addr"),
    ("B08", "J16", "经营范围", "scope"),
    ("C02", "J07", "身份证姓名与工商法定代表人", "legal"),
    ("D01", "J01", "开户凭证户名与工商名称", "name"),
    ("D08", "J07", "开户凭证法定代表人与工商法定代表人", "legal"),
    ("G02", "J01", "租赁合同承租方与工商名称", "name"),
    ("B10", "J08", "注册资本", "money"),          # v33：执照「壹佰万元」对工商「500万元」两次运行都没人发现；只进 conflicts
]
J34_PAIRS = 7
OUTCOME_LABEL = {"corrected": "更正", "confirmed_diff": "确认不一致", "unstable": "两次识别不一致", "unreadable": "无法确认"}
DERIVE_DEP_RE = re.compile(r"^Y｜派生:([A-Z0-9,-]+)｜")


def same_fact(kind, orig, biz):
    """原件识别值 orig 与工商值 biz 是否同一事实。前 7 类口径与 v28 的 J34 逐项对比完全一致。"""
    if kind in ("name", "addr", "scope"):
        return nfkc_name(orig) == nfkc_name(biz)
    if kind == "code":
        return biz.replace(" ", "").upper() == orig.replace(" ", "").upper()
    if kind == "legal":
        return biz in orig or orig in biz
    if kind == "date":
        return parse_date(biz) == parse_date(orig)
    if kind == "money":
        o, b = money_yuan(orig), money_yuan(biz.split("；")[0])
        return o is None or b is None or abs(o - b) < 1
    if kind == "period":
        j_end = dates_in(biz.split("起", 1)[-1]) if "截止 " in biz else []
        o_end = dates_in(orig) if not any(w in orig for w in ("长期", "永久")) else []
        return (j_end[-1:] or None) == (o_end[-1:] or None)
    raise ValueError(kind)


PUNCT_RE = re.compile(r"[\s()（）\[\]【】<>《》「」“”\"'‘’。．.，,、；;：:！!？?·•…\-—_/]")


CN_DIGIT = {"零": 0, "〇": 0, "壹": 1, "一": 1, "贰": 2, "二": 2, "两": 2, "叁": 3, "三": 3, "肆": 4, "四": 4, "伍": 5, "五": 5,
            "陆": 6, "六": 6, "柒": 7, "七": 7, "捌": 8, "八": 8, "玖": 9, "九": 9}
CN_UNIT = {"拾": 10, "十": 10, "佰": 100, "百": 100, "仟": 1000, "千": 1000}
CN_BIG = {"万": 10 ** 4, "亿": 10 ** 8}


def cn_number(t):
    total, section, num = 0, 0, 0
    for ch in t:
        if ch in CN_DIGIT:
            num = CN_DIGIT[ch]
        elif ch in CN_UNIT:
            section += (num or 1) * CN_UNIT[ch]
            num = 0
        elif ch in CN_BIG:
            total += (section + num) * CN_BIG[ch]
            section, num = 0, 0
        else:
            return None
    return total + section + num


def money_yuan(text):
    """「人民币壹佰万元」「500万元」「500.000000万人民币」→ 元；没写单位（工商常见「300.000000」）或读不出返回 None，不比较。"""
    if not re.search(r"[万亿元圆]", text or ""):
        return None
    t = re.sub(r"\s|人民币|元|圆|整|币种.*$|\(.*?\)|（.*?）", "", text or "")
    t = t.replace("注册资本", "").replace("：", "").replace(":", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(万|亿)?(?:人民币)?", t)
    if m:
        return float(m.group(1)) * (CN_BIG.get(m.group(2)) or 1)
    v = cn_number(t) if t else None
    return float(v) if v else None


def same_reading(kind, a, b):
    """同一栏位两次识别的结果是否相同（忽略空白、标点与括号、全半角、日期写法）。
    v33：am2 二次识别时只删了括号「（…）」，被判“两次识别不一致”，经营范围整条丢失——标点差异不算两次识别不同。"""
    if nfkc_name(a) == nfkc_name(b):
        return True
    if PUNCT_RE.sub("", unicodedata.normalize("NFKC", a or "")) == PUNCT_RE.sub("", unicodedata.normalize("NFKC", b or "")):
        return True
    if kind in ("date", "period"):
        da, db = dates_in(a), dates_in(b)
        long_a, long_b = any(w in a for w in ("长期", "永久")), any(w in b for w in ("长期", "永久"))
        return bool(da) and da == db and long_a == long_b
    return False


def pair_rows(doc):
    """每一对的状态：same 一致 / diff 不一致 / na 任一侧没有值，无法比较。"""
    by = {x["id"]: x for x in doc["items"]}
    out = []
    for orig, biz, label, kind in PAIRS:
        o, b = by[orig], by[biz]
        if o["source"].startswith("Y｜") and b["source"].startswith("Y｜"):
            out.append((orig, biz, label, kind, "same" if same_fact(kind, o["value"], b["value"]) else "diff"))
        else:
            out.append((orig, biz, label, kind, "na"))
    return out


def diff_text(by, orig, biz, label, kind):
    if kind == "scope":
        return "%s %s 与 %s 文字不同" % (label, biz, orig)
    return "%s %s=%s≠%s=%s" % (label, biz, by[biz]["value"], orig, by[orig]["value"])


def confirm_suffix(st, orig):
    return "【已二次识别确认】" if (st.get("rechecked") or {}).get(orig, {}).get("outcome") == "confirmed_diff" else ""


def recheck_pending(doc, st):
    done = st.get("rechecked") or {}
    return [(o, b, l) for o, b, l, k, status in pair_rows(doc) if status == "diff" and o not in done]


def gate_problems(doc, st):
    """明细能否进入组装：工商与原件识别不一致的项必须已二次识别；模型写的派生行依据变了必须重判。"""
    probs = []
    rp = recheck_pending(doc, st)
    if rp:
        probs.append("RECHECK 工商与原件识别不一致 %d 项尚未二次识别复核：%s" % (len(rp), "、".join("%s(%s)" % (o, l) for o, _, l in rp)))
    stale = list(st.get("stale") or [])
    if stale:
        probs.append("STALE 以下由模型写入的派生行，其依据行已被修改，须重新判断后用 fill --force 重提：" + "、".join(stale))
    return probs


def snapshot(doc):
    return {x["id"]: (x["value"], x["source"]) for x in doc["items"]}


def mark_stale(doc, st, before, skip):
    """模型自己写的「派生:…」行（脚本不会重算）：依据行被改了就标 stale，等模型重判。"""
    # 只看「值」变没变：复核往 source 末尾追加说明、值不变时，依赖它的派生行仍然有效
    changed = {x["id"] for x in doc["items"] if before[x["id"]][1] != "" and x["value"] != before[x["id"]][0]}
    stale = set(st.get("stale") or [])
    derived = set(st.get("derived") or [])
    model = set(st.get("modelFilled") or [])
    for x in doc["items"]:
        i = x["id"]
        if i in skip or i in derived or i not in model:
            continue
        m = DERIVE_DEP_RE.match(x["source"])
        if m and set(m.group(1).split(",")) & changed:
            stale.add(i)
    st["stale"] = sorted(stale - set(skip))


def recheck_lines(doc, st):
    by = {x["id"]: x for x in doc["items"]}
    lines = []
    for o, b, l in recheck_pending(doc, st):
        lines.append("RECHECK_ITEM %s|%s|首次识别=%s|首次来源=%s|工商 %s=%s|工商来源=%s" % (
            o, l, by[o]["value"], by[o]["source"][2:120], b, by[b]["value"], by[b]["source"][2:100]))
    return lines


# ───────────────────────── 派生 ─────────────────────────

def val(doc, i):
    it = next(x for x in doc["items"] if x["id"] == i)
    return it["value"] if it["source"].startswith("Y｜") else None


def derive(doc, st):
    """每次都按当前的依据行重算「脚本自己写过的派生行」（v29）；模型写的行和别的预填行不动。
    v28 只补待填行，fill --force 改了源字段后 B15/B16/J34 等已写的派生行不会更新，审核 A 删值后还会留着旧结果。"""
    by = {x["id"]: x for x in doc["items"]}
    pre = set(st["prefilled"])
    base = parse_date(st["base"] or "")
    origin = st.get("baseOrigin") or ""
    derived, auto_conf = set(), []
    for i in st.get("derived") or []:          # 先清掉上一次脚本写的派生行，下面按当前依据重新算
        if i in by:
            by[i]["value"], by[i]["source"] = None, ""
            pre.discard(i)
    for m in st.get("autoConflicts") or []:    # 脚本自己加过的冲突说明也一并重建
        if m in doc["notes"]["conflicts"]:
            doc["notes"]["conflicts"].remove(m)

    def pending(i):
        return by[i]["source"] == ""

    def Y(i, v, src):
        if pending(i):
            by[i]["value"], by[i]["source"] = v, "Y｜" + src
            pre.add(i)
            derived.add(i)

    def N(i, code, why):
        if pending(i):
            by[i]["value"], by[i]["source"] = None, "N｜%s｜%s" % (code, why)
            pre.add(i)
            derived.add(i)

    def need(i, *deps):
        """依据都是 Y → 返回各值；任一为 N（不是待填）→ 直接 N R12 并返回 None；依据待填 → 返回 None 不动。"""
        vals = []
        for d in deps:
            if by[d]["source"] == "":
                return None
            if not by[d]["source"].startswith("Y｜"):
                N(i, "R12", "缺 %s" % d)
                return None
            vals.append(by[d]["value"])
        return vals

    # 成立月数 / 主体类型 / 分公司 / 合伙
    if pending("B16"):
        v = need("B16", "B04", "A06")
        if v:
            f, b = parse_date(v[0]), parse_date(v[1])
            if f and b and f <= b:
                n = months_between(f, b)
                Y("B16", str(n), "派生:B04,A06｜成立日 %s；基准日 %s(%s)；(%d-%d)*12+(%d-%d)=%d；%s；结果%d" % (
                    f.isoformat(), b.isoformat(), origin, b.year, f.year, b.month, f.month, (b.year - f.year) * 12 + b.month - f.month,
                    "基准日的日小于成立日的日，再减1" if b.day < f.day else "基准日的日不小于成立日的日，不减", n))
    t = need("B17", "B02") if pending("B17") else None
    if t:
        ty = t[0]
        if "分公司" in ty or "合伙" in ty or "个人独资" in ty:
            r = "其他"
        elif "个体工商户" in ty:
            r = "个体工商户"
        elif "股份有限公司" in ty:
            r = "股份有限公司"
        elif "有限责任公司" in ty:
            r = "有限责任公司"
        else:
            r = "其他"
        Y("B17", r, "派生:B02｜B02=%s，主体类型为%s" % (ty, r))
    if pending("B18"):
        t = need("B18", "B02")
        if t:
            Y("B18", "true" if "分公司" in t[0] else "false", "派生:B02｜B02=%s，%s「分公司」字样" % (t[0], "含" if "分公司" in t[0] else "不含"))
    if pending("B19"):
        t = need("B19", "B02")
        if t:
            Y("B19", "true" if "合伙" in t[0] else "false", "派生:B02｜B02=%s，%s「合伙」字样" % (t[0], "含" if "合伙" in t[0] else "不含"))
    # 营业期限：有效期、快到期
    if base and pending("B11"):
        t = need("B11", "B05", "B04") if pending("B11") else None
        if t:
            long_term = any(w in t[0] for w in ("长期", "永久"))
            ds = dates_in(t[0])
            f = parse_date(t[1])
            if long_term and f and f <= base:
                Y("B11", "true", "派生:B05,A06｜营业期限为「%s」，无截止日；基准日 %s 不早于成立日 %s，执照有效" % (t[0], base.isoformat(), f.isoformat()))
            elif ds and not long_term:
                end = ds[-1]
                Y("B11", "true" if end >= base else "false", "派生:B05,A06｜营业期限截止 %s；基准日 %s；%s" % (
                    end.isoformat(), base.isoformat(), "未届满" if end >= base else "已届满"))
    # v42：清单 derive 声明的通用派生（名称比较、期间、距到期、原样带出）；依次跑到不再有新行，支持派生行之间互相依赖
    specs = {i: d for i, d in derive_specs(load_items()).items() if i in by}
    for _ in range(len(specs) + 1):
        left = [i for i in specs if pending(i)]
        for i in left:
            run_derive_spec(i, specs[i], need, Y, base, by)
        if [i for i in specs if pending(i)] == left:
            break
    # v39：是否灵工平台企业（B26）：按执照经营范围原文逐词核对 FLEX_PLATFORM_WORDS
    if "B26" in by and pending("B26"):
        t = need("B26", "B08")
        if t:
            hit = [w for w in FLEX_PLATFORM_WORDS if w in t[0]]
            Y("B26", "true" if hit else "false", "派生:B08｜经营范围逐词核对（%s）：%s" % (
                "、".join(FLEX_PLATFORM_WORDS), ("含「%s」" % "、".join(hit)) if hit else "均未出现"))
    # 注册地境内
    if pending("J32"):
        t = need("J32", "J13")
        if t and t[0].startswith(PROVINCES) and not any(w in t[0] for w in ("香港", "澳门", "台湾", "台北")):
            Y("J32", "false", "派生:J13｜J13=%s，地址以国内省级行政区开头，为境内地址" % t[0])
    # 工商期限/状态是否有效、吊销注销事实
    if base and pending("J35"):
        t = need("J35", "J05", "J10")
        if t:
            dead = [w for w in ("吊销", "注销", "撤销") if w in t[0]]
            ds = dates_in(t[1].split("起", 1)[-1]) if "截止 " in t[1] else []
            expired = bool(ds) and ds[-1] < base
            ok = not dead and not expired
            Y("J35", "true" if ok else "false", "派生:J05,J10,A06｜J05=%s；J10=%s；基准日 %s；%s" % (
                t[0], t[1], base.isoformat(), "均有效" if ok else ("状态为" + "、".join(dead) if dead else "期限已届满")))
    if pending("J36"):
        j19, j20, j05 = by["J19"], by["J20"], by["J05"]
        if j05["source"] != "":
            facts = [("J19", j19), ("J20", j20)]
            have = [("%s=%s" % (k, x["value"])) for k, x in facts if x["source"].startswith("Y｜")]
            dead = [w for w in ("吊销", "注销", "撤销") if j05["value"] and w in j05["value"]]
            if have or dead:
                Y("J36", "；".join(have + (["J05=%s" % j05["value"]] if dead else [])), "派生:J19,J20,J05｜接口返回吊销/注销事实")
            else:
                Y("J36", "接口未返回吊销/注销信息", "派生:J19,J20,J05｜J19、J20 为空；J05=%s，非吊销/注销/撤销；不据此写「无风险」" % (j05["value"] or "未返回"))
    # 工商与执照的一致性（前 7 对），以及身份证/开户凭证/租赁合同与工商的比对（只进 conflicts）
    if pending("J34"):
        deps = ["J01", "J02", "J07", "J09", "J10", "J13", "J16", "B01", "B03", "B06", "B04", "B05", "B07", "B08"]
        t = need("J34", *deps)
        if t:
            diffs = [diff_text(by, o, b, l, k) + confirm_suffix(st, o)
                     for o, b, l, k, status in pair_rows(doc)[:J34_PAIRS] if status == "diff"]
            rc = (st.get("rechecked") or {})
            rec = "；复核记录：" + "、".join("%s=%s" % (o, OUTCOME_LABEL.get(rc[o]["outcome"], rc[o]["outcome"]))
                                             for o, _, _, _ in PAIRS[:J34_PAIRS] if o in rc) if any(o in rc for o, _, _, _ in PAIRS[:J34_PAIRS]) else ""
            if diffs:
                Y("J34", "不一致：" + "；".join(diffs), "派生:" + ",".join(deps) + "｜逐项对比，不裁决" + rec)
            else:
                Y("J34", "无不一致", "派生:" + ",".join(deps) + "｜J01/J02/J07/J09/J10/J13/J16 与 B01/B03/B06/B04/B05/B07/B08 逐项一致" + rec)
    if by["J34"]["source"].startswith("Y｜") and by["J34"]["value"].startswith("不一致："):
        auto_conf.append("工商与执照不一致（未裁决）：" + by["J34"]["value"][len("不一致："):])
    if by["J08"]["source"].startswith("N｜R09｜"):
        auto_conf.append("工商注册资本来源冲突（未裁决）：" + by["J08"]["source"].split("｜", 2)[2])
    for o, b, l, k, status in pair_rows(doc)[J34_PAIRS:]:
        if status == "diff":
            auto_conf.append("原件识别与工商不一致（未裁决）：" + diff_text(by, o, b, l, k) + confirm_suffix(st, o))
    for o, r in (st.get("rechecked") or {}).items():
        if r.get("conflict"):
            auto_conf.append(r["conflict"])
    for m in auto_conf:
        if m not in doc["notes"]["conflicts"]:
            doc["notes"]["conflicts"].append(m)
    st["autoConflicts"] = auto_conf
    # 附件盘点
    if pending("A12") and doc["materials"] and all(k in doc["materials"] for k in st["needStatus"]):
        if True:
            def mkey(k):
                b = k.split("[")[0]
                return (MATERIAL_ORDER.index(b) if b in MATERIAL_ORDER else 99, k)
            Y("A12", "；".join("%s=%s" % (k, doc["materials"][k][0]) for k in sorted(doc["materials"], key=mkey)), "materials 盘点｜见 materials 段逐字段状态")
    st["prefilled"] = sorted(pre)
    st["derived"] = sorted(derived)


# ───────────────────────── fill / finish / show ─────────────────────────

def pending_rows(doc):
    return [x for x in doc["items"] if x["source"] == ""]


def report(rid, doc, st, header=False):
    pend = pending_rows(doc)
    ys = sum(1 for x in doc["items"] if x["source"].startswith("Y｜"))
    ns = sum(1 for x in doc["items"] if x["source"].startswith("N｜"))
    miss_mat = [k for k in st["needStatus"] if k not in doc["materials"]]
    print("OK work/%s/input-extract-detail.json  Y=%d N=%d 待填=%d 共%d条" % (rid, ys, ns, len(pend), len(doc["items"])))
    if header:
        print("已预填材料状态：" + "；".join("%s=%s" % (k, v[0]) for k, v in doc["materials"].items()))
    if miss_mat:
        print("MATERIALS 待填（fill 的 materials 里给 [状态, 依据]；状态：可读/不可读；依据=原件一个真实栏位原文，PDF 加页码）：" + "、".join(miss_mat))
    specs = derive_specs(load_items())
    wait = [x for x in pend if x["id"] in specs]          # v42：清单声明了 derive 的行，依据填好后脚本自动算，不让模型读
    pend = [x for x in pend if x["id"] not in specs]
    if wait:
        print("WAIT %d 行由脚本按清单 derive 声明派生，依据就绪后自动写入（不用 fill）：%s" % (
            len(wait), "、".join("%s←%s" % (x["id"], ",".join(specs[x["id"]]["from"])) for x in wait)))
    if pend:
        print("PENDING 待填 %d 行（id|name|desc）——读材料后用 fill 提交；取不到写 null + Rxx｜具体原因：" % len(pend))
        for x in pend:
            print("%s|%s|%s" % (x["id"], x["name"], x["desc"]))
    for g in gate_problems(doc, st):
        print(g)
    for ln in recheck_lines(doc, st):
        print(ln)
    if recheck_pending(doc, st):
        print("→ 回看这些原件栏位（PDF 到对应页码）重新识别一次，用 detail.py recheck 提交；每项只能复核一次。工商值不得直接覆盖原件值。")


def cmd_fill(a):
    doc, st = load_detail(a.rid)
    spec = read_stdin("fill", a.rid)
    by = {x["id"]: x for x in doc["items"]}
    pre, errs, done, autofix, skipped, sanitized, fallback = set(st["prefilled"]), [], [], [], [], [], []
    items_by = {x["id"]: x for x in load_items()}
    before = snapshot(doc)
    for r in spec.get("rows") or []:
        if not (isinstance(r, list) and len(r) == 3):
            errs.append("行格式应为 [id, value|null, text]: %s" % json.dumps(r, ensure_ascii=False)[:80])
            continue
        i, v, text = r
        if i not in by:
            errs.append("%s 不在清单里" % i)
            continue
        if i in pre and not a.force:      # v37：不算错（v35 五次都重交了 F01/A12，整次 fill 因此退出 1）
            skipped.append(i)
            continue
        if not isinstance(text, str) or not text.strip():
            errs.append("%s 的 text 为空" % i)
            continue
        text = PREFIX_RE.sub("", text.strip(), count=1)  # 脚本自己加 Y｜/N｜，模型多写了就去掉
        if id_numbers(text) or id_numbers(v if isinstance(v, str) else ""):
            errs.append("%s 含身份证号码：不抄录身份证号码，证据写「公民身份号码栏可见，按规定不抄录」即可" % i)
            continue
        if v is None:
            if not N_RE.fullmatch(text):
                errs.append("%s 取不到时 text 须为「Rxx｜具体原因」，如「R10｜无业务判断口径」（Rxx 取 R01–R15，原因至少 4 个字）；你写的是：%s" % (i, text[:60]))
                continue
            by[i]["value"], by[i]["source"] = None, "N｜" + text
        else:
            if isinstance(v, bool):
                v = "true" if v else "false"
            elif isinstance(v, (int, float)):
                v = str(v)
            elif not isinstance(v, str) or v == "":
                errs.append("%s 的 value 须为非空字符串或 null" % i)
                continue
            if "｜" not in text:
                fixed = fix_source(text)
                if not fixed and default_source(items_by.get(i, {})):
                    fixed = "%s｜%s" % (default_source(items_by[i]), text)
                if not fixed:
                    errs.append("%s 有值时 text 须为「来源｜证据」，例如 [\"%s\",\"%s\",\"营业执照 bizlicUrl p1 类型栏｜有限责任公司\"]；来源写材料名+字段+页码/栏位，判断类也一样；材料没提供就写 null + R01" % (i, i, v))
                    continue
                autofix.append(i)
                text = fixed
            if "伪造嫌疑" in items_by.get(i, {}).get("name", ""):   # 取不到的行常写“无法确认是否真实”，那是存疑，不是断言
                # v0.2：放到补「｜」之后（80 号证据没写「｜」，v40 在补之前就跳过了删句）；删不掉就当场退回，
                # 不再写入后等 build 的 CHECK（71/80 号 fill 回 PASS、build 回 CHECK，循环到超时）
                text, cut = strip_assertions(text)
                if cut:
                    sanitized.append(i)
                bad = assertion_words(text)
                if bad:
                    n = st.setdefault("assertRejects", {}).get(i, 0) + 1
                    st["assertRejects"][i] = n
                    if n > ASSERT_MAX_REJECT:
                        by[i]["value"], by[i]["source"] = None, "N｜R06｜依据连续 %d 次只有「%s」这类断言，没有写出看到的具体现象，不作判断" % (n, "、".join(bad))
                        fallback.append(i)
                        done.append(i)
                        continue
                    clauses = [c.strip("，,；;。、 ") for c in re.split(r"[，,；;。、]", text.partition("｜")[2]) if any(w in c for w in bad)]
                    errs.append("%s 的依据每一句都带断言字样「%s」（%s）：伪造嫌疑类只写看了哪些地方、看到了什么，"
                                "不出现“真实/合规/正常/可信/无异常”这些词；没看到异常就写「未见…」。"
                                "连续 %d 次仍这样，脚本把本行记为 null R06（第 %d 次）" % (
                                    i, "、".join(bad), "；".join("「%s」" % c for c in clauses[:3]), ASSERT_MAX_REJECT + 1, n))
                    continue
            by[i]["value"], by[i]["source"] = v, "Y｜" + text
        done.append(i)
    mats = spec.get("materials") or {}
    for k, v in mats.items():
        if not (isinstance(v, list) and len(v) == 2 and v[0] in ("可读", "不可读", "仅URL", "未提供") and isinstance(v[1], str)):
            errs.append("materials.%s 应为 [状态, 依据]，状态取 可读/不可读/仅URL/未提供" % k)
            continue
        if id_numbers(v[1]):
            errs.append("materials.%s 的依据含身份证号码：不抄录，改写姓名栏等其他栏位原文" % k)
            continue
        doc["materials"][k] = v
    for k, lst in (spec.get("notes") or {}).items():
        if k not in doc["notes"] or k == "unresolvedProperties" or not isinstance(lst, list):
            errs.append("notes.%s 不能这样提交" % k)
            continue
        for x in lst:
            if isinstance(x, str) and x not in doc["notes"][k]:
                doc["notes"][k].append(x)
    st["modelFilled"] = sorted(set(st["modelFilled"]) | set(done))
    st["derived"] = [i for i in st.get("derived", []) if i not in done]       # 模型改写了的行，脚本不再接管
    for o, b, _, _ in PAIRS:                                                  # 原件或工商侧被改，之前的复核结论作废，需重新比对
        if o in done or b in done:
            st["rechecked"].pop(o, None)
    pend, miss_mat = finalize(a.rid, doc, st)
    mark_stale(doc, st, before, done)
    st["stale"] = [i for i in st["stale"] if i not in done]
    save_state(a.rid, st)
    if autofix:
        print("AUTOFIX 以下行漏了「｜」，已补上来源（开头能认出的来源，认不出就用该条所属的材料；下次直接写「来源｜证据」）：" + "、".join(autofix))
    if fallback:
        print("ASSERT_FALLBACK 以下伪造嫌疑类行连续被退回仍只有断言，已记为 null R06，不用再交：" + "、".join(fallback))
    if sanitized:
        print("TRIMMED 伪造嫌疑类条目的依据去掉了含“真实/合规/正常/可信/无异常”的分句（只写逐项看了什么）：" + "、".join(sanitized))
    if skipped:
        print("SKIP %s 已由脚本预填，不用再填，未采用你提交的值（确要覆盖请加 --force）" % "、".join(skipped))
    for e in errs:
        print("REJECT " + e)
    if errs:
        print("被拒 %d 行；其余 %d 行已写入，下次只需重发被拒的行" % (len(errs), len(done)))
    else:
        print("已写入 %d 行" % len(done))
    report(a.rid, doc, st)
    if not pend and not miss_mat and not errs and not gate_problems(doc, st):
        print("PASS 明细完整（%d 条，无待填）；unresolvedProperties %d 行。可以运行 combine.py build" % (len(doc["items"]), len(doc["notes"]["unresolvedProperties"])))
        print(RELEASE_MARKER)
    sys.exit(1 if errs else 0)


def finalize(rid, doc, st):
    """补派生行、生成 notes（unresolvedProperties / unreadMaterials）并落盘。返回 (待填行, 缺的材料状态)。"""
    derive(doc, st)
    lines = []
    for x in doc["items"]:
        if x["source"].startswith("N｜"):
            _, code, why = x["source"].split("｜", 2)
            lines.append("%s｜%s｜%s" % (x["name"], code, why))
    doc["notes"]["unresolvedProperties"] = lines
    unread = [x for x in doc["notes"]["unreadMaterials"] if not x.startswith("@auto:")]
    auto = []
    for k, v in doc["materials"].items():
        if v[0] == "不可读":
            auto.append("%s｜%s" % (k, v[1]))
    for f, code in st["invalid"].items():
        auto.append("%s｜URL 失效或不可用（%s），网关已置空，未尝试读取" % (f, code))
    doc["notes"]["unreadMaterials"] = unread + [x for x in auto if x not in unread]
    write_detail(rid, doc)
    save_state(rid, st)
    return pending_rows(doc), [k for k in st["needStatus"] if k not in doc["materials"]]


def cmd_finish(a):
    doc, st = load_detail(a.rid)
    pend, miss_mat = finalize(a.rid, doc, st)
    report(a.rid, doc, st)
    if pend or miss_mat:
        print("FAIL 还有待填内容，补 fill 后再 finish")
        sys.exit(2)
    if gate_problems(doc, st):
        print("FAIL 复核门禁未过：先 detail.py recheck（工商与原件识别不一致）或重提 stale 的派生行，再 finish")
        sys.exit(3)
    print("PASS 明细完整（%d 条，无待填）；unresolvedProperties %d 行" % (len(doc["items"]), len(doc["notes"]["unresolvedProperties"])))
    print(RELEASE_MARKER)


def cmd_show(a):
    doc, st = load_detail(a.rid)
    if a.pending:
        report(a.rid, doc, st)
        return
    for x in doc["items"]:
        src = x["source"]
        st = src[:1] if src[:2] in ("Y｜", "N｜") else "-"
        print("%s|%s|%s|%s|%s" % (x["id"], x["name"], "(空)" if x["value"] is None else x["value"], st, (src[2:] if st != "-" else "待填")[:120]))


def cmd_compare(a):
    doc, st = load_detail(a.rid)
    by = {x["id"]: x for x in doc["items"]}
    rc = st.get("rechecked") or {}
    names = {"same": "一致", "diff": "不一致", "na": "无法比较（任一侧没有值）"}
    print("COMPARE 工商与原件识别逐项比对（%d 项；前 %d 项即 J34）" % (len(PAIRS), J34_PAIRS))
    for o, b, l, k, status in pair_rows(doc):
        tail = ""
        if o in rc:
            tail = "｜已复核：" + OUTCOME_LABEL.get(rc[o]["outcome"], rc[o]["outcome"])
        short = lambda v: v if v is None or len(v) <= 40 else v[:40] + "…"
        print("%s|%s|%s|原件 %s=%s|工商 %s=%s%s" % (o, l, names[status], o, short(by[o]["value"]), b, short(by[b]["value"]), tail))
    for ln in recheck_lines(doc, st):
        print(ln)
    rp = recheck_pending(doc, st)
    if rp:
        print("待复核 %d 项：回看原件对应栏位（PDF 到页码）重新识别一次，用 recheck 提交。" % len(rp))
        sys.exit(3)
    print("OK 没有待复核项")


def cmd_recheck(a):
    """工商与原件识别不一致时，回看原件二次识别后提交。每项只复核一次。
    二次识别 = 首次 → 确认不一致：保留原件值，在 source 追加复核记录，冲突说明标「已二次识别确认」，不用工商值覆盖；
    二次识别 ≠ 首次且 = 工商 → 首次识别有误：更正为二次识别值；
    二次识别 ≠ 首次且 ≠ 工商 → 两次识别不一致：该项置 N R06，不取值；
    二次识别仍无法确认（value=null）→ 该项置 N，不取值。"""
    doc, st = load_detail(a.rid)
    spec = read_stdin("recheck", a.rid)
    by = {x["id"]: x for x in doc["items"]}
    pairs = {p[0]: p for p in PAIRS}
    status = {p[0]: p[4] for p in pair_rows(doc)}
    before = snapshot(doc)
    errs, done, lines = [], [], []
    for r in spec.get("rows") or []:
        if not (isinstance(r, list) and len(r) == 3):
            errs.append("行格式应为 [原件条目ID, 二次识别值|null, text]: %s" % json.dumps(r, ensure_ascii=False)[:80])
            continue
        oid, v2, text = r
        if oid not in pairs:
            errs.append("%s 不在比对清单里（可复核的条目：%s）" % (oid, "、".join(pairs)))
            continue
        if oid in st["rechecked"]:
            errs.append("%s 已经复核过一次，不再复核（每项只复核一次）" % oid)
            continue
        if status[oid] != "diff":
            errs.append("%s 与工商一致或任一侧没有值，无需复核" % oid)
            continue
        if not isinstance(text, str) or not text.strip():
            errs.append("%s 的 text 为空" % oid)
            continue
        text = PREFIX_RE.sub("", text.strip(), count=1)
        _, biz, label, kind = pairs[oid]
        o, b = by[oid], by[biz]
        v1, bv = o["value"], b["value"]
        if v2 is None:
            if not N_RE.fullmatch(text):
                errs.append("%s 二次仍无法确认时 text 须为「Rxx｜具体原因」；你写的是：%s" % (oid, text[:60]))
                continue
            code, why = text.split("｜", 1)
            o["value"], o["source"] = None, "N｜%s｜首次识别为「%s」，与工商 %s=「%s」不一致，二次复核无法确认（%s），不取值" % (code, v1, biz, bv, why)
            outcome = "unreadable"
            conflict = "%s：首次识别「%s」与工商 %s「%s」不一致，二次复核无法确认，均未作为已核实" % (label, v1, biz, bv)
        else:
            if not isinstance(v2, str) or not v2.strip():
                errs.append("%s 的二次识别值须为非空字符串或 null" % oid)
                continue
            if "｜" not in text:
                errs.append("%s 有值时 text 须为「来源｜证据」，证据写二次识别时原件栏位的原文" % oid)
                continue
            ev = text.split("｜", 1)[1]
            conflict = None
            if same_reading(kind, v2, v1):
                outcome = "confirmed_diff"
                o["source"] = o["source"] + "；复核：二次识别（%s）与首次一致，与工商 %s=「%s」不同，确认不一致，保留原件识别值，未用工商值覆盖" % (ev[:80], biz, bv)
            elif same_fact(kind, v2, bv):
                outcome = "corrected"
                o["value"], o["source"] = v2, "Y｜%s；复核：首次识别为「%s」有误，二次识别更正，与工商 %s 一致" % (text, v1, biz)
            else:
                outcome = "unstable"
                o["value"], o["source"] = None, "N｜R06｜两次识别不一致（首次「%s」，二次「%s」），且都与工商 %s=「%s」不符，无法确定，不取值" % (v1, v2, biz, bv)
                conflict = "%s：两次识别不一致（首次「%s」，二次「%s」），工商 %s「%s」，均未作为已核实" % (label, v1, v2, biz, bv)
        st["rechecked"][oid] = {"outcome": outcome, "first": v1, "second": v2}
        if conflict:
            st["rechecked"][oid]["conflict"] = conflict
        done.append(oid)
        lines.append("%s %s：%s" % (oid, label, OUTCOME_LABEL[outcome]))
    st["derived"] = [i for i in st.get("derived", []) if i not in done]
    pend, miss_mat = finalize(a.rid, doc, st)
    mark_stale(doc, st, before, done)
    save_state(a.rid, st)
    for e in errs:
        print("REJECT " + e)
    if lines:
        print("复核结果：" + "；".join(lines))
    print("已处理 %d 项，被拒 %d 项" % (len(done), len(errs)))
    report(a.rid, doc, st)
    if not pend and not miss_mat and not errs and not gate_problems(doc, st):
        print("PASS 复核完成，明细完整（%d 条，无待填）。可以运行 combine.py build" % len(doc["items"]))
        print(RELEASE_MARKER)
    sys.exit(1 if errs else 0)


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

USAGE = 'init --biz <工商文件>... --rules <规则文件>...（init 不带 --rid，requestId 从 stdin ctx 取）；fill/finish/show/compare/recheck --rid <requestId>；例 args=["init","--biz","文件1","文件2","文件3","--rules","规则文件1","机构规则文件"]'


def main():
    ArgParser.usage_hint = USAGE
    ap = ArgParser()
    sp = ap.add_subparsers(dest="cmd", required=True, parser_class=ArgParser)
    i = sp.add_parser("init")
    i.add_argument("--rid", default=None)  # 兼容模型多写；以 stdin ctx.requestId 为准
    i.add_argument("--biz", nargs="*", default=[])
    i.add_argument("--rules", nargs="+")
    f = sp.add_parser("fill")
    f.add_argument("--rid", required=True)
    f.add_argument("--force", action="store_true")
    n = sp.add_parser("finish")
    n.add_argument("--rid", required=True)
    w = sp.add_parser("show")
    w.add_argument("--rid", required=True)
    w.add_argument("--pending", action="store_true")
    c = sp.add_parser("compare")
    c.add_argument("--rid", required=True)
    rc_ = sp.add_parser("recheck")
    rc_.add_argument("--rid", required=True)
    a = ap.parse_args(repair_argv(sys.argv[1:], "detail.py", USAGE))
    for k in ("biz", "rules"):  # 多文件参数：逗号拼接也拆开（路径不含逗号）
        if isinstance(getattr(a, k, None), list):
            setattr(a, k, [x.strip() for f in getattr(a, k) for x in f.split(",") if x.strip()])
    {"init": cmd_init, "fill": cmd_fill, "finish": cmd_finish, "show": cmd_show,
     "compare": cmd_compare, "recheck": cmd_recheck}[a.cmd](a)


if __name__ == "__main__":
    main()
