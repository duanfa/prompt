# 劳务转灵工报告 Agent

目录参照 `enterpriseAcess`：Agent 默认通过已接入 MCP 取数，Skill 负责计算结果校验与 Excel 模板填充。报告只输出 `.xlsx`。当前版本契约为 `labor-compliance-excel-v1-3-0`，主提示词保留原文件名以便原位更新。

- Agent 主提示词：[主提示词_v1-0-0_编排版.md](主提示词_v1-0-0_编排版.md)
- Skill：[skills/labor-compliance-report/SKILL.md](skills/labor-compliance-report/SKILL.md)
- Excel 模板：[labor-compliance-template.xlsx](skills/labor-compliance-report/assets/labor-compliance-template.xlsx)
- Excel 示例：[labor-compliance-20261105.xlsx](examples/labor-compliance-20261105.xlsx)

内置模板已原样替换为 `用工合规/风控报告模板.xlsx`，按用户新版保留四页顺序：灵工固定用工特征风控报告、客户风险汇总、命中人员明细、月度证据。生成时清除全部样例记录和公式，保留原有标题、栏目次序及蓝灰配色，按数据量扩展表格和全部预警的月度卡片。客户核查资料、参数和人员状态计数放客户页下方；人员币种、关闭时间及完整参数从明细Q列起；全部17个SQL证据字段放月度卡片下方。不依赖原模板所在位置。

## 运行

在 Agent 中绑定 `labor-compliance` MCP（Streamable HTTP，Bearer Token 由平台管理）：

```text
http://10.168.1.100:4445/servers/ec76ef3c8c3f4be6b64c463a2261b256/mcp
```

工具名 `get-labor-compliance-results`，接受可选 `ds / customer_id / currency`。当前默认且仅支持 `20261105` 模拟批次。MCP 已配置文件返回：平台保存原始三表 JSON，Agent 把清单 path、sha256、bytes 直接交给脚本，不通过模型复制数据。接入详情见 [MCP 及结果口径](skills/labor-compliance-report/references/api-contract.md)。

Python 3.9+、Node.js、`@oai/artifact-tool`。脚本自动识别 Codex 捆绑运行时，也可以通过 `--node`、`--node-modules` 或 `LABOR_REPORT_NODE`、`LABOR_REPORT_NODE_MODULES` 指定。部署时需一同携带模板、references 和 scripts。

WanScope 的 `RunSkillScript` 使用 `python -I`、清空环境并重设 HOME；脚本已兼容隔离模式。管理员需在 Skill 根目录加入指向真实部署依赖的 `runtime.json`，或提供 `--runtime-config work/runtime.json`；详见[运行时部署](skills/labor-compliance-report/references/api-contract.md#运行时部署wanscope)。仅上传 Skill 并不会安装 Node 和 artifact-tool。

[Archive.zip](skills/labor-compliance-report/Archive.zip) 为本次 MCP 版 WanScope 部署包，ZIP 根目录包含 SKILL.md，排除缓存、`__MACOSX` 和旧压缩包，包含模板、scripts、references、agents 及本机已验证 Node/artifact-tool 路径的 `runtime.json`。迁移到其他机器时由管理员修改运行时路径；不打包 Token、`node_modules` 或历史报告。上传后需同步更新 Agent 主提示词并保持 MCP 绑定；本项目修改不会自动更新 WanScope 已安装版本。

```bash
cd /Users/duanfa/wanlianyida/prompt/laborCompliance
python3 skills/labor-compliance-report/scripts/generate_report.py \
  --input 'tool-results/<会话标识>/<本次结果文件>.json' \
  --mock-data \
  --output outputs/demo/report.xlsx
```

`--mcp-result` 接受完整 JSON-RPC 响应或其 `result` 中的 CallToolResult；先拒绝错误，再提取三张表。若已经保存原三表，使用 `--input /path/to/results.json`。模拟文件需加 `--mock-data`。用户明确指定其他 GET 来源时仍可用 `--url`，不能把 MCP URL 传入此参数，也不自动回退到 HTTP 或样例。脚本始终输出校验摘要并保存同名 `.checks.json`；有 MCP 清单时增加 `--expected-sha256`、`--expected-bytes`。仅需视觉验收时才用 `--preview-dir /tmp/labor-report-preview` 生成 PNG。三表内部仍按 SQL 原结构，不增加报告字段。

模板默认可直接复用。`--template` 用于同版式模板替换，必须保留原工作表名称和卡片/表头位置；任意新模板需要同步修改填充映射。

金额按 SQL 定义：客户全量有效发放金额与预警人员金额分列，不重复相加；多币种不混加。客户表和人员表的黄色区域分别维护本对象的核查信息；客户页下方按客户ID＋币种统计人员状态，表格排序后仍对应。总览展示数据异常；空返回不会残留模板演示记录，也不代表全部客户无风险。
