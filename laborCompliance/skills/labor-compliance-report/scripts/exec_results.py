#!/usr/bin/env python3
"""Validate saved exec/data pages without reading credentials or calling APIs."""

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

FIXED_TASKS = {
    "enterprise_fixed_emp_warn_detl": "fes_fixed_emp_warn_detl",
    "enterprise_fixed_emp_warn_sum": "fes_fixed_emp_warn_cust_sum",
    "enterprise_fixed_emp_warn_evidence": "fes_fixed_emp_warn_mon_evi",
}
FORMAT = "labor-compliance-exec-pages-v1"


def need(condition, message):
    if not condition:
        raise ValueError(message)


def positive_id(value, label):
    need(type(value) is int and 0 < value <= 9223372036854775807,
         f"{label} 必须为正Long整数，不能用浮点数、taskId或表名代替")
    return value


def unwrap(response):
    """Accept raw Resp, CallToolResult, or a JSON-RPC response. Preserve errors."""
    need(isinstance(response, dict), "结果文件必须为JSON对象")
    need("error" not in response, "MCP JSON-RPC返回error，停止生成")
    if "jsonrpc" in response:
        need(response["jsonrpc"] == "2.0" and "result" in response, "无效JSON-RPC响应")
        response = response["result"]
    need(isinstance(response, dict) and "error" not in response, "MCP result无效或含error")
    flag = response.get("isError", False)
    need(type(flag) is bool and not flag, "MCP isError=true或无效，停止生成")
    if "code" in response:
        return response
    if "structuredContent" in response:
        result = response["structuredContent"]
        need(isinstance(result, dict) and "code" in result, "structuredContent缺少完整code/data包装")
        return result
    content = response.get("content")
    need(isinstance(content, list), "MCP结果缺少完整Resp或content")
    candidates = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
            continue
        try:
            item = json.loads(block["text"], parse_float=Decimal)
        except ValueError:
            continue
        if isinstance(item, dict) and "code" in item:
            candidates.append(item)
    need(len(candidates) == 1, "content须含唯一完整Resp，不能使用预览、摘要或重复结果")
    return candidates[0]


def validate_page(response, job, page_no):
    response = unwrap(response)
    code = response.get("code")
    message = response.get("message", response.get("msg"))
    if "succeed" in response:
        need(type(response["succeed"]) is bool and response["succeed"],
             f"取数业务失败：code={code!r}，succeed={response['succeed']!r}，message={message!r}")
    # DEV uses code=200 even for rejected requests: succeed must explicitly be true.
    if code in ("200", 200):
        need(response.get("succeed") is True,
             f"取数业务失败：code={code!r}不能单独代表成功，message={message!r}")
        data = response.get("model")
        field = "model"
    else:
        need(code == "OK", f"取数业务失败：code={code!r}，message={message!r}")
        data = response.get("data")
        field = "data"
    need(isinstance(data, dict), f"成功响应缺少完整{field}分页对象，须核对实际接口结构")
    need(type(data.get("execId")) is int and data["execId"] == job["execId"], "返回execId与调用方任务不符")
    positive_id(data.get("taskId"), "data.taskId")
    if "taskId" in job:
        need(data["taskId"] == positive_id(job["taskId"], "job.taskId"), "返回taskId与调用方任务不符")
    for field in ("domain", "bizKey", "resultTable"):
        expected = "enterprise" if field == "domain" else job[field]
        need(data.get(field) == expected, f"返回{field}与调用方任务不符，停止合并")
    need(type(data.get("total")) is int and data["total"] >= 0, "total须为非负整数")
    need(type(data.get("pageNo")) is int and data["pageNo"] == page_no, "返回页码不符或重复页")
    size = data.get("pageSize")
    need(type(size) is int and 1 <= size <= 1000, "pageSize须为1至1000整数")
    rows = data.get("rows")
    need(isinstance(rows, list) and all(isinstance(row, dict) for row in rows), "rows须为完整对象数组")
    count = max(1, (data["total"] + size - 1) // size)
    need(page_no <= count, "页码超出total范围")
    expected_rows = min(size, max(0, data["total"] - (page_no - 1) * size))
    need(len(rows) == expected_rows, f"第{page_no}页行数不符：预期{expected_rows}，实际{len(rows)}，可能被截断")
    for row in rows:
        need(all(isinstance(key, str) and key for key in row), "rows列名必须为非空字符串")
        if "exec_id" in row:
            value = row["exec_id"]
            need(type(value) is int or isinstance(value, str) and re.fullmatch(r"[0-9]+", value), "行exec_id格式无效")
            need(int(value) == job["execId"], "行exec_id与结果任务不符")
    return data, response.get("traceId")


def resolve_page_path(item, base, protected):
    filename = item.get("path")
    need(isinstance(filename, str) and filename.strip(), "分页文件缺少path")
    file_path = (base / filename).resolve()
    need(file_path not in protected, "输出路径不能覆盖输入分页文件")
    return file_path


def read_verified_file(item, file_path):
    sha, size = item.get("sha256"), item.get("bytes")
    need(isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha), "分页文件缺少有效sha256")
    need(type(size) is int and size >= 0, "分页文件缺少有效bytes整数")
    raw = file_path.read_bytes()
    need(len(raw) == size, "分页文件字节数与MCP清单不符")
    digest = hashlib.sha256(raw).hexdigest()
    need(digest == sha.lower(), "分页文件SHA-256与MCP清单不符")
    return json.loads(raw.decode("utf-8"), parse_float=Decimal), {"path": str(file_path), "bytes": size, "sha256": digest}


