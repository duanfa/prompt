# 新版 exec/data 接口契约

版本为 `labor-compliance-excel-v1-4-5`。

## ContextForge

| 配置 | 值 |
| --- | --- |
| 服务 | labor-compliance（DEV）或 labor-compliance-mysql（Fake API） |
| 工具 | get-labor-compliance-results，名称以当前工具列表为准 |
| DEV MCP URL | http://10.168.1.100:4445/servers/ec76ef3c8c3f4be6b64c463a2261b256/mcp |
| Fake API MCP URL | http://10.168.1.100:4445/servers/46e58485143246bea7edcd3007e18cfe/mcp |
| 传输 | Streamable HTTP |
| MCP认证 | 平台管理的ContextForge Bearer Token |
| 上游环境 | DEV，调用方已确认 |
| 上游URL | http://dtsp-dev-api.10000da.vip/bdp-ontology/api/v1/ontology/sql-task/exec/data |
| HTTP | POST，Content-Type: application/json |

调用方已取消DEV业务登录认证，接口不再需要上游登录凭据；ContextForge自身仍用Bearer认证。2026-11-18从网关无业务凭据探测空请求，不再返回UC_A1_0014，而是code="200"、message="execId不能为空"、model=null、succeed=false。该探测只验证登录阻断已消失，未验证真实任务成功取数。

## 请求及响应

```json
{"execId":90001,"bizKey":"enterprise_fixed_emp_warn_detl","pageNo":1,"pageSize":1000}
```

90001 仅为文档示例。每页传入该任务的 `execId`（Long）和 `bizKey`（字符串）。`pageNo` 默认 1，`pageSize` 默认 100、最大 1000。DEV 按 `execId` 查执行结果。Fake API 按 `bizKey` 查 MySQL 最新固定用工批次，回传调用方的 `execId`，并在 `data.etlBatchNo` 标识实际批次。`domain` 和 `resultTable` 用于核验响应。

标准成功响应示例。固定用工三表的 DEV 回放确认了 `code=OK/data`，包括成功空表。
```json
{
  "code": "OK",
  "msg": "success",
  "data": {
    "execId": 90001,
    "taskId": 1,
    "domain": "enterprise",
    "bizKey": "enterprise_flexible_employ_r01",
    "resultTable": "ads_esp_fes_entp_flxe_3m_manage_info_mi",
    "total": 0,
    "pageNo": 1,
    "pageSize": 1000,
    "rows": []
  },
  "traceId": "文档示例"
}
```

