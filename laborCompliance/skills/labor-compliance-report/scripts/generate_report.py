#!/usr/bin/env python3
"""Fill the bundled Excel template from three SQL result tables. Python 3.9+."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen
from xml.dom.minidom import parseString
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
# WanScope runs installed scripts with python -I, which omits the script directory.
# Load scripts and dependencies from the installed skill.
sys.path[:0] = [str(HERE), str(SKILL / "vendor")]
from validate_results import CUSTOMERS, EVIDENCE, WORKERS, need, validate
from exec_results import FIXED_TASKS, TASKS, excel_scalar, load_manifest

VERSION = "labor-compliance-excel-v1-4-5"
EVIDENCE_ID_COLUMNS = ("exec_id", "etl_batch_no", "warn_id", "rule_version", "customer_id", "worker_id")
EVIDENCE_MONTH_COLUMNS = ("obs_month", "month_amount", "anchor_day", "window_start", "window_end",
                          "window_amount", "window_ratio")
EVIDENCE_HEADERS = dict(zip(EVIDENCE_ID_COLUMNS + EVIDENCE_MONTH_COLUMNS, (
    "执行ID", "数据批次号", "预警ID", "规则版本", "客户ID", "灵工ID", "观察月份",
    "月金额（元）", "当月锚定日", "窗口起始日", "窗口截止日", "窗口金额（元）", "窗口占比",
)))
CUSTOMER_COLUMNS = (
    ("客户ID", "customer_id"), ("客户名称", "customer_name"), ("发放人数U", "total_worker_cnt"),
    ("规律人数H", "regular_worker_cnt"), ("命中占比", "hit_worker_ratio"), ("R02人数", "r02_worker_cnt"),
    ("涉及金额(元)", "involved_amount"), ("客户预警", "is_customer_warn"),
)
CUSTOMER_REVIEW_COLUMNS = ("核查优先级", "列1", "列2", "列3", "列12")
CUSTOMER_NUMBER_FORMATS = {"命中占比": "0.00%", "涉及金额(元)": "#,##0.00"}
WORKER_COLUMNS = (
    ("预警ID", "warn_id"), ("客户ID", "customer_id"), ("客户名称", "customer_name"),
    ("灵工ID", "worker_id"), ("脱敏姓名", "worker_name_masked"), ("主要规则", "main_rule"),
    ("优先级", "priority"), ("覆盖月数", "cover_month_cnt"), ("金额波动率", "volatility"),
    ("近3月累计应发金额(元)", "total_amount_3m"), ("固定发放日（系统识别）", "anchor_day"),
    ("固定发放比例（%）", "min_window_ratio"),
)
WORKER_REVIEW_COLUMNS = ("列1", "列2", "列3", "列4", "列5")
WORKER_NUMBER_FORMATS = {"金额波动率": "0.00%", "近3月累计应发金额(元)": "#,##0.00",
                         "固定发放比例（%）": "0.00%"}
REPORT_TIMEZONE = timezone(timedelta(hours=8))
FIXED_HEADER_ROW = 1


def worker_evidence_links(workers, evidence, groups, header_row):
    first_data_row = header_row + 1
    def key(warn_id, customer_id, worker_id):
        values = (warn_id, customer_id, worker_id)
        if all(type(value) in (str, int) and value != "" for value in values):
            return tuple(str(value) for value in values)
        return None

    destinations = {}
    for first, _ in groups:
        row = evidence[first]
        identity = key(row["warn_id"], row["customer_id"], row["worker_id"])
        if identity is not None:
            destinations.setdefault(identity, f"'月度证据'!C{first + first_data_row}")

    links = {}
    for index, row in enumerate(workers, first_data_row):
        identity = key(row["预警ID"], row["客户ID"], row["灵工ID"])
        if identity in destinations:
            links[f"A{index}"] = destinations[identity]
    return links


def fixed_report_metadata(jobs):
    calculated_at = None
    for job in jobs.values():
        for row in job["rows"]:
            value = row.get("etl_time")
            if not isinstance(value, str):
                continue
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            stamp = stamp.astimezone(REPORT_TIMEZONE) if stamp.tzinfo else stamp.replace(tzinfo=REPORT_TIMEZONE)
            if calculated_at is None or stamp > calculated_at:
                calculated_at = stamp
    if calculated_at is None:
        calculated_at = datetime.now(REPORT_TIMEZONE)

    run_month = calculated_at.year * 12 + calculated_at.month - 1
    end_year, end_month = divmod(run_month - 1, 12)

    def period(months, include_year):
        start_year, start_month = divmod(run_month - months, 12)
        if start_year != end_year:
            return f"{start_year}年{start_month + 1}月—{end_year}年{end_month + 1}月"
        year = f"{start_year}年" if include_year else ""
        return f"{year}{start_month + 1}—{end_month + 1}月"

    return {"reportDate": calculated_at.strftime("%Y-%m-%d\n%H:%M:%S"),
            "period": f"{period(3, True)}；R02扩展至{period(6, False)}", "rule": "V1.0 / 人民币 CNY"}


def customer_warning(value):
    if value in (1, "1"):
        return "R03命中"
    if value in (0, "0"):
        return "未命中"
    return None


def fixed_summary(customers, workers):
    missing = "未提供"
    customer_ids = [row.get("customer_id") for row in customers]
    warnings = [(row.get("customer_id"), customer_warning(row.get("is_customer_warn"))) for row in customers]
    by_rule = {rule: [row for row in workers if row.get("main_rule") == rule] for rule in ("R01", "R02")}

    def count_pairs(rows):
        pairs = [(row.get("customer_id"), row.get("worker_id")) for row in rows]
        return len(set(pairs)) if all(valid_id(customer) and valid_id(worker) for customer, worker in pairs) else missing

    def valid_id(value):
        return type(value) in (str, int) and value != ""

    amount = missing
    r01 = by_rule["R01"]
    if all(row.get("currency") == "CNY" for row in r01):
        try:
            amounts = [Decimal(str(row.get("total_amount_3m"))) for row in r01]
            if all(value.is_finite() for value in amounts):
                amount = excel_scalar(sum(amounts, Decimal("0.00")))
        except InvalidOperation:
            pass

    all_customers = len(set(customer_ids)) if all(map(valid_id, customer_ids)) else missing
    r03 = (len({customer for customer, flag in warnings if flag == "R03命中"})
           if all_customers != missing and all(flag for _, flag in warnings) else missing)
    r01_count, r02_count = (count_pairs(by_rule[rule]) for rule in ("R01", "R02"))
    if any(row.get("main_rule") not in ("R01", "R02") for row in workers):
        r01_count = r02_count = amount = missing
    return [("已评估客户", all_customers), ("客户聚集预警", r03), ("客户－灵工预警数", r01_count),
            ("重点人员预警数", r02_count), ("涉及金额（近3月，元）", amount)]


def formatted_number(value):
    if isinstance(value, str):
        try:
            number = Decimal(value)
        except InvalidOperation:
            return value
        if number.is_finite():
            return excel_scalar(number)
    return value


def project_rows(job, columns, review_columns, number_formats):
    rows = []
    for record in job["rows"]:
        row = {label: record.get(field) for label, field in columns}
        for label in number_formats:
            row[label] = formatted_number(row[label])
        rows.append(row)
    job["rows"] = rows
    return {"columns": tuple(label for label, _ in columns) + review_columns,
            "blankColumns": review_columns, "numberFormats": number_formats}


def project_customer_rows(job):
    view = project_rows(job, CUSTOMER_COLUMNS, CUSTOMER_REVIEW_COLUMNS, CUSTOMER_NUMBER_FORMATS)
    for row in job["rows"]:
        row["客户预警"] = customer_warning(row["客户预警"])
    return view


def read_result_file(filename, wrapped=False, expected_sha256=None, expected_bytes=None):
    """Read the platform's original bytes and verify its manifest when supplied."""
    raw = Path(filename).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None:
        need(re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256), "expected-sha256 必须是64位十六进制")
        need(digest == expected_sha256.lower(), "输入文件 SHA-256 与 MCP 文件清单不符，停止生成")
    if expected_bytes is not None:
        need(expected_bytes >= 0 and len(raw) == expected_bytes, "输入文件字节数与 MCP 文件清单不符，停止生成")
    response = json.loads(raw.decode("utf-8"))
    payload = read_mcp_result(response) if wrapped else response
    return payload, {"path": str(filename), "bytes": len(raw), "sha256": digest,
                     "integrity_verified": expected_sha256 is not None,
                     "size_verified": expected_bytes is not None}


