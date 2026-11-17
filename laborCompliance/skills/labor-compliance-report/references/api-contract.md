# MCP 及结果口径

## MCP 取数（默认）

| 配置项 | 值 |
| --- | --- |
| 服务名 | `labor-compliance` |
| 工具名 | `get-labor-compliance-results`（可能带平台命名空间前缀） |
| MCP URL | `http://10.168.1.100:4445/servers/ec76ef3c8c3f4be6b64c463a2261b256/mcp` |
| 传输 | Streamable HTTP |
| 认证 | Bearer Token，由平台连接配置管理，Skill 不保存或生成 Token |
| 数据性质 | 模拟数据，默认且仅提供批次 `20261105` |

工具注册原名为 `get_labor_compliance_results`，网关实际暴露的名字是 **`get-labor-compliance-results`**；调用时从当前工具列表确认完整名称，不猜测平台前缀。Agent 使用平台已接入的工具，脚本只负责读取保存结果和生成 Excel，不访问 MCP 或管理凭据。

工具参数 `ds / customer_id / currency` 均可省略，传入时为非空字符串。默认参数 `{}` 返回全部范围。仅传用户明确提供的筛选，不自动使用系统当天日期。

```json
{
  "ds": "20261105",
  "customer_id": "C-DEMO-001",
  "currency": "CNY"
}
```

以上为筛选客户 A 的参数示例，不是所有报告的固定参数。客户和币种精确匹配，三表同步裁剪；当前不分页。未知客户/币种成功返回三张空表；格式不合法或未知批次为调用失败。

### 将 MCP 返回交给脚本

保存完整 `tools/call` 返回为工作区 JSON 文件，然后使用 `--mcp-result work/mcp-result.json`。脚本接受以下两层形态：

- `CallToolResult`：`{"content": [...], "structuredContent": {三张表}, "isError": false}`。
- JSON-RPC 响应：`{"jsonrpc": "2.0", "id": 1, "result": {上述 CallToolResult}}`。

处理顺序：遇到 JSON-RPC `error` 或 `isError=true` 立即失败；成功时优先取 `structuredContent`，仅在其不存在时解析 `content` 中一份完整三表 JSON 文本。不合并两份相同结果，不解析展示摘要或截断内容。结构异常仍由三表校验拒绝，不能从错误结果凑出空表。

若平台直接提供原三表对象，保存后使用 `--input work/results.json`。已有用户快照直接复用，不为出报告重复调用 MCP。保存时保持全部字段、行和定点字符串，不让模型手工抄写或重新计算。

**当前 MCP 必须加 `--mock-data`**。HTTP 的 `X-Mock-Data` 响应头不会自动随三张表传入 MCP；脚本不通过客户名称或 ID 猜测数据性质。若日后切换真实数据，应同步更新服务描述、Agent 主提示词和 Skill 中的模拟约定。

401、未绑定工具、网络故障、工具失败或无法取得完整返回时停止，并报告实际原因；不自行换源、获取 Token、安装客户端或重复搜索工具。连接配置由管理员维护，不将 Token 写入 Skill、提示词或报告。

## 三表结构

数据对象顶层为三张 SQL 表名，各值为完整行数组：`dws_lgw_risk_customer_warn_sum`、`dws_lgw_risk_worker_warn_detail`、`dwd_lgw_risk_worker_warn_month_evidence`。没有 `data` 包装或报告结论字段。保留原 SQL snake_case 字段及 `ds` 分区字段。全部字段的类型和原 SQL 注释见 [result-schema.json](result-schema.json)。

| SQL 类型 | JSON 表达 |
| --- | --- |
| STRING | 字符串，标志字段为 `"1"` / `"0"` |
| BIGINT | 整数，不能当作字符串或布尔值 |
| DECIMAL(18,2) | 金额定点字符串，例如 `"6000.00"` |
| DECIMAL(10,6) | 比率定点字符串，例如 `"0.300000"`，显示为30.00% |
| DATETIME | `yyyy-MM-dd HH:mm:ss`，演示按北京时间理解 |
| 未填写的核查信息 | `null`；不能写成“无风险”或自动填入结论 |

报告脚本也接受合法 JSON 数字形式的 DECIMAL，内部使用 Decimal 计算，推荐接口仍用字符串保精度。

用户明确提供普通 HTTP 来源时，原有 `--url` 继续支持 GET 三表接口；成功应为200，错误对象 `error/message` 不代表空结果，`X-Mock-Data: true` 自动标记模拟。`--url` 不支持 MCP 协议地址。默认通过平台 MCP 工具取数，不访问本机 localhost 或网关内部容器地址。