接口也可能返回 `code/message/model/succeed`。参数错误也可使用 `code="200"`。只有 `code` 为字符串"200"或整数200、`succeed` 为布尔true且 `model` 是完整分页对象时才处理该包装。使用 `code=OK/data` 时，`succeed` 若存在也必须为布尔true。返回身份须匹配 [两组任务配对](../SKILL.md#调用方输入与接口)。`rows` 保留动态对象列。

一项任务的全部页必须保持execId、taskId、domain、bizKey、resultTable、total、实际pageSize不变；pages按1…ceil(total/pageSize)排列。每个中间页应有pageSize行，末页为余数；total=0也需要第1页且rows=[]。不接受空中间页、错页、重复文件、不足或多出的页；聚合行数必须精确等于total。行含exec_id时也核对其值。Fake API 返回的 `etlBatchNo` 必须在三项任务及全部页面中一致。没有新主键契约，不做跨行内容去重。

## 任务清单

MCP文件模式每次保存原始完整Resp（保留code/message/model/succeed或文档code/msg/data包装），也兼容保存CallToolResult或JSON-RPC包装。文件清单的complete仅表示该文件保存完整；先检查RPC错误/isError，再检查业务成功条件（含succeed），最后核对分页。

在工作区写一份小清单，放入 `offlineSqlResults` 的身份字段和各页文件引用。输入提供 `taskId` 时将其保留为每项的整数 `taskId`。以下示例使用固定用工预警三表。
```json
{
  "format": "labor-compliance-exec-pages-v1",
  "domain": "enterprise",
  "mock": false,
  "jobs": [
    {
      "execId": 90001,
      "bizKey": "enterprise_fixed_emp_warn_detl",
      "resultTable": "fes_fixed_emp_warn_detl",
      "pages": [
        {"path":"tool-results/会话/r01-p1.json","sha256":"本次文件实际64位SHA256","bytes":1234}
      ]
    },
    {
      "execId": 90002,
      "bizKey": "enterprise_fixed_emp_warn_sum",
      "resultTable": "fes_fixed_emp_warn_cust_sum",
      "pages": [
        {"path":"tool-results/会话/r02-p1.json","sha256":"本次文件实际64位SHA256","bytes":1234}
      ]
    },
    {
      "execId": 90003,
      "bizKey": "enterprise_fixed_emp_warn_evidence",
      "resultTable": "fes_fixed_emp_warn_mon_evi",
      "pages": [
        {"path":"tool-results/会话/r03-p1.json","sha256":"本次文件实际64位SHA256","bytes":1234}
      ]
    }
  ]
}
```

上述ID、路径、哈希和字节数均为格式示例，不能直接运行。用本次实际值；每个pages按返回页码升序追加。三个execId应分别对应各自任务。相对path按脚本工作目录（WanScope workspace）解析，**不是按清单所在目录解析**，不改写平台path。用户直接提供响应文件时，可由脚本/终端计算该原文件哈希和大小，不能声称是MCP签发的来源证明。

执行scripts/exec_results.py --manifest work/exec-manifest.json，输出compact分页摘要，不输出rows。字段包括每项execId/taskId/bizKey/resultTable/total/pageSize/pageCount/savedPageCount/complete/nextPage。只有缺页时按nextPage和实际pageSize继续取数。源文件不全时此摘要允许complete=false，但报告脚本强制拒绝不完整任务。

报告入口scripts/generate_report.py --exec-manifest work/exec-manifest.json --output outputs/本次任务/report.xlsx。当前输入不需要顶层--expected-sha256/--expected-bytes，每页由清单分别校验。明确模拟数据时mock=true；DEV环境标签不代表模拟。

## 动态字段与报告边界

- 固定用工预警报告类型为 `fixed_employment`，客户汇总、人员明细、月度证据分别写入对应页。成功空表显示0行。
- 历史灵工分期报告类型为 `flexible_periods`，R03写客户页，R01和R02分表写人员页，月度证据标为“未提供”。
- 长整数和高精度小数保留精度，null及缺失键显示“未提供”。完整业务字段和主键待确认，`business_mapping_verified=false`。`monthly_evidence_available=true` 表示工作簿包含实际证据行。
- [旧字段字典](result-schema.json)和[原报告映射](rules-and-report.md)适用于旧版完整SQL快照。

## 运行时部署

常规分页导出使用 RunSkillScript 的 Python 3.9+ 环境和 openpyxl。RunSkillScript 使用 python -I，清空环境、重设 HOME，只允许工作区相对路径参数。预览和旧版快照入口使用 Node.js 与 @oai/artifact-tool，通过 Skill 根目录的 runtime.json 配置。
```json
{"node":"/deployment/node/bin/node","node_modules":"/deployment/node/node_modules"}
```
替换为部署机实际可访问路径；相对配置路径按runtime.json所在目录解析。不要把node_modules或认证凭据打包。优先级为命令行--node/--node-modules、runtime.json、环境变量、Codex默认路径。不修改管理员Skill或共享依赖。

在 WanScope「技能」上传或更新 `labor-compliance-report-v1`，绑定到 Agent 并开启 `WANSCOPE_SKILL_SCRIPTS=on`。同步更新主提示词，从新一轮调用的 `generate_report.py --version` 核对加载版本。版本检查和分页校验使用 60 秒，Excel 导出使用 `timeout_seconds=300`。部署时设置 `WANSCOPE_SKILL_SCRIPT_TIMEOUT=300` 并重启服务，脚本执行上限取调用参数和服务配置的较小值。模板验收时可传 `--preview-dir`。

## 兼容旧版

显式提供旧版完整SQL三表文件时，仍支持generate_report.py的--input、--mcp-result和旧HTTP GET的--url。原字段结构见result-schema.json，原业务口径见rules-and-report.md。这些不是当前MCP响应结构，不是业务接口认证或分页失败时的回退来源。
