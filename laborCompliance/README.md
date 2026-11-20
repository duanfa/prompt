# 灵工风控报告 Agent

当前版本 `labor-compliance-excel-v1-4-2`，通过ContextForge读取DEV的离线SQL执行结果，输出Excel。

- [主提示词](主提示词_v1-0-0_编排版.md)
- [Skill](skills/labor-compliance-report/SKILL.md)
- [部署包](skills/labor-compliance-report/Archive.zip)
- [接口及任务清单格式](skills/labor-compliance-report/references/api-contract.md)
- [内置四页模板](skills/labor-compliance-report/assets/labor-compliance-template.xlsx)

Agent读取网关注入的 `offlineSqlResults`。支持固定用工预警的人员明细、客户汇总和月度证据，也兼容历史灵工分期三表。MCP工具 `get-labor-compliance-results` 使用以下地址。
```text
http://10.168.1.100:4445/servers/ec76ef3c8c3f4be6b64c463a2261b256/mcp
```

上游已改为 `POST http://dtsp-dev-api.10000da.vip/bdp-ontology/api/v1/ontology/sql-task/exec/data`。参数只有execId/pageNo/pageSize，保留完整业务包装及动态rows。文档使用code=OK/msg/data，DEV实测错误使用code=200/message/model/succeed；code=200也可能succeed=false，不能单看code判断成功。工具不再调用模拟容器，不接收ds/customer_id/currency。DEV业务登录认证已取消，ContextForge仍使用Bearer认证，凭据不进入Skill。

Agent先取每任务第一页，通过MCP文件清单保存路径和哈希；写小任务清单并调用exec_results.py读取分页摘要；按实际pageSize取完剩余页后，用generate_report.py --exec-manifest生成。全程不通过模型转抄rows，不把单个文件的complete当成所有分页已齐。

报告沿用四页模板。固定用工预警的三张结果表按原始列写入对应页，成功空表显示0行。历史灵工分期的月度证据页标为“未提供”。脚本摘要记录报告类型、任务行数及是否有实际月度证据行。

依赖Python3.9+、Node.js和@oai/artifact-tool。WanScope隔离运行使用Skill根目录runtime.json中的部署机路径。上传 `Archive.zip` 更新 `labor-compliance-report-v1`，绑定到 Agent，确认已开启 RunSkillScript 并同步主提示词。取数前执行 `generate_report.py --version` 确认安装版本。

旧SQL快照仍支持 `--input`、`--mcp-result`、`--url`，原示例为旧版快照报告。
