---
name: admission-v0-1-catalog
description: 提取清单：以人工核对过的清单为全量提取目标，规定 input-extract-detail.json 的格式、来源写法和未提取原因码。
metadata:
  prompt-contract: admission-noshell-v0-1
  prompt-version: "0.1"
---
# admission-noshell-v0-1 / admission-v0-1-catalog

# 提取清单与 input-extract-detail.json

**目标：清单里的每一条都要有归宿——取到值（写明来源和证据），或取不到（写明原因码和具体原因）。不允许沉默漏项。** 清单与 input 无关：清单条目不论规则是否引用都要提取；只有“规则引用键 ∩ 有清单条目支撑的键 + 固定标识”才会进入 input。

## 一、本 skill 目录里的文件

| 文件 | 用途 |
|---|---|
| `scripts/detail.py` | 明细脚本：`init` 预填、`fill` 合并你读材料得到的行并重算派生、`recheck` 提交二次识别结果、`compare`（只读，12 项比对）、`show`、`finish` |
| `scripts/combine.py` | 组装脚本：`plan`（只读，列出键与条目）、`build`（按你基于当次定义提交的 map/skip/set 组装并校验，生成并校验 `input-combine.json`，打印 `CHECK`，映射落盘 `work/<id>/key-map.json`）、`validate`；只读摘要 `rules`、`props`；`result`（从引擎原始返回过滤出命中规则，写 `work/<id>/hit-rules.json`，打印计数、漏斗结论和 `NEED_BASIS`）；`summary`（只读 hit-rules.json，校验依据/下一步草稿，渲染 summary，打印最终结果 `FINAL`）。**业务属性映射和判断由模型决定；脚本不设默认业务属性表或派生公式** |
| `scripts/combine_tool.py`、`scripts/combine_config.json` | 上面两个脚本用的库和配置 |
| `scripts/run_process_required.json` | 调 mcp_run_process 必带的预设键（四个标识 + 用工场景，无兜底）与枚举键兜底值，build 读取，你不用读 |
| `extract-items-checked.json` | **清单（唯一数据源）**：人工核对过的全部条目（id/group/name/desc，条数以文件为准；可选 `derive` 声明派生、`notice`=[{condition,desc}] 声明 summary“注意”里的提醒——condition 由模型在 summary 草稿里按语义判断是否成立，desc 原样告知用户）。改清单只改它；脚本按条目名称归组，在补充材料里插入/调整条目不必改脚本 |

脚本都由 RunSkillScript 运行（只用标准库）。`RunSkillScript` 报路径不存在 / 没有这个工具时按主提示词第六节“技能配置异常”处理，不得改为手写明细。

**用工场景预设**：`Employer.usage_scenario` 必填，和机构 ID 一样由 build 从请求 `projCont`（A08 项目内容）原文自动传入（`run_process_required.json`），不做枚举转码，你不映射、不分类、不 set；提交了也只打印 `PRESET_OVERRIDE_IGNORED` 并忽略。请求没有 projCont 时不传。

**机构规则输入必填**：inst-list-rc-rules 返回的 model 表达式与 mcp_list_rule 的 condition 一起交给 plan/build/validate。参与审核的机构规则引用属性必须出现在 input-combine.json 的 refKeys、entities 和 input 中，并保留引用规则原文及条目证据；定义未返回也照传。属性仍按本次含义 map/set，不新增固定业务属性表。缺项时脚本报 `INST_REQUIRED_MISSING`、不输出可调用的 INPUT；unfilled 或 notFoundInDefinition 不能代替这些必填输入。

## 二、明细条目格式（文件由 `detail.py` 写，路径 `work/<requestId>/input-extract-detail.json`）

清单全部条目的顺序、齐全、五字段由脚本保证。你提交 `[id, value, text]`，脚本按下面的规则校验（不符会 REJECT）：

1. text 里**不写** `Y｜`/`N｜`：有值时 text=`来源｜证据`（脚本拼成 `Y｜来源｜证据`），取不到时 value=null、text=`Rxx｜具体原因`（脚本拼成 `N｜Rxx｜具体原因`）。
2. **任何字符串里不得出现 ASCII 双引号和反斜杠**，引用原文引号一律写成「」或 “ ”。
3. **value 是字符串或 null**：数字写 `"123"`，布尔写 `"true"` / `"false"`，日期写原文或按 desc 要求的格式，文本逐字原文。**取不到一律 `null`**（不写 `"NULL"`、空串、`"无"`、`0`、`false` 占位）。
4. **来源与证据**：来源 = 请求字段名 / 材料中文名＋文件字段＋页码＋栏位 / 视频文件＋时间点 / 图片第几张 / `工商:<D|B|T>.<字段>` / `派生:<依据条目ID>`。证据 = 原件栏位原文、回答原话、工具字段原值，或算式＋两侧原文；只写最终事实，不含推演。PDF/图片来源必须含栏位原文（PDF 含页码），只写“显示/可读/一致”不算。取不到的具体原因点名材料、页码或工具、读到什么/没读到什么；“无”“未提供”“略”“看不清”不合格。
5. 一个条目有多个来源时：value 取第一个成功来源（顺序 D、B、T），证据段列出各接口原值；值不一致时 value 取 null、原因码 R09，并写入 notes.conflicts。
6. false 与 N 的界线：只有“材料已读成功、范围足以覆盖、明确确认不存在”才是 `"false"`；“没看到”一律 `null` + N。

