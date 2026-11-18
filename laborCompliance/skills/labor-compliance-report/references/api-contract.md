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

WanScope 当前对该工具配置 `mode=file`，平台在模型上下文截断之前保存原始文本，返回文件清单：

```json
{"mode":"file","saved":true,"complete":true,"path":"tool-results/<session_id>/get-labor-compliance-results_<随机标识>.json","encoding":"text","bytes":12345,"sha256":"<64位原文件哈希>","tool_state":"success"}
```

示例中的字节数、标识及哈希只是格式说明。必须采用本次实际清单；确认 `saved/complete` 为 true、状态 success、encoding 为 text。原文件是三张表的 JSON，直接将清单 path 传给 `--input`，并传实际 `--expected-sha256` 和 `--expected-bytes`。脚本按原始 UTF-8 字节校验，不修改文件；哈希校验是传递完整性校验，不代表上游业务真实性。不能用 Write 抄写、只保存清单或把清单本身当三表，不 Read 整份数据后转抄，不重复请求 MCP。

用户已经提供的三表文件直接 `--input`；已有包装文件继续支持 `--mcp-result`：

- `CallToolResult`：`{"content": [...], "structuredContent": {三张表}, "isError": false}`。
- JSON-RPC 响应：`{"jsonrpc": "2.0", "id": 1, "result": {上述 CallToolResult}}`。

包装处理先拒绝 JSON-RPC error 或 isError=true，再优先读取 structuredContent，仅在缺失时解析 content 中唯一完整三表文本。不合并重复结果，不接受摘要、预览、截断内容。平台保存失败时停止当前生成并说明，不重新调用只为保存结果，也不让模型转抄大段数据。

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

报告使用 Skill 内置 `assets/labor-compliance-template.xlsx`，与用户新版《风控报告模板.xlsx》一致。固定四页顺序为“灵工固定用工特征风控报告”“客户风险汇总”“命中人员明细”“月度证据”。生成时清除模板样例及示例判定公式，预警取上游值；动态扩展客户表、人员表、全部预警月份卡片及完整17字段证据表。客户核查资料和参数位于客户页下方，人员币种、关闭时间及参数从明细Q列起。输出仅为 `.xlsx`，不添加旧版规则页、“核查与参数”页或Markdown报告，也不依赖原模板路径。

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
  "args": ["--input", "<本次清单.path>", "--expected-sha256", "<本次清单.sha256>", "--expected-bytes", "<本次清单.bytes转为字符串>", "--mock-data", "--output", "outputs/demo/report.xlsx"],
  "timeout_seconds": 60
}
```

先调用已绑定 MCP，直接采用平台保存的文件路径执行上述脚本；不要把 Token 或 MCP URL 当作脚本参数。服务默认脚本超时上限为60秒，传300也不会提高上限，较大数据需管理员调整 `WANSCOPE_SKILL_SCRIPT_TIMEOUT`。未验证平台连接和依赖时不能声称生产环境已跑通。

模拟快照为2026-11-05：3客户、23条人员预警、90条月证据；R01为16条、R02为7条。客户A：U40/H12/R02 4/R03命中；B：U20/H8/R02 2/未命中；C：U30/H3/R02 1/未命中。三客户全量近3月金额合计1,278,600.00 CNY，预警人员部分474,600.00 CNY。它们是演示数据，不是从源流水实际跑出的生产统计。

## 校验摘要与预览

脚本版本 `labor-compliance-excel-v1-3-0`。正常生成不传 `--preview-dir`，仍校验三表、重算并扫描全部公式、核对 Excel 金额与精确十进制源数据。stdout 返回一份简洁 JSON，始终保存 `<报告名>.checks.json`。包含输入原文件哈希/大小及是否验证、输出路径/字节数/哈希、批次和规则版本、三表条数、R03/R02计数、分币种全量及预警人员金额、公式错误数、异常和耗时。`elapsed_seconds` 是脚本自身耗时，不是 Agent 全流程耗时。

只在模板/版式改动、新规模首次验收或实际布局疑点时追加 `--preview-dir work/preview`。该模式另外导出四页PNG及原始工作簿 checks.json；常规模式不做逐图 Read、逐行 Excel 转文本或聊天手算。数据异常仍会写入报告，不因关闭PNG而跳过任何数据/公式检查。

脚本只返回文件路径，不负责发布下载URL。WanScope 当前通过会话“文件”面板下载；只有调用方实际提供可用文件引用时才作为链接交付，不将 `outputs/...` 当作公网下载地址。报告目录不创建额外 README。