def data_summary(payload):
    """Summarize validated snapshots with exact decimals and separate currencies."""
    customers, workers = payload[CUSTOMERS], payload[WORKERS]
    first = next(iter(customers or workers), None)
    amounts = {}
    for currency in sorted({r["currency"] for r in customers}):
        amounts[currency] = {
            "customer_involved_amount": format(sum((Decimal(str(r["involved_amount"])) for r in customers
                                                    if r["currency"] == currency), Decimal(0)), ".2f"),
            "warned_worker_amount_3m": format(sum((Decimal(str(r["total_amount_3m"])) for r in workers
                                                  if r["currency"] == currency), Decimal(0)), ".2f"),
        }
    return {"ds": first["ds"] if first else None,
            "rule_version": first["rule_version"] if first else None,
            "customer_warn_count": sum(r["is_customer_warn"] == "1" for r in customers),
            "r02_worker_warn_count": sum(r["main_rule"] == "R02" for r in workers),
            "amounts_by_currency": amounts}


def read_url(url):
    need(urlsplit(url).scheme in ("http", "https"), "接口地址必须使用 http/https")
    with urlopen(url, timeout=20) as response:
        need(response.status == 200, f"接口未成功返回：HTTP {response.status}")
        return json.loads(response.read().decode("utf-8")), response.headers.get("X-Mock-Data", "").lower() == "true"


