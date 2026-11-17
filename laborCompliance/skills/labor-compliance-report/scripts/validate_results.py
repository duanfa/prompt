#!/usr/bin/env python3
"""Validate the three SQL calculation result tables. Python 3.9+."""

import calendar
import json
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

CUSTOMERS = "dws_lgw_risk_customer_warn_sum"
WORKERS = "dws_lgw_risk_worker_warn_detail"
EVIDENCE = "dwd_lgw_risk_worker_warn_month_evidence"
TABLES = (CUSTOMERS, WORKERS, EVIDENCE)
OPTIONAL = {"handler", "check_conclusion", "check_basis", "close_time"}
SCHEMA = Path(__file__).resolve().parents[1] / "references/result-schema.json"


def need(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    need(not isinstance(value, bool) and isinstance(value, (str, int, float, Decimal)),
         f"无法评估：金额或比率不是有效数字：{value!r}")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"无法评估：非法数字 {value!r}") from exc
    need(result.is_finite(), "无法评估：不接受 NaN 或 Infinity")
    return result


def months_between(start, end):
    for value in (start, end):
        need(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value),
             f"无法评估：月份格式错误 {value!r}")
        datetime.strptime(value, "%Y-%m")
    first = int(start[:4]) * 12 + int(start[5:]) - 1
    last = int(end[:4]) * 12 + int(end[5:]) - 1
    need(0 <= last - first <= 120, "无法评估：观察期倒置或超出支持范围")
    return [f"{n // 12:04d}-{n % 12 + 1:02d}" for n in range(first, last + 1)]