## 关联键和统计范围

- 客户汇总唯一键：`ds + customer_id + currency`，规则版本为同批次快照属性。
- 人员主键：`warn_id`；每客户＋灵工＋币种只保留最高主要规则，R02 已包含 R01。
- 月证据唯一键：`warn_id + obs_month`；关联时还要核对 `customer_id / worker_id / currency / rule_version / ds`，不能只按 `worker_id` 关联。
- `ds` 为评估日期，R01/R03 取评估日前最近3个完整自然月，R02取6个完整月，均不含评估当月。报告基准日使用 ds，不用系统当天日期改写历史报告。
- 同一批次报告不混合规则版本。多个批次分别出报告，不能重复累计同一预警的历史快照。
- 完整报告覆盖已返回的全部已评估客户，包括未命中 R03 或没有人员预警的客户；不凭明细是否为空删除客户。

## 已知来源差异

来源为用户的 `bdata.sql` 与《劳务转灵工风控规则.xlsx》：第一页“风控规则”，第二页“风控报告样式”。完整 SQL 副本保存在模拟接口的 `schema/bdata.sql`。本 Skill 字段字典由该 SQL 的三张表及分区字段逐项生成。

第二页的客户金额公式仅汇总预警人员金额，但 SQL 的 `involved_amount` 定义为客户全部有效流水累计。本实现按用户指定的 SQL 结构与字段定义，区分客户全量金额和其中预警人员金额，保留样例的多客户报告栏目。

报告样例存在“列1～列5”等占位列及“后续措施”人工信息，本接口未定义后续措施字段；映射到已有状态、负责人、结论、依据时使用准确的字段名，不补造字段或事实。

报告使用 Skill 内置 `assets/labor-compliance-template.xlsx`，由原工作簿保留规则内容与版式生成，已清除样例数据和失效命名表公式。输出为 `.xlsx`，动态扩展客户与人员表，并增加完整“月度证据”和“核查与参数”页；不再生成 Markdown 报告。模板不依赖原 Documents 文件的位置。

## 运行时部署（WanScope）

`RunSkillScript` 以 `python -I` 执行管理员安装的 `.py`，工作目录为 workspace。脚本已兼容同目录导入，不需要在工作区创建模块副本。该工具会清空环境变量、把 HOME 指向 workspace，只允许相对路径参数，因此不能用继承的 `LABOR_REPORT_*` 或外部绝对路径参数配置依赖。

由管理员准备 Node.js 和 `@oai/artifact-tool`，将 **服务进程实际可访问的路径** 写入 Skill 根目录 `runtime.json` 后重新上传 Skill。配置格式：

```json
{
  "node": "/deployment/node/bin/node",
  "node_modules": "/deployment/node/node_modules"
}
```

以上仅说明格式，需替换为部署机真实路径。`node_modules` 下必须存在 `@oai/artifact-tool/`；配置中的相对路径按 runtime.json 所在目录解析。不要将 `node_modules` 打进 Skill 包。管理员也可把配置放在工作区，然后调用时增加 `["--runtime-config", "work/runtime.json"]`。配置优先级为命令行 `--node/--node-modules`、配置文件、环境变量、Codex 默认路径。

WanScope 示例（以管理员平台登记的实际 Skill 名称替换 `labor-compliance-report-v1`）：

```json
{
  "script": "labor-compliance-report-v1/scripts/generate_report.py",
  "args": ["--mcp-result", "work/mcp-result.json", "--mock-data", "--output", "outputs/demo/report.xlsx"],
  "timeout_seconds": 60
}
```

先调用已绑定 MCP、通过平台文件工具保存完整返回，再执行上述脚本；不要把 Token 或 MCP URL 当作脚本参数。服务默认脚本超时上限为60秒，传300也不会提高上限，较大数据需管理员调整 `WANSCOPE_SKILL_SCRIPT_TIMEOUT`。未验证平台连接和依赖时不能声称生产环境已跑通。

模拟快照为2026-11-05：3客户、23条人员预警、90条月证据；R01为16条、R02为7条。客户A：U40/H12/R02 4/R03命中；B：U20/H8/R02 2/未命中；C：U30/H3/R02 1/未命中。三客户全量近3月金额合计1,278,600.00 CNY，预警人员部分474,600.00 CNY。它们是演示数据，不是从源流水实际跑出的生产统计。