def read_mcp_result(response):
    """Unwrap a saved CallToolResult or JSON-RPC response without hiding errors."""
    need(isinstance(response, dict), "MCP 返回必须是 JSON 对象")
    need("error" not in response, f"MCP 调用失败：{response.get('error')}")
    if "jsonrpc" in response:
        need(response["jsonrpc"] == "2.0" and "result" in response, "MCP JSON-RPC 响应缺少有效 result")
        response = response["result"]
    need(isinstance(response, dict), "MCP result 必须是 JSON 对象")
    need("error" not in response, f"MCP 调用失败：{response.get('error')}")
    flag = response.get("isError", False)
    need(type(flag) is bool, "MCP isError 必须是布尔值")
    if flag:
        content = response.get("content", [])
        message = "；".join(block.get("text", "") for block in content
                           if isinstance(block, dict) and isinstance(block.get("text"), str)) if isinstance(content, list) else ""
        raise ValueError("MCP 调用失败：" + (message[:1000] or "isError=true"))
    if "structuredContent" in response:
        payload = response["structuredContent"]
        need(isinstance(payload, dict), "MCP structuredContent 必须是三表 JSON 对象")
        return payload
    content = response.get("content")
    need(isinstance(content, list), "MCP 返回缺少 structuredContent 或 content 数组")
    candidates = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
            continue
        try:
            payload = json.loads(block["text"])
        except ValueError:
            continue
        if isinstance(payload, dict) and all(table in payload for table in (CUSTOMERS, WORKERS, EVIDENCE)):
            candidates.append(payload)
    need(len(candidates) == 1, "MCP content 必须包含且仅包含一份完整三表 JSON；摘要或截断文本不能生成报告")
    return candidates[0]


