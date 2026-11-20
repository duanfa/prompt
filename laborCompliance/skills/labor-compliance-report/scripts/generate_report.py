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
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
# WanScope runs installed scripts with python -I, which omits the script directory.
# Load trusted, bundled siblings from this location rather than the workspace cwd.
sys.path.insert(0, str(HERE))
from validate_results import CUSTOMERS, EVIDENCE, WORKERS, need, validate
from exec_results import FIXED_TASKS, TASKS, excel_scalar, load_manifest

SKILL = HERE.parent
VERSION = "labor-compliance-excel-v1-4-2"


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


def generate_exec_excel(payload, output, source, mock=False, template=None, node=None,
                        modules=None, preview_dir=None, runtime_config=None):
    """Export validated task results using their report's sheet assignments."""
    output = Path(output).resolve()
    template = Path(template or SKILL / "assets/labor-compliance-template.xlsx").resolve()
    need(output.suffix.lower() == ".xlsx", "报告必须使用.xlsx格式")
    need(template.is_file() and output != template, "模板不存在或输出试图覆盖模板")
    node, modules = runtime_paths(node, modules, runtime_config)
    jobs = payload["jobs"]
    if payload["report_type"] == "fixed_employment":
        detail, customer, evidence = FIXED_TASKS
        workers = [detail]
        notices = ["固定用工预警按人员明细、客户汇总、月度证据分别展示原始列。"]
        if not jobs[evidence]["rows"]:
            notices.append("本次月度证据任务成功返回0行。")
    else:
        r01, r02, customer = TASKS
        workers, evidence = [r01, r02], None
        notices = ["R01和R02为不同观察期的人员结果，行数分别列示。",
                   "灵工分期任务没有独立月度证据表。"]
    notices.append("原始列保留上游值。汇总口径、统一观察期及规则版本需查阅上游字段定义。")
    with tempfile.TemporaryDirectory(prefix="labor-exec-excel-") as temp:
        work = Path(temp)
        (work / "node_modules").symlink_to(modules, target_is_directory=True)
        shutil.copy2(HERE / "fill_task_results.mjs", work / "fill_task_results.mjs")
        request = {"results": excel_scalar(payload), "issues": notices, "mock": mock or payload["mock"],
                   "layout": {"workers": workers, "customer": customer, "evidence": evidence},
                   "template": str(template), "output": str(output), "checksFile": str(work / "checks.json"),
                   "previewDir": str(Path(preview_dir).resolve()) if preview_dir else None}
        (work / "request.json").write_text(json.dumps(request, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        child = subprocess.run([node, str(work / "fill_task_results.mjs"), str(work / "request.json")],
                               cwd=work, capture_output=True, text=True, timeout=300)
        need(child.returncode == 0, "Excel写入失败：" + (child.stderr.strip() or child.stdout.strip()))
        need((work / "checks.json").is_file(), "Excel脚本未返回校验摘要")
        checks = json.loads((work / "checks.json").read_text(encoding="utf-8"))
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
            "formula_error_count": 0, "mock": request["mock"], "source": source,
            "rows_by_biz_key": counts, "jobs": [{k: v for k, v in job.items() if k not in ("rows", "traceIds")}
                                               for job in jobs.values()],
            "business_mapping_verified": False,
            "monthly_evidence_available": evidence is not None and counts[evidence] > 0, "data_issues": notices}


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
