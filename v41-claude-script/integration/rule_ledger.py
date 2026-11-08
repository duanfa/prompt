"""Backend reference: derive counts and render both summaries from trusted rules.

Call in process, after receiving the untruncated engine response. The model must
never supply the `response` argument. This module is not a runtime Skill/script.
"""

import hashlib
import json
import re
from collections import Counter


CATEGORIES = (
    "准入基本标准", "禁入及限制行业", "准入资料", "业务核查与审核留痕", "其他"
)


class LedgerError(ValueError):
    pass


# false whose reason says an attribute/object is absent MAY not have been evaluated.
# v26: that depends on the expression shape.
#   * top level is only AND: any conjunct reported as "不满足 …" was evaluated (its attribute was
#     supplied) and failed, so the whole AND is false whatever the missing conjuncts are -> determined.
#   * single clause / OR / mixed top level / no expression: a missing part could still have made it
#     true -> insufficient (conservative).
_MISSING_RE = re.compile(r"(属性|对象)不存在")
_FAILED_RE = re.compile(r"不满足")
INSUFFICIENT_LABEL = "未触发（所需属性未取得，未据此核实）"


def _top_level_connectives(expr):
    """Connectives ('AND'/'OR') that sit outside (), {}, [] and quotes."""
    found, depth, quote, i = set(), 0, None, 0
    while i < len(expr):
        ch = expr[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        elif depth == 0 and ch == " ":
            m = re.match(r" (AND|OR) ", expr[i:])
            if m:
                found.add(m.group(1))
                i += len(m.group(0)) - 1
        i += 1
    return found


def is_insufficient(state, reason, expression=None):
    if not (state == "false" and isinstance(reason, str) and _MISSING_RE.search(reason)):
        return False
    if isinstance(expression, str) and _top_level_connectives(expression) == {"AND"} \
            and _FAILED_RE.search(reason):
        return False
    return True


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def result_state(value):
    # bool is a subclass of int: do not accept 0/1 as false/true.
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str and value in {"true", "false", "skip"}:
        return value
    raise LedgerError("INVALID_RESULT_STATE")


def build_ledger(response, *, engine_call_id, request_id, input_snapshot,
                 complete, ok_code=0, category_by_rule=None):
    """`complete` must come from transport, not the model or a preview file."""
    if complete is not True:
        raise LedgerError("ENGINE_RESULT_INCOMPLETE")
    if not isinstance(response, dict) or type(response.get("code")) is not type(ok_code) \
            or response.get("code") != ok_code:
        raise LedgerError("ENGINE_RESULT_NOT_OK")
    if not isinstance(request_id, str) or not request_id \
            or response.get("requestId") != request_id:
        raise LedgerError("REQUEST_ID_MISMATCH")
    if not isinstance(engine_call_id, str) or not engine_call_id:
        raise LedgerError("ENGINE_CALL_ID_REQUIRED")
    if not isinstance(input_snapshot, dict):
        raise LedgerError("INPUT_SNAPSHOT_REQUIRED")
    data = response.get("data")
    rules = data.get("ruleCheckList") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        raise LedgerError("RULE_LIST_REQUIRED")
    normalized, seen = [], set()
    category_by_rule = category_by_rule or {}
    for row in rules:
        if not isinstance(row, dict):
            raise LedgerError("INVALID_RULE_ENTRY")
        rid = row.get("ruleId")
        if not isinstance(rid, str) or not rid.strip():
            raise LedgerError("INVALID_RULE_ID")
        if rid in seen:
            raise LedgerError("DUPLICATE_RULE_ID: " + rid)
        seen.add(rid)
        state = result_state(row.get("result"))
        category = category_by_rule.get(rid, "其他")
        if category not in CATEGORIES:
            raise LedgerError("INVALID_SERVER_CATEGORY: " + rid)
        normalized.append({"ruleId": rid, "result": state,
                           "category": category,
                           "insufficient": is_insufficient(state, row.get("reason"), row.get("expression")),
                           **{k: row.get(k) for k in
                              ("ruleName", "ruleSource", "expression", "reason")}})
    counts = Counter(row["result"] for row in normalized)
    return {
        "contract": "admission-rule-ledger-v1",
        "requestId": request_id, "engineCallId": engine_call_id,
        "inputSha256": digest(input_snapshot), "responseSha256": digest(response),
        "stats": {"total": len(normalized),
                  "determined": counts["true"] + counts["false"],
                  "true": counts["true"], "false": counts["false"],
                  "skip": counts["skip"],
                  "falseInsufficient": sum(1 for r in normalized if r["insufficient"])},
        "rules": normalized,
    }


def finalize(response, draft, *, engine_call_id, request_id, input_snapshot,
             complete, ok_code=0, category_by_rule=None):
    """Rebuild the ledger from a server-held response, validate, then render.

    Returns only internal artifacts; merge summary fields into the existing
    final schema in the server hook. Store the other artifacts in the workspace.
    Counts and public/debug prose are never taken from a model's rendered text.
    """
    ledger = build_ledger(response, engine_call_id=engine_call_id,
                          request_id=request_id, input_snapshot=input_snapshot,
                          complete=complete, ok_code=ok_code,
                          category_by_rule=category_by_rule)
    if not isinstance(draft, dict) or draft.get("engineCallId") != engine_call_id \
            or draft.get("responseSha256") != ledger["responseSha256"] \
            or draft.get("inputSha256") != ledger["inputSha256"]:
        raise LedgerError("DRAFT_SNAPSHOT_MISMATCH")
    groups = draft.get("groups")
    if not isinstance(groups, list):
        raise LedgerError("GROUPS_REQUIRED")
    all_rules = {r["ruleId"]: r for r in ledger["rules"]}
    expected = {rid for rid, row in all_rules.items() if row["result"] != "skip"}
    covered = set()
    ordered = {(cat, state, basis): [] for cat in CATEGORIES
               for state in ("true", "false") for basis in ("determined", "insufficient")}
    for group in groups:
        if not isinstance(group, dict):
            raise LedgerError("INVALID_GROUP")
        cat, state = group.get("category"), group.get("result")
        basis = group.get("basis", "determined")
        if not isinstance(cat, str) or not isinstance(state, str) \
                or not isinstance(basis, str) or (cat, state, basis) not in ordered:
            raise LedgerError("INVALID_CATEGORY_OR_DIRECTION")
        ids, text = group.get("ruleIds"), group.get("text")
        if not isinstance(ids, list) or not ids:
            raise LedgerError("GROUP_RULE_IDS_REQUIRED")
        if not isinstance(text, str) or not text.strip() \
                or any(c in text for c in ("\n", "\r", "【", "】")):
            raise LedgerError("INVALID_GROUP_TEXT")
        if any(rid in text for rid in all_rules):
            raise LedgerError("RULE_ID_IN_PUBLIC_TEXT")
        for rid in ids:
            if not isinstance(rid, str) or rid not in all_rules:
                raise LedgerError("UNKNOWN_RULE_ID: " + str(rid))
            if rid in covered:
                raise LedgerError("DUPLICATE_COVERAGE: " + rid)
            if rid not in expected:
                raise LedgerError("SKIP_RULE_REFERENCED: " + rid)
            if all_rules[rid]["result"] != state:
                raise LedgerError("WRONG_DIRECTION: " + rid)
            if all_rules[rid]["category"] != cat:
                raise LedgerError("WRONG_CATEGORY: " + rid)
            if ("insufficient" if all_rules[rid]["insufficient"] else "determined") != basis:
                raise LedgerError("WRONG_BASIS: " + rid)
            covered.add(rid)
        ordered[(cat, state, basis)].append((text.strip(), ids))
    missing = expected - covered
    if missing:
        raise LedgerError("MISSING_RULE_IDS: " + ",".join(sorted(missing)))
    counts = ledger["stats"]
    if counts["determined"]:
        extra = (f"，其中{counts['falseInsufficient']}条因所需属性未取得而未触发、未据此核实"
                 if counts["falseInsufficient"] else "")
        header = (f"本次共{counts['determined']}条规则给出明确结果"
                  f"（命中{counts['true']}条、未命中{counts['false']}条{extra}）。")
        public, debug = [header], [header + "【来源：全部已判定规则】"]
        for cat in CATEGORIES:
            if not any(ordered[(cat, s, b)] for s in ("true", "false")
                       for b in ("determined", "insufficient")):
                continue
            plain_parts, debug_parts = [], []
            for state, basis, label, optional in (
                    ("true", "determined", "命中", False),
                    ("false", "determined", "未命中", False),
                    ("false", "insufficient", INSUFFICIENT_LABEL, True)):
                items = ordered[(cat, state, basis)]
                if optional and not items:
                    continue
                plain_parts.append(label + "：" + ("；".join(t for t, _ in items) or "无"))
                debug_parts.append(label + "：" + ("；".join(
                    t + "【来源：" + "、".join(ids) + "】" for t, ids in items) or "无"))
            public.append("【" + cat + "】" + "。".join(plain_parts) + "。")
            debug.append("【" + cat + "】" + "。".join(debug_parts) + "。")
        summary, summary_debug = "\n\n".join(public), "\n\n".join(debug)
    else:
        summary = "无已判定（true/false）的规则"
        summary_debug = summary + "【来源：无】"
    return {"ledger": ledger, "summary": summary, "summary_debug": summary_debug,
            "validation": {"passed": True, "covered": len(covered),
                           "engineCallId": engine_call_id,
                           "responseSha256": ledger["responseSha256"],
                           "inputSha256": ledger["inputSha256"],
                           "draftSha256": digest(draft),
                           "missing": [], "duplicate": [], "wrongDirection": []}}