def runtime_paths(node=None, modules=None, config=None):
    settings = {}
    config = Path(config).resolve() if config else SKILL / "runtime.json"
    if config.is_file():
        settings = json.loads(config.read_text(encoding="utf-8"))
        need(isinstance(settings, dict), "运行时配置必须是 JSON 对象")
        need(not (set(settings) - {"node", "node_modules"}), "运行时配置仅支持 node 和 node_modules")
        for key, value in settings.items():
            need(isinstance(value, str) and value.strip(), f"运行时配置 {key} 必须是非空路径")
            configured = Path(value)
            settings[key] = str((config.parent / configured).resolve())
    else:
        need(config == SKILL / "runtime.json", f"运行时配置文件不存在：{config}")
    bundle = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
    node = node or settings.get("node") or os.environ.get("LABOR_REPORT_NODE") or (str(bundle / "bin/node") if (bundle / "bin/node").is_file() else shutil.which("node"))
    modules = modules or settings.get("node_modules") or os.environ.get("LABOR_REPORT_NODE_MODULES") or str(bundle / "node_modules")
    need(node and Path(node).is_file(), "未找到 Node.js；请用 --node 指定可执行文件，或由管理员配置 Skill 根目录 runtime.json")
    need((Path(modules) / "@oai/artifact-tool").is_dir(),
         "未找到 @oai/artifact-tool；请用 --node-modules 指定依赖目录，或由管理员配置 Skill 根目录 runtime.json")
    return str(Path(node).resolve()), Path(modules).resolve()


