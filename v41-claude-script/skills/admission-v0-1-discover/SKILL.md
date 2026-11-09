---
name: admission-v0-1-discover
description: 取全本次审核规则和属性定义，建立“规则引用键”清单、视频目标和标识映射；工具失败先重试一次。
metadata:
  prompt-contract: admission-noshell-v0-1
  prompt-version: "0.1"
---
# admission-noshell-v0-1 / admission-v0-1-discover

# 规则与属性发现

1. 工具名按平台工具列表里的完整名称调用（如 `mcp__ontology-mcp__mcp_list_rule`；本文的 mcp_list_rule 等是简称），名字错了改完整名重发一次，不调用 `reset_tools`。原样使用网关 requestId/domain/scene 调 mcp_list_rule；有分页/更多标记则取完。规则返回后，下一轮再调 mcp_list_property，`input` 传 `{}`（不带 `name`，一次取回全部对象，不按规则推对象清单，也不补查）；两者**不在同一轮并行发出**（实测并行时都返回 BIZ_FAIL“domain 不能为空”）。没有真实返回不得造规则。**同一轮（和 mcp_list_rule 一起）调 inst-rc-rule-mcp 的机构规则查询**，入参只传请求的机构 ID `hrInstId` 原值；返回形如 `{"model":[{"companyName":"Employer.employer_name CONTAINS [修匀]"},{"projectName":"Project.project_name CONTAINS [修匀]"}]}`，每一项是一条机构风控规则（名称：条件）。返回的 `item_count` 应等于 `combine.py props` 打印的“共 N 个对象”。
2. 规则、定义都是落盘文件，返回里只有元数据，**看不到正文是正常的**：把 `path` 交给脚本（`--rules` 后面同时写 mcp_list_rule 与机构规则两个 path，脚本合并，机构规则编号为 `INST-<名称>`），不要 Read/Grep/Write 它们，不要凭空猜对象或属性名；要看内容用 `combine.py rules --rules <路径> [--grep 词]` / `combine.py props --props <路径> [--obj 对象]`。
3. **规则引用键清单由 `combine.py build` 自动提取**（全部 condition，含嵌套 AND/OR/NOT；字面值、关键字、比较值不当属性），后面 input、notes 都以它为准；要核对用 `combine.py rules` 看每条规则的引用键。规则引用而定义里没有的对象/属性由脚本记入 notFoundInDefinition，不用处理；**机构规则引用的键例外**：plan 打印 `INST_KEYS`，定义里没有也要按 label 含义 map 到清单条目后传给 mcp_run_process。
4. **允许进入 input 的键 = 与客户准入有关的规则引用键 ∩ 当次定义返回 + 四个预设标识**。规则范围由你按当次含义判断，明确无关的用 rules.drop 提交原因；脚本不按历史属性表或阶段词自行排除规则，未明确排除则保留。定义有但规则未引用的字段只作证据。
5. **映射（红线 10）由你按本次含义决定**：先用 `combine.py plan` 查看所有规则引用键的 label/comment、规则条件和清单事实；同义原文用 map，需业务判断或枚举选项时用 map 列依据并以 set 提交值和证据（枚举按红线 5 当选择题：有 enum 交所选元素的 key，最高置信度超过 50% 才选，否则留空 null、skip R10），对不上或依据不足则 skip。脚本没有业务属性默认表。属性名和清单编号随时可能变化，不按旧名、标签关键词或固定编号套值；综合属性须查看相关反证，不能只取有利条目。
6. **skip 原因码怎么选**（一个键只占一个码，冲突时 R11 > R14 > R13 > R10；拿不准时：像结果类的默认 R14，需业务判断的默认 R10，明显依赖外部来源的默认 R13）：
   - **R14 结果类**：含义为审核结论、处置、风险等级、是否放行/通过/复核、汇总信号，永远不填。
   - **R13 外部来源**：本次请求、材料、工商都不可能提供的（结算、个人、资金流水、代发、充值、阶段门、复核记录、规则变更、机构自定义规则、名单命中、三方违法/舆情核查、历史结论）。
   - **R10 无口径**：需业务判断、名单或实际核查，而对应清单条目的 desc 或 facts skill“属性填写原则”没给口径的，**默认不填**；分类不明按此，不凭后缀猜。定义自带选项（`enum` 或 comment「枚举 X：」）的枚举键不算“无口径”，按红线 5 当选择题选，选不出过半项才 R10。
   - **R11 定义与规则用法冲突**：属性定义的含义与规则条件里的用法对不上——不传，不硬塞编码或中文名，记 toolIssues。先用 `combine.py rules --grep` 核对原始 condition，是自己看错就直接纠正，不记工具问题。
7. **用工场景不用你判断**：`Employer.usage_scenario` 已预设取项目内容 projCont 原文（见下文“标识”）。所属行业、实际业务类别等其他分类键仍按 facts skill“一般行业兜底”判断。
8. 清单里规则没引用的条目不因此跳过，仍要提取到 input-extract-detail.json。

## 标识

四个标识和用工场景已预设（见主提示词红线 2，配置在 catalog 的 `scripts/run_process_required.json`），build 自动传入，**不用你映射**：

| 请求值 | 清单条目 | 传入的键 |
|---|---|---|
| entpId 企业 ID | A01 | `Employer.employer_id` |
| entpName 企业名称 | A02 | `Employer.enterprise_name` |
| rqId 需求 ID | A03 | `Demand.demand_id` |
| hrInstId 机构 ID | A04 | `LaborAgency.agency_id` 与 `Agency.agency_id`（同值） |
| projCont 项目内容 | A08 | `Employer.usage_scenario`（必填，原文照传，不做枚举转码） |

- 四个 ID 不可互换；脚本不允许把预设键改映到别的条目，也不允许 skip；审核单 ID 不用企业 ID 代替；请求没有值不编造。
- 用工场景：不要对它提交 map/skip/set；提交了 build 不退回，只打印 `PRESET_OVERRIDE_IGNORED` 并照旧取 projCont 原文。
- 预设之外，定义里若还有含义**确实相同**的别的属性，可以再用 `map` 映射到同一个条目，同值同传；一般不用。`combine.py plan` 的“标识候选”只是提示。
- `build` 打印 `PRESET_UNDEFINED` = 某预设键本次定义里没有（仍照传）；预设键请求没值就不传，只记 notes.toolIssues，不用处理。打印 `FALLBACK_FILLED` = 某规则引用的枚举键没取到值、已按配置兜底传入（只记 notes.toolIssues，不用处理，不写进摘要依据）。预设键名跟不上本体改名时，只改配置，不改提示词或代码。
- 引擎自己的入参键可能比定义多，第一次调用前无从得知：引擎返回 `ruleCheckList=null` 并在 `failures` 里点名“取不到 X.y”时，按 output skill 第二节补一条 `force` 映射并重试一次。**不要事先凭记忆或旧版本去猜要不要传**。

## 失败

**mcp_list_rule / mcp_list_property 报错或 ToolNotFound：必须用原参数、原工具名真实重试一次**。机构规则查询失败或返回为空：重试一次，仍失败在 toolIssues 记工具原话，只用 mcp_list_rule 的规则继续，不使整案退出。仍失败，或缺 domain/scene（不重试残缺请求），走 output skill 的“审核未完成”。部分定义缺失不使整案退出。