## 三、原因码（N 行必用其一；以本表为唯一原因码表）

| 码 | 含义 | 使用条件 |
|---|---|---|
| R01 | 请求未提供 | 附件清单/请求字段里没有该材料或字段（含 URL 失效，见“附件可用性说明”） |
| R02 | 材料不可读 | 已提供但当前实际无法查看；原因写具体现象。不得仅因日志 `[unknown]` 使用 |
| R03 | 材料可读但无此内容 | 材料看得清，但该栏位/条款原文没有载明（写看了哪页哪栏） |
| R04 | 仅有 URL，未验证 | 官网/公众号等只给地址，不能证明可打开 |
| R05 | 视频读取失败 | 超时/无证据/排队超时；写实际尝试次数 |
| R06 | 判断不确定 | 视频回答含疑似、可能、无法判断等推测措辞或未单独问过该项；图像/材料类判断（原件扫描、伪造嫌疑、招牌是否匹配等）拿不准也用此码 |
| R07 | 工商无数据 | 工具失败、未查到、或返回该字段为空 |
| R08 | 定义未返回 | 参数在规则里出现但 mcp_list_property 未返回该属性（仅影响 input 键；事实本身仍可取值） |
| R09 | 来源冲突未裁定 | 两个同级来源给出不同事实，无法裁定；双方事实写 conflicts |
| R10 | 无业务判断口径 | 需业务判断/名单/外部分类，本流程没有完整口径（牌照、行业禁入、灰名单、敏感场景等）；不得猜测，不得填 false |
| R11 | 定义含义与规则用法冲突 | 属性定义的含义与规则条件里的用法对不上 |
| R12 | 依赖的源事实缺失 | 派生值的某侧原文是 N；写缺哪一项（条目 ID） |
| R13 | 外部来源，本次无 | 违法犯罪/舆情三方核查、结算、个人、资金流水等，本次请求、材料、工商都不可能提供 |
| R14 | 结果类 | 审核结论、处置、风险等级等由引擎产出，永远不填 |
| R15 | 与本次目标无关 | 材料已提供但与任何清单条目无关，仅记录，不精读 |

## 四、规则引用但取不到的键（只在 combine 里登记）

清单只是抽取的原始数据，和规则、属性不强绑定，所以**不维护任何“固定不填键”名单或“条目→属性”对照表**；清单条目 `desc` 里的「Xxx.yyy」属性名只是历史提示。本次规则**实际引用**、但按语义对不上任何清单条目的键，不进明细，也不进 input：在 build 的 `skip` 里按原因码声明（怎么选码见 discover skill 第 6 条），脚本登记到 `input-combine.json` 的 `unfilled`，并在 notes.unresolvedProperties 按实体＋原因码合并成行（R14 只一行）。映射了但主条目为 N 的键，脚本沿用主条目的码。没有任何规则引用的属性不登记；定义里没返回的键由脚本写 notFoundInDefinition。

## 五、一致性硬规则

1. combine 里每个有 value 的属性都必须能追到明细条目：主条目有值时 value 是它的类型转换（见 facts skill）；需要业务判断或多个条目综合判断的属性，value 按本次属性定义及规则含义由模型给出，map 里列出全部依据，用 `set` 提交，value_source 以 `派生:` 开头。
2. 派生条目（source 写 `派生:<依据条目ID>`）：任一依据条目为 null，则该条目必为 `N｜R12｜缺 <依据条目ID>`，不得用别的值顶替（脚本写的派生行自动处理；你写的派生行出现 STALE 时重判）。
3. 同一事实在 notes 与 items 里不得矛盾；N 条目的原因必须与 materials 状态、视频原话、工商返回一致（R01↔materials 未提供；R02↔不可读且有具体现象；R04↔仅URL；R05↔有尝试次数；R06↔视频原话含推测措辞或该项未单独问过）。
4. 禁止为了让 N 变 Y 而推测；红线 3、4、5 照常适用。身份证号码不抄录（清单没有此项）；开户凭证账号（D10）按清单要求提取，**value 和 source 的证据段都完整抄录原件账号栏的账号，不脱敏、不加星号、不截断**；原件上有看不清的位数时不补全、不猜，整条按 N 处理（R03 或 R06，写明哪几位看不清）。
5. **工商与原件识别的比对**由 `detail.py` 完成（12 项，结果写 J34 与 notes.conflicts，见 materials skill 第二步半）：不一致的项必须回看原件二次识别（`recheck`），工商值不覆盖原件识别值。
6. 行业代码/名称只作原文事实，不映射禁入或敏感（R10）；工商没有牌照字段，**不等于没有牌照**；单位未明示不自补，原样记。
