"""Export validated execution results using the bundled four-sheet template."""

import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from openpyxl import load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.formatting.formatting import ConditionalFormattingList
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidationList
from openpyxl.worksheet.table import Table, TableStyleInfo

from exec_results import need


SHEET_NAMES = ["灵工固定用工特征风控报告", "客户风险汇总", "命中人员明细", "月度证据"]
NAVY = "223B57"
SECTION = "EEF3F8"
MISSING = "未提供"
EXCEL_ERRORS = {"#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!", "#SPILL!", "#CALC!"}


def write(cell, value):
    if isinstance(value, str):
        need(len(value) <= 32767, "单元格文本超过Excel上限，不能截断生成")
        need(not ILLEGAL_CHARACTERS_RE.search(value), "单元格文本包含 Excel 不支持的控制字符")
        need(value not in EXCEL_ERRORS, f"上游结果包含 Excel 错误值 {value}")
        cell.value = value
        cell.data_type = "s"
    else:
        cell.value = value


def title(sheet, address, value, *, height=32, fill=None):
    sheet.merge_cells(address)
    cell = sheet[address.split(":")[0]]
    write(cell, value)
    sheet.row_dimensions[cell.row].height = height
    cell.alignment = Alignment(wrap_text=True, vertical="center")
    if fill:
        cell.fill = PatternFill("solid", fgColor=fill)
        cell.font = Font(name="Microsoft YaHei", size=11, bold=True,
                         color="FFFFFF" if fill == NAVY else NAVY)


def write_summary(sheet, sections, fixed, mock, notices):
    for row in sheet.iter_rows(min_row=3, max_row=8, max_col=16):
        for cell in row:
            if cell.value is not None:
                cell.value = None
    customer = next(job for _, label, job in sections if label in ("客户汇总", "R03"))
    jobs = [job for _, _, job in sections]
    fields = {
        "A2": "灵工固定用工特征风控报告 执行结果",
        "A3": "模拟数据验收报告。按任务分别展示原始结果。" if mock else "按任务分别展示原始执行结果。",
        "A4": "报告日期", "C4": MISSING, "D4": "观察期", "K4": "规则版本",
        "F4": "见上游结果字段" if fixed else "R01近3月，R02近6月。具体起止月见上游字段。",
        "M4": "见上游结果字段",
        "A5": "分页、文件完整性与任务身份校验通过。人员去重、金额口径及风险结论待完整字段定义确认。",
        "A6": "客户汇总行数" if fixed else "R03客户结果行数",
        "A7": customer["total"],
        "D6": "人员明细行数" if fixed else "R01近3月明细行数",
        "D7": jobs[0]["total"],
        "G6": "月度证据行数" if fixed else "R02近6月明细行数",
        "G7": jobs[2 if fixed else 1]["total"],
        "J6": "已读取结果页数", "J7": sum(job["pageCount"] for job in jobs),
        "M6": "金额统计", "M7": "见原始列",
    }
    for address, value in fields.items():
        write(sheet[address], value)
    for row, height in ((3, 32), (5, 32), (6, 36), (7, 32)):
        sheet.row_dimensions[row].height = height
    for address in ("A3", "F4", "M4", "A5", "A6", "D6", "G6", "J6", "M6"):
        sheet[address].alignment = Alignment(wrap_text=True, vertical="center")
    title(sheet, "A10:P10", "本次执行范围", fill=SECTION)
    columns = (("A", "B"), ("C", "H"), ("I", "K"), ("L", "M"), ("N", "P"))
    for (left, right), label in zip(columns, ("任务", "结果表", "execId", "结果行数", "分页数")):
        title(sheet, f"{left}11:{right}11", label, fill=NAVY)
    for row, (_, label, job) in enumerate(sections, 12):
        values = (label, job["resultTable"], job["execId"], job["total"], job["pageCount"])
        for (left, right), value in zip(columns, values):
            title(sheet, f"{left}{row}:{right}{row}", value)
    title(sheet, "A16:P16", "数据范围与缺失资料", fill=SECTION)
    for row, value in enumerate(notices, 17):
        title(sheet, f"A{row}:P{row}", value, height=36)


def raw_value(value):
    if value is None:
        return MISSING
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return value