def generate_excel(payload, output, mock=False, template=None, node=None, modules=None, preview_dir=None, runtime_config=None):
    output = Path(output).resolve()
    template = Path(template or SKILL / "assets/labor-compliance-template.xlsx").resolve()
    need(output.suffix.lower() == ".xlsx", "报告必须使用 .xlsx 格式")
    need(template.is_file(), f"Excel 模板不存在：{template}")
    need(output != template, "输出路径不能覆盖 Excel 模板")
    issues, _ = validate(payload)
    node, modules = runtime_paths(node, modules, runtime_config)
    with tempfile.TemporaryDirectory(prefix="labor-compliance-excel-") as temp:
        work = Path(temp)
        (work / "node_modules").symlink_to(modules, target_is_directory=True)
        shutil.copy2(HERE / "fill_template.mjs", work / "fill_template.mjs")
        request = {"tables": payload, "issues": issues, "mock": mock,
                   "template": str(template), "output": str(output),
                   "checksFile": str(work / "checks.json"),
                   "previewDir": str(Path(preview_dir).resolve()) if preview_dir else None}
        (work / "request.json").write_text(json.dumps(request, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        # Export to a temporary file first; a failed run leaves any earlier report intact.
        child = subprocess.run([node, str(work / "fill_template.mjs"), str(work / "request.json")],
                               cwd=work, capture_output=True, text=True, timeout=300)
        need(child.returncode == 0, "Excel 写入失败：" + (child.stderr.strip() or child.stdout.strip()))
        # Native spreadsheet libraries may log to stdout; use a dedicated machine channel.
        need((work / "checks.json").is_file(), "Excel 脚本未保存校验摘要")
        checks = json.loads((work / "checks.json").read_text(encoding="utf-8"))
    need(isinstance(checks, dict), "Excel 脚本未返回有效校验摘要")
    counts = {"customers": len(payload[CUSTOMERS]), "workers": len(payload[WORKERS]),
              "evidence": len(payload[EVIDENCE])}
    need(checks.get("rows") == counts, "Excel 校验摘要行数与输入不符")
    need(type(checks.get("formula_error_count")) is int and checks["formula_error_count"] == 0,
         "Excel 公式校验未通过")
    summary = data_summary(payload)
    book_amounts = checks.get("amounts_by_currency")
    need(isinstance(book_amounts, dict) and set(book_amounts) == set(summary["amounts_by_currency"]),
         "Excel 金额汇总币种与输入不符")
    for currency, amounts in summary["amounts_by_currency"].items():
        for field, expected in amounts.items():
            actual = book_amounts[currency].get(field)
            need(actual is not None and Decimal(str(actual)).quantize(Decimal("0.01")) == Decimal(expected),
                 f"Excel 金额汇总与输入不符：{currency}/{field}")
    need(output.is_file() and output.stat().st_size > 0, "Excel 输出文件不存在或为空")
    try:
        relative = str(output.relative_to(Path.cwd().resolve()))
    except ValueError:
        relative = None
    return {"version": VERSION, "output": str(output), "output_relative": relative,
            "output_bytes": output.stat().st_size,
            "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "formula_error_count": 0, "mock": mock, "data_issues": issues,
            "customers": len(payload[CUSTOMERS]), "workers": len(payload[WORKERS]),
            "evidence": len(payload[EVIDENCE]), **summary}


def group_monthly_evidence(job):
    columns = EVIDENCE_ID_COLUMNS + EVIDENCE_MONTH_COLUMNS
    groups = {}
    for index, row in enumerate(job["rows"]):
        identity = [row.get(column) for column in EVIDENCE_ID_COLUMNS]
        key = index if any(value in (None, "") for value in identity) else json.dumps(identity, sort_keys=True)
        projected = {column: row.get(column) for column in columns}
        projected["window_ratio"] = formatted_number(projected["window_ratio"])
        groups.setdefault(key, []).append(projected)

    rows = []
    group_ranges = []
    for group in groups.values():
        group.sort(key=lambda row: (row["obs_month"] in (None, ""), str(row["obs_month"])))
        start = len(rows)
        rows.extend(group)
        group_ranges.append((start, len(rows)))
    job["rows"] = rows
    return {"columns": columns, "headers": EVIDENCE_HEADERS, "identityColumns": len(EVIDENCE_ID_COLUMNS),
            "groups": group_ranges, "columnWidths": {"warn_id": 42}, "numberFormats": {"window_ratio": "0.00%"}}


def generate_exec_excel(payload, output, source, mock=False, template=None, node=None,
                        modules=None, preview_dir=None, runtime_config=None):
    """Export validated task results using their report's sheet assignments."""
    output = Path(output).resolve()
    template = Path(template or SKILL / "assets/labor-compliance-template.xlsx").resolve()
    need(output.suffix.lower() == ".xlsx", "报告必须使用.xlsx格式")
    need(template.is_file() and output != template, "模板不存在或输出试图覆盖模板")
    jobs = payload["jobs"]
    if payload["report_type"] == "fixed_employment":
        detail, customer, evidence = FIXED_TASKS
        workers = [detail]
        notices = ["固定用工预警分别展示人员明细、客户汇总和月度证据。月度证据按预警标识分组，逐月列示。"]
        if not jobs[evidence]["rows"]:
            notices.append("本次月度证据任务成功返回0行。")
    else:
        r01, r02, customer = TASKS
        workers, evidence = [r01, r02], None
        notices = ["R01和R02为不同观察期的人员结果，行数分别列示。",
                   "灵工分期任务没有独立月度证据表。"]
    if evidence is None:
        notices.append("原始列保留上游值。汇总口径、统一观察期及规则版本需查阅上游字段定义。")
    else:
        notices.append("客户按客户ID去重。人员按客户－灵工组合及主规则统计。涉及金额为R01近3月人民币金额之和。")
    export_mock = mock or payload["mock"]
    layout = {"workers": workers, "customer": customer, "evidence": evidence}
    results = excel_scalar(payload)
    if evidence is not None:
        layout["headerRow"] = FIXED_HEADER_ROW
        layout["summaryMetadata"] = fixed_report_metadata(jobs)
        layout["summaryMetrics"] = fixed_summary(jobs[customer]["rows"], jobs[detail]["rows"])
        layout["customerView"] = project_customer_rows(results["jobs"][customer])
        layout["workerView"] = project_rows(results["jobs"][detail], WORKER_COLUMNS,
                                            WORKER_REVIEW_COLUMNS, WORKER_NUMBER_FORMATS)
        layout["workerView"]["columnWidths"] = {"预警ID": 42, "客户名称": 32}
        layout["evidenceView"] = group_monthly_evidence(results["jobs"][evidence])
        layout["workerLinks"] = worker_evidence_links(results["jobs"][detail]["rows"], results["jobs"][evidence]["rows"],
                                                      layout["evidenceView"]["groups"], FIXED_HEADER_ROW)
    if preview_dir or node or modules or runtime_config:
        checks = generate_exec_preview(results, layout, notices, export_mock, template, output,
                                       node, modules, preview_dir, runtime_config)
    else:
        try:
            from exec_excel import export_exec_workbook
        except ModuleNotFoundError as exc:
            if exc.name != "openpyxl":
                raise
            raise ValueError("缺少 openpyxl，无法导出 Excel；请部署含 vendor 依赖的完整 Skill 包") from exc
        checks = export_exec_workbook(results, layout, notices, export_mock, template, output)
    counts = {biz: job["total"] for biz, job in jobs.items()}
    need(checks.get("rows_by_biz_key") == counts, "工作簿行数与三项任务total不符")
    need(type(checks.get("formula_error_count")) is int and checks["formula_error_count"] == 0, "Excel公式检查未通过")
    need(output.is_file() and output.stat().st_size > 0, "报告文件不存在或为空")
    try:
        relative = str(output.relative_to(Path.cwd().resolve()))
    except ValueError:
        relative = None
    return {"version": VERSION, "format": payload["format"], "report_type": payload["report_type"],
            "output": str(output), "output_relative": relative,
            "output_bytes": output.stat().st_size, "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "formula_error_count": 0, "mock": export_mock, "source": source,
            "rows_by_biz_key": counts, "jobs": [{k: v for k, v in job.items() if k not in ("rows", "traceIds")}
                                               for job in jobs.values()],
            "business_mapping_verified": False,
            "monthly_evidence_available": evidence is not None and counts[evidence] > 0, "data_issues": notices}


def generate_exec_preview(results, layout, notices, mock, template, output,
                          node, modules, preview_dir, runtime_config):
    node, modules = runtime_paths(node, modules, runtime_config)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".labor-exec-excel-", dir=output.parent) as temp:
        work = Path(temp)
        staged = work / "report.xlsx"
        (work / "node_modules").symlink_to(modules, target_is_directory=True)
        shutil.copy2(HERE / "fill_task_results.mjs", work / "fill_task_results.mjs")
        request = {"results": results, "issues": notices, "mock": mock, "layout": layout,
                   "template": str(template), "output": str(staged), "checksFile": str(work / "checks.json"),
                   "previewDir": str(Path(preview_dir).resolve()) if preview_dir else None}
        (work / "request.json").write_text(json.dumps(request, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        child = subprocess.run([node, str(work / "fill_task_results.mjs"), str(work / "request.json")],
                               cwd=work, capture_output=True, text=True, timeout=300)
        need(child.returncode == 0, "Excel写入失败：" + (child.stderr.strip() or child.stdout.strip()))
        need((work / "checks.json").is_file(), "Excel脚本未返回校验摘要")
        checks = json.loads((work / "checks.json").read_text(encoding="utf-8"))
        if layout.get("workerLinks"):
            add_preview_hyperlinks(staged, output, layout["workerLinks"])
        else:
            staged.replace(output)
        return checks


def add_preview_hyperlinks(staged, output, links):
    """Add native links to the Node export without rewriting cell values or styles."""
    sheet_path = "xl/worksheets/sheet3.xml"
    pending = staged.with_name("linked.xlsx")
    with ZipFile(staged) as source, ZipFile(pending, "w") as target:
        with parseString(source.read(sheet_path)) as doc:
            sheet = doc.documentElement
            namespace = sheet.namespaceURI
            prefix = f"{sheet.prefix}:" if sheet.prefix else ""
            hyperlinks = doc.createElementNS(namespace, prefix + "hyperlinks")
            later_tags = {"printOptions", "pageMargins", "pageSetup", "headerFooter", "rowBreaks", "colBreaks",
                          "customProperties", "cellWatches", "ignoredErrors", "smartTags", "drawing", "legacyDrawing",
                          "legacyDrawingHF", "picture", "oleObjects", "controls", "webPublishItems", "tableParts", "extLst"}
            following = next((child for child in sheet.childNodes if child.localName in later_tags), None)
            sheet.insertBefore(hyperlinks, following)
            for address, location in links.items():
                link = doc.createElementNS(namespace, prefix + "hyperlink")
                link.setAttribute("ref", address)
                link.setAttribute("location", location)
                hyperlinks.appendChild(link)
            sheet_xml = doc.toxml(encoding="utf-8")
        for member in source.infolist():
            target.writestr(member, sheet_xml if member.filename == sheet_path else source.read(member))
    pending.replace(output)


def save_checks(filename, result):
    """Save the same compact checks even when PNG previews are disabled."""
    filename = Path(filename)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=filename.parent,
                                     prefix=".labor-checks-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(filename)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mcp-result", type=Path, help="已保存的 MCP tools/call 返回，支持 CallToolResult 或完整 JSON-RPC 响应")
    source.add_argument("--url", help="返回完整三表快照的 GET 接口")
    source.add_argument("--input", type=Path, help="已保存的三表 JSON 响应")
    source.add_argument("--exec-manifest", type=Path, help="固定用工预警或灵工分期三表的MCP分页文件清单")
    parser.add_argument("--expected-sha256", help="MCP 文件清单中的原始文件 SHA-256，读取时校验")
    parser.add_argument("--expected-bytes", type=int, help="MCP 文件清单中的原始文件字节数，读取时校验")
    parser.add_argument("--output", type=Path, required=True, help="Excel .xlsx 报告路径")
    parser.add_argument("--template", type=Path, help="同版式 Excel 模板；默认使用 Skill 内模板")
    parser.add_argument("--mock-data", action="store_true", help="明确标记模拟数据")
    parser.add_argument("--node", help="Node.js 可执行文件")
    parser.add_argument("--node-modules", help="包含 @oai/artifact-tool 的 node_modules 目录")
    parser.add_argument("--runtime-config", type=Path, help="管理员运行时路径 JSON；默认读取 Skill 根目录 runtime.json")
    parser.add_argument("--preview-dir", type=Path, help="仅视觉验收时启用 PNG；不传仍执行全部数据及公式校验")
    args = parser.parse_args()
    started = time.monotonic()
    try:
        checks_file = args.output.with_suffix(".checks.json").resolve()
        if args.exec_manifest:
            need(args.expected_sha256 is None and args.expected_bytes is None,
                 "新版每页哈希与字节数放在任务清单pages内，不使用顶层expected参数")
            payload, source = load_manifest(args.exec_manifest, protected=(args.output.resolve(), checks_file))
            result = generate_exec_excel(payload, args.output, source, args.mock_data, args.template,
                                         args.node, args.node_modules, args.preview_dir, args.runtime_config)
        elif args.url:
            need(args.expected_sha256 is None and args.expected_bytes is None,
                 "MCP 文件哈希和字节数校验仅适用于 --input/--mcp-result")
            payload, is_mock = read_url(args.url)
            source = {"type": "http", "integrity_verified": False, "size_verified": False}
        else:
            source_path = args.mcp_result or args.input
            need(source_path.resolve() not in (args.output.resolve(), checks_file), "输出路径不能覆盖输入文件")
            payload, source = read_result_file(source_path, bool(args.mcp_result),
                                               args.expected_sha256, args.expected_bytes)
            is_mock = False
        if not args.exec_manifest:
            result = generate_excel(payload, args.output, args.mock_data or is_mock, args.template,
                                    args.node, args.node_modules, args.preview_dir, args.runtime_config)
        result.update(source=source, checks_file=str(checks_file),
                      elapsed_seconds=round(time.monotonic() - started, 3),
                      preview_generated=args.preview_dir is not None)
        save_checks(checks_file, result)
    except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print(f"报告未生成：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