def load_manifest(filename, protected=(), require_complete=True):
    filename = Path(filename).resolve()
    need(filename not in protected, "输出路径不能覆盖任务清单")
    raw = filename.read_bytes()
    manifest = json.loads(raw.decode("utf-8"))
    need(isinstance(manifest, dict) and manifest.get("format") == FORMAT, f"任务清单format必须为{FORMAT}")
    need(manifest.get("domain") == "enterprise", "任务清单domain须为enterprise")
    need(type(manifest.get("mock", False)) is bool, "mock须为布尔值")
    jobs = manifest.get("jobs")
    need(isinstance(jobs, list) and len(jobs) == 3, "报告需要同一组的三项任务清单")
    need(all(isinstance(job, dict) and isinstance(job.get("bizKey"), str) for job in jobs),
         "任务须为带bizKey字符串的对象")
    jobs_by_key = {job["bizKey"]: job for job in jobs}
    need(jobs_by_key.keys() == FIXED_TASKS.keys(), "任务清单须完整匹配固定用工预警三表")
    results, seen_execs, seen_files, files, inline_files = {}, set(), set(), [], []
    source_batches = set()
    base = Path.cwd()
    for biz, table in FIXED_TASKS.items():
        job = jobs_by_key[biz]
        need(job.get("resultTable") == table, f"{biz}结果表与约定不符")
        exec_id = positive_id(job.get("execId"), "job.execId")
        need(exec_id not in seen_execs, "三项任务execId不能相同")
        seen_execs.add(exec_id)
        pages = job.get("pages")
        need(isinstance(pages, list) and pages, f"{biz}须包含至少一页，包括total=0时的第一页")
        rows, traces, metadata = [], [], None
        for page_no, page in enumerate(pages, 1):
            need(isinstance(page, dict), "分页清单项须为对象")
            mode = page.get("mode", "file")
            need(mode in ("file", "inline"), "分页清单mode须为file或inline")
            file_path = resolve_page_path(page, base, protected)
            need(file_path not in seen_files, "分页文件被重复使用")
            seen_files.add(file_path)
            if mode == "inline":
                need(set(page) == {"mode", "path"}, "内联分页只接受mode和path")
                need(file_path.is_relative_to(base), "内联分页须保存在工作区内")
                response = json.loads(file_path.read_text(encoding="utf-8"), parse_float=Decimal)
                inline_files.append(str(file_path))
            else:
                response, source = read_verified_file(page, file_path)
                files.append(source)
            data, trace = validate_page(response, job, page_no)
            batch = data.get("etlBatchNo")
            if "etlBatchNo" in data:
                need(isinstance(batch, str) and re.fullmatch(r"[1-9][0-9]*", batch),
                     "etlBatchNo 须为正整数的字符串表示")
            source_batches.add(batch)
            need(len(source_batches) == 1, "结果的 MySQL 批次不一致，停止合并")
            current = (data["taskId"], data["total"], data["pageSize"])
            if metadata is None:
                metadata = current
            need(current == metadata, "分页间taskId/total/pageSize变化，不能合并不一致快照")
            rows.extend(data["rows"])
            traces.append(trace)
        task_id, total, size = metadata
        page_count = max(1, (total + size - 1) // size)
        need(len(pages) <= page_count, f"{biz}分页数量超出total")
        complete = len(pages) == page_count and len(rows) == total
        if require_complete:
            need(complete, f"{biz}分页不完整：已取{len(pages)}/{page_count}页，{len(rows)}/{total}行")
        results[biz] = {"execId": str(exec_id), "taskId": str(task_id), "bizKey": biz,
                        "resultTable": job["resultTable"], "total": total, "pageSize": size,
                        "pageCount": page_count, "savedPageCount": len(pages), "complete": complete,
                        "nextPage": len(pages) + 1 if not complete else None,
                        "traceIds": traces, "rows": rows}
    return {"format": FORMAT, "domain": "enterprise", "report_type": "fixed_employment",
            "mock": manifest.get("mock", False), "jobs": results}, {
        "type": "exec-pages", "path": str(filename), "sha256": hashlib.sha256(raw).hexdigest(),
        "integrity_verified": not inline_files, "size_verified": not inline_files,
        "files": files, "inline_files": inline_files}


def excel_scalar(value):
    """Protect Long IDs and precise decimals before JSON crosses into JavaScript."""
    if isinstance(value, Decimal):
        need(value.is_finite(), "不接受NaN/Infinity数值")
        return float(value) if len(value.as_tuple().digits) <= 15 else str(value)
    if type(value) is int and len(str(abs(value))) > 15:
        return str(value)
    if isinstance(value, dict):
        return {key: excel_scalar(item) for key, item in value.items()}
    if isinstance(value, list):
        return [excel_scalar(item) for item in value]
    return value


if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="校验已保存的exec/data页面，仅输出分页摘要，不输出rows")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        result, source = load_manifest(args.manifest, require_complete=False)
        jobs = [{k: v for k, v in job.items() if k not in ("rows", "traceIds")} for job in result["jobs"].values()]
        print(json.dumps({"format": FORMAT, "report_type": result["report_type"],
                          "complete": all(job["complete"] for job in jobs),
                          "jobs": jobs, "integrity_verified": source["integrity_verified"],
                          "size_verified": source["size_verified"],
                          "inline_page_count": len(source["inline_files"])}, ensure_ascii=False))
    except (ValueError, TypeError, OSError) as exc:
        print(f"结果页校验失败：{exc}", file=sys.stderr)
        sys.exit(2)