def write_table(sheet, start, job, name):
    keys = list(dict.fromkeys(key for row in job["rows"] for key in row))
    bottom = start + max(len(job["rows"]), 1)
    need(len(keys) <= 16384 and bottom <= 1048576, "结果超出Excel单表行列上限，请先拆分请求范围")
    banner_end = get_column_letter(max(len(keys), 8))
    title(sheet, f"A{start-2}:{banner_end}{start-2}", f'{job["bizKey"]} / {job["resultTable"]}', fill=SECTION)
    title(sheet, f"A{start-1}:{banner_end}{start-1}",
          f'execId={job["execId"]}，共{job["total"]}行，{job["pageCount"]}页。按原始列展示。')
    if not keys:
        message = f'该任务成功返回{job["total"]}行，未提供列定义。'
        title(sheet, f"A{start}:H{start}", message)
        if job["rows"]:
            for row_no in range(start + 1, bottom + 1):
                write(sheet.cell(row_no, 1), MISSING)
        return bottom, [[message]] + [[MISSING]] * len(job["rows"])

    used = set()
    headers = []
    for index, key in enumerate(keys, 1):
        header = key
        while header.lower() in used:
            header = f"[{index}] {header}"
        used.add(header.lower())
        headers.append(header)
        cell = sheet.cell(start, index)
        write(cell, header)
        cell.font = Font(name="Microsoft YaHei", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
        width = 30 if re.search("time|date|table|name|conclusion|basis", key, re.I) else 24
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.row_dimensions[start].height = 48

    expected = [headers]
    for row_no, record in enumerate(job["rows"], start + 1):
        values = [raw_value(record.get(key)) for key in keys]
        expected.append(values)
        for index, value in enumerate(values, 1):
            write(sheet.cell(row_no, index), value)
        sheet.row_dimensions[row_no].height = 40
    table = Table(displayName=name, ref=f"A{start}:{get_column_letter(len(keys))}{bottom}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    sheet.add_table(table)
    return bottom, expected


def verify_saved_workbook(path, sections):
    workbook = load_workbook(path, read_only=True)
    try:
        need(workbook.sheetnames == SHEET_NAMES, "保存后的工作簿页签不完整")
        for sheet in workbook:
            need(all(cell.data_type not in ("f", "e") for row in sheet.iter_rows() for cell in row),
                 f"{sheet.title} 包含公式或错误单元格")
        for sheet_name, start, expected in sections:
            if not expected:
                continue
            cells = workbook[sheet_name].iter_rows(
                min_row=start, max_row=start + len(expected) - 1, max_col=len(expected[0]), values_only=True,
            )
            for row_no, (actual, wanted) in enumerate(zip(cells, expected), start):
                # Excel reads literal empty strings as blank cells.
                wanted = tuple(None if value == "" else value for value in wanted)
                need(actual == wanted, f"{sheet_name} 第{row_no}行写入校验失败")
    finally:
        workbook.close()


def export_exec_workbook(results, layout, notices, mock, template, output):
    workbook = load_workbook(template)
    need(workbook.sheetnames == SHEET_NAMES, "模板须保留新版四个工作表")
    main, customers, workers, evidence = workbook.worksheets
    for sheet in workbook:
        sheet.sheet_view.showGridLines = False
    for sheet in (customers, workers, evidence):
        for address in list(sheet.merged_cells.ranges):
            sheet.unmerge_cells(str(address))
        for name in list(sheet.tables):
            del sheet.tables[name]
        sheet.conditional_formatting = ConditionalFormattingList()
        sheet.data_validations = DataValidationList()
        sheet.delete_rows(1, sheet.max_row)

    jobs = results["jobs"]
    fixed = layout["evidence"] is not None
    worker_jobs = [jobs[key] for key in layout["workers"]]
    customer_job = jobs[layout["customer"]]
    if fixed:
        sections = [(workers, "人员明细", worker_jobs[0]), (customers, "客户汇总", customer_job),
                    (evidence, "月度证据", jobs[layout["evidence"]])]
        table_names = ["WorkerResults1", "CustomerResults", "MonthlyEvidence"]
    else:
        sections = [(workers, "R01", worker_jobs[0]), (workers, "R02", worker_jobs[1]),
                    (customers, "R03", customer_job)]
        table_names = ["WorkerResults1", "WorkerResults2", "CustomerResults"]
        title(evidence, "A1:P1", "月度证据 未提供", fill=SECTION)
        title(evidence, "A3:P3", "灵工分期结果未提供独立月度证据表。", height=38)
    write_summary(main, sections, fixed, mock, notices)

    checks = []
    starts = {}
    counts = {}
    for (sheet, _, job), name in zip(sections, table_names):
        if sheet.title not in starts:
            title(sheet, "A1:P1", f"{sheet.title} 原始执行结果", fill=SECTION)
            sheet.freeze_panes = "A6"
        start = starts.get(sheet.title, 5)
        bottom, expected = write_table(sheet, start, job, name)
        starts[sheet.title] = bottom + 5
        counts[job["bizKey"]] = max(0, len(expected) - 1)
        checks.append((sheet.title, start, expected))

    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=output.parent, prefix=".labor-report-", suffix=".xlsx", delete=False) as file:
        pending = Path(file.name)
    try:
        workbook.save(pending)
        verify_saved_workbook(pending, checks)
        pending.replace(output)
    finally:
        workbook.close()
        pending.unlink(missing_ok=True)
    return {"rows_by_biz_key": counts, "formula_error_count": 0}
