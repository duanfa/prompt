#!/usr/bin/env python3
"""Fill the bundled Excel template from three SQL result tables. Python 3.9+."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
# WanScope runs installed scripts with python -I, which omits the script directory.
# Load trusted, bundled siblings from this location rather than the workspace cwd.
sys.path.insert(0, str(HERE))
from validate_results import CUSTOMERS, EVIDENCE, WORKERS, need, validate

SKILL = HERE.parent


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
                   "previewDir": str(Path(preview_dir).resolve()) if preview_dir else None}
        (work / "request.json").write_text(json.dumps(request, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        # Export to a temporary file first; a failed run leaves any earlier report intact.
        child = subprocess.run([node, str(work / "fill_template.mjs"), str(work / "request.json")],
                               cwd=work, capture_output=True, text=True, timeout=300)
        need(child.returncode == 0, "Excel 写入失败：" + (child.stderr.strip() or child.stdout.strip()))
    return {"output": str(output), "mock": mock, "data_issues": issues,
            "customers": len(payload[CUSTOMERS]), "workers": len(payload[WORKERS]),
            "evidence": len(payload[EVIDENCE])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--mcp-result", type=Path, help="已保存的 MCP tools/call 返回，支持 CallToolResult 或完整 JSON-RPC 响应")
    source.add_argument("--url", help="返回完整三表快照的 GET 接口")
    source.add_argument("--input", type=Path, help="已保存的三表 JSON 响应")
    parser.add_argument("--output", type=Path, required=True, help="Excel .xlsx 报告路径")
    parser.add_argument("--template", type=Path, help="同版式 Excel 模板；默认使用 Skill 内模板")
    parser.add_argument("--mock-data", action="store_true", help="明确标记模拟数据")
    parser.add_argument("--node", help="Node.js 可执行文件")
    parser.add_argument("--node-modules", help="包含 @oai/artifact-tool 的 node_modules 目录")
    parser.add_argument("--runtime-config", type=Path, help="管理员运行时路径 JSON；默认读取 Skill 根目录 runtime.json")
    parser.add_argument("--preview-dir", type=Path, help="可选：导出各工作表的渲染预览和校验信息")
    args = parser.parse_args()
    try:
        if args.url:
            payload, is_mock = read_url(args.url)
        else:
            source_path = args.mcp_result or args.input
            need(source_path.resolve() != args.output.resolve(), "输出路径不能覆盖输入文件")
            response = json.loads(source_path.read_text(encoding="utf-8"))
            payload = read_mcp_result(response) if args.mcp_result else response
            is_mock = False
        result = generate_excel(payload, args.output, args.mock_data or is_mock, args.template,
                                args.node, args.node_modules, args.preview_dir, args.runtime_config)
    except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print(f"报告未生成：{exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