def validate(payload):
    """Reject unusable schemas; retain upstream values and disclose evidence issues."""
    need(isinstance(payload, dict), "响应必须是包含三张结果表的 JSON 对象")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for table in TABLES:
        need(table in payload and isinstance(payload[table], list), f"缺少结果数组：{table}")
        for index, row in enumerate(payload[table]):
            label = f"{table}[{index}]"
            need(isinstance(row, dict), f"{label} 必须是对象")
            missing = set(schema[table]) - set(row)
            need(not missing, f"{label} 缺少 SQL 字段：{sorted(missing)}")
            for field, spec in schema[table].items():
                value, kind = row[field], spec["type"]
                if field in OPTIONAL and value is None:
                    continue
                need(value is not None, f"无法评估：{label}.{field} 为 null，不能按零处理")
                if kind == "BIGINT":
                    need(type(value) is int and value >= 0, f"{label}.{field} 必须是非负整数")
                elif kind.startswith("DECIMAL"):
                    need(number(value) >= 0, f"{label}.{field} 必须是非负定点数")
                else:
                    need(isinstance(value, str), f"{label}.{field} 必须是字符串")
                    if kind == "DATETIME":
                        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            need(re.fullmatch(r"\d{8}", row["ds"]), f"{label}.ds 应为 yyyyMMdd")
            datetime.strptime(row["ds"], "%Y%m%d")
            for field in ("customer_id", "currency", "rule_version"):
                need(row[field].strip(), f"{label}.{field} 不能为空")
            for field in ("is_customer_warn", "is_upgraded", "has_pay_flag"):
                if field in row:
                    need(row[field] in ("0", "1"), f"{label}.{field} 必须为字符串 0/1")

    snapshots = {(r["ds"], r["rule_version"]) for t in TABLES for r in payload[t]}
    need(len(snapshots) <= 1, "无法评估：混入多个评估批次或规则版本，请分别生成报告")
    need(all(version == "V1.0" for _, version in snapshots), "当前规则说明仅支持V1.0，请先提供其他版本的规则定义")
    customers, workers, evidence = (payload[t] for t in TABLES)
    customer_map = {}
    for row in customers:
        key = (row["customer_id"], row["currency"])
        need(key not in customer_map, f"客户汇总重复：{key}")
        customer_map[key] = row
    worker_map, people = {}, set()
    for row in workers:
        need(row["warn_id"].strip() and row["worker_id"].strip(), "预警ID及灵工ID不能为空")
        need(row["warn_id"] not in worker_map, f"预警ID重复：{row['warn_id']}")
        key = (row["customer_id"], row["worker_id"], row["currency"])
        need(key not in people, f"人员重复（R01/R02 应只保留主要规则）：{key}")
        need((row["customer_id"], row["currency"]) in customer_map,
             f"人员预警找不到对应客户汇总：{row['warn_id']}")
        need(row["main_rule"] in ("R01", "R02"), f"未知主要规则：{row['main_rule']}")
        worker_map[row["warn_id"]] = row
        people.add(key)
    grouped, seen = defaultdict(list), set()
    for row in evidence:
        key = (row["warn_id"], row["obs_month"])
        need(key not in seen, f"月度证据重复：{key}")
        need(row["warn_id"] in worker_map, f"存在孤立月度证据：{key}")
        owner = worker_map[row["warn_id"]]
        need(all(row[k] == owner[k] for k in ("customer_id", "worker_id", "currency")),
             f"月度证据关联对象不一致：{key}")
        months_between(row["obs_month"], row["obs_month"])
        seen.add(key)
        grouped[row["warn_id"]].append(row)

    issues = []

    def check(condition, message):
        if not condition:
            issues.append(message)

    def close_check(row, label):
        check(row["warn_status"] in ("待核查", "核查中", "已关闭"), f"{label} 核查状态不在约定枚举内")
        if row["warn_status"] == "已关闭":
            check(all(row[k] and row[k].strip() for k in OPTIONAL),
                  f"{label} 已关闭但负责人、结论、依据或关闭时间不全")
            check(row["check_conclusion"] in ("存在风险", "合理业务场景", "证据不足"),
                  f"{label} 已关闭但核查结论无效")

    for row in customers:
        key = (row["customer_id"], row["currency"])
        label = "/".join(key)
        related = [w for w in workers if (w["customer_id"], w["currency"]) == key]
        u, h = row["total_worker_cnt"], row["regular_worker_cnt"]
        check(0 <= row["r02_worker_cnt"] <= h <= u, f"{label} 不满足 R02人数≤H≤U")
        check(h == len(related) and row["r02_worker_cnt"] == sum(w["main_rule"] == "R02" for w in related),
              f"{label} 汇总人数与完整人员明细不一致，可能漏页或漏数据")
        if u > 0:
            check(abs(number(row["hit_worker_ratio"]) - Decimal(h) / u) <= Decimal("0.0000005"),
                  f"{label} 命中占比与 H/U 不一致")
            expected = h >= row["worker_cnt_threshold"] and Decimal(h) / u >= number(row["ratio_threshold"])
            check((row["is_customer_warn"] == "1") == expected, f"{label} R03 结果与参数快照不一致")
        else:
            issues.append(f"{label} U=0，H/U 无法评估，不将其解释为无风险")
        check(len(months_between(row["obs_start_month"], row["obs_end_month"])) == 3,
              f"{label} R03 观察期不是连续3个月")
        evaluation_month = f"{row['ds'][:4]}-{row['ds'][4:6]}"
        check(len(months_between(row["obs_end_month"], evaluation_month)) == 2,
              f"{label} 截止月不是评估日前一个完整自然月")
        check(number(row["involved_amount"]) >= sum((number(w["total_amount_3m"]) for w in related), Decimal(0)),
              f"{label} 客户全量金额小于预警人员金额，需核对金额范围")
        close_check(row, label)

    for row in workers:
        label = row["warn_id"]
        months = months_between(row["obs_start_month"], row["obs_end_month"])
        expected_count = 6 if row["main_rule"] == "R02" else 3
        check(row["cover_month_cnt"] == len(months) == expected_count, f"{label} 规则、覆盖月数、观察期不一致")
        customer = customer_map[(row["customer_id"], row["currency"])]
        check(row["obs_end_month"] == customer["obs_end_month"], f"{label} 与客户观察期截止月不一致")
        check(row["priority"] == ("重点" if row["main_rule"] == "R02" else "普通"), f"{label} 人员优先级与主要规则不一致")
        check(1 <= row["anchor_day"] <= 31, f"{label} 固定发放日不在1至31日内")
        monthly = sorted(grouped[label], key=lambda x: x["obs_month"])
        check([e["obs_month"] for e in monthly] == months, f"{label} 月度证据缺失或超出观察期，无法核实连续性")
        check([e["obs_month_seq"] for e in monthly] == list(range(1, len(months) + 1)), f"{label} 月序不连续")
        for e in monthly:
            month = e["obs_month"]
            amount, window_amount = number(e["month_amount"]), number(e["window_amount"])
            check(e["has_pay_flag"] == "1" and amount > 0 and e["pay_cnt"] > 0,
                  f"{label}/{month} 无有效发放，不能支持连续命中")
            check(0 <= window_amount <= amount, f"{label}/{month} 窗口金额超出月金额")
            check(Decimal(0) <= number(e["window_ratio"]) <= 1, f"{label}/{month} 窗口占比超出0至1")
            if amount > 0:
                check(abs(number(e["window_ratio"]) - window_amount / amount) <= Decimal("0.0000005"),
                      f"{label}/{month} 窗口占比与金额不一致")
            end_day = calendar.monthrange(int(month[:4]), int(month[5:]))[1]
            anchor = min(row["anchor_day"], end_day)
            check(e["anchor_day"] == anchor and e["window_start"] == max(1, anchor - row["window_days"])
                  and e["window_end"] == min(end_day, anchor + row["window_days"]),
                  f"{label}/{month} 锚点或日期窗口不符合参数快照")
        if monthly:
            minimum = min(number(e["month_amount"]) for e in monthly)
            maximum = max(number(e["month_amount"]) for e in monthly)
            check(minimum == number(row["month_amount_min"]) and maximum == number(row["month_amount_max"]),
                  f"{label} 最高/最低月金额与证据不一致")
            if minimum > 0:
                check(abs(number(row["volatility"]) - (maximum - minimum) / minimum) <= Decimal("0.0000005"),
                      f"{label} 波动率与证据不一致")
            check(min(number(e["window_ratio"]) for e in monthly) == number(row["min_window_ratio"]),
                  f"{label} 最低窗口占比与证据不一致")
            recent_months = set(months_between(customer["obs_start_month"], customer["obs_end_month"]))
            check(sum((number(e["month_amount"]) for e in monthly if e["obs_month"] in recent_months), Decimal(0))
                  == number(row["total_amount_3m"]), f"{label} 近3月金额与证据不一致")
        check(number(row["volatility"]) <= number(row["amount_tolerance"]), f"{label} 金额波动率超出容差快照")
        check(number(row["min_window_ratio"]) >= Decimal("0.80"), f"{label} 最低窗口占比不足V1.0的80%")
        close_check(row, label)
    return issues, grouped

