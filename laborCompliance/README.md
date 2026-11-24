# 灵工风控报告 Agent

当前版本 `labor-compliance-excel-v1-4-7`，通过 ContextForge 读取 DEV 或 Fake API 的结果，输出 Excel。

- [主提示词](主提示词_v1-0-0_编排版.md)
- [Skill](skills/labor-compliance-report/SKILL.md)
- [部署包](skills/labor-compliance-report/Archive.zip)
- [接口及任务清单格式](skills/labor-compliance-report/references/api-contract.md)
- [内置四页模板](skills/labor-compliance-report/assets/labor-compliance-template.xlsx)

Agent 使用网关注入的 `offlineSqlResults` 读取固定用工预警的人员明细、客户汇总和月度证据。MCP工具 `get-labor-compliance-results` 使用以下地址。
```text
http://10.168.1.100:4445/servers/ec76ef3c8c3f4be6b64c463a2261b256/mcp
```

两套 MCP 的分页请求均发送 `execId`、`bizKey`、`pageNo`、`pageSize`。DEV 按 `execId` 查询已执行任务。MySQL 版按 `bizKey` 读取当前结果表，回传调用方的 `execId`。两套服务均使用 ContextForge Bearer 认证。 [接口契约](skills/labor-compliance-report/references/api-contract.md)

Agent先取每项任务的第一页。文件模式页使用MCP清单提供的path，sha256/bytes为可选元数据。完整内联JSON原样保存后，页引用只需mode=inline和path。两种模式均调用exec_results.py校验业务响应和分页，按实际pageSize取完剩余页后，用generate_report.py --exec-manifest生成。

报告沿用四页模板。固定用工预警总览展示五项业务指标，客户页展示指定的八个结果字段和五个留空列。人员明细保留原始列。月度证据展示指定字段，合并组内重复的标识列，逐月保留证据行。成功空表显示0行。脚本摘要记录报告类型、任务行数及是否有实际月度证据行。

分页结果导出使用 Python 3.9+ 和部署包 `vendor/` 中随附的 openpyxl 及 et_xmlfile，运行时可离线导出。预览及旧快照入口使用 Node.js 和 @oai/artifact-tool，路径配置在 Skill 根目录的 runtime.json。上传 `Archive.zip` 更新 `labor-compliance-report-v1`，绑定到 Agent，确认已开启 RunSkillScript 并同步主提示词。取数前执行 `generate_report.py --version` 确认安装版本。

旧SQL快照仍支持 `--input`、`--mcp-result`、`--url`，原示例为旧版快照报告。

## 本地重打包

在 `skills/labor-compliance-report` 目录执行下列命令。`vendor/` 已包含 openpyxl 和 et_xmlfile 及其许可证，重打包无需联网。

```sh
zip -q -r -X -FS Archive.zip SKILL.md agents assets/labor-compliance-template.xlsx \
  references runtime.json scripts vendor \
  -x '*/.DS_Store' '*/__pycache__/*' '*.pyc' '*.pyo'
unzip -tq Archive.zip
```
