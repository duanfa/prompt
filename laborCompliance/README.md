# 灵工风控报告 Agent

当前版本 `labor-compliance-excel-v1-4-5`，通过 ContextForge 读取 DEV 或 Fake API 的结果，输出 Excel。

- [主提示词](主提示词_v1-0-0_编排版.md)
- [Skill](skills/labor-compliance-report/SKILL.md)
- [部署包](skills/labor-compliance-report/Archive.zip)
- [接口及任务清单格式](skills/labor-compliance-report/references/api-contract.md)
- [内置四页模板](skills/labor-compliance-report/assets/labor-compliance-template.xlsx)

Agent读取网关注入的 `offlineSqlResults`。支持固定用工预警的人员明细、客户汇总和月度证据，也兼容历史灵工分期三表。MCP工具 `get-labor-compliance-results` 使用以下地址。
```text
http://10.168.1.100:4445/servers/ec76ef3c8c3f4be6b64c463a2261b256/mcp
```

两套 MCP 的分页请求均发送 `execId`、`bizKey`、`pageNo`、`pageSize`。DEV 按 `execId` 查询已执行任务。MySQL 版按 `bizKey` 读取当前结果表，回传调用方的 `execId`。两套服务均使用 ContextForge Bearer 认证。 [接口契约](skills/labor-compliance-report/references/api-contract.md)

Agent先取每任务第一页，通过MCP文件清单保存路径和哈希；写小任务清单并调用exec_results.py读取分页摘要；按实际pageSize取完剩余页后，用generate_report.py --exec-manifest生成。全程不通过模型转抄rows，不把单个文件的complete当成所有分页已齐。

报告沿用四页模板。固定用工预警的三张结果表按原始列写入对应页，成功空表显示0行。历史灵工分期的月度证据页标为“未提供”。脚本摘要记录报告类型、任务行数及是否有实际月度证据行。

分页结果导出使用 Python 3.9+ 和 openpyxl。预览及旧快照入口使用 Node.js 和 @oai/artifact-tool，路径配置在 Skill 根目录的 runtime.json。上传 `Archive.zip` 更新 `labor-compliance-report-v1`，绑定到 Agent，确认已开启 RunSkillScript 并同步主提示词。取数前执行 `generate_report.py --version` 确认安装版本。

旧SQL快照仍支持 `--input`、`--mcp-result`、`--url`，原示例为旧版快照报告。
