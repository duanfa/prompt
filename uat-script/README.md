## 当前修订：stdin 错误码覆盖全部子命令、NEED_VALUE 口径统一、枚举只认原值（2026-11-10，版本仍为 0.1）

- **stdin 解析统一到 `scripts/stdin_json.py`**：此前本目录 `detail.py` 实际并未实现下面描述的 `STDIN_ROWS_CLOSED`/`STDIN_JSON_INVALID`（测试先行、代码未跟上），`combine.py build`/`summary` 解析失败也只有一句旧报错。现在 detail.py init/fill/recheck/verify 与 combine.py build/summary 共用：合法 JSON 原样接收；同层重名键、顶层不是对象按语法失败计；只修 fill 的 rows 少 `]` 这一种；其他一律 `STDIN_JSON_INVALID <步骤>`（带“同一步骤连续第 N 次”）。计数落盘 `work/<rid>/.stdin-failures.json`，按步骤分开，解析成功清零。连续第二次：fill/recheck/verify/init/build 打印 `STDIN_GIVE_UP`，按主提示词第六节「stdin 语法错误的有限恢复」收尾、不调用引擎；summary 打印 `WARN STDIN_LENIENT`，由脚本生成依据/下一步并照常出 FINAL。契约外的顶层键只打印 `WARN STDIN_UNKNOWN_KEY` 并忽略（不新增拒绝）。
- **discover skill 第 38 行**改为与主提示词第 7 条、output skill 一致：用工场景 NEED_VALUE 只提醒、不拦门禁，`GATE: READY` 即调引擎。
- **枚举不做关键词/同义归一**：本目录 combine.py 没有 `enum_alias_pick`，`enum_check` 只认与编码或中文选项完全一致的值；原文→选项由模型按语义判断后 set 提交。测试里依赖同义归一的断言已改为“不归一”（「公司不从事集资」「为客户提供理财产品推广服务」「营业期限至2030年到期」「即将到期」「基本存款账户」均不归一）。
- catalog `Archive.zip`（新增 `scripts/stdin_json.py`，不含 `__MACOSX`/`.DS_Store`）、discover/output `SKILL.md.zip` 重打包；`runtime_manifest.json` 重算（runtime 54,388 → 54,861，script 194,863 → 204,087，script 按 scripts/*.py 计）。**仅本地验证，未部署。**

## 当前修订：job 216 的 stdin 括号错误恢复与有限重试（2026-11-10，版本仍为 0.1）

216 连续 29 次 fill 都因 rows 数组在 notes 前少一个 `]` 失败，模型反复改写最后一行说明，错误结构没有变化。`detail.py` 现在只在完整三元组数组、顶层契约、无重名键和全文解析均通过时补这个括号；所有 value/text 保持原样，打印 `WARN STDIN_ROWS_CLOSED` 并继续处理。其他损坏仍拒绝，打印稳定错误码 `STDIN_JSON_INVALID`。主提示词与 catalog skill 规定有限恢复或拆分小批提交，同一步骤连续第二次语法失败即提交审核未完成。

历史入参只读重放：216 的 29/29 份失败入参均恢复解析，93 行事实和证据保持原样；221 的 5 份非空合法脚本 stdin 保持原样。详见 [诊断与证据](../../artifacts/ontology-job-216-loop-20261110/diagnosis.md) 和 [平台接入说明](integration/防循环与结构化stdin接入.md)。脚本边界修复不能替代平台按步骤识别无进展失败并硬终止；结构化 stdin 和平台终止本次只提供接入方案。

更新主提示词、catalog SKILL.md、catalog Archive.zip、runtime_manifest.json；新增解析边界与实际落盘回归。**仅本地验证，未部署、未重跑远端任务。**

全量 185 项，184 通过；唯一失败为旧测试访问已删除的 B24，在恢复修改前解析入口的临时副本中同样复现。新增 7 项测试全部通过。完整输出和复现记录见上述诊断目录。

---

## 历史修订：业务分类命中加固（2026-11-09，版本仍为 0.1）

上一条（codex）只在 facts skill 里加了分类口径。复盘 job 179/168/173（均为该版本）：模型三次都选对了（mining_underground / debt_collection / headcount_rebate），但 **173 的分类没进引擎**，传销规则没跑，只得到转人工。根因在脚本，不在模型：

1. **只交 set 不交 map → 静默丢弃**：build 先判「无映射」记 R10，根本没走到 set 分支（plan 只打印一行 UNDECIDED）。首轮只交 set 时更是直接 NO_MAP。
2. **「set 来源必须与 map 一致」反复退回**：用工场景默认映射 A08，模型依据写 A08,A07 就被拒；三个 job 各多跑 2–4 轮 build，每轮重写 stdin 都可能丢键（set 原来每次必须重提）。

改法分三层：

- **脚本兜底（combine.py）**：set 依据里的条目就是映射，不必另写 map；依据比 map 多时自动同步（`MAP_SYNCED`），只有同一次提交里 set 少引了 map 的条目才退回（保留防挑证据）；set 落盘（`SET_KEPT`），带依据条目值指纹，明细改了自动作废（`SET_STALE`），null 撤回、skip 同键即撤回。
- **召回门禁**：`combine_config.json` 新增 `categorySignals`（按选项中文名匹配，不绑编码；否定句不算）。plan 对业务分类枚举键打印 `CATEGORY_TASK` 任务卡（原文、各选项触发的规则、线索、提交模板）。build 时项目内容/交付要求/项目简介/岗位名称有特殊类别线索，而该键未传、传了一般类、或传了不触发规则的选项 → `CHECK CATEGORY_SIGNAL` 阻断调用引擎；模型重选，或在 `categoryReview` 写明误报理由（≥10 字，进 toolIssues 供人工复核）。脚本只提示，不定值；选了另一个特殊类别视为模型判断，放行。
- **新 skill `admission-v0-1-category`**：四步判定（写机制 → 按决策顺序单选：违法 > 擦边灰产 > 传销 > 金融 > 高危 > 私域微商 > 一般 → 反例自查 → 只交 set），含用工场景/经营范围分维度表和 7 个例子。facts skill 原「业务类别单选」长文移入该 skill，facts 只留指引；主提示词改为八个 skill，第 2 轮同时加载 `-category`，红线 10 与第 4 轮说明同步。

验证：全量 172 项，170 通过；剩余 2 项为原有失败（B24、21≠18），与本次无关。新增门禁测试覆盖 18 种业务编码 + 用户反馈的理财/传销/语音陪聊原文（skip 和一般业务都被拦、正确编码放行）、任务卡、只交 set、选另一特殊类、否定句与一般业务不误拦、误报需书面复核；改写 4 项旧断言（set 不再必须重提、有线索时 skip/多选被门禁拦）。

部署：WanScope 上**新增注册** skill `admission-v0-1-category`（`skills/admission-v0-1-category/SKILL.md.zip`），更新主提示词、facts / discover `SKILL.md.zip`、catalog `Archive.zip`。runtime_manifest 已重算（runtime 51,081 → 52,823，script 177,341 → 187,172）。**未部署、未重跑远端模型**；线索词表为草稿，请业务确认。

---

## 当前修订：业务类别与用工场景单选（2026-11-09，版本仍为 0.1）

trace `ca1601985a15486a627b9683ad39fd08` 的项目、交付要求已明确按直接和间接发展人数计酬、多层向上返利，`actual_business_category` 却被整体记为 R10。此次定义同时有“多级分销”和“拉人头返利”，应单选 `headcount_rebate`（拉人头返利），保留合同否认该机制的冲突证据。

- facts skill 补齐业务单选口径：理财、集资、网贷、典当、拍卖、催收、虚拟币、多级分销、拉人头返利、语音陪聊（本版规则归入擦边服务）、色情服务、电信诈骗、网络赌博、建筑劳务、建筑施工、矿山井下、高空高危、危化品生产。明确的业务机制可支持分类，不能因未做外部核实、合同泛称软件服务或相关选项重叠而直接跳过；仍按当次定义取编码。
- **取代此前“用工场景一律原文照传”**：`run_process_required.json` 的 `enumFromDefinition=true` 表示本次定义有 enum/comment 枚举时，接收模型 map/set 的单选值，正常校验枚举；未提交判断则 NEED_VALUE，不以项目原文替代。没有枚举定义时保留自动取项目原文的兼容行为。四个标识仍固定取请求。原项目、交付要求仍保留在明细中。
- 医药销售、直播/直播带货、影视传媒、律所、会计师事务所、保险经纪代理按本次实际岗位分类；经营范围类目另按登记范围判断，维度之间不互塞编码。临时医药销售、兼职主播、保险产品地推等实际行业业务不套用临时辅助岗位例外；无关的临时会场布置、现场引导仍保留提醒。
- 分类由模型基于证据选择，脚本只组装与校验，不以关键词自动裁定业务类别或修改规则引擎结论。维护与验收用的详细映射示例见 [业务分类单选口径](references/业务分类单选口径.md)；运行时所需口径已包含在 facts SKILL.md 内，无须额外文件读取工具。
- 验证：全量 164 项，162 通过；剩余 2 项为原有清单断言（B24 已不存在、证明条目数 21≠18），已用修改前脚本独立复现。分类与场景相关 20 项通过，含 18 种业务编码、7 种行业场景、单值/多值检查、冲突保留、原文兼容与辅助岗位边界。三个修改过的 skill 均通过技能格式校验。
- 更新包：主提示词、facts `SKILL.md.zip`、discover `SKILL.md.zip`、catalog `Archive.zip`；三个压缩包已逐文件核对源码，runtime_manifest 已重算（runtime 51,081，script 177,341）。
- **仅完成本地适配和组装回归，未部署、未重跑远端模型或引擎。** 编码进入 input 的回归不等于真实模型已对全部案例正确选择，也不等于线上拦截已验证。

---

## 当前修订：summary 排版（2026-11-09，版本仍为 0.1）

需求（用户）：summary 的样式参照《风控信息报告-结构化版.html》，**只改排版格式，文字内容不改**。

- `combine.py summary` 渲染：标题带序号（`## 1 · 结论` / `## 2 · 依据` / `## 3 · 下一步` / `## 4 · 注意`）；结论行放进引用块并加粗，前加级别图标（⛔ 拦截、🔴 建议拦截、🟡 转人工、🟢 通过、⚪ 暂无结论）；依据、注意改为无序列表，依据写成「要点：说明」时要点加粗；下一步为引用块里的无序列表。结论行、依据、下一步、注意的文字与原来逐字相同，段落、条目、顺序不变。
- `combine_config.json`：`summaryHeadings` 改为带序号的标题；新增 `summaryStyle.levelIcons`。
- output skill 第三节、回归验收清单同步排版说明。
- 测试：`test_summary` 用 `unformat()` 把排版还原成原纯文本格式，原有内容断言不变；新增 2 项排版用例（格式与“去掉记号后与原文本一致”、暂无结论图标与无要点依据不加粗）。test_summary 37 项通过；test_scripts 仍是原有的 2 项失败（B24、21≠18），与本次无关。
- catalog `Archive.zip`、output `SKILL.md.zip` 重打包；`runtime_manifest.json` 重算（runtime 45 951 → 46 120，script 173 572 → 174 466）。
- **需留意**：配置原说明写着“前端按标题切分”，标题字样从 `## 结论` 变为 `## 1 · 结论`，前端若按旧标题切分需同步；不想改前端可把 `summaryHeadings` 改回旧值，其余排版不受影响。

---

## 当前修订：名称传给引擎前统一口径、章的内容填企业名称（2026-11-09，版本仍为 0.1）

依据 trace `416155b0…`、`ac09911b…`：①`tax_clearance_taxpayer_name`、`tax_payment_taxpayer_name`、`social_insurance_unit_name` 传了 `true`——模型把它们 map 到「…与企业名称是否一致」条目（H29/H23/H17），而不是名称原文条目（H29-1/H23-1/H17-1）；②`lease_contract_party_b_name` 传「上海修匀软件合同专用章」；③`settlement_account_name`「…(个人独资)」与 `enterprise_name`「…（个人独资）」括号全半角不同。规则 `X != Employer.enterprise_name` 由引擎逐字比较，②③都会误命中。

| 改动 | 说明 |
|---|---|
| 文字统一（脚本） | `combine_tool.norm_text`：NFKC（全角括号/字母/数字/冒号分号等 → 半角）+ 中文标点表（【】〔〕《》“”‘’「」。、—…→ 英文）+ 去零宽字符 + 去首尾和中间空白，只保留两个英文字母/数字之间的一个空格（"ABC Technology"、"2025-12-31 00:00:00"）。`combine build` 组装 input 时对**所有**字符串取值做这一遍（含企业名称等标识键），两侧口径一致 |
| 为什么不在 `input-extract-detail.json` 落盘时做 | 试过：工商预填与派生行的文字脚本还要按原样解析（J08 按「；」切、J10 找「截止 」、J34 以「不一致：」开头），统一后 4 项回归失败；明细也是摘要引文的核对来源。所以明细保持原文，统一放在出口（build）；`validate` 与摘要引文校验都认统一后的写法 |
| 章的内容（提示词） | materials skill 新增「章的内容」：印文去掉合同专用章/财务专用章/业务专用章/发票专用章/公章/专用章等字样后主体名称与执照名称 B01 一致（只差空格、括号全半角也算）→ **value 填企业名称 A02 原文**，证据写印文原文；主体名称不同（简称、缺字、别家公司）→ 照抄印文。清单 G11 desc 同步 |
| 名称键不收布尔 | 提示词：facts skill 第 6 条写明名称键只 map 名称原文条目，不 map「…是否一致/是否匹配」条目。脚本兜底：`type_fix` 对规则里与另一属性 `=`/`!=` 比较、label 含“名”的键，收到布尔不传，打印 `TYPE_DROPPED` |

- 撤回上一稿的“名称对齐”（按规则对方原文改值）及 `combine_config.json nameAlign`，由上面三项取代。
- 测试：`integration/test_name_align.py` 7 项（标点/空格统一、英文词间空格保留、非字符串不动、input 统一而明细保持原文、括号全半角两侧一致、主体不同照传、布尔不当名称传）。全量 142 项，140 通过；`test_v39_new_items_are_derived`（找不到 B24）、`test_v35_supplement_groups_follow_names_not_h_numbers`（期望 18 得 21）**改动前就失败**，是清单增删条目后测试未同步。
- facts / materials `SKILL.md.zip`、catalog `Archive.zip` 重打包（不含 `__MACOSX`、`__pycache__`）；`runtime_manifest.json` 重算（runtime 45 951 → 46 120，script 173 572 → 174 466）。
- **需留意**：①传给引擎的中文标点也被改成英文（如经营范围「；」→「;」、「、」→「,」），规则里若写死中文标点做 CONTAINS 比较会对不上（目前未见）；②“是不是该企业的章”由模型判断，只靠提示词；③未在真实 WanScope 运行。

---

## 历史修订：派生改为清单声明的通用工具 + 回归夹具按需补齐（2026-11-09，版本仍为 0.1）

起因：清单加了 G12（承租方的章是否与企业名称一致）后 59 项回归失败——58 项是 G12 没有夹具答案、整张清单门禁卡住后续所有步骤，1 项是测试写死了 163 条。

- **清单 `derive` 声明**（`extract-items-checked.json` 条目可选字段）：`{"op": 工具名, "from": [依据条目ID…], 其它参数}`。`detail.py` 只执行通用计算，比什么、阈值多少写在清单里：
  - `same_name`（两名称逐字比较，忽略空白/括号全半角；可选 `ignoreSuffix` 先去掉左侧末尾字样）、`in_period`（基准日是否在 [开始, 结束]，可选 `label`）、`days_to_expiry`（距到期天数 ≤ `withinDays`，必填；长期/永久 → false；已过期 → false，依据注明已过期天数；依据已填仍算不出时打印 `NEED_REVIEW` 交模型 fill）、`copy`（同栏原样带出）。
  - 原先写死在脚本里的 B15、D04、B22、G05、G07、B24、B25 改为清单声明（输出文字不变，只去掉“阈值 30 天（暂定）”里的“暂定”）；对应编号从 `ANCHORS` 移除。新增 **G12 = same_name(G11, A02)**，忽略「合同专用章/财务专用章/业务专用章/专用章/公章」后缀。
  - init 校验声明（未知 op、引用不存在的条目、缺 `withinDays` 等）→ 直接报错退出，不悄悄留空。声明了 derive 的待算行打印为 `WAIT G12←G11,A02`，不再列进给模型的 PENDING。派生行之间可互相依赖（循环到不再有新行）。`DERIVE_DEP_RE` 支持 `H1-15` 这类带连字符的编号。
  - **未改**：B11、B16–B19、B26、J32–J36 等仍是脚本内逻辑（含业务口径，见 Codex 评审第 1、4 条）；D04 仍比 D01 对 B01（清单名已改为“企业名称”，如需改比 A02 只改清单 `from`）。
- **回归夹具按需补齐**：`integration/test_scripts.py` 新增 `fill_fixture()`——先按 v25 夹具 fill，清单后来新增、夹具里没有答案且非 derive 的行再用 `null + R03` 补一轮；全部 9 处调用改用它。删去夹具里手工补的 G11 行。全流程用例不再写死 163 条 / 94 Y，改为条目与清单一致、夹具覆盖的行值一致。
- 新增 5 项测试：G12 随 G11 派生与重算、清单新增 derive 条目与普通条目无需改脚本且全流程 PASS、阈值来自清单、声明写错时 init 报错、当前清单声明有效。全量 **135 项通过**。
- facts / materials SKILL.md、主提示词第 74 行同步；facts / materials `SKILL.md.zip` 重打包；`runtime_manifest.json` 重算（runtime 44 162 → 44 328）。catalog `Archive.zip` 未重打包。

---

## 历史修订：run_process 必填键单独成文件、枚举键兜底（2026-11-09，版本仍为 0.1）

- 新增 `skills/admission-v0-1-catalog/scripts/run_process_required.json`：
  - `required`：调 `mcp_run_process` 必带的 6 个预设键（`Employer.employer_id`、`Employer.enterprise_name`、`Demand.demand_id`、`LaborAgency.agency_id`、`Agency.agency_id`、`Employer.usage_scenario`），每项写 `key`、取值条目 `item`、`soft`、`why`。**不设兜底**：请求没值就不传，只在 `notes.toolIssues` 记“必填键 X … 无值，未传给 mcp_run_process”，build 照常通过。取代 `combine_config.json` 的 `fixedItems` / `fixedIdentifiers` / `softPresets`（已删除；新文件缺失时 `combine_tool.py` 仍读旧字段）。本体改名只改这个文件。
  - `enumFallbacks`（当前为空）：规则引用的枚举键没取到值时的兜底，每项 `key`、`fallback`、`why`。只对本次规则引用、定义里有选项、且模型没给出值的键生效；兜底值过 `enum_check`（中文选项换成 enum 编码，不是选项就不传并记 toolIssues）；传入后移出 unfilled，`value_source` 记 `兜底｜run_process_required.json｜…`，打印 `FALLBACK_FILLED`，只记 `notes.toolIssues`，不进摘要。`required` 里的键写在这里无效。
- facts skill 的“一般行业兜底”（模型按证据判断所属行业等分类键）不受影响，未改。
- 主提示词红线 2 删去键名映射清单和必填原因（移入配置的 `why`），保留“只放有证据的值、不映射/不改映/不 skip、不得为让规则运行而填值”；discover“标识”、catalog 说明同步。
- 测试：新增 `integration/test_run_process_required.py`（6 项：必填键有值照传、无值不传只记 notes、必填键不吃枚举兜底、枚举兜底按 enum 转码并移出 unfilled、兜底不是选项不传、模型已给值不覆盖）；`test_v30_preset_follows_the_config_not_the_code` 改为修改新文件。全量通过（以暂存区的 `extract-items-checked.json` 运行；工作区里新加的 G12 尚无夹具，会让依赖 fill 的用例失败，与本次无关）。
- catalog / discover `SKILL.md.zip` 重打包（catalog 内的清单仍是不含 G12 的旧版）；`runtime_manifest.json` 重算（runtime 45 951 → 46 120，script 173 572 → 174 466）。

---

## 历史修订：用工场景预设 + 工具报错收敛（2026-11-09，版本仍为 0.1）

依据 trace `e974ced3873959f85da0eeec26b2d462`（`ontology_agent_job_205_df_9_1`）的 3 类 `exit code: 1`：

| 报错 | 性质 | 改动 |
|---|---|---|
| `规则返回不是成功码：code=200 msg=None`（inst-list-rc-rules） | 脚本缺陷：只认 `code=0` | `combine.py rules_list` 认 `0`/`200`（数字或字符串）及无 code；其他码仍报错 |
| `set.AdmissionDoc.business_license_expiry_date 应为 [值, "派生:ID,ID｜依据"]` | 模型格式错误，校验正确 | facts skill 第 4 条加格式要求与正例；单个条目的原文/日期直接 map，不用 set |
| `next[5] 的 ruleId 不是本次命中的结论级别或其余级别的规则` | 模型把“已满足/已通过”写进下一步，校验正确 | output skill 3.2 第 3 条：`next` 只写要对方做的事，已满足/未命中规则不写、不放进 ruleIds |

**用工场景预设（用户约定）**：`Employer.usage_scenario` 必填，和机构 ID 一样由 build 从请求 `projCont`（A08 项目内容）原文自动传入，不做枚举转码；定义里有没有都传，请求没值不传。

- `combine_config.json`：`fixedIdentifiers` 增加 `A08 → Employer.usage_scenario`，`fixedItems` 增加 A08；新增 `softPresets: ["A08"]`——模型对它提交的 map/skip/set 不退回，只打印 `PRESET_OVERRIDE_IGNORED` 并忽略（四个 ID 改映/skip 仍退回）。
- **取代上一节“一般行业兜底”对用工场景的处理**：删除 `generalIndustryFallback` 配置与 `general_industry_fallback()`；所属行业、实际业务类别等其他分类键的“一般行业”判断口径不变。
- 主提示词红线 2/10、discover“标识”表、facts 第 1 条与一般行业兜底、catalog 说明同步。
- 测试：删除 `test_industry_fallback.py`（11 项），新增 `test_usage_scenario_preset.py`（6 项：原文照传、有 enum 不丢、map/skip/set 被忽略不退回、定义缺失仍传、projCont 为空不编造、规则返回 code=200/0 通过而 500 仍拒）；`test_scripts` 全流程期望 input 增加 `usage_scenario`。全量 **124 项通过**。
- catalog / discover / facts / output 四个 `SKILL.md.zip` 重打包并与源码逐文件核对一致；`runtime_manifest.json` 重算（runtime 43 930 → 44 288，script 168 529 → 166 717）。
- **需留意**：用工场景传的是项目内容原文，RULE-GATE-003（`IS EMPTY`）只在 projCont 为空时命中；RULE-IND-006/007 这类按编码比较（`= sensitive`、`= av_production`）的规则不会命中（见下文 v39 第 3 条）。本次未部署、未重跑线上任务。

---

## 历史修订：移除调试摘要（2026-11-09，版本仍为 0.1）

- 最终结构化输出仅保留 `input`、`notes`、`summary`；schema、主提示词和 output / catalog skill 同步。
- `combine.py summary` 仅打印 `SUMMARY` 与 `FINAL`，`summary-final.json` 仅含 `summary`，不再生成调试摘要及说明段。结论、依据、下一步、有事项时的注意段保持现有逻辑；规则计数和处置级别仍保存在命中规则明细和运行日志中。
- 台账参考实现、回归断言和验收说明一并更新。全量 **129 项测试通过**；catalog / output 技能压缩包与源码逐文件核对一致，`runtime_manifest.json` 已重算（runtime 43,930，script 168,529）。

以下历史修订中涉及摘要格式的描述，以本节及当前 output skill 为准。

---

## 历史修订：一般行业兜底（2026-11-09，版本仍为 0.1；用工场景部分已被上方“用工场景预设”取代）

依据 trace `d6ca22bf3aa15455fedd581b4a9f3536`（205 号）：所属行业和实际业务均已按软件开发判断为一般行业，但用工场景漏映射，触发空值拦截。

- 主提示词、facts / discover skill：业务内容可辨识、未命中金融/传销/违法/高危/同业/敏感/音视频制作，且一般行业置信度过半时，显式提交一般行业及证据；不因申报人没有逐字填写分类而 skip。未知、冲突和仅有违法类规则未命中不兜底。
- `combine.py build`：两个来源已按本次定义确认为一般行业且证据齐全、却遗漏用工场景时，沿用证据补齐，打印 `GENERAL_INDUSTRY_FALLBACK`；保留 extractIds 和派生来源，清除该遗漏项的 UNDECIDED / unfilled / unresolvedProperties。三个属性各按自身 enum 转码，不猜英文编码，不覆盖显式 map/skip/set。
- 配置在 `combine_config.json.generalIndustryFallback`；仅修改实际部署目录 `prompt/v41-claude-script`，历史 docs 版本保留。
- 新增 11 项集成测试，含七种特殊类别等子用例；全量 **129 项通过**。catalog / facts / discover 三个 `SKILL.md.zip` 已更新，`runtime_manifest.json` 已重算（runtime 44 217，script 170 205）。

详细边界见 [一般行业兜底说明](references/general-industry-fallback.md)。本次未部署、未重新提交远端任务；空值规则的处置级别保持原配置。

---

## 历史修订：v01-2 测试问题修复——用工场景缺值拦截、95 号工具名死循环（2026-11-09，版本仍为 0.1）

依据：v39-1 / v01-2 对比（`demos/ontology_case/analysis/v39-1_vs_v01-2/`）。

| 问题 | 根因 | 改动 |
|---|---|---|
| v01-2 有 54 单因 RULE-GATE-003（`Employer.usage_scenario IS EMPTY`，处置拦截）被拦截 | `usage_scenario` 定义是 comment 枚举（金融类…一般行业），facts skill 第 8 条“行业/业务分类无口径不填”与红线 5“枚举当选择题”冲突，模型多数按第 8 条 skip R10（44 号 notes 原文：“usage_scenario｜R10｜无业务判断口径”） | facts 第 8 条把“定义自带选项的枚举”排除在外，新增“枚举选项即口径”；红线 5、discover R10 同步；`combine.py plan` 对被 `键 IS EMPTY/IS NULL` 规则引用的键打印 `EMPTY_GATE`（规则、处置），提醒 skip 会直接命中 |
| 95 号 UPSTREAM_TASK_FAILED | trace `4ea31437…`：本体规则查询写成简称 `mcp_list_rule`（实际 `mcp__ontology-mcp__mcp_list_rule`），之后 10 次 `reset_tools`↔`mcp_list_rule` 交替直到失败 | 主提示词一.3、discover 第 1 条：按工具列表完整名称调用；名字错了改完整名重发一次；不调 `reset_tools`；仍不存在按“技能配置异常”收尾 |
| 6 条规则“无法解析”（RULE-ADM-026、DOC-024/026/027/028、INST-007） | 服务端规则含 `IS NOT NULL`，引擎不支持 | agent 侧无法改；改写建议见 `demos/ontology_case/analysis/v39-1_vs_v01-2/规则语法修复建议.md`，需在规则库修改 |
| 测试 | — | 新增 1 条 `EMPTY_GATE` 用例，共 118 项通过 |
| 版本 | — | 七个 `SKILL.md.zip` 重打包；`runtime_manifest.json` 重算（runtime 42 321 → 42 909，script 166 753 → 167 226） |

**需留意**：①用工场景选了中文选项（如“一般行业”）后，RULE-GATE-003 不再命中，但 RULE-IND-006（`= sensitive`）、RULE-IND-007（`= av_production`）按英文编码比较，传中文选项仍不会命中；需要本体给 `usage_scenario` 加 `enum`（编码↔中文），或规则改按中文选项比较。②EMPTY_GATE 只是提示，是否填值仍由模型按证据判断。③未重跑，需用 v01-2 的 63 单回归确认拦截数回落。

---

## 当前修订：RunSkillScript 参数塞成一项的防呆（2026-11-08）

需求（用户）：trace `7bd54b0ab98c829ccfb8a69d0722ae10` 的 `REPLY_FAILED`（phase=tool，RunSkillScript）。根因：模型把 `init --rid … --biz a,b,c --rules x,y` 连同数百个换行塞进 `args` 的一项，`detail.py` 在 argparse 阶段退出（exit 2，`invalid choice`）。另一个潜在错误：`init` 本来不收 `--rid`，就算拆对了也会报 `unrecognized arguments`。网关（WanScope）不改，防呆全部放在本目录。

| 文件 | 改动 |
|---|---|
| `detail.py`、`combine.py` | ①`repair_argv`：某项含换行/控制字符、首尾空白，或像整条命令（空白后跟 `-x`/`--x`），按空白拆回逐项（本流程路径都是 `tool-results/…`，没有空格），打印 `WARN ARGS_REPACKED` 后照常执行；②`--biz`、`--rules` 逗号拼接的路径也拆开（以前只有 `--biz` 兼容）；③参数错误统一输出 `ERROR INVALID_SCRIPT_ARGS` + 用法 + “改一次，同一错误第二次出现就不再试”，exit 2 |
| `detail.py init` | 接受多写的 `--rid`，与 stdin `ctx.requestId` 不一致时报错（exit 2）；requestId 仍以 ctx 为准 |
| 主提示词“脚本路径固定”段、第 2 轮 init | 写明 args 一词一项并给对/错示例；init 不带 `--rid`；`WARN ARGS_REPACKED` 结果有效、不重跑；参数错误最多修正重试 1 次，再错记 toolIssues、按“技能配置异常”处理 |
| 测试 | 新增 3 条 `ArgsGuardTests`：原样复现塞成一项的 init（前后各 200 个换行、逗号拼路径、多写 --rid），产出与逐项调用完全一致；init `--rid` 不一致报错；detail/combine 参数错误打印可修正提示。全部 117 条通过 |
| 版本 | catalog `SKILL.md.zip` 重打包；`runtime_manifest.json` 重算（runtime 41 981 → 42 321，script 163 073 → 166 753） |

**需留意**：①按空白拆分的前提是路径不含空格；含空格的路径会被拆错，表现为“文件读不了”的 WARN。②模型输出数百个换行属于生成退化，脚本只能兜住这一次调用；本次 `REPLY_FAILED` 是否还有调用失败之后的其他原因，要看 trace 末尾。③网关侧在启动脚本前拦截（`INVALID_SCRIPT_ARGS`）按要求没做，以后要做可以把这里的判断移过去。

---

## 当前修订：营业执照清单调整——公司鲜章与登记机关章分开（2026-11-08）

需求（用户）：清单改了营业执照条目：B12 改为「是否彩色」、B13 改为「是否有公司的鲜章」（公司红色公章，不是颁发机关的章）；删 B21「盖章名称」；新增 B27「是否有登记机关的章」；B18/B19/B22/B23/B26 的 desc 精简。清单仍是 163 条（删一条、加一条）。

| 文件 | 改动 |
|---|---|
| `extract-items-checked.json` | B27 的 desc 写明口径：看执照自带的登记机关（颁发机关）章，不是公司公章；看到 true，没看到 false，拿不准 N R06 |
| materials skill 营业执照行 | 去掉 B21；画面判断里写明 B13 是公司鲜章（不是颁发机关的章）、新增 B27 登记机关的章，二者分开判断 |
| facts skill 第 4 点 | 读图判断行改为「B12–B14 彩色/公司鲜章/清晰、B27 登记机关的章」，B27 由模型提交，不是脚本派生 |
| `integration/fixtures/v25_run/fill_spec.json` | 夹具里的 B21 换成 B27（true，登记机关处红色圆章） |
| `references/examples/input-extract-detail.example.json` | 按新清单同步名称、desc，删 B21、加 B27 |
| 版本 | 七个 `SKILL.md.zip` 重打包；`runtime_manifest.json` 重算（runtime 41 927 → 41 981，script 163 073 不变） |

**需留意**：①脚本未改——B27 不由脚本派生，由模型读图填。②B12/B13 的 desc 变短后，原先「黑白件没看到章必须 false」「彩色件不要求章」的判断口径没了，影像合格（彩色，或非彩色但可见鲜章）改由 facts skill 第 3 点和规则本身综合判断；B13 现在只认公司章，执照上的登记机关章不再算。③B21 删除后，规则里若有引用「盖章名称」的键，组装时会 skip，请确认规则侧不依赖它。④测试 test_scripts 57、test_combine_tool 1、test_rule_ledger 14、test_summary 35、test_model_mapping 7 全部通过。

---

## 当前修订：接入 inst-rc-rule-mcp 机构风控规则（2026-11-08）

需求（用户）：inst-rc-rule-mcp 和 mcp_list_rule 一起调用，返回 `{"model":[{"companyName":"Employer.employer_name CONTAINS [修匀]"},{"projectName":"Project.project_name CONTAINS [修匀]"}]}`；规则里的参数 `Employer.employer_name`、`Project.project_name` 在调 mcp_run_process 时一起传。v40-1 里这两条规则（`<hrInstId>-companyName/-projectName`）全部因“属性不存在 / Project 对象不存在”跳过。

| 文件 | 改动 |
|---|---|
| `combine_tool.py` | 新增 `inst_rules` / `load_rules` / `inst_keys`：`{"model":[{名称:条件}]}`（外面再包 data 也认）每项转成一条规则，`ruleId=INST-<名称>`、适用阶段准入；与 mcp_list_rule 的 `{data:[…]}` 合并 |
| `combine.py` | `plan`/`build`/`names`/`rules`/`validate` 的 `--rules` 可给多个文件。机构规则引用的键本体定义没有也照传：plan 打印 `INST_KEYS` 并列出这些键（label 取规则名 companyName/projectName），build 用临时定义组装，不进 notFoundInDefinition |
| `detail.py` | `init --rules` 可给多个文件；企业名称关键词表（J33）也读机构规则，认 `CONTAINS [修匀]`、`[甲,乙]` 写法 |
| 主提示词第 1/2/4 轮、discover skill | 第 1 轮与 mcp_list_rule 同轮调机构规则查询，入参只传 `hrInstId`；`--rules` 写两个 path；`INST_KEYS` 的键按 label 含义 map 到请求原文（企业名称 A02、项目内容 A08）；查询失败重试一次，仍失败记 toolIssues、不使整案退出 |
| 测试 | 新增 2 条：用你给的 model 原样做夹具，plan 列出键、build 后 input 含 `employer_name` 与 `project_name`、规则挂在属性上；init 读机构规则关键词使 J33 命中。共 114 项通过 |

**需留意**：①工具的确切名称未知（仓库与 trace 里都没有），提示词写“inst-rc-rule-mcp 的机构规则查询，入参 hrInstId”，部署后看 trace 里实际工具名是否被调用。②`[修匀]` 是方括号写法，规则引擎是否按“包含其中任一词”解释由引擎决定，脚本只原样传条件。③映射仍由模型决定：项目名称在请求里没有单独字段，提示词建议用项目内容 A08；如有更合适的字段请告知。④未在真实 WanScope 运行。

---

## 当前修订：枚举属性按选择题选一项（2026-11-08）

需求（用户）：规则涉及的枚举属性，定义里有 `enum` 就从 enum 选，没有就从 comment 列的选项里选；枚举是选择题，置信度高于 50% 选得分最高的一项，低于 50% 可以不填。

| 文件 | 改动 |
|---|---|
| `combine.py` | 新增 `enum_options`：读属性定义的 `enum`（`[{"finance":"金融类"}…]`、`[{"code":…,"label":…}…]`、`["finance"…]`、`{"finance":"金融类"}` 都认），没有 enum 时取 comment「枚举 X：」后的选项。`enum_check` 替换原 `enum_mismatch`：有 enum 只收 enum 编码，交中文选项自动换成编码；没有 enum 收 comment 选项原文，规则条件里出现过的编码也收（兼容旧本体）；其他值 `ENUM_DROPPED`、记 R10。`plan` 对每个枚举键打印 `ENUM 选项`、汇总 `ENUM_KEYS`，enum 编码与规则条件编码对不上时打印 `ENUM_RULE_MISMATCH` |
| 主提示词红线 5、facts / discover skill | 枚举当选择题：最高一项置信度过半就 set 提交，依据写「选项｜置信度约N%｜理由」；不过半 skip R10。删去“只传规则条件里出现过的编码”“中文标签不当枚举” |
| 测试 | v30 两条“中文标签一律不收”的旧用例改写为新口径；新增 enum 优先、中文选项转编码、规则编码不在 enum 里提示 1 条。共 112 项通过 |

**需留意**：①没有 enum 时传的是 comment 的中文选项，而现有规则条件比较的是英文编码（如 `enterprise_type = individual_business`），这类规则不会因中文选项命中；本体给出 enum 后才对得上。用 `!=`/`NOT IN` 比较的规则（如 RULE-ADM-019 `validation_status != doc_passed`）传中文选项会被判为“不等于”，该键是结果类、一般 skip R14。②你给的 enum 样例编码（finance、unlawful、hazardous）和现有规则编码（financial、illegal、high_risk）不同，届时 plan 会打印 `ENUM_RULE_MISMATCH`，需本体与规则统一。③置信度由模型自评，脚本只核对是否为选项，不核对置信度。④未在真实 WanScope 运行。

---

## 当前修订：业务属性改由模型按当次定义判断（2026-11-08）

已移除本体组装的业务属性默认映射与固定派生公式；模型根据当次定义、规则和证据显式提交 map/skip/set，规则范围也由模型决定。四个请求标识仍自动传入。下文历史版本中关于默认映射和脚本派生的说明已被本修订替代。

本版 111 项集成测试全部通过。详细职责、验证及部署范围见 [修订说明](references/id-card-image-ok-fix.md)。

---

# v0.1（admission-noshell-v0-1，修订 0.1）：修 71/80 号失败的死循环；租赁合同双方盖章（新增 G11）、租赁材料错传改由提示词约定

**基线：v40-claude 40-claude.1。依据：v39-1 / v40-1 同输入 63 单对比（`outputs/ontology-v39-v40-20261108/对比报告.md`），本次复核确认其结论成立：v40 准确性较好（同范围确认错误 32→16），但错误仍集中在租赁合同两类，且两版都有。**

| 现象（复核方式） | v39-1 | v40-1 |
|---|---|---|
| 出租方只有签字、承租方一枚合同章，被记成双方盖章 true（目视 44、70 号租赁原件） | 23 单 | 11 单（70 号由 false 反转成 true，摘要写“双方均已盖章”） |
| leaseAgreementUrl 实际是开户许可证，却把上下游合同“履行期限至 2026-09-30”当租期，记租期已过 | 74、93 号 | 74、75 号（75 号结论因此由“通过”变“建议拦截”） |

**71、80 号失败原因（Langfuse trace 7b67946d…、5aa20715…）**：明细 fill 到 PASS 后，`combine.py build` 打印 `CHECK B23/C10/D12/F06/G08/H15 的依据含断言字样「真实/合规/正常」`、退出码 1；模型用 `fill --force` 重交，fill 回 PASS，build 又回同样的 CHECK。80 号在 fill↔build 之间来回 10 轮，04:59:32 模型调用报错整单失败；71 号同样循环约 10 轮直到 05:00 后中止。原因有两处：
- 证据没写「｜」时（80 号“逐项看过：证号格式合规，…”），v40 先删断言、后补来源；删断言要求有「｜」，所以什么都没删，补完来源写进去后被 build 查出。
- 用「、」连写时（71 号“证号格式合规、地址为国内真实地址、无卡通头像”），整段算一句，删掉就没内容，v40 选择“不动，交给 build 的 CHECK”，fill 仍回 PASS。模型每次只换几个词，“格式合规”一直在。

两类租赁问题按“业务判断归提示词、脚本只管组装与格式”的分工，仍由提示词约定：清单新增 G11「承租方的章内容」，先取承租方章的印文，再判断出租方处是否另有一枚公司章（G09）。一度写进 `detail.py` 的印文正则核对与 G01 清空逻辑已撤回。

## 改动

| 问题 | 文件 | 改动 |
|---|---|---|
| 71/80 死循环 | `detail.py fill` | 伪造嫌疑类行先补「｜」再删断言分句，「、」也算分句；删完仍有断言（或删完没内容）就当场 `REJECT` 并引出含断言的原句，不写入；同一行第 3 次仍这样记 `N｜R06`（打印 `ASSERT_FALLBACK`），保证 build 不再报 CHECK、不会循环。facts skill 同步说明 |
| 双方盖章误判 | materials / facts skill、清单 G11 | G11 记承租方签章处印文；G09 只有出租方处另有一枚非承租方名称的公司章才 true，出租方只签字、只有承租方一枚章、同一枚章跨两处都记 false，证据分别写两处印文；不判断合同效力 |
| 材料错传当租赁合同 | materials skill | G01=true 须照抄标题且是租赁合同；leaseAgreementUrl 实为开户许可证等时 G01=false 写实际标题，G02–G04/G09–G11 记 null R03，不从上下游合同取租期、承租方、盖章 |
| 文档 | materials skill 租赁合同行、回归清单 | 写明上述口径；回归清单加 v41 两行 |
| 测试 | `integration/test_scripts.py` | 新增 2 条用 71/80 号原句复现死循环（无「｜」、「、」分句；只有断言 → 两次退回、第三次 R06）；v37 旧用例“删完没内容交给 build CHECK”改为当场退回。租赁 G09/G01 的脚本用例随脚本检查一并撤回 |
| 版本 | 全部 | 目录、skill 名、契约、revision 改为 v41；七个 `SKILL.md.zip` 重打包；`runtime_manifest.json` 重算（runtime 41 517 → 41 849，script 168 043 → 173 033）。顺带改正 README 里 v39 小节标题误写成 v40 契约的问题 |

## 验证

- test_scripts 54、test_model_mapping 7、test_combine_tool 1、test_rule_ledger 14、test_summary 35，共 111 项全部通过。
- **未在真实 WanScope 运行**；没有拿到两轮的工作区明细（input-extract-detail.json），G09/G11/G01 口径只靠提示词，效果要真实运行才能看出；模型实际写证据的方式可能与测试样例不同。

## 本版没改、需要另外处理

1. 71/80 的另一个可能因素没查：两单都在 build 失败后仍反复 fill，说明模型没看 fill 的 PASS 与 build 的 CHECK 之间的矛盾；本版从脚本侧消除矛盾，没改主提示词的轮次限制。
2. **6 条规则两版都无法解析**（RULE-ADM-026、RULE-DOC-024/026/027/028、RULE-INST-007，`IS NOT NULL` 相关），属规则引擎/规则表达式问题；其中 RULE-DOC-027 引用双方盖章，G09 改对了也进不了结论。
3. 规则引用 `Employer.employer_name`、`Project.project_name`，而 input 用 `Employer.enterprise_name`、没有 Project，相关规则两版都 skip；54 号“多层返利”两版都“通过”。需在本体侧统一键名，不在本版提示词里处理。
4. 照片是否体现交付（F03 等）两版口径不稳（69、73、82、84、93、95、99 号），口径待业务定，本版未动。60 号视频 v40 未给值，原因未查。

## 部署

- WanScope 上七个 skill 换成 `admission-v0-1-*`（各目录 `SKILL.md.zip`），主提示词换成 `主提示词_v0-1_编排版.md`。

---

# v40-claude（admission-noshell-v40-claude，修订 40-claude.1）：下一步同一风险点只写一条、去掉提示词里的举例

**基线：v39-claude 39-claude.1。需求（用户）：①job_148 下一步第 2、3 条重复（同为视频未一镜到底：一条模型自写、一条为覆盖 RULE-DOC-016 带 ruleIds），提示词只加一句“同一风险点只写一条”，不举例；②去掉提示词里各种举例。**

## 改动

| 需求 | 文件 | 改动 |
|---|---|---|
| ① | output skill 3.2 第 3 条 | 末尾加“同一风险点只写一条。” |
| ② | 主提示词、七个 skill | 删去“如…/例如…/比如…”式举例、“不要这样写→改成”对照表、明细格式示例行、历史案例（v24/v35/v37 job_54 实测）；规则本身的口径、词表、编号对照表、脚本输出名保留 |
| 版本 | 全部 | 目录、skill 名、契约、revision 改为 v40；七个 `SKILL.md.zip` 重打包；`runtime_manifest.json` 重算（runtime 43 337 → 41 517） |

脚本、配置、清单与 v39 相同（只改了 `CONTRACT` 版本号）。

## 验证

- test_scripts、test_combine_tool、test_rule_ledger、test_summary 全部通过。
- **未在真实 WanScope 运行**；“同一风险点只写一条”只靠提示词约束，脚本不检查重复。

## 部署

- WanScope 上七个 skill 换成 `admission-v40-claude-*`（各目录 `SKILL.md.zip`），主提示词换成 `主提示词_v40-claude_编排版.md`。

---

# v39-claude（admission-noshell-v39-claude，修订 39-claude.1）：清单字段更新、summary 给客户看、组装前先筛规则、灵工受限行业例外提醒

**基线：v38-claude 38-claude.1。需求（用户）：①清单换成 `extract-items-modify.json`；②summary 少用技术话术，让客户看懂；③summary 不带字段变量、字段代号，用业务用语；④返回的规则先判断是否与客户准入有关，无关的抛掉，不把它们表达式里的字段放进 input-combine.json；⑤灵工禁入行业里，如果招的是灵工岗位（如金融公司招展会临时工作人员、地推人员），放进提醒。**

## 改动

| 需求 | 文件 | 改动 |
|---|---|---|
| ① 清单 | `extract-items-checked.json` | 换成你改过的清单（166 → 162 条）：删 D03「账户性质允许」、I01–I10「管理员信息与客户登记表」；新增 B24/B25（成立日期、营业期限）、B26「是否灵工平台企业」、C13/C14（身份证有效期起止）、G09「双方都盖章」、G10「结束时间」；G04 改为「开始时间」；D02、D10、F03、F04 的 desc 更新。`extract-items-modify.json` 不再单独保留 |
| ① 清单 | `detail.py` | 删去 I 组预填（v38 的 `REG_FIELDS` 等）；租期改为 G04 开始 + G10 结束算「在租期内」G05 与「快到期」G07；B24/B25 由 B04/B05 原样带出（同一栏位，不让模型重复读）；B26 按执照经营范围 B08 逐词核对 desc 里的词表（人力外包、灵活用工、劳务派遣、劳务外包、劳务服务、劳务中介、劳务输出）；D03 派生删除；名称锚点同步 |
| ① 清单 | `combine_config.json` defaultMap | 用工场景只取 A08 项目内容原文（I07 没了）；账户性质改由 D02 原文按关键词派生（含「专用」「临时」→ other，基本户/一般户不传）；`AdmissionDoc.lease_contract_both_sealed` 由 skip R10 改为取 G09 |
| ②③ summary | `combine.py summary` | 依据、下一步里（「」原文之外）出现清单编号（B08…）、原因码（R06…）、英文字段名/变量名（entpName、scene_photo_count…）或技术词（属性、字段、枚举、编码、引擎、入参、映射、派生、漏斗…）就退回，ERR 里给出业务说法；analysis 先把代号换成中文再校验。“注意”段、宽松模式补齐的话术、结论行由脚本统一换成业务用语（附件字段名→材料中文名，请求字段名→“企业名称/项目内容”等，`工商:D.xxx`→“工商登记信息”，清单编号→条目中文名，原因码、工具名去掉）。暂无结论时结论行写“提交的信息还不足以完成自动核验”，技术原因保存在命中规则明细和运行日志中 |
| ②③ summary | `combine_config.json` | 新增 `plainLanguage`（禁用词、建议说法、字段中文名、暂无结论的业务说法）；`noConclusion` 去掉“漏斗” |
| ②③ summary | output skill 3.2 | 新增“summary 是给客户看的”写法要求与对照表（不要这样写 → 改成） |
| ④ 规则先筛 | `combine.py build` | 组装前先判断规则是否与客户准入有关（`RULE_SCOPE`）：适用阶段只属签约/结算/处置/复核治理、名称和说明不提准入/禁入/入驻、条件里也没有一个键能由准入资料取到的，判为无关并列出；**它们条件里的字段不进 input-combine.json**（refKeys、unfilled、notes.unresolvedProperties 都不出现），`rulesDropped` 记录规则 ID 与原因。模型可在 build 的 stdin 用 `{"rules":{"keep":[…],"drop":{"规则ID":"原因"}}}` 改判，落盘 key-map.json。签约阶段但由准入资料判定的规则（开户名称一致、账户性质、职场视频）保留 |
| ④ 规则先筛 | `combine.py result/summary`、`combine_tool.py validate` | 被抛掉的规则即使引擎给出命中，也不进命中表、不进漏斗、不进依据，result 打印 `OUT_OF_SCOPE`，hit-rules.json 保留计数；validate 的键数闭合只按保留的规则算 |
| ⑤ 灵工例外 | `combine.py`、`combine_config.json` `flexJobException` | 企业名称/工商行业属金融、医疗医药、影视、律师/会计、矿业能源、建筑施工，且岗位名称/项目内容/交付要求/项目简介含展会、地推、促销、活动执行、搬运分拣等临时辅助岗位词、又不含该行业业务词（金融：催收、贷款、理财、开户、办卡、拉新、保险销售等）时，“注意”里加一条：“企业属于X类行业，该行业一般不开展灵活用工；但本次招聘的「岗位原文」属于临时性、辅助性岗位，不涉及X业务本身，可以按灵活用工承接，建议人工核实……”。只提醒，**不改结论**；传销、违法灰产不设例外。NEED_BASIS 打印 `FLEX_JOB` 提示模型下一步可请对方补岗位说明 |
| 文档 | 主提示词、facts / discover / materials / output skill、回归清单 | 红线 11 → 13 条（新增 12 规则先筛、13 灵工例外），轮次表第 4 轮说明；materials 表补 C13/C14、G04/G09/G10；facts 派生清单、defaultMap 说明同步；回归清单新增 v39 五行、删 v38 登记表一行 |
| 测试 | `integration/` | 夹具 fill_spec 拆租期（G04/G10）、补 G09；map_spec 的 account_type_allowed 改 skip；新增 test_scripts 5 条（用工场景取 A08、新条目派生、G09 进双方盖章、规则先筛、抛掉的规则不进结论），删 v38 I 组 4 条；test_summary 新增 3 条（依据/下一步拒代号与技术词、注意段改写成业务用语、灵工例外提醒），4 处断言按新话术改 |

## 验证

- test_scripts 60、test_combine_tool 1、test_rule_ledger 14、test_summary 35 全部通过。
- 在 v25 夹具（1103 规则，197 条）上：规则先筛抛掉 32 条（结算 15、复核治理 10、处置 5、签约 2），规则引用键 154 → 127；在 v35 规则（76 条）上抛掉 2 条（签约/结算阶段资料齐全），签约阶段的开户、视频规则保留。
- 七个 `SKILL.md.zip` 重新打包（catalog 含 162 条清单与四个脚本）；`runtime_manifest.json` 重算（runtime 36 120 → 43 337，script 157 268 → 168 043；v38 的 manifest 里主提示词 sha256 已过期，本次一并重算）；`references/examples/` 按 162 条重新生成。

## 未验证 / 需要你定

1. **未在真实 WanScope 运行。**
2. **B24/B25 与 B04/B05 含义重复**（都是成立日期、营业期限），我让脚本把 B04/B05 原样带出，模型不重复读。如果你本意是另一份材料上的日期，告诉我来源，我改成模型读取。
3. **C13/C14 与 C03（背面有效期截止日）部分重复**：C14 结束时间和 C03 是同一栏，现在三条都由模型读；C05 有效期、C09 快到期仍按 C03 算。
4. **规则先筛的口径是我按“适用阶段 + 能否由准入资料取值”定的**：结算/签约/处置/复核治理之外的阶段（需求发布、业务核查）一律保留。业务核查类规则（如任务类别、岗位分类）大多仍会 skip，但没有抛掉，因为它们和岗位/行业判断有关。要更激进（比如抛掉需求发布阶段），改 `combine_config.json` 的 `ruleScope.laterStages`。
5. **灵工例外的行业词表和岗位词表是草稿**，请业务过目（`flexJobException`）。和规则的冲突：1103 规则里有 RULE-IND-FIN-002「金融产品拉新地推建议拦截」，所以我把“地推”放进例外的前提是**推的不是金融产品**（含拉新、开户、办卡、贷款等词就不出提醒）。行业只看企业名称和工商行业，没看经营范围（经营范围里“金融信息服务”之类太常见，误报多）。
6. “注意”最后一条的标签仍是你 v38 定的“agent全局分析（仅供参考）”，其中“agent”对客户来说偏技术；要改成“综合提示（仅供参考）”之类，改 `combine_config.json` 的 `analysisLabel` 即可。
7. 技术词检查会让模型多被退回几次，但 v38 的“被拒 2 次后第 3 次宽松收尾”仍在，不会死循环。

## 部署

- WanScope 上七个 skill 换成 `admission-v40-claude-*`（各目录 `SKILL.md.zip`），主提示词换成 `主提示词_v39-claude_编排版.md`。

---

# v38-claude（admission-noshell-v38-claude，修订 38-claude.1）：用工场景按原文传、summary 不再死循环、注意段加 agent 全局分析

**基线：v37-claude 37-claude.1（含你在 v37 清单里新增的 I01–I10“管理员信息与客户登记表”和 G05 口径）。依据：v36_1 与 v37_1 两轮 63 个任务的对比，你人工核对后确认 v37 更准，本版在 v37 上改。**

## 需求与依据

| 需求 | 依据 |
|---|---|
| `usage_scenario` 取 I07“登记表.用工场景说明”，为空取 `projCont`，固定写死 | 两轮 62 对任务全部因 RULE-GATE-003（用工场景为空）拦截，掩盖了其余明细差异 |
| 解决 summary 死循环 | v37 job_54：引擎已出结果，summary 把一段材料里没有的「软件开发人员组织·发票类目：信息技术服务」改标点重交 29 次，最后一次模型调用报错，整单 `UPSTREAM_TASK_FAILED`（排队 19 分钟 + 执行 8 分钟作废） |
| “注意”加一条“agent全局分析（仅供参考）” | 规则没覆盖的问题没有出口，如 job_54 项目内容“按发展人员数量计酬，并设置多层返利”，相关规则全部 skip，摘要也没提 |

## 改动

| 文件 | 改动 |
|---|---|
| `detail.py init` | I 组（按条目名称关键词找，不写死编号）按请求字段预填：有值取原文；登记表栏目字段在但为空写「该栏为空」；请求没有写 N R01；“登记表内容与实际相符”固定 N R10。请求里出现未识别字段时，找不到字段的 I 组行留给模型填，并在 toolIssues 提示。**候选字段名是推测的**（`usageScenario`、`adminName` 等，见 `REG_FIELDS`） |
| `combine_config.json` defaultMap | `Employer.usage_scenario`：skip R10 → `derive: text_fallback`，ids `[I07, A08]`，`emptyValues: ["该栏为空"]`，`raw: true` |
| `combine.py build` | 新派生口径 `text_fallback`（依次取第一个有值、且不是「该栏为空」的条目原文，value_source 写明是否回退）；`raw` 的键按原文照传，不做枚举/类型过滤 |
| `combine.py summary` | ①被拒计数落盘（`work/<id>/.summary-tries.json`），**被拒 2 次后第 3 次进入宽松模式**：不合格的条目丢弃，缺的依据/下一步用规则名称 + comment 补齐，打印 `LENIENT`，必出 `FINAL`；非法 JSON 同样计数；通过后计数清零。②引文被拒时 ERR 附“最接近的原文”或“去掉「」”的提示。③NEED_BASIS 列出可放进「」的原文（交付要求、项目内容、开票类目、登记表用工场景说明、经营范围）。④草稿新增可选 `analysis`（0–3 条，6–200 字），拼成“注意”的最后一条：`agent全局分析（仅供参考）：…`；不合格条目只打印 `ANALYSIS_DROPPED`，从不退回 |
| `combine_config.json` | 新增 `analysisLabel`、`release.basisFallback` |
| output skill | 草稿格式加 analysis 及写法口径；「」只抄 NEED_BASIS 列出的原文或明细 Y 行原文；被拒只改点名条目、不反复改标点；summary 最多 3 次 |
| 主提示词 | 红线 10 加用工场景口径；红线 11 加 analysis 与 3 次上限；轮次表第 7 轮说明 |
| facts skill | 派生属性清单加用工场景；I 组由 init 预填 |
| 回归清单 | 新增 v38 四行；明细条数 156 → 166 |
| 测试 | test_scripts +4（I 组预填、用工场景取 I07、为空回退 projCont、未识别字段留给模型），3 处断言按新行为改（166 条、Y/N 91/75、usage_scenario 有值）；test_summary +5（最接近原文、NEED_BASIS 列原文与 analysis、第 3 次宽松收尾且不含编造引文、非法 JSON 也收尾、analysis 放注意末条且只丢不退），`summary()` 辅助函数每次清计数 |

## 验证

- test_scripts 59、test_combine_tool 1、test_rule_ledger 14、test_summary 32 全部通过。（v37 原样跑：你加了 I 组后 test_scripts 有 10 个失败，因为没人填这 10 行；v38 由脚本预填后恢复。）
- **用 v37 job_54 的真实 work 文件和它最后一次被拒的原稿重放 v38 的 summary**：第 1、2 次被拒，第 3 次打印 `LENIENT` 并通过；摘要里没有编造的引文，下一步由规则说明补齐。
- 七个 `SKILL.md.zip` 重新打包（catalog 含 166 条清单与四个脚本）；`runtime_manifest.json` 重算（runtime 35 034 → 36 120，script 147 292 → 157 268）。

## 未验证 / 需要你定

1. **未在真实 WanScope 运行。**
2. **I 组的请求字段名是我推测的**：现有 126 条测试请求里都没有管理员/登记表字段。网关实际字段名确定后补进 `detail.py` 的 `REG_FIELDS`，否则 I07 永远是 N，用工场景实际都会取 projCont。
3. **用工场景按原文传之后**：RULE-GATE-003（`IS EMPTY`）只在 projCont 也为空时命中；RULE-IND-006（`= sensitive`）、RULE-IND-007（`= av_production`）这类按编码比较的规则**永远不会命中**。这是“固定写死原文”的直接后果，如需这两条生效，要么本体补“编码—中文”字典，要么规则改为按原文关键词判断。
4. 宽松模式补的依据/下一步是机械话术（“命中「规则名」：comment”/“针对「规则名」：comment，请补充或更正相关资料后重新提交”），不如模型写的具体；只在模型两次都写不对时出现。
5. “最接近的原文”按共有字符数挑，job_54 重放时挑出的片段不理想（如「人员组织服务合同 p1 甲方：…」），只起提示作用；真正保证结束的是第 3 次的宽松收尾。
6. agent全局分析由模型写、脚本只做格式和引文校验，内容是否有价值只能看真实运行；它不影响结论。
7. I05、I10 的 desc 写着 `AdmissionDoc.sms_verified`、`AdmissionDoc.content_matches_actual`，但 defaultMap 里 `admin_phone_verified`、`registration_actual_match` 等仍是 skip R13，本版没把它们映射到 I 组（需求里没有）。要映射请告诉我对应关系。
8. `references/examples/` 两个示例仍是 156 条的旧版，没有重新生成（运行时不读）。

## 部署

- WanScope 上七个 skill 换成 `admission-v38-claude-*`（各目录 `SKILL.md.zip`），主提示词换成 `主提示词_v38-claude_编排版.md`。
- 网关与 SOP 无需改动。

---

# v37-claude（admission-noshell-v37-claude，修订 37-claude.1）：减少模型轮数、固定映射、脚本拼最终结果

**基线：v36-claude 修订 36-claude.4（含漏斗 4 级、其余级别并入下一步、注册资本来源冲突等全部改动）。需求（用户）：按 v35 五次运行（ontology_agent_job_43_v35-am1…am5）的分析，执行“只改提示词和脚本”的改进。**

## 依据（v35 五次 trace）

- 主 Agent 每次 14–17 轮模型调用，耗时 17–28 分钟；86% 的时间在等首个 token，且随上下文（3.5 万→8.9 万 token）增长。**减少轮数是主要手段。**
- build 每次跑 3–4 次（首次只为打印 PLAN、再提交映射、再补 NEED_VALUE、自审后重跑）；result→summary(无 stdin)→summary(草稿) 三轮；审核 A、审核 B 都是自审（平台没有 Agent 工具），五次全部“通过”。
- 同一属性的映射五次各不相同（64 个键只有 20 个一致），导致 `business_license_image_ok` 五次为 F/T/T/F/T、补充材料类属性时有时无，规则命中不同。
- am2、am3 最后一轮把 notes 里的“”改成直引号且未转义，GenerateStructuredOutput 原始参数不是合法 JSON。
- 摘要“注意”段重复（“办公场所视频 办公场所视频”、“未作为已核实”两次、模型又把经营范围/注册资本写一遍、“待比对”、括号全半角差异）。
- 五次 fill 都被拒若干行（重交 F01/A12、判断类短句漏写「｜」）。

## 改动

| 文件 | 改动 |
|---|---|
| `combine_config.json` | 新增 `defaultMap`：本体当前规则引用的 64 个键的默认处理（map 到清单条目，或 skip 原因码），每条带属性 label；本次定义的 label 不同就不套用。派生口径：`image_ok`（彩色或鲜章任一 true 即合格，都 false 或文字不清晰为不合格）、`when_false`（账户性质/租期/证件有效期/执照状态：依据为 false 传 other/expired，为 true 不传）、`keyword_code`（企业类型含分公司/合伙/个独/个体时传编码）、`count_true`（三类证明都有值时计数）。发票关联方、合同配套映射到 H10/H14，**未提供时不传**（v35 有两次推成 false）；双方盖章、照片真实性、用工场景、主营核验类等无口径的 skip |
| `combine.py build` | 模型没提交的键套用 defaultMap（模型 map/skip 优先）；不带 stdin 即可一次组装完成；打印 `DEFAULT_MAP`/`DEFAULT_OFF`；新增 `CHECK`（伪造嫌疑类条目依据含“真实/合规/正常/可信/无异常”、E05 不是 true/false）——替代自审 A 的机械项，有 CHECK 退出 1 |
| `combine.py result` | 直接打印 `NEED_BASIS`（暂无结论打印 `NO_DRAFT`），省掉一轮不带 stdin 的 summary |
| `combine.py summary` | 通过后打印 `FINAL {input,notes,summary}` 并写 `final-output.json`，模型原样作为 GenerateStructuredOutput 参数；notes/摘要里的弯引号统一成「」 |
| `combine.py` “注意”段 | 模型 conflicts 里涉及工商比对的、“待比对”的、只差括号全半角的不再进“注意”；重复的附件名、重复的“未作为已核实”去掉 |
| `detail.py fill` | 重交脚本预填的行打印 `SKIP`，不算错；漏写「｜」时认不出来源就用该条所属材料作来源（AUTOFIX），不再 REJECT；伪造嫌疑类有值行写入时去掉含断言的分句（`TRIMMED`） |
| output skill | 重写：删除审核 A/B 的 Agent 模板与自审要求（13 567 → 4 678 字），流程改为 build → 引擎 → result → summary → 提交 FINAL；下一步不得猜类别、不得加规则没有的要求 |
| 主提示词 | 红线 7、10 与第二节轮次表改为新流程（第 4–8 轮）；预填行说明、conflicts 写法（不重复工商比对、不在别处下“伪造”结论） |
| facts / discover / catalog / video skill | 映射改为默认表、派生由脚本算、CHECK 处理；去掉审核员相关措辞 |
| 测试 | test_scripts +9（默认映射一次组装、影像合格派生、枚举编码派生、企业类型编码、计数、label 变了不套用、模型映射优先、断言分句去除、预填重交不算错），2 个旧用例按新行为改断言；test_summary +4（result 打印 NEED_BASIS、NO_DRAFT、FINAL 与去弯引号、注意段去重）。新夹具 `integration/fixtures/v37/`：当前本体的属性（取自 v35-am1 的 PLAN 输出）和规则（取自 response-1105 的 expression） |

## 预期轮数

v35：14–17 轮。v37 正常路径：①skill+规则+工商 ②skill+属性+视频+init ③fill ④(recheck) ⑤build ⑥引擎 ⑦result ⑧summary ⑨提交 —— 约 8–9 轮。runtime 文本 43 190 → 35 034 字（output skill 13 567 → 4 678）。

## 验证

test_scripts 55、test_combine_tool 1、test_rule_ledger 14、test_summary 27 全部通过；七个 SKILL.md.zip 与 catalog Archive.zip 重新打包；runtime_manifest 重算（runtime 43 190 → 35 034，script 130 846 → 147 292）。

## 未验证 / 需要你定

1. **未在真实 WanScope 运行**，轮数和耗时是按流程推算的。
2. **默认映射表是我按 v35 五次运行的多数映射 + 36.4 已确认的反例定的**，请过目 `combine_config.json` 的 `defaultMap`，尤其：`workplace_real→E10`、`admission_submitted_at→A06`（基准日，缺 apply_date 时回退为任务提交日）、`scope_sensitive→B09`、`supplement_evidence_kinds` 按三类证明“是否提供”计数、`independent_employment_qualification` 设为 skip R10。
3. 去掉审核 A/B 后，语义类错误（如材料来源的值没有原文、视频推测被当结论）只靠提示词约束；v35 的自审也没拦下过这类问题，但这是一处取舍。
4. `GenerateStructuredOutput` 仍需模型整份抄写 FINAL（平台不支持引用文件，见上次分析），只是不再自己拼，抄写出错风险降低、耗时不变。
5. 注册资本：沿用 36.4 的 D/B 不一致记 R09 的做法；“三接口多数一致”未做。经营范围差异的来源接口未核对。
6. `usage_scenario` 仍 skip（本体缺“编码—中文”字典），RULE-GATE-003 仍会命中拦截——需本体/规则侧处理（36.4 已记录）。

---

# v36-claude 修订 36-claude.3：漏斗改为 4 级（拦截>建议拦截>转人工>通过）

**基线：36-claude.2。需求（用户）：漏斗“拦截>建议拦截>建议放行>放行并关注>放行”改为“拦截>建议拦截>转人工>通过”；两个放行级都并入“通过”。**

改动：
1. `combine_config.json` 的 `riskLadder` 改 4 级：建议放行→转人工（副标题“需转人工核验后决定是否入驻”），放行并关注、放行→通过（“可正常入驻”）。副标题仍是草稿，请审。riskMeasure 必须与级别逐字相同，**引擎规则返回“建议放行”“放行并关注”“放行”将不再被识别**（进 `FUNNEL_UNRECOGNIZED`）；需要引擎侧把这些规则的 riskMeasure 改为“转人工”“通过”。
2. `combine.py`：下一步口径（`NEXT_HINT`/`OTHER_HINT`）把建议放行与放行并关注合并为“转人工”一条；通过级沿用原放行级逻辑（依据夸资料 4–6 条，下一步固定“✅ 业务可正常开展、正常入驻。”）；未判定与未触发计数保存在命中规则明细中；提示文字“放行”→“通过”。
3. output skill、主提示词、回归清单同步；测试按新级别改名，图片场景夹具的 riskMeasure “放行并关注”改为“转人工”。修订号、manifest、zip 重算。

验证：test_scripts 44、test_combine_tool 1、test_rule_ledger 14、test_summary 23 全部通过。
未验证/需留意：①未在真实 WanScope 运行；②原“放行并关注”的“提高不足点”并入转人工，结论为通过时不再有这类下一步；③没有命中规则时结论为“通过”，沿用原“无命中=最宽一级”；④“暂无结论”文案不变；⑤历史夹具（list_rule_1103 等）里 riskMeasure 仍是旧名，不影响现有测试。

---

# v36-claude 修订 36-claude.2：其余命中级别的规则并入“下一步”

**基线：v36-claude 36-claude.1。需求（用户）：“下一步”里，除了结论级别，把其余命中级别的规则的注意事项也加进来，让客户处理或注意。**

改动（`combine.py summary` + 提示词）：
1. 结论之外、已命中且级别在漏斗内的规则（放行级除外，它没有要处理的事项）单列为“其余命中级别的规则”：NEED_BASIS 多打印一段（ruleId|级别|ruleName|reason|comment 全文）和各级处理口径（`OTHER_HINT`）。依据仍只写结论级别的规则，结论不变。
2. 草稿 `next` 的元素可以是字符串（结论级别的事项，最多 8 条，不变），也可以是 `{"ruleIds":[…],"text":"…"}`；其余级别的每条命中规则必须至少出现在一条带 ruleIds 的下一步里，否则报“没有出现在任何一条下一步里”；ruleIds 不属于结论级别或其余级别（如放行级、未命中）报错；文字仍过原有校验（无规则 ID/英文属性名、「」引文逐字）。
3. 其余级别的命中规则仍须逐条并入下一步；命中明细保存在 hit-rules.json，不额外生成说明段。
4. output skill 3.2、审核条款 2、主提示词第 11 条、回归清单同步；修订号、manifest、zip 重算。

验证：test_scripts 44、test_combine_tool 1、test_rule_ledger 14、test_summary 23（新增 1，改 1 个旧用例：原断言“其余级别不出现在 NEED_BASIS”，现改为单列段并要求 next 覆盖）全部通过。
未验证/需留意：①未在真实 WanScope 运行；②下一步条数变多，可能超过前端展示预期；③放行级命中（riskMeasure=放行 且 result=true）不并入；riskMeasure 不在漏斗内的命中仍只在说明里提示；④其余级别的下一步按级别口径由模型写，不单独加级别前缀，若要标明“另（建议拦截）”需再定格式；⑤“注意”段仍只放材料/附件类事项，未放规则注意事项（需求按“下一步”处理）。

---

# v36-claude（admission-noshell-v36-claude，修订 36-claude.1）

**基线：v35-claude。需求（用户）：营业执照、法人身份证如果不是彩色复印，就必须盖鲜章。起因：v32 两次运行里身份证为黑白、没有章（C07=false、C08=false），但 am1 仍把身份证影像判合格（理由“正反面齐全、姓名有效期清晰”），am2 把该属性当作无业务口径不填，最终都没有提示补正。**

改动（只改提示词与清单口径，脚本未动）：
1. `extract-items-checked.json`：B12、B13、C07、C08 原来 desc 为空，补成明确口径（彩色只判颜色；章只看画面上有无公章印迹；黑白/灰度件没看到章必须 false，不得因文字清晰放过；身份证正反面分别看，任一面黑白且无章则 C08=false；拿不准 N R06）。
2. facts skill 新增「营业执照、法人身份证的影像要求」：彩色即满足，非彩色必须有鲜章；执照与身份证的“原件彩色扫描或鲜章复印件”类影像合格属性，仅当 B12/C07 或 B13/C08 为 true 才可 true，两者都 false 填 false；并声明该属性有口径，不适用“无本流程口径不填”（am2 因此跳过）。
3. materials skill 执照、身份证两行写明影像要求；output 审核条款 7 由只管执照扩到身份证，彩色与鲜章都 false 而合格属性为 true 则退回改 false。
4. 目录、skill 名、修订号、runtime_manifest、zip 全部换成 v36。

验证：test_scripts 44、test_combine_tool 1、test_rule_ledger 14、test_summary 22 全部通过（脚本未改，这些测试不覆盖提示词文本）。runtime_characters 41 691 → 42 255。
未验证/需留意：
1. 未在真实 WanScope 运行，需用 v32 同一条请求（身份证黑白无章）回归，期望身份证影像合格属性 = false。
2. 本版只保证该属性取 false；“需要补正”是否出现在 summary 的“注意”里，取决于规则引擎该属性的命中结果。**没有新增独立 notice 通道**（输出契约仍只有 notes；摘要只展示最高处置级别命中项，仍可能被更高级别风险盖住），需要的话下一版在 combine.py 的“注意”段按 B12/B13/C07/C08 直接生成补正话术。
3. 规则引擎侧身份证影像属性的名称我没看到（fixture 里只有执照的 origin_color_scan），口径写成按“同类影像合格属性”处理；若引擎没有该属性，这条不会命中任何规则。
4. “正反面各自判断”是我拟的口径（只要任一面黑白无章就不满足），请确认。鲜章与黑白件上的灰色章印如何区分，也靠模型看图，不稳定。
5. 继承 v35 全部未验证事项。

---

# v35-claude（admission-noshell-v35-claude，修订 35-claude.1）

**基线：v34-claude。需求（用户）：人工核对清单 `extract-items-checked.json` 在「补充材料」里新增了完税证明、无欠税证明各一整组条目（H24–H35 为新增或后移），条目由 144 变 156，后面的编号整体后移；要求 `detail.py` 不要把 H 编号写死，并确认 `extract-rows.txt` 可以删。**

## 问题

v34 的脚本按旧编号写死：①`SUPPLEMENT` 把 H16–H21 对应到 `noTaxCertSbUrl`，新增的完税/无欠税条目（H24–H33）不属于任何附件组，附件没提供时不会自动 N，要模型手填；②官网/公众号两条在脚本里写死为 H22、H23，清单改号后它们是「完税证明是否提供」「完税证明公司名称是否匹配」，会被错误地写成「官网仅有 URL 未验证」；③提示词、skill、示例、测试里还有「144 条」和 H 编号。

## 改动

| 文件 | 改动 |
|---|---|
| `extract-rows.txt`、`integration/build_catalog_v34.py` | **删除**。v32 起运行时没有任何代码读 `extract-rows.txt`（`detail.py` 只读 `extract-items-checked.json`，catalog SKILL.md 不再提它），v34 里它已和清单不同步（144 行对 156 条）。清单是唯一数据源 |
| `scripts/detail.py` | 补充材料不再写死 H 编号：`SUPPLEMENT_PREFIX` 按条目**名称开头**归组（增值税专用发票 / 上下游合同 / 社保证明+完税证明+无欠税证明→同一个请求参数 `noTaxCertSbUrl`），`online_ids()` 按名称找「官网/公众号…可打开」「…关联」两条。以后在补充材料里插入、改号，只要名称沿用「xx证明…」「官网/公众号…」前缀就自动并入，不用改脚本 |
| `scripts/detail.py` | 新增 `ANCHORS` + `check_anchors()`：脚本里仍按编号引用的 A–G、J 组条目（约 70 个，如 B05、J34），逐个用名称关键词核对；清单改号/改名对不上时 `init` 打印 `WARN 清单与脚本按编号引用的条目对不上：…`，不再悄悄写错行 |
| 主提示词、catalog/facts/materials/output skill、回归清单、schema 说明 | 去掉「144 条」（改为「清单全部条目」）；去掉社保/完税/官网/伪造嫌疑的 H 编号，改用条目名称描述；materials 表改为社保/完税/无欠税证明合并一行（同一参数，三种证明各六条） |
| `references/examples/*` | 由清单重新生成（156 条） |
| 测试 | 夹具 `fill_spec.json` 的 H16–H21 按新清单扩为 H16–H33；断言 144→156、待填 68→80、Y/N 91/65；H17/H20 派生行测试改为 H17/H23；**新增 4 条**：官网两条换编号仍对得上且三类证明整组 N R01、补充材料插入新「无欠税证明…」条目自动并组、脚本引用的编号对不上时 WARN、当前清单通过全部锚点核对 |

## 编号现状（清单现状，仅供对照；脚本和提示词不再依赖）

补充材料：H01–H11 增值税专用发票，H12–H15 上下游合同，H16–H21 社保证明，H22–H27 完税证明，H28–H33 无欠税证明，H34–H35 官网/公众号。

## 验证

test_scripts 44（新增 4）、test_combine_tool 1、test_rule_ledger 14、test_summary 22 全部通过；七个 SKILL.md.zip 重新打包（catalog 包不再含 extract-rows.txt）；runtime_manifest 重算。

## 需要你定 / 留意

1. **清单 desc 疑似有误（你人工核对的数据，我没改）**：H16、H17、H22–H26、H28–H32 的 desc 是 `" + 主体名称原文"`（开头像被截断）；H18–H20 的 desc 是从伪造嫌疑条目抄来的「违背常识的情况、AI生成痕迹」，与名称（信用代码/日期/盖章）不符；H21、H27、H33 名称里有「是否是否」。模型取值只看 desc，建议补成明确口径（例如「证明上的统一社会信用代码原文，与 B03 逐字比」「证明出具/开具日期原文，与基准日比较是否在 3 个月内」「是否有公章/电子章」）。
2. 三种证明共用一个附件参数：材料里只有其中一两种时，缺的那种按 R03 写「未见该证明」；如果要拆成三个请求参数，只需在 `detail.py` 的 `SUPPLEMENT_PREFIX` 里把一行拆成三行。
3. 部署：上传的 catalog skill 包要用新的（脚本 + 清单），不再带 `extract-rows.txt`；其余六个 skill 照旧更新。
4. 未在真实 WanScope 上运行；新增的完税/无欠税条目已在夹具里走通，真实材料的取值口径取决于上面第 1 条。
5. 继承 v34 全部未验证事项。

---

# v34-claude（admission-noshell-v34-claude，修订 34-claude.1）

**基线：v33-claude。需求（用户）：把 `notes.conflicts` 的内容整理成人能读的、准入校验口径的话，放进最终 summary 新增的“注意”一项；文件超时/没有提供这类事项也放进“注意”。**

## summary 结构

`## 结论` / `## 依据` / `## 下一步` / **`## 注意`（新增）**；不生成说明段。“注意”没有任何事项时不出现。**“注意”由 `combine.py summary` 从明细文件生成，不经模型**，所以不用模型再写一遍，也不会写偏。

## “注意”里有什么

| 来源 | 写法（例） |
|---|---|
| 材料与工商不一致（结构化生成，不解析旧文字） | `营业执照名称与工商登记不一致：材料上为「智元创新（无锡）科技有限公司」，工商登记为「…软件有限公司」。请核实并说明原因。` |
| 经营范围不一致（文字太长，只列各自多出的项） | `营业执照经营范围与工商登记不一致（已回看原件二次确认）：材料上有而工商没有：智能机器人的研发；工商有而材料上没有：货物进出口、技术进出口。请核实并说明原因。` |
| 注册资本 | `营业执照注册资本与工商登记不一致：材料上为「人民币壹佰万元」，工商登记为「500万元」。` |
| 二次识别仍不稳/无法确认 | `…回看原件两次识别结果不同（「A」与「B」），工商登记为「C」，需人工核对原件。` |
| 模型写进 conflicts 的其他冲突（如视频招牌与申报名称不同） | 去掉英文字段名、换成中文材料名，末尾标“仅作提示，未作为已核实结论”：`办公场所视频：视频招牌原文「万联易达集团」与申报名称「…」不一致，仅作提示，未作为已核实结论。` |
| 附件超时/失效 | `租赁合同：下载超时，相关核验未进行，请重新提供。` / `业务场景照片：链接失效或不可用…` |
| 附件无法读取 | `以下材料无法读取：无欠税及社保证明（仅占位文字），相关内容未核验。` |
| 请求未提供 | `本次未提供：增值税发票、上下游合同，相关核验按未提供处理。` |
| 模型补记的读取失败（如视频及实际尝试次数） | `办公场所视频读取失败：视频读取两次均超时。` |

不裁决真假：只说“材料上是什么、工商是什么”，请申请方核实。附件字段的中文名在 `combine_config.json` 的 `attachmentNames`，新增附件只改配置。

## 改动

| 文件 | 改动 |
|---|---|
| `scripts/combine.py` | `attention_lines()`（读 `input-extract-detail.json`、`.detail-state.json`）、`diff_sentence()`、字段名中文化；summary 渲染第四段“注意” |
| `scripts/combine_config.json` | `summaryHeadings.attention`、`attachmentNames`、`attachmentIssue` |
| 主提示词、output skill | 摘要段落说明加“注意”（脚本生成，你不写不改）；notes.conflicts 仍按“材料中文名、冲突字段、双方事实各一句”写 |
| 测试 | test_summary 新增 2（整理与各来源、无事项不出现该段）；标题配置用例加 `attention` |

## 验证

test_scripts 40、test_combine_tool 1、test_rule_ledger 14、test_summary 22（新增 2）全部通过；七个 SKILL.md.zip 重新打包并逐文件核对；runtime_manifest 重算（runtime 41 082 → 41 447，script 117 509 → 123 789）。**未在真实 WanScope 运行**；“注意”的措辞是我按准入校验口径拟的，请你看一眼话术是否合适。

## 需要你定

1. “注意”放在“下一步”之后、目前没有事项时整段不出现；如果网关要求固定四段，可改成无事项时写“无”。
2. 要不要把“材料与工商不一致”同时放进“依据”或“下一步”里引导申请方整改（现在只在“注意”提示）。

## 部署

主提示词、七个 skill 一起换成 v34；catalog 里的 `combine.py`、`combine_config.json` 必须同时更新。

---

# v33-claude（admission-noshell-v33-claude，修订 33-claude.1）

**基线：v32-claude。依据：v32 两次真实运行（qwen3.8-max，2026-11-06）**
- `trace-c5b30fc5…` = ontology_agent_job_43_v32-am1（有视频），5 分 32 秒，结论「拦截」
- `trace-c8f64c2c…` = ontology_agent_job_43_v32-am2（无视频），4 分 58 秒，结论「拦截」

两次都提交成功，结论都只来自 RULE-GATE-003「用工场景为空转人工」（与 v30/v31 相同，业务口径问题，见“需要你定”）。本版只修 trace 里看到、能由脚本结构性兜住的问题；主提示词和 skill 只同步了几处措辞。

## 这两次运行里看到的问题

| # | 现象（trace 原文） | 影响 | 本版处理 |
|---|---|---|---|
| 1 | am1 把**文字传给了布尔键**：`main_business_queryable` ← J16 经营范围全文；`peer_platform_merchant`（是否同属灵活用工平台）← E06 视频招牌「万联易达集团；WAN LIAN YI DA GROUP；员工内购会」；`registration/sign/settlement_stage_complete`、`validation_status` ← A12 附件盘点串。build 只有枚举校验，全部进了 input 并送进引擎 | 引擎拿到错误类型的值，规则判定不可信；同一请求 am2 就没这样映射，结果全看模型发挥 | `combine.py build` 新增**类型校验**（按规则怎么用这个键）：只和 true/false 比的键只收布尔，只和数字比的键只收数字，否则 `TYPE_DROPPED` 不传、记 R10 |
| 2 | 日期原样传：`business_license_establish_date="2026年04月28日"`、`business_license_expiry_date="2026年04月28日 至 长期"`、`admission_submitted_at="2026-11-06"`；规则是 `expiry_date <= admission_submitted_at` | 两侧格式不同按字符串比，碰巧没出错 | build 把日期键统一成 `yyyyMMdd`（到期类取截止日）；“长期/永久”不造日期、不传（规则只在有截止日且已到期时触发） |
| 3 | `detail.py` 的已知附件里**没有 `legalIdCardFrontUrl/BackUrl`**，被当成“未知附件”，于是“整组没提供 → 自动 N R01”全部失效：am2 没视频，E01–E10 仍要模型手填；增值税发票没提供，H01–H11 两次都由模型填（还先填成 `"false"` 被拒一轮） | 每次多 1–2 轮 fill | 身份证两个字段加入已知附件与材料顺序；法人身份证组按这两个字段判断；补充材料增加“增值税发票 H01–H11”“社保/完税 H16–H21”两个子组 |
| 4 | am2 `recheck` 的 stdin 结尾**多写了一个 `}`**，脚本报“双引号请改写成「」”，模型连错两次后把经营范围原文里的括号「（…）」删了再交 → 判为“两次识别不一致” → **B08 经营范围置 N、退出比对** | 一个真实存在的执照/工商不一致被当成识别不稳，经营范围也丢了 | ①stdin 结尾多余的 `}`/`]` 自动忽略并 WARN；②报错给出出错位置附近的原文，并写明“只改出错符号，不要改 value/text”；③二次识别比较忽略标点与括号差异 |
| 5 | 首次 fill 被拒 18 行（am1）/19 行（am2），几乎都是判断行漏了「｜」，如「营业执照 bizlicUrl 为JPEG图片…」 | 每次多 1 轮（约 15 秒）+ 一次重发 | text 以「材料名 xxxUrl [pN]」开头时自动在来源后补「｜」（打印 AUTOFIX）；仍不符的报错带一条正确示例 |
| 6 | am1 materials 依据写了**完整身份证号码**（materials skill 明令不抄录） | 敏感信息进了明细文件和日志 | fill 拒收含身份证号的 text/value/materials 依据（校验位+出生日期判定，19 位银行账号不误判） |
| 7 | 执照注册资本「人民币壹佰万元」vs 工商「500万元」，**两次运行都没发现**（11 项比对里没有注册资本） | 真实的材料与工商不一致没进 conflicts | 比对加第 12 项 B10↔J08（只进 conflicts；工商没写单位时不比，避免 v25 数据「300.000000」误报） |
| 8 | am1 自审第⑤项写“`detail.py compare` 输出：…其余一致”，但**这次运行根本没调用 compare** | 自审数字是编的（与 v24/v25 同一模式） | build 直接打印 `COMPARE_SUMMARY` 一行；output skill 自审⑤改为“贴出 build 的 COMPARE_SUMMARY 原文”，不再要求另跑 compare |
| 9 | summary 校验：am1 引「交付要求」被拒后，改写成「dlvrDemd」「projCont」就通过了，最终摘要里出现英文字段名；被拒时还另报“RULE-GATE-003 没出现在任何依据里”（其实写了），am2 模型为此困惑了一轮 | 摘要给客户看，出现内部字段名 | 「」里是纯英文标识符时拒收；依据因引文被拒时，不再另报“规则未覆盖”，改为提示“这条依据已带 X，只改文字即可” |
| 10 | 清单 C12「是否外籍与港澳台人员」的 desc 是 C11（持证人核实状态）的复制 | init 打印的口径是错的 | 改为“按证件类型原文：居民身份证→false；外国人永久居留证、港澳台居民居住证/通行证→true；看不清→N R03” |

**观察到、本版没改的**（不是脚本能兜住的，或需要你定）：
- am1 的其他语义性映射偏差：`lease_contract_both_sealed` ← G01（合同可读≠双方盖章）、`supplement_main_business_verified`/`supplement_alt_materials_ok` 由“社保、完税证明已提供”推出 true、`business_license_image_ok` 在 B12/B13 都为 false 时 set 成 true。类型对、含义错，脚本判断不了。am2 对这些键全部 skip。两次同一请求，进入 input 的键数 27 vs 15，差异主要在这里。
- 画面判断类不稳定：同一张执照，B12（原件彩色扫描）am1=false（理由“是 JPEG”）、am2=true。
- GATE-003 仍是唯一决定结论的规则（见“需要你定”）。

## 改动位置

| 文件 | 改动 |
|---|---|
| `scripts/combine.py` | `type_fix()`（布尔/数字/日期按规则用法校验与规范化）、`TYPE_DROPPED` 输出、`COMPARE_SUMMARY` 输出；summary 拒收「英文字段名」、引文被拒时不再连带报“规则未覆盖” |
| `scripts/combine_tool.py` | validate 允许日期键的值是明细原文日期的 `yyyyMMdd` 形式 |
| `scripts/detail.py` | 已知附件加身份证两字段；整组/子组自动 N（视频、身份证、增值税发票、社保完税）；stdin 容错与报错定位；fill 自动补「｜」、拒收身份证号；二次识别忽略标点；比对加注册资本（含大写金额解析） |
| `extract-items-checked.json` / `extract-rows.txt` | C12 desc 更正（`build_catalog_v33.py` 重新生成，只此一行变化） |
| 主提示词、catalog/materials/facts/output skill | “11 项”→“12 项”；facts 补一句 TYPE_DROPPED 与日期规范化；output 自审⑤改为引用 COMPARE_SUMMARY |

## 验证

- integration：test_scripts 40（原 32 + 新 8）、test_combine_tool 1、test_rule_ledger 14、test_summary 20（原 19 + 新 1）全部通过；原有用例一个未改。
- 新用例逐条对应上表：文字映射到布尔键被丢弃且键数仍闭合、日期统一 yyyyMMdd、长期不传/有截止日取截止日、AUTOFIX 与示例报错、身份证号拒收且 19 位账号不误判、stdin 多一个 `}` 被接受、二次识别只差括号判“确认不一致”、注册资本不一致被比出、身份证字段为已知附件后视频/发票整组自动 N、summary 拒收「dlvrDemd」且不连带报错。
- 七个 `SKILL.md.zip` 重新打包并逐文件核对；runtime_manifest 重算（runtime 40 881 → 41 082 字符，script 108 277 → 117 509）。
- **未在真实 WanScope 运行**。v32 两次运行的规则/属性定义/工商原文只在平台落盘、不在 trace 里，新用例用的是 v25 夹具 + 按 trace 构造的规则片段。

## 需要你定

1. **GATE-003「用工场景为空转人工」（riskMeasure=拦截）**：`usage_scenario` 是枚举，请求里没有行业分类字段，规则条件里也没出现“一般行业”的编码，所以只能不传 → 每个请求都被拦截。v30 起每次运行结论都只来自这条。要么请求带上用工场景编码，要么调整这条规则的 riskMeasure / 条件。
2. TYPE_DROPPED 目前是“丢弃 + 记 R10”，不阻断。若希望映射错类型时直接让 build 失败、逼模型改映射，可以改成退出码非 0（代价是多一轮）。

## 部署

主提示词、七个 skill 一起换成 v33；catalog 的 `detail.py`、`combine.py`、`combine_tool.py`、`extract-*.json/txt` 必须同时更新（提示词里的 COMPARE_SUMMARY、12 项比对依赖新脚本）。

---

# v32-claude（admission-noshell-v32-claude，修订 32-claude.1）

**基线：v31-claude。需求（用户）：写摘要只看命中的规则——用程序把引擎返回过滤一遍，只摘出命中结果，存成 `hit-rules.json`，去掉大量未命中结果，让注意力更集中。**

## 先回答：summary-draft.json 是什么

它**不是**总结结果，是模型提交的「依据/下一步」草稿（`{"basis":[…],"next":[…]}`），在 `combine.py summary` 校验通过后才落盘，只作留档，后面没有任何步骤读它。真正的总结结果是同目录的 `summary-final.json`（仅含渲染后的 summary），也就是 SUMMARY 行的内容。本版只把这两个文件的用途写进了 output skill，没改它们。

## 改动

| # | 改动 | 位置 |
|---|---|---|
| 1 | `combine.py result --rid <id> --file <原始返回>`：从原始返回里只摘出 result=true 的规则，写 `work/<id>/hit-rules.json`：`hits`（ruleId、ruleName、riskMeasure、漏斗级别、是否结论级别、reason、comment 全文、stage）+ `counts`（总数、已判定、命中、未命中 F/U、skip、后续阶段 skip、未知状态、重复 ID）+ `funnel`（结论级别、副标题、无结论原因）+ `source`（原始文件 path、sha256、全部 ruleId） | `combine.py` |
| 2 | `result` 的打印只列命中规则；未命中（am2 是 12 条 F）和 skip（63 条）只给计数。`FUNNEL_HITS` 改列 ruleId，不再列小表序号（am2 模型把序号 15 读成了“15 条命中”） | `combine.py` |
| 3 | `combine.py summary --rid <id>` 只读 hit-rules.json，不再读原始返回；规则计数保存在 `counts`。仍兼容旧调用 `--file`（给了就先重新生成 hit-rules.json） | `combine.py` |
| 4 | 审核 B 不再复制“规则小表”和 NEED_BASIS，改为 Read hit-rules.json（H）和明细（E）；自审对照也指向 H 里的 comment | output skill 3.4 |
| 5 | 引擎没跑起来（ENGINE_FAILED，退出 5）时不写 hit-rules.json | `combine.py` |
| 6 | 主提示词执行表第 7 行、第一节第 4 条，catalog 文件表，output 第三节同步；写明 summary-draft.json / summary-final.json 的用途 | 主提示词、catalog、output |

保留的：`allRuleIds`（全部规则 ID）只给脚本用来拒绝“依据里写了规则 ID”，模型不需要读；未命中的规则全文不进文件。原始返回文件不删，仍是唯一来源，hit-rules.json 里有它的 sha256。

## 这样做合理吗（我的判断）

方向合理，但收益要说准：**v31 的模型本来就没读过 78 条原文**——`result` 小表只列 true/false（am2 是 15 行），`summary` 的 NEED_BASIS 只列结论级别的命中规则。所以这次真正去掉的是小表里那 12 条“未命中”行，以及审核 B 要复制的那张表。另外两个好处更实在：①写摘要的输入变成一个固定的、可 Read 的小文件，审核员和事后排查都看同一份；②`summary` 不再依赖原始返回，计数和命中都来自同一次过滤，不会两次解析不一致。

## 验证

- integration：test_scripts 32、test_combine_tool 1、test_rule_ledger 14、test_summary 19（原 16 + 新 3）全部通过。原有 2 个用例因输出格式变化（计数行措辞、FUNNEL_HITS 改列 ruleId、未命中行不再打印）改了断言，期望的数值不变。
- 新增用例：hit-rules.json 只含命中规则且 comment 全文、计数正确；**删掉原始返回文件后** summary 仍能出 NEED_BASIS 并渲染，命中明细计数与原来一致；依据里写未命中规则的 ID 仍被拒；没有 hit-rules.json 时 summary 提示先跑 result；引擎失败不生成文件。
- 七个 `SKILL.md.zip` 重新打包并逐字节核对；runtime_manifest 重算（runtime 40 186 → 40 881 字符，script 105 636 → 108 277）。
- **未在真实 WanScope 运行**；am2 的引擎原始返回不在 trace 里（只有落盘元数据），没法用它复现。

## 部署

主提示词、七个 skill 一起换成 v32；catalog 里的 `combine.py` 必须同时更新（旧脚本没有 `result --rid`，也不会写 hit-rules.json，新提示词下的 `summary --rid` 会报“先运行 result”）。

---

# v31-claude（admission-noshell-v31-claude，修订 31-claude.1）

**基线：v30-claude。依据：v30 真实运行 `trace-53bc87f8…`（ontology_agent_job_43_116-am2，qwen3.8-max，4 分 53 秒，19 次模型调用、输入 135.5 万 token / 输出 1.7 万 token，成功提交，结论「拦截」）。需求：找出没起作用、或可以简化的提示词，不改变原意。**

**脚本（detail.py、combine.py、combine_tool.py、combine_config.json）、清单、schema 一字未改**，只改主提示词和 7 个 SKILL.md。运行时提示词 49 623 → 40 186 字符（−19%）。

## 这次运行里看到的（据此判断哪些提示词没用）

| # | 现象（trace 原文） | 结论 |
|---|---|---|
| 1 | 平台**没有 Agent 工具**：审核 A、审核 B 都走了“自审”分支 | 两段独立审核员模板（约 6 千字）每次都随 output skill 加载、但从未被用到；不删（以后有 Agent 工具还要用），把“没有 Agent 工具”的自审写到条款后面单独一段，条款本身只保留需要语义判断的那部分 |
| 2 | 模型从头到尾没有用 Read/Write/Edit/Glob/Grep（全部由脚本完成） | 主提示词里“明细一次 Write、Write/Edit 不与引擎同轮、不要 Read/Grep 落盘文件”等在 4 处重复，合并为第一节第 3、4 条各一次 |
| 3 | **视频问法没被遵守**：video skill 与 ReadVideo 在**同一轮**发出（第 2 轮），模型调 ReadVideo 时还没看到固定问法，实际问的是“是否为真实办公场所……是否有叠化转场、无人空镜、渲染感”——正是 video skill 禁止的问法 | 这是结构问题，不是措辞问题：固定问法从 video skill **移到主提示词第二节**，第 2 轮调 ReadVideo 时已在上下文里；video skill 只保留取值与重试规则 |
| 4 | 主提示词红线与各 skill **大段重复**：四个标识预设在主提示词、discover、facts、output 各写一遍；二次识别的四种判定在红线 9 和 materials 各写全一遍，catalog、business、facts 再各复述一次；漏斗规则在主提示词开头、红线 11、output 3.1 各写一遍 | 每条规则只在一个地方写全，其余位置改为一句话 + 指向 |
| 5 | 部署的主提示词比仓库 v30 **旧一版**（trace 里还是“固定四段”的旧摘要结构；skill 是新的） | 不是提示词问题；见“部署”第 1 条 |
| 6 | `combine.py build` 带 `set` 补了 `business_license_image_ok` 之后，因 B23/C10 `fill --force` 又重跑 build（不带 set），该值丢失，模型发现后重提一次 | v30 提示词说“映射落盘沿用”，没说 set 不落盘 → 加一句“set 不落盘，之后每次重跑 build 都要再带上”（脚本行为如此，只是把它写出来） |
| 7 | 模型把 `FUNNEL_HITS 拦截:15` 读成“15 条命中”并困惑 | `15` 是小表序号。output skill 第三节加半句说明（不改脚本） |
| 8 | 自审时模型自己发现 B23/C10 写了“国内真实地址”并改掉 | facts 的禁用字样规则起作用了；保留，并补“含‘国内真实地址’这类写法” |
| 9 | 模型把 `usage_scenario` 按 R10 skip → GATE-003「用工场景为空转人工」命中 → 结论「拦截」 | **不是提示词冗余问题，本版不改**；见“需要你定”第 1 条 |

## 删掉 / 合并了什么（原意不变）

| 位置 | 删减 | 为什么不改变原意 |
|---|---|---|
| 主提示词开头 | 摘要四级口径的整段复述 | 红线 11 + output skill 3.2 已有完整表格 |
| 红线 2 | 合并成一段：四个标识、企业名称必传的原因、“不为让规则运行而填值” | 内容全保留，只去掉与 discover“标识”一节重复的括号说明 |
| 红线 5 | 吸收原第二节下方“枚举属性只传规则里出现过的编码”整段 | 同一规则原来写两处 |
| 红线 9 | 二次识别四种判定结果的展开 | materials 第二步半是唯一完整版本，红线只留硬约束（每项一次、工商不覆盖原件、不出 PASS） |
| 第一节 | 删“本次属性白名单 = …”（与红线 2 同义）；工具清单去掉 Read/Write/Edit、FinalizeRuleSummary（本版不用）；“落盘、不读正文、用 rules/props/result 看”合并成一条 | 这些工具主流程本来就禁用；FinalizeRuleSummary 在 output skill 已写“本版不使用” |
| 第二节 | 执行表各行去掉与红线重复的括号；“脚本代替模型读大文件”一段并入第一节第 4 条；**加入视频固定问法** | 见上表第 3 条 |
| 第三节 | 删“格式不变”“没有 Bash、不手写 JSON”“规则、定义不需要你抄写”等说明性句子 | 红线 6 已规定 |
| 第六节 | unresolvedProperties 那条原来写了半句又重复半句（v30 遗留的病句），改成“脚本生成，原样使用” | 与 build 的 NOTES 行一致 |
| discover | 删已由脚本完成的“提取规则引用键”的手工步骤说明；“内部分类 direct/derived/judgment/result/nosource”与“skip 原因码”合并为一张按 R14/R13/R10/R11 的选码表（拿不准时的默认码从 catalog 第四节搬来） | 分类只是为了选 skip 原因码，合并后口径相同 |
| business | 删 J01–J29 逐项写 source 的手工步骤（init 已从三个落盘文件预填 J 组），保留取值口径 | 本次 J 组只有 J29、J32 留给模型 |
| catalog | 删已废弃的 `extract-rows.txt`、`names` 命令说明；明细格式示例只留两行；第四节去掉与 discover 重复的选码规则 | 文件仍在包里，脚本不变 |
| materials | 第一步的表格改成两条（init 已预填“未提供/仅URL/URL 失效”，模型只需给可读/不可读） | 与 detail.py init 的输出一致 |
| facts | 成立月数算法改为指向审核 A 条款 7（脚本计算）；派生行重算说明合并为一处 | 算法原文仍在条款 7 |
| output | 审核 A 模板去掉已由脚本 validate 的条款 1、2、10(a)(b)、11(a)(c)（原来写着“已校验”却仍原文放在模板里），条款编号不变 | 模板头部原本就写明这些条款审核员不审 |
| 全部 | 删版本考古（“v22 实测…”“v28 的代码实际不会，v29 起会”“am8：…”） | 只保留对行为有约束力的那半句；历史在 change.log |

## 部署（需要你做）

1. **先确认 WanScope 里主提示词是哪一版**：am2 用的是 v30 早期文本（“固定四段”），与 skill 不一致。本版请把 `主提示词_v31-claude_编排版.md` 整份替换 system_prompt。
2. 七个 skill 换成 `admission-v31-claude-*`（`SKILL.md.zip` 已重新打包；catalog 包里的脚本与 v30 相同）。
3. `runtime_manifest.json` 已重算（runtime_characters 49 623 → 40 186，script_characters 不变 105 636）。

## 未验证 / 需要你定

1. **「拦截」结论是否符合业务预期**：GATE-003「用工场景为空转人工」的 riskMeasure 是「拦截」；`Employer.usage_scenario` 是枚举（金融类…一般行业），而请求只有交付要求「内部管理系统」，按现有口径（不猜分类）只能 skip，于是“用工场景为空”命中。只要请求里没有行业分类字段，每个请求都会被这条规则拦截。这是业务口径/规则配置问题，提示词没改；要么请求带上行业分类，要么调这条规则的 riskMeasure。
2. 同一结果里 RULE-ADM-007/023（“成立满 6 个月年限通过”）是 true，riskMeasure 是复合写法「不足3月拦截，3-6月建议拦截」，按 v30 口径不识别、只进说明。`established_months=6` 来自 2026-04-28→2026-11-06，脚本算对了。
3. 简化后的提示词**没有真实运行过**；integration 四组测试（32 / 1 / 14 / 16）全部通过，但它们只测脚本，不测提示词文本。
4. 视频问法移到主提示词后，video skill 里不再有问法原文；若部署时只换了 skill 没换主提示词，模型会找不到问法。
5. 没删、但本次也没用到的：两段审核员模板（平台无 Agent 工具）、视频重试规则、引擎失败补传 force 映射、技能配置异常文案——都属于异常分支，本次运行没触发，不代表没用。

---

# v30-claude（admission-noshell-v30-claude，修订 30-claude.1）

**基线：v29-claude。需求：新版规则引擎的返回里每条规则带 `riskMeasure`，有「拦截 > 建议拦截 > 建议放行 > 放行并关注 > 放行」的漏斗过滤关系；摘要要做成截图里的样子：一个结论（带副标题），下面是依据、下一步、说明三段编号列表。**

**本版还按 v29 的真实运行 am8（`trace-a18ab52b…`，55 个观测）做了一次修订，见下面“am8”一节。** am8 暴露的阻断**是我在 v29 引入的**，v30 原先沿用了它。

**最新一处修订（你的决定）：四个标识预设，不再由模型映射**——entpId→`Employer.employer_id`、entpName→`Employer.enterprise_name`、rqId→`Demand.demand_id`、hrInstId→`LaborAgency.agency_id` 与 `Agency.agency_id`；四个 ID 不可互换。这**推翻了我上一版的取舍**（我当时按“映射不能写死”没有预先传 `Agency.agency_id`，导致每个请求会先失败一次）。详见下面“四个标识预设”一节。

**最新修订（你的决定，2026-11-06）：摘要规则重写，删除 summary_debug。** 之前的摘要规则整体作废（T/F 全覆盖、“（X级）/（未命中）”标签、按阶段汇总“重新核查”、收尾追问、说明段、来源标注）。新规则只按**漏斗卡在的级别**写：拦截=依据围绕命中规则的 comment 举证、下一步告诉怎么改正；建议拦截=依据同上、下一步转人工核验+怎么降低风险点；建议放行=依据同上、下一步转人工核验+怎么降低违规嫌疑/补佐证；放行并关注=依据围绕 comment 指出小不足、下一步怎么提高；放行=依据围绕提交的资料夸真实合规（4–6 条）、下一步固定一条。`summary` 为 `## 结论 / ## 依据 / ## 下一步` 三段；最终仅提交 input、notes、summary 三个字段；schema 同步，不生成调试摘要或说明段。草稿格式：`{"basis":[{"ruleIds":[…],"text":"…"}],"next":["…"]}`，脚本校验：依据只能引用结论级别的命中规则且逐条覆盖、放行级条数、引文须逐字出自提取明细、不含规则 ID/英文属性名。下面表格里关于“来源标注”的描述是 v30 初版，已被本段取代。`integration/rule_ledger.py` 及其测试、台账接入文档是 v29 遗留且未部署，当前已同步为仅生成 summary。

先说结论：**v29 及以前明确“不给整体准入结论”，v30 把它反过来了**——摘要现在有结论，结论只取命中规则 `riskMeasure` 的漏斗结果。这是业务口径的变化，不是我顺手加的功能。

| # | 现象 / 需求 | 改动 | 位置 |
|---|---|---|---|
| 1 | 摘要是“首句计数 + 【类别】命中/未命中”的纯文本，没有结论，也没有 riskMeasure | 摘要固定四段：`## 结论`（「级别｜副标题」）、`## 依据`、`## 下一步`、`## 说明`，各段编号列表，标题来自配置，前端按标题切分 | `combine.py summary`、`combine_config.json`、output skill 第三节 |
| 2 | 结论怎么来 | 漏斗：**只看命中（result=true）规则的 riskMeasure，取最严的一级**；`riskMeasure` 必须与五级之一**逐字相同**才进漏斗，复合写法、空值不识别、不猜、不拆分，列入说明；有已判定规则但一条没命中 → 放行；**没有已判定规则，或命中规则的 riskMeasure 都不识别 → “暂无结论”，不给放行** | `combine.py result / summary` |
| 3 | 摘要里的数字、结论、编号靠模型写，历史上多次被实测推翻（v24→v26 自审写“约 120 ✓”） | **当前结论、编号由脚本生成，依据和下一步由模型写草稿并经脚本校验**；模型只写“依据”每一条的文字，脚本校验：每条 T/F 规则至少出现一次、U 和 skip 不进依据、不混桶、不混处置级别、F 依据不得写“已合规/已核实/已满足/已一致/有效期内”、不含规则 ID/英文属性名/【】、「」引文必须逐字出自申报原文（A07–A10、A13，可用…省略）。当前仅输出 `summary`，不生成来源标注和说明段 | `combine.py summary` |
| 4 | 下一步（图里 5 条）从哪来 | 按你的选择“命中规则的 comment 动态生成”：①该级别固定开头 ②结论级别命中规则的 comment 描述（逐字）③结论为建议放行/放行并关注/放行时，按适用阶段（需求发布/签约/结算/处置）汇总 skip 规则成“<阶段>时重新核查：规则名…” ④comment 里「｜」后的额外段逐字作“提示：” ⑤配置里的收尾追问。**没有来源的内容不写**（例如图里“单人月结算上限 20 万”，只有某条规则的 comment 带这个额外段才会出现） | `combine.py summary` |
| 5 | v29 的台账路径（`FinalizeRuleSummary` / `rule_ledger.py`）按旧摘要格式渲染 | **本版不使用**，output skill 第三节 3.6 写明；`rule_ledger.py` 和它的 14 个测试没改（仍按 v29 格式通过），接入前必须先改 | output skill、`integration/` |
| 6 | 失败状态 | 引擎失败、审核未完成、摘要未完成三种仍是**纯文本一句话**，不拼四段 | output skill 第四节 |

## am8（v29 真实运行）：我核实到的

am8 比 am7 走得远：规则/定义/工商/视频/明细/复核/组装/审核都过了，**走到了规则引擎**，然后失败。

- **阻断原因：引擎要 `Agency.agency_id`。** 引擎返回 `code=0`、`ruleCheckResult=fail`、`ruleCheckList=null`，`failures` 第一条是 `hrInst：取值失败：从入参里取不到 Agency.agency_id`，后两条（`riskTags`、`allRules`）和一条 `skipped`（`riskRules`）都是它连带出来的。模型提交的是 `Institution.institution_id`（本次定义里表示机构的属性），引擎不认。
- **这是 v29 的回归，我自己引入的。** v28 在固定标识里**总是**传 `Agency.agency_id`（“不依赖定义是否返回”）；v29 为了“不写死属性名”把它删了，并且在 v29 说明里写过“引擎是否依赖它，我不知道，请确认”——现在确认了：依赖。v30 原先照搬了 v29，同样会失败。
- **模型没有重试，也没有用对的办法读结果。** 提示词允许重试的条件是“调用报错/非成功码/明确指出名称或枚举错误”，而这次是 `code=0`；`combine.py result` 报“文件里没有 data.ruleCheckList”（其实有，值是 null），模型又对结果文件用了 `rules` 命令，最后用 Read 读原始文件才看清，还多写了一个没用的 `summary-draft.json`。最终提交的是正确的失败文案。
- **新问题（我在 v29 说“映射质量取决于模型”时担心的，这次出现了）**：提交给引擎的 input 里有 4 个枚举属性传了错误的值——`enterprise_type="有限责任公司"`、`bank_account_nature="基本户"`（中文标签）、`lease_contract_status=true`、`id_card_valid_status=true`（布尔）。规则里这些键都是跟英文编码比较的（`= individual_business`、`= other`、`= expired`），v28 的红线 5 本来禁止这样传，但 v29 去掉映射表后，脚本再也拦不住。
- **v29 的新功能这次真跑通了**：B08 经营范围与工商不一致 → 复核 → “确认不一致”，冲突里带「已二次识别确认」。
- 我**没有**看 am8 的规则和属性定义原文（trace 里是落盘清单）。

## 四个标识预设（你的决定，取代下面“每个请求会先失败一次”那段取舍）

| 请求值 | 清单条目 | 传入的键 |
|---|---|---|
| entpId 企业 ID | A01 | `Employer.employer_id` |
| entpName 企业名称 | A02 | `Employer.enterprise_name` |
| rqId 需求 ID | A03 | `Demand.demand_id` |
| hrInstId 机构 ID | A04 | `LaborAgency.agency_id` 与 `Agency.agency_id`（同值） |

- **放在配置里，不在代码里**：`combine_config.json` 的 `fixedIdentifiers`。本体改名时只改这一个文件，不改提示词和代码（有测试：把 A02 改成别的键名，input 随之变化）。
- **`build` 自动传入**，定义里有没有这个键都传（`Agency.agency_id` 在 am8 的定义里就没有，引擎却要）；请求没给的 ID 不传，也不报错、不进 unfilled。`build` 会打印 `PRESET_UNDEFINED`，列出本次定义里没有、仍照传的预设键，**只在输出里，不进 notes**。
- **四个 ID 不可互换**：模型把预设键改映到别的条目（如 `Employer.employer_id` 映到 A03），或 skip 预设键，`build` 直接报错。
- 预设之外，模型仍可把含义确实相同的别的属性再映射到同一个条目（同值同传），其余所有键仍按语义映射。
- 提示词里所有“由你按含义映射标识”的说法已删除（主提示词红线 2 和 10、执行表第 4 行、discover 的“标识”一节、facts、catalog、审核 A 条款 3、回归清单）。审核 A 现在只复核三个 ID 没有互换。
- **顺手修了一个真实 bug**：被拒绝的映射提交（例如上面那种“改映预设键”）原先**已经写进了 `key-map.json`**，之后每次 build 都带着这个错误映射失败。现在全部校验通过后才落盘。我是写预设测试时撞上的。
- 代价/风险：**这四个键名现在是配置里的固定值**。若本体再改名而配置没跟上，input 会带着一个定义里没有的键，规则里引用新名字的那些会 skip；`PRESET_UNDEFINED` 会提醒。引擎自己点名要别的入参键时，仍走上面的“补传 force 映射、最多再调一次”。
- **清单 A02 的说明文字没改**：`extract-items-checked.json` 里 A02 的 desc 仍写着 `Employer.employer_name（必入 input）`，与现在的预设（`Employer.enterprise_name`）不一致。那是你人工核对的数据，我没动；提示词里已声明 desc 里的属性名只是历史提示。要不要改，请你定。

## v30 针对 am8 的修订

| # | 改动 | 位置 |
|---|---|---|
| 1 | `combine.py result` / `summary` 识别“`ruleCheckList` 为 null + `failures`”：打印 `ENGINE_FAILED`、逐条 `FAILURE`/`SKIPPED`，**从引擎自己的报错里读出它点名缺的入参键**（`MISSING_INPUT_KEY X.y`），退出码 5；脚本里不写死任何键名（测试里换成 `Foo.bar_id` 照样读出） | `combine.py` |
| 2 | 重试条件放宽：`code=0` 但引擎没跑起来也算失败；有 `MISSING_INPUT_KEY` 时，在 build 里补一条 `{"ids":[标识条目],"force":true}` 映射（已保存的映射沿用，只补这一条），重建、**重新过审核 A**、再调一次引擎（就是原来“最多再调一次”的那一次）；只补它点名的那个键，不连带别的；没点名或第二次仍失败 → 写“规则引擎执行失败”纯文本。明确禁止用 Read 读原始文件、对结果文件用 `rules` 命令 | output skill 第二、四节，discover，主提示词 |
| 3 | **枚举属性取值校验**（红线 5 的脚本版）：属性定义 comment 以“枚举”开头的键，取值必须是规则条件里与它比较过的编码（`= x`、`IN {x,y}`）；不符打印 `ENUM_DROPPED`，该键不进 input、记 R10，键数仍闭合。`set` 给的值同样校验。只靠 comment 开头的“枚举”二字和规则字面量，不写死属性名 | `combine.py`、facts、主提示词 |

**（已被上面“四个标识预设”取代）一个我当时没替你定的取舍：每个请求都会先失败一次。** 因为定义里没有 `Agency.agency_id`，而我按你“映射不能写死”的要求没有预先传它，所以只要引擎依赖它，第一次调用必然失败，靠第二次调用补上。代价是每个请求多一次引擎调用和一次审核 A。**另一种做法**是在配置里列一个“引擎必传的入参键”清单（v28 事实上就是这么做的，只是写在代码里）。这样不会多失败一次，但键名写死在配置里，引擎改了要同步改配置。你更看重哪个，告诉我。

## 验证

`integration/` 下四个测试文件全部通过：`test_scripts.py` 32、`test_combine_tool.py` 1、`test_rule_ledger.py` 14、**新增 `test_summary.py` 16**（含 am8 的引擎失败返回原文做夹具、枚举取值校验、补传引擎点名的键）。新增用例覆盖：漏斗五级各取最严、skip 不参与、没有已判定规则不给放行、未识别的 riskMeasure 不被猜、**用你给的 `response-1105.json`**（结论「拦截」，复合写法被标为未识别）、**按截图假设的场景**（`response_image_scenario.json`，渲染出四段、级别标签只标每级第一条、下一步五条、去来源后等于 summary、不含规则 ID）、引文必须出自申报原文、覆盖/方向/级别/措辞校验、U 桶不进依据、放行类提醒只算准入阶段的 skip、拦截类不列后续阶段复核、结果不完整不渲染。**我做了 7 个破坏性检查**（把“取最严”改成“取最宽”、全 skip 也给放行、允许 U 进依据、不核对引文、去掉放行提醒、不拦规则 ID、允许 F 写已合规），测试都能抓住；其中“允许 U 进依据”一开始没被抓住，补了测试才抓住。am8 修订另做了 5 个破坏性检查（关闭枚举校验、枚举永远通过、不提取缺失键、失败时退出码 0、null 列表当正常），全部被抓住。标识预设另做了 6 个破坏性检查（预设不并入映射、允许改映、允许 skip 预设键、非规则引用的标识为 N 也进 unfilled、预设不带强制传入、先落盘后校验），全部被抓住；其中“预设不带强制传入”那一条我第一次做错了（替换文本缩进写错、断言被我自己吞掉，变异没有应用，却显示通过），发现后重做才算数。

## 我替你做的取舍（请确认）

1. **副标题与下一步第一条：只有「放行并关注」是你图里的原文**（“可入驻，建议在合作过程中持续关注”；“业务可正常开展、正常入驻”；“纳入重点监控：抽查打卡定位与交付成果，确认任务真实发生”）。**其余四级的副标题和下一步开头是我起草的**（拦截：不予准入，请勿自动放行；建议拦截：建议拦截，需人工复核后决定；建议放行：建议放行，需人工确认后入驻；放行：可正常入驻），请审，在 `combine_config.json` 的 `riskLadder` 里改，不用动代码。
2. **标题语法 `## 结论` 等是我选的**，前端按什么切分我不知道。改 `combine_config.json` 的 `summaryHeadings` 即可。
3. **收尾追问“需要我进一步核查这家公司的关联公司或历史判定记录吗？”照图写进了模板**。这是对话式追问，结构化提交里没人回答；不想要就把配置里的 `closing` 置空。
4. **“依据”的措辞比图更保守。** 图里第 6 条是“三流一致核实通过 …… 主体一致”，这是肯定式的核实结论；引擎对未命中（false）只说“条件不成立”，不能推出“已一致/已核实”，所以我沿用 v29 的规矩，只写“……的情形未命中”。如果你认为 F 规则可以写成肯定式，改 `combine.py` 里的 `BAD_F`。
5. **图里依据第 1 条的“标题句 + 缩进子项”层级复现不了**：摘要是平铺的编号列表，一条规则的多点内容拆成几条相邻的依据，级别标签只标每个级别的第一条。
6. **“没有已判定规则不给放行”是我加的保护。** 按漏斗字面，没有命中就是“放行”；但全部 skip 时“放行”等于把没判定过的企业放行，所以改成“暂无结论”。若你要字面语义，改 `analyze()` 里对应一行。
7. **放行类结论的提醒也是我加的**：结论为建议放行/放行并关注/放行，且仍有准入阶段的 skip 或“未触发”规则时，说明里加一句“该结论仅基于已判定的规则…可能影响结论”。后续阶段（需求发布/签约/结算/处置）的 skip 不触发它。
8. **“已判定但一条都没命中 → 放行”会在判定很少时也放行。** 例如只判了 1 条且未命中。说明里会写出已判定条数和跳过条数，但脚本不设“最少已判定条数”的门槛，要不要设请你定。
9. **图里“说明”第 1 条“付款方修正为…后，三流一致核对通过”不是引擎结果**，是实际业务核查那一步的叙述，本版不生成这类内容。说明只有计数、结论取自哪一级、未识别的 riskMeasure、放行类提醒。

## 关于你给的 `response-1105.json`

78 条规则，4 条有结果（3 true、1 false），74 条 skip。结论是**拦截**（`RULE-GATE-001`、`RULE-GATE-003` 命中，riskMeasure 都是“拦截”）；`RULE-GATE-002` 的 riskMeasure 是“不足3月拦截，3-6月建议拦截”，不在五级内，**未计入结论**，列在说明里。你说这是测试数据，按你假设的场景做，所以我**没有**为这份数据的特殊性写特殊逻辑。只提醒一点：这 3 条“为空转人工”规则只因输入缺企业名称/成立日期/用工场景而命中，v26 时就观察到这类 `IS EMPTY` 规则在输入缺失时必命中，**在真实数据上，只要这些属性没填，漏斗就会得出“拦截”**。要得到“放行并关注”这类结论，这些属性得先能填进 input，这不是 v30 能解决的。

## 未验证与已知局限

- **没有在真实 WanScope 里跑过。** 脚本用 `python3 -I` 在本机测，未经过 RunSkillScript。
- **没有真实的“放行并关注”返回样本。** 图里的场景我是按截图造的夹具，规则 ID、comment、riskMeasure 都是假设的；真实引擎里放行类规则的 comment 写法（尤其「｜」后的额外段）会直接决定“下一步”的内容。
- **“下一步”里 comment 描述逐字出现**，如果真实 comment 写得像规则说明而不是行动（如“主体类型为个体工商户的直接禁入”），下一步读起来会像复述规则。这取决于规则库的 comment 怎么写。
- 前端是否真的按 `## 标题` 切分、是否能渲染 emoji（✅ 👁️ 🔄 ⛔ ⚠️），我不知道。
- 审核 B 是模型，只看语义；脚本校验不了“依据文字是否忠实于规则”。
- **部署必须同时更新 `combine.py` 和 `combine_config.json`**：旧的 config 没有 `riskLadder`，`result` 会直接报错。
- **枚举校验只能拦“规则里出现过的编码”以外的值，拦不住“编码对但语义错”**；规则里没出现过的编码（例如“有限公司”对应的编码，规则只写了 `= individual_business`）模型无从得知，所以这类键会被丢弃、对应规则 skip，而不是被正确求值。要让它们参与判定，得让规则库或属性定义提供编码表。
- **日期格式没有校验**：am8 的 input 里有 `business_license_establish_date="2026年04月28日"`、`business_license_expiry_date="2026年04月28日 至 长期"`、`admission_submitted_at="2026-11-05"` 三种写法，清单 B05 的说明写着“比较类键用 8 位 yyyyMMdd”，但脚本不检查。我没看到引擎对日期的要求，所以没动。
- am8 里 `fill` 仍被拒 7 行（text 缺「来源｜证据」格式），第二、三次又拒 1 行（C01 连续两次），v28 的 am7 也有同样现象，说明报错提示还不够；我没改。
- 继承自 v29 的未验证事项仍然有效（映射由模型决定、`Agency.agency_id` 不再写死、清单 desc 里 8 条带属性名的历史提示、list_rule/list_property 并行是否真会失败、审核 A 5 轮后“删除后继续”与红线 7 的矛盾、开户账号完整抄录等），见下方 v29 说明。

---

# 以下是 v29 的说明（保留作背景，名称以 v30 为准）

# v29-claude（admission-noshell-v29-claude，修订 29-claude.1）

**基线：v28-claude-script（含 2026-11-05 对 v28 的两处修订：审核 A 最多 5 轮、开户账号 D10 不脱敏，这两处在 v29 里照常保留）。需求：三个工商服务返回的企业信息，要与模型从 PDF/图片识别出的营业执照、身份证等信息比对；发现不匹配，回看原件再识别一次；确认确实不一样，更新到 input-extract-detail.json。**

**同一版里还修了 v28 在 am7 真实运行里的阻断（见下“am7 trace”），并把“清单条目→本体属性”的映射从对照表改成模型按语义决定。**

先说结论：v28 只有 J34 一项比对（执照七个字段对工商），没有“不一致 → 回看原件”这一步；而且在核对时发现 v28 还有一个更底层的缺陷，会让“更新明细”这件事本身不可靠，见第 2 行。

| # | 现象 | 改动 | 位置 |
|---|---|---|---|
| 1 | v28 没有“不一致 → 回看原件再识别一次 → 确认后更新明细”的闭环。J34 只比营业执照七项，身份证姓名、开户凭证、租赁合同承租方不参与；现有“针对性复核一次”只针对栏位仍为空，不覆盖“已识别但与工商不一致” | 新增 11 项比对（B01/B03/B06/B04/B05/B07/B08 对 J01/J02/J07/J09/J10/J13/J16；C02、D08 对 J07；D01、G02 对 J01）。不一致的项在 fill 输出里以 `RECHECK_ITEM` 列出；新增 `detail.py recheck`（提交二次识别）和 `detail.py compare`（只读查看）。**每项只复核一次**。结果：二次=首次 → 确认不一致，保留原件值，source 追加“复核：…”，J34/conflicts 标「已二次识别确认」；二次≠首次且=工商 → 更正；二次≠首次且≠工商 → 置 N R06；二次仍看不清 → 置 N。**工商值永远不覆盖原件值** | `detail.py`、主提示词红线 9 与执行表 3b、materials“第二步半”、business、catalog |
| 2 | **v28 缺陷（本次复现）**：`derive()` 只补 `source==""` 的待填行，所以 `fill --force` 改了源字段后，已写好的派生行不重算。实测：把 B01 改成别的名称，B15 仍 true、J34 仍“无不一致”；把 B04 删成 null，B16 仍是 23 且照常 PASS。facts skill 写“依赖它的派生行脚本会自动变 N R12”，代码里并不成立。这也让审核 A 的删值修复（现 5 轮）绕得过去 | `derive()` 每次先把脚本自己写过的派生行（`st.derived`）复位，再按当前依据重算，并重建它加的冲突说明（`st.autoConflicts`）。模型自己 `--force` 改写过的行不再被脚本接管 | `detail.py` |
| 3 | 模型自己写的“派生:…”行（H17/H20 社保/完税名称匹配、B09、F03 等）脚本无法代算，依据变了也没提示 | 依据行的**值**变了（只改 source 说明不算）→ 输出 `STALE`，要求模型重判后 `fill --force` 重提 | `detail.py`、facts |
| 4 | 门禁只看“待填为 0” | fill/recheck 的 PASS 要求同时：无待填、无未复核的不一致项、无 STALE；`finish` 在此时退出码 3；`combine.py build` 也拒绝（退出码 2，“复核门禁”） | `detail.py`、`combine.py` |
| 6 | **am7 阻断（见下节）**：本体把 `Employer.employer_name` 改名为 `enterprise_name`，v28 校验器仍强制要求旧名，`build` 两次报 `input 缺 Employer.employer_name`，规则引擎未执行 | 去掉脚本里所有写死的属性名（固定标识键、`_name` 后缀、结果类正则、定义冲突清单、`Agency.agency_id` 特例）；**删除 `key_map.json`**。新增 `combine.py plan`；`build` 的 stdin 提交 `map`/`skip`/`fixedUnmapped`/`toolIssues`，映射落盘 `work/<id>/key-map.json` 并在之后的 build 沿用；首次 build 无映射 → 打印 PLAN 并退出 4。校验按清单里的四个标识条目 A01–A04（清单侧稳定）判断：有值就必须映射到某个属性，或在 `fixedUnmapped` 写明原因 | `combine.py`、`combine_tool.py`、`combine_config.json`、主提示词红线 10 与执行表第 4 轮、discover/facts/catalog/output |
| 7 | 映射不再是对照表，语义是否对得上没人把关 | 审核 A 条款 6 扩展：逐个核对 `entities` 每个属性的 label/comment 与其主条目 name/desc 含义一致，对不上就删除该属性；条款 3 改为按 A01–A04 覆盖校验 | output skill |
| 5 | 审核员看不到附件，无法判断是否真的复核过 | 审核 A 新增条款 12：不一致项的原件侧 source 必须有“复核：”记录；原件值不得被写成工商值；确认不一致须有「【已二次识别确认】」与 conflicts；不得把“不一致”写成“伪造”。5 轮后仍缺复核记录的按 N R06 处理 | output skill |

## am7 trace（`trace-b28027ff…`，35 个观测）：我核实到的

- **失败原因属实**：`combine.py build` 两次输出 `ERR input 缺 Employer.employer_name`、`validate: 1 errors`，INPUT 只有 `Employer.employer_id` 和 `Agency.agency_id`，最终摘要“审核未完成：技能配置异常…规则引擎未执行”。`combine_tool.py` 的校验写死 `Employer.employer_name`，`combine.py` 又因定义没有该键而跳过它，模型用 `set` 补传无效。
- **映射表整体失效**：65 个规则引用键里 64 个报 UNMAPPED（`enterprise_name`、`established_months`、`enterprise_type`…），不止企业名称一处。这次本体只有 **7 个对象、76 条规则**（v25 是 24 个对象、197 条），说明本体变动很大，补几个键名治不了根。
- **新发现，与 README 里 am6 的推断不符**：am7 里模型把 `mcp_list_rule` 和 `mcp_list_property` **放在同一轮并行调用，两个都成功**（item_count 76 / 7）。这不能证明 am6 的 BIZ_FAIL 不是并发导致（可能偶发），但“并行必失败”的前提不成立，v28 里“必须分轮”的硬性表述依据变弱。**我没有改这条规则**，等你决定。
- 另外观察到：第一次 `fill` 被拒 18 行（text 没有「来源｜证据」格式），模型还试图提交脚本预填的 J34 被拒；这两处 v28 已有的提示都生效了，最后 144 条明细完整通过。
- **没有 am7 的规则/属性原文**（trace 里只有落盘清单，没有正文），所以我没能用 am7 的真实文件复现，只能用 v25 真实数据 + 模拟改名（`employer_name→enterprise_name`、`founded_months→established_months`）回归。

## 验证

`integration/` 下三个测试文件全部通过：`test_scripts.py` 25 个（原 9 + 复核 10 + 语义映射 6）、`test_combine_tool.py` 1、`test_rule_ledger.py` 14。新增用例用 v25 真实运行的请求/工商返回/规则/属性：派生行随依据重算（含删值变 N R12、旧冲突不残留）、名称变更流入 B15/J34、不一致时 build 被门禁拒绝、确认不一致保留原件值、首次误识别被更正、两次不一致/无法确认置 N、已复核项不可重复复核、与工商一致的项被拒、身份证姓名对法定代表人、改了已复核的行后重新开放比对、STALE 的产生与清除。v25 真实数据的 input 逐项一致这条回归仍通过——映射改由模型提交后（夹具 `map_spec.json` 由旧映射表转换而来），结果与真实运行一致。语义映射新增 6 个用例：无映射时打印 PLAN 退出 4；**模拟 am7 改名后仍能组装并通过校验**；标识条目没映射/没声明原因被拦下，声明后放行并写入 toolIssues；UNDECIDED/IGNORED 提示；映射格式与自相矛盾（同键既 map 又 skip）报错；审核退回后沿用已保存映射。

## 我替你做的取舍（请确认）

1. **比对范围 11 项。** 你说的是“营业执照、身份证等”，我加了身份证姓名 C02、开户凭证 D01/D08、租赁合同承租方 G02。这四项只进 conflicts，不进 J34（J34 的 desc 固定为执照七项）。v28 时这些条目都没有被规则属性引用，复核不影响 input；**v29 起映射由模型决定，若你把它们映射到某个属性，复核更正后的值会随重新组装进入 input**。
2. **“两次识别不一致”按保守处理：** 二次识别既不等于首次、也不等于工商时，该项置 N R06 不取值，不猜哪次对。
3. **“同一事实”口径沿用 v28 的 J34**：名称/地址/经营范围忽略空白和括号全半角后逐字比，信用代码忽略空格和大小写，法定代表人互相包含算同，成立日期按日，营业期限比截止日。
4. **每项只复核一次**，不是“复核到一致为止”。

## 未验证与已知局限（请先看）

- **映射质量现在取决于模型。** 以前是维护者写好的表（可能过时，但稳定）；现在每次由模型按 label/comment 判断。脚本只能校验格式、条目存在、标识覆盖，**校验不了语义对不对**；兜底是审核 A 条款 6，但审核员也是模型。把“成立月数”映射到含义不同的属性，脚本不会发现。
- **v28 总是传 `Agency.agency_id`（写死），v29 不再写死。** 本体不返回机构 ID 属性时，v29 默认不传（除非模型用 `force` 降级或规则引用了该键）。引擎是否依赖 `Agency.agency_id`，我不知道，**请确认**。
- **清单 `desc` 里仍有 8 条带「对象.属性」提示**（A02、A03、A04、C11、C12、H10、J32、J33；A02 写着 `Employer.employer_name（必入 input）`，正是 am7 里会误导的一条）。这是你人工核对的数据，我没改；提示词里已声明“只是历史提示、不作映射依据”，但**建议你决定是否从清单里去掉**（改 `extract-items-checked.json` 与 `extract-rows.txt`）。
- `plan` 的输出随规则数增长：v25 那套 154 个键约 324 行、2 万字符；am7 的 65 个键小得多。
- 标识候选列表是按 label 里含“ID/编号/名称”且涉及企业/客户/需求/机构/代理的子串筛的，只是提示，漏了也能用 `combine.py props --obj` 看全。

- **没有在真实 WanScope 里跑过。** 脚本用 `python3 -I` 在本机按 RunSkillScript 的方式测，未经过平台本身。
- **“二次识别”无法被脚本验证。** 脚本只能比较字符串，不知道模型是否真的回看了原件、还是照抄了首次的值。约束只来自提示词和审核 A 条款 12（审核员能看到 source 里的复核记录与二次识别原文，但看不到附件）。同一个模型对同一张图再看一次，错误可能重复出现，这不是独立验证。
- **经营范围 B08 最容易触发复核。** 口径只忽略空白和括号全半角，不忽略标点（如全角“；”与半角“;”、顿号）。长文本识别时标点差异很常见，可能多数请求都会对 B08 做一次复核。这是 v28 的 J34 就有的口径，v29 没改；若想放宽，改 `same_fact` 的 `scope` 分支。
- **法定代表人是企业时，C02/D08 对 J07 的比对没有意义**，会产生一次无效复核。脚本没有按 J07 的“类型”区分。
- **工商侧也可能是错的**，脚本不裁决，只记冲突。
- 复核通过只说明“识别准不准”，不是真伪判断；确认不一致 ≠ 伪造，提示词已要求不据此填伪造嫌疑类条目。
- 继承自 v28 的未验证事项仍然有效（见下方 v28 说明）：新脚本未端到端运行、`input:{}` 取全部对象来自口头确认、规则/属性并行调用失败的根因未确认、T/F/U 分桶口径待业务确认。
- 继承自 v28 的审核 A 5 轮上限与“删除后继续是否算通过”的矛盾（output skill 与红线 7）仍未解决。
- **开户账号 D10 现在完整抄录**（v28 修订），账号会完整出现在明细、审核员 prompt 和 trace 里。
- 部署：把 agents_config 里的 system_prompt 和七个 skill 更新为 v29（各 `SKILL.md.zip` 已重新打包；catalog 包含 scripts）。**必须同时更新 catalog 里的 `detail.py` 和 `combine.py`，只换提示词不换脚本会缺少 `compare`/`recheck` 命令。**

---

# 以下是 v28 的说明（保留作背景，名称以 v29 为准）

# v28-claude（admission-noshell-v28-claude，修订 28-claude.1）

**基线：v27-claude。依据：v27 三次真实运行的 trace（am3 全部未落盘 / am4 只有规则与属性落盘 / am5 全部落盘）。核心：工具结果保持落盘，由脚本代替模型读取；落盘后模型不再猜对象清单。**

| # | 现象（trace 证据） | 改动 | 位置 |
|---|---|---|---|
| 1 | am5 没读到规则就请求 5 个对象，只回 3 个；154 个规则引用键 117 个找不到定义，input 仅 9 个字段 | mcp_list_property 的 input 传 `{}`（不带 name，返回全部对象），**第 2 轮单独发（与 mcp_list_rule 并行会报 BIZ_FAIL，见下）**；新增 `combine.py rules / props` 摘要命令；禁止 Read/Grep/Write 落盘文件 | 主提示词二、discover skill、`combine.py` |
| 2 | `--biz` 逗号拼接（am3、am5）；am4 把规则文件当 `--biz`，静默接受，工商只填 14 条（应约 35） | 逗号兼容；传规则/属性文件报错；打印读到哪几个工商接口 | `detail.py init`、主提示词 |
| 3 | fill 被拒 am4 四次、am5 七次（写成 `N｜R10｜…`） | 自动去 `Y｜/N｜` 前缀；报错带示例；合格行先写入，只重发被拒的；show 状态分列、空值显示（空） | `detail.py fill / show` |
| 4 | 引擎返回 9 万字符单行 JSON，Read/Grep 折腾约 2.5 分钟 | `combine.py result --file`：计数 + true/false 小表（T/F/U 桶） | `combine.py`、output skill、主提示词 |
| 5 | am5 擅自在最终输出里加 27 KB 的 `extractionReport` 被拒重发（约 100 秒） | 明确禁止自加；规则待定 | 主提示词、output skill |

## 修订（2026-11-05，按用户要求，修订号仍为 28-claude.1）

| # | 改动 | 位置 |
|---|---|---|
| 1 | **审核 A 的“审核→修复→重跑 build”上限由 2 轮改为 5 轮**；5 轮后仍有退回的处理不变（条款 3、4、5、6、8 按删除该属性继续；条款 2 或 validate 无法修复则不发引擎请求）。**审核 B（摘要审核）仍是 2 轮**，未改 | 主提示词第二节第 5 行；output skill 第一节“处理”两处；`references/回归验收清单` |
| 2 | **开户账号 D10 不再脱敏**：value 和 source 证据段都完整抄录账号栏原文，不加星号、不截断；原件上有看不清的位数时不补全，整条记 N（R03 或 R06）。审核 A 条款 10(k) 由“证据段不得出现完整账号”改为“须完整抄录；出现星号/省略号/只有前后几位则退回” | catalog skill 第五节第 4 条；materials skill 开户凭证行；output skill 条款 10(k)；`references/回归验收清单` |

注意：①账号是个人/企业敏感数据，现在会完整出现在 `input-extract-detail.json`、审核员 prompt 和 Langfuse trace 里；②账号是否进入 `input` 仍由“规则引用 + 定义返回”决定，本次没改；③脚本（`detail.py`、`combine.py`）本来就没有对 D10 做脱敏，未改，`integration/` 测试未改；④修订号没有递增，已部署的 28-claude.1 与本次内容无法靠版本号区分，部署时请注意；⑤`runtime_manifest.json` 已重算（runtime_characters 40648 → 40891），catalog、materials、output 三个 `SKILL.md.zip` 已重新打包；⑥`integration/` 下 test_scripts（9）、test_combine_tool（1）、test_rule_ledger（14）全部通过，但这些测试不覆盖提示词文本，**两项改动没有真实运行验证**。

## 发布后发现的 bug（am6）

第一版 v28 把 mcp_list_rule 和 mcp_list_property 放在第 1 轮并行发出，结果两个调用都返回“BIZ_FAIL：domain 不能为空”（请求里 domain 实际是 enterprise），模型重试一次仍失败，按提示词走“审核未完成”，没有调规则引擎。已改为 mcp_list_rule 在第 1 轮、mcp_list_property 在第 2 轮。**根因没有确认**：list_rule 的参数与 am3–am5 完全相同却也失败，唯一的新变化是并行发出 list_property，所以判断是本体服务对同一 requestId 的并发调用有问题，但这是推断；服务端代码不在仓库里，没法核实。若改后仍失败，问题在 `input:{}` 本身或服务端。

## 未验证（请先看）

- 没有在真实 WanScope 里跑过新脚本。
- “不带 name 返回全部对象”来自你的确认，我没有实际调用过；本版 fixture 里 am3 的定义是 24 个对象。
- am5 的引擎结果、规则、定义落盘内容在 trace 里看不到，T/F/U 桶没对 am5 核对。
- 桶判定对 am4 的实际结果是 F=8、U=0，而 am4 模型自己写的是 U=4（ADM-003/006/010、IND-PRO-001）。这四条 expression 最外层都是 AND 且 reason 含“不满足”，按 output skill 3.1 应是 F；哪边符合业务口径请你确认。
- 本版没有做 extractionReport，也没改 `references/` 里的 schema 草案与回归清单（它们仍写着“schema 含该字段才输出”，不加载进 Agent）。

---

# 以下是 v27 的说明（保留作背景，名称以 v28 为准）

# v27-claude（admission-noshell-v27-claude，修订 27-claude.1）

**基线：v26-claude。目标：把“模型逐字输出的两个大 JSON”交给脚本生成，用 WanScope 的 `RunSkillScript` 运行。依据：v25 一次真实运行的 trace——extract-detail 一次调用 181 秒 / 12 106 输出 token，combine 一次调用 230 秒 / 32 526 输出 token，两个 Write 工具本身只花 0.02 秒；时间全在模型生成文本。**

## 做法

WanScope 的 `RunSkillScript`（`service/wanscope/server/workspace.py`）：运行已安装 skill 里 `scripts/*.py`，固定 `python3 -I`、空环境、工作区当 cwd、60 秒超时、输出上限 200000 字符；`args` 只能是工作区内相对路径，数据走 `stdin`；服务端按 `<skill>/scripts/x.py` 解析 agent 前缀。MCP 结果落盘（`AgentToolConfig.tool_results`，mode=file）后返回的清单里有 `path`，**可以直接当脚本参数**，模型不需要转抄规则和工商返回。

| 步骤 | v26（模型手写） | v27（脚本） |
|---|---|---|
| 明细 144 行 | 模型 Write 约 27 KB | `detail.py init` 预填 **76 行**（请求字段 A 组、工商 J 组 27 条、请求里没有的材料整组 N、企业名称关键词命中、注册地境内），模型只 `fill` 读材料得到的 **55 行（约 4.5 KB）**，脚本再算 13 行派生（成立月数、主体类型、分公司/合伙、有效期、快到期、名称比较、账户性质、租期、工商一致性、附件盘点） |
| combine | 模型 Write 93.6 KB（v26 估 14 KB） | `combine.py build` 按实时规则/属性文件生成，**14 KB，0.03 秒**，内置 `validate`（键数按实体闭合、rules 逐字、input 一致） |
| notes.unresolvedProperties | 模型从明细和 unfilled 手工合并 | 脚本生成（`NOTES` 行），模型原样用 |
| 读回 + 引号扫描 + 自审键数 | 每次都要模型做 | 取消（JSON 由脚本序列化，一定合法；键数由脚本算） |
| 模型还要做的 | — | ①读材料后提交 `fill`；②个别需多条明细共同判断的属性用 `set` 提交 |

轮次由 9 轮变 8 轮：加载+规则+工商 → 其余 skill + 属性 + 视频 + `detail.py init` → `detail.py fill` → `combine.py build` → 审核 A → mcp_run_process → 摘要 → 提交。

## 用 v25 那次真实运行验证了什么（`integration/test_scripts.py`，4 个用例，全部通过）

输入是那次的真实请求、工商三接口返回、规则、属性定义，按 RunSkillScript 的方式运行（`python3 -I`、空环境、cwd=工作区、stdin 管道）：

- `init` 后明细 Y=39 / N=37 / 待填 68；预填值与那次模型手写的值比较：**74 个相同，只有 J08、J10 的文字格式和 A12 的拼接顺序不同**（J10：脚本写“截止日未返回”，模型写“长期”）。
- `fill` 提交 55 行后：Y=91 / N=53（与那次模型手写的 Y/N 数一致）；B16=23、B15=true、J34=无不一致，来源文字与手写一致。
- `build` 后：**`input` 与那次真实运行的 input 逐项相同**；`keys: N=154 M=10 L=0 K=144 (M+L+K=154)`；`validate: OK`；combine 14 077 字节（那次 93 598）。
- 拒绝路径：对预填行提交、格式错、非法 JSON、清单外 id 都会被 REJECT 并说明；规则新增键会输出 UNMAPPED，定义里没有的键进 notFoundInDefinition 且键数仍闭合；多条明细派生属性先 NEED_VALUE，`set` 后进 input。
- 发现并修复一个 bug：规则引用了属性定义里没有的键时，被静默丢弃（未进 notFoundInDefinition）。

## 需要同时部署（缺一不可）

1. **WanScope 后端**设 `WANSCOPE_SKILL_SCRIPTS=on` 并重启；Agent 的工具里要有 `RunSkillScript`。
2. **mcp_list_rule、mcp_list_property、三个工商工具设 `tool_results` 为 `file`**（`"server:tool": {"mode":"file"}`；README 的“MCP result delivery”）。不开则返回内联、没有 `path`，脚本读不到——提示词已写明此时按“技能配置异常”处理。
3. 上传的 catalog skill 包要带 `scripts/` 目录和 `extract-items-checked.json`（`SKILL.md.zip` 已打包）；其余六个 skill 照旧。
4. 脚本只用标准库，Python ≥ 3.11 即可，**`service/pyproject.toml` 不用加依赖**。

## 没验证的（请先看这一段）

- **没有在真实 WanScope 里跑过。** 我用同样的参数（`python3 -I`、空环境）在本机跑，没有经过 `RunSkillScript` 本身；`workspace.py` 的路径解析、参数检查（args 里不能有绝对路径或 `..`）我读了代码，但没有端到端验证。
- **MCP 落盘文件的实际内容**：按 `mcp_results.py` 的实现，文件是 MCP 返回原文，后面可能带网关页脚 `Request reference: …`，脚本用 `raw_decode` 只取第一个 JSON；这一点用 trace 里规则返回的真实文本（含页脚）验证过，但没用平台真正落盘的文件验证。工商三接口的返回我用 trace 里的文本模拟。
- **模型是否严格按 `detail.py init` 的 stdin 格式传参**（把请求原样放进 `request`、把网关附件警告放进 `warnings`）：init 的 stdin 要求模型把请求 JSON 重新输出一遍（本例 1.4 KB），请求大时会增加输出；可由网关把请求落盘成文件后改成 `--request <文件>`（未做）。
- 预估耗时（模型输出约 6 KB 而非 40 KB，各约 180 秒和 230 秒的两次生成大幅缩短）**没有实测**。
- `key_map.json` 是我按那次运行的 30 个已映射键和 125 个“清单里没有对应条目”的键建的，规则变了要维护；新键默认进 unfilled，不会误填。
- `BusinessCheck.task_content / invoice_category / position` 三个键在 map 里标了 `hold`（有明细但按 v24/v25 口径“自报不是核实”不填），**改口径只改 key_map 里这一行**。
- 脚本的判断（`B17` 主体类型分类、`D03` 账户性质、`J32` 注册地境内、`J34` 一致性）是我按 facts skill 的描述实现的，规则外的写法（如“专用存款账户”）会保持待填交给模型。

---

# 以下是 v26 的说明（保留作背景，名称以 v27 为准）

# v26-claude（admission-noshell-v26-claude，修订 26-claude.1）

**基线：v25-claude。依据：v25 一次真实运行的 trace（ontology_agent_job_43_115-am2，30 个观测，约 11 分 5 秒）及其中的 input-extract-detail.json、input-combine.json、summary-draft.json 和引擎返回（199 条 = 3 true + 14 false + 182 skip）。改动只对应这次运行里观察到的现象。**

## 结论

v25 改的 6 处里，视频问法（视频 URL 失效，没跑到）和伪造嫌疑断言词（仍有违反）没有被验证或只部分有效；**第 3、4 条（unfilled 卫生、自审写四个数）实测没起作用**；另外发现摘要里有一处方向错误和一处依据误判。v26 针对这几处：

## 相对 v25 的改动

| # | 现象（证据） | 改动 | 位置 |
|---|---|---|---|
| 1 | **摘要方向错误**：result=false 的 `RULE-RISK-001` 被放进 result=true 的 group，成稿写成“【禁入及限制行业】命中：企业名称未命中行业黑名单关键词；机构自定义规则命中…”；`RULE-IND-PRO-001` 在小表里是 insufficient，却被放进 determined 的“未命中”组；首句 x=10，“未触发”段只列了 9 个。模型的审核 B 自审写了“17 个 ID 各出现一次 ✓”，没核对方向 | 小表加“桶”列（T 命中 / F 未命中 / U 未触发）；S 的 ruleIds 必须从对应桶里抄；自审必须**逐 group 写一行**“group｜result/basis｜ruleIds｜这些 ID 在小表的桶”，并核对 x = U 桶个数 = “未触发”段 ID 个数、“命中”段每个 ID 的 result 都是 true；审核 B 条款 2 同步 | output skill 3.2 / 3.4 |
| 2 | **insufficient 判得太粗**：规则是“reason 含‘属性/对象不存在’就算没求值”，14 条 false 里 10 条被判 insufficient。实际上它们大多是 AND 表达式，其中一个分项已用你填的值求值并不成立（如 `founded_months=23` 使“3–6 个月”规则确定不成立；`business_scope_sensitive=false` 使 `… = true AND …` 确定不成立），摘要却说“因所需属性未取得而未据此核实”，把已有结论写成了没核实 | insufficient 改为**按表达式结构判**：最外层只有 AND 且 reason 里有“不满足 …” → determined；单个条件、最外层含 OR、AND/OR 混合、reason 只有“不存在” → insufficient。`rule_ledger.py` 的 `is_insufficient` 同步实现（`台账与摘要终结器接入.md` 里写的“已知偏保守”正是这一条）。用本次引擎返回回放：14 条 false 全部 determined（原 10 条 insufficient），x=0 | output skill 3.1；integration/rule_ledger.py |
| 3 | **v25 第 3 条没生效**：combine 的 unfilled 仍有 260 个键，其中 139 个没有任何规则引用（`AdmissionDoc.doc_id`、`BankFlow.bank_flow_id` 等整对象属性）；entities 里有 143 行，其中 129 行 value 为 null，且全部同时又登记在 unfilled。规则引用键实际 154 个。原因：facts 模板里放了一个 `"value":null` 的示例行，模型照着给每个定义属性都写了一行 | ① combine 新增 `refKeys`（只看 condition、按实体分组），**先写**；② entities **只放 value 非 null 的属性**，模板去掉 null 示例行；③ unfilled 只来自 refKeys 里不在 entities 的键，沿用主条目的 N 码；④ 键数按实体 n = m + l + k 闭合 | facts 组装规则 0/1/7；主提示词 combine 一节；catalog 第四节；output 审核 A 条款 11 |
| 4 | **自审的键数是编的**：写“N 约 120、K = N − M − L ≈ 106、N = M + L + K ✓”，实际 N=154、K=260。v25 要求“写出四个数”，模型就用倒推凑出等式 | 自审④改为**按实体写等式** `实体｜n=m+l+k`，禁用“约/≈”，禁止用 N−M−L 倒推 K；新增⑥扫描伪造嫌疑类 source 的断言字样 | output skill 自审 |
| 5 | **combine 写盘 230 秒、32 526 输出 token、93.6 KB**，其中 `rules` 副本 65 KB（272 份，来自上面 129 个 null 行）。整次运行 665 秒，combine 一次 Write 占 35% | 随第 3 条自然消失，不改 `rules` 字段本身。把本次运行的同一批事实按 v26 格式重排：**93.6 KB → 14.1 KB**，且 `validate --rules` 键数闭合 N=154=10+0+144 | —（效果见第 6 条验证） |
| 6 | 伪造嫌疑类 B23 的 source 仍写“信用代码 18 位格式合规；地址为国内真实地址”（v25 第 5 条要求不写） | facts 明列禁用字样“真实/合规/正常/可信/无异常”；审核 A 条款 10(i) 同样扫描；自审⑥ | facts 第 2 条；output 条款 10(i) |
| 7 | 视频 URL 失效：materials 写“未提供”，N 条目用 R01，而 unreadMaterials 里又登记了它——三处口径不统一 | materials 表加一行：网关“附件可用性说明”列出的 URL 失效字段 → 状态“未提供”，依据写 `URL 失效（<code>），已置空`，同时记入 unreadMaterials；审核 A 条款 9 同步 | materials skill；output 条款 9 |
| 8 | 验证手段 | `combine_tool.py`：skeleton 输出 `refKeys`、null 键进 unfilled、新增 `render_combine`；`validate` 新增：entities 含 null 属性、缺 refKeys、refKeys 与规则引用不一致、unfilled 不在 refKeys、按实体 n=m+l+k。`rule_ledger.py` AND/OR 感知 + 5 个新测试。用 v25 真实 combine 回归：旧格式报 381 个错误（含 `N=154 ≠ M+L+K=260`），v26 格式重排后只剩 1 个（规则顺序与 list_rule 不同，无害） | integration/ |

## 没改、需要你决定的

- **规则侧（v25 已提，本次再次出现）**：`RULE-GATE-002`（`Employer.risk_gate IS NULL`）和 `RULE-DEMAND-001`（`Demand.risk_file IS EMPTY`）对 Agent 永远命中，使 `ruleCheckResult` 恒为 fail。本次 3 条命中里 2 条是这类，另 1 条是机构规则 `employer_name CONTAINS [修匀]`（真实命中，企业名“上海修匀软件…”）。
- **AdmissionDoc 无 doc_type**：v26 的 AND 感知让 DOC-017/018/023/025 变成 determined false（因为 `account_name_matches=true` 等分项已求值不成立）。这是“条件不成立”的转述，不是“该证照已核实合格”；但**它假定你把 F01 业务场景照片数 3 填给 `photo_count`、F04 填给 `deliverable_explained` 是你要的映射**（规则说的是“交付照片”）。如果想回到 v25 的保守口径，把 output skill 3.1 的 AND 一条删掉、`rule_ledger.py` 的 `is_insufficient` 里 AND 分支去掉即可。
- **BusinessCheck 对象不存在**导致 ~58 条 skip，与 v25 相同，未动。
- **unresolvedProperties 仍有 101 行**（视频 10 项、身份证 13 项等逐项 N 条目），最终 GenerateStructuredOutput 46 秒、4 899 输出 token 主要是它。要不要把同一份材料整体缺失的合并成一行，是口径问题，未改。

## 部署

- 先注册七个新名称 `admission-v26-claude-*`，再更新主提示词 `主提示词_v26-claude_编排版.md`；导入后检查返回首行含 `admission-noshell-v26-claude`。
- catalog skill 发布 `SKILL.md`、`extract-items-checked.json`、`extract-rows.txt`（各 skill 目录下的 `SKILL.md.zip` 已重新打包）。清单本身与 v25 完全相同，`extract-rows.txt` 重新生成后逐字一致。
- 若平台侧接了 `rule_ledger.py`（路径 A），同步换成 v26 的版本，否则台账仍按旧口径标 insufficient，会与模型按新口径写的 S 冲突（`WRONG_BASIS`）。
- 运行时 md 总字数 42469（v25 为 39720，增加 2749，主要是 output 的自审和 insufficient 判定、facts 的 refKeys 步骤）。

## 未验证

- **没有做线上回归。** 第 3、4、5 条（entities 只放有值、refKeys、按实体闭合）只验证了：格式在离线工具里自洽，且 v25 那次真实事实能按新格式表达并通过 `validate --rules`；**模型是否照新写法做、combine 是否真的变短，要再跑一次同一条请求看**。v25 就是“写了明确要求、模型没照做”，这次把示例里诱导 null 行的那一行去掉并加了先写 refKeys 的步骤，但不能保证。
- 第 1 条（桶）同理：只改了提示词和自审要求，没有重跑。路径 A（台账工具）若接入则由程序保证，无需依赖模型。
- 第 7 条的 URL 失效处理、视频问法（v25 第 1 条）本次运行没有视频，仍未验证。
- 耗时没有测。上面的 93.6 KB → 14.1 KB 是用同一批事实离线重排的结果，不是模型实际输出。

---

# 以下是 v25 的说明（保留作背景，名称以 v26 为准）

# v25-claude（admission-noshell-v25-claude，修订 25-claude.1）

**基线：v24-claude。依据：v24 一次真实运行的 trace 与三个产物（input-extract-detail.json、input-combine.json、summary-draft.json）。改动只对应在这次运行里观察到的现象，没有顺手重写。**

## 相对 v24 的改动

| # | 现象（证据） | 改动 | 位置 |
|---|---|---|---|
| 1 | ReadVideo 的问题被模型改写成“请描述视频内容……办公场所看起来是否真实？有无疑似虚构、AI生成、渲染感”，并带上了企业名称；视频模型随即给出“AI生成、渲染感、样板间状态”的整体印象，被写进 E05 的 value 和 conflicts。v24 的 video skill 明明写了“问题里不放申报企业名称、不做真伪结论” | 固定问法改为**逐字使用**；明令不得出现企业名称、不得问真伪/是否 AI 生成/名称是否一致；名称比对由 Agent 拿第 5 项读到的原文自己做 | video skill；主提示词第 2 轮 |
| 2 | E05 的 value 被写成一整句“视频具有强烈AI生成或3D渲染特征：……”，来源是整段 00:00-00:13，没有具体时间点和画面 | E05 的 value 只能是 `"true"` / `"false"` / null：true 须有具体时间点和画面；“未见明确证据”→ false；笼统印象或推测措辞 → null（N R06），印象只进 conflicts | video skill；output skill 审核条款 5 |
| 3 | `input-combine.json` 的 unfilled 登记了 288 条，其中 **146 条没有任何规则引用**（把整个对象的属性都列了进去）；**15 个键同时登记在两个原因码下**（如 risk_level 在 R10 和 R14，subject_type 在 R10 和 R11）；规则引用的 5 个键漏登记（AdmissionDoc.premises_fictitious，和 4 个定义里没有的 RuleChangeLog 键），notFoundInDefinition 却是空的。副作用：notes.unresolvedProperties 多出几十行，Write combine（62 秒）和最终 GenerateStructuredOutput（48 秒）都因此变长 | facts 第 7 条改成“**N = M + L + K**”算法：先去重得到规则引用键清单，每个键恰好一个去向；只登记规则引用键；一个键只占一个原因码，优先级 R11 > R14 > R13 > R10；定义里没有的进 notFoundInDefinition。catalog 第四节、output 审核条款 11(c) 同步 | facts / catalog / output skill |
| 4 | 本运行环境没有 Agent 工具，模型按 output skill 走了自审，逐条款全部写 ✓、“passed=true”，没发现上面第 2、3 条 | 自审由“三件事”扩成“五件事”，新增④键数核对（必须写出 N、M、L、K 四个数并抽查 3 个 unfilled 键）和⑤E05 格式；说明为什么不能只写 ✓ | output skill |
| 5 | 伪造嫌疑类条目的 source 写了“地址为国内真实地址”“核准号格式合规”，而 skill 自己规定 false 不是“真实/已核实”的依据 | source 只写逐项看了什么，不写“真实/合规”断言 | facts skill |
| 6 | 验证手段 | `combine_tool.py validate --rules` 新增：unfilled 键必须被规则引用、不得出现在两个原因码下、N = M + L + K、规则引用键不得漏登记。已用 v24 那次真实产物回归：报出 137 个无规则引用键、15 个双码键、5 个漏登记键，N=154 ≠ 149 | integration/combine_tool.py |

## 没改、需要你决定的（详见对话）

- **规则侧**：`RULE-GATE-002`（`Employer.risk_gate IS NULL`）对 Agent 永远命中——risk_gate 是引擎/结果类，Agent 不会也不该填；`RULE-DEMAND-001`（`Demand.risk_file IS EMPTY`）只要请求没有风控文件也命中。这次 ruleCheckResult=fail 的 3 条命中里有 2 条是这类“没有数据就命中”，另 1 条是机构规则 `Employer.employer_name CONTAINS [修匀]`（真实命中）。
- **AdmissionDoc 无法区分材料类型**：8 条证照/账户/视频/照片规则都要求 `AdmissionDoc.doc_type = ...`，单对象接口下 doc_type 不填，这些规则全部“属性不存在”，没有真正求值（摘要已如实写成 insufficient）。是否改成按 doc_type 分次调用引擎，取决于 mcp_run_process 是否支持，且网关取的是哪一次返回。
- **BusinessCheck 对象不存在**导致 58 条规则 skip。请求里有项目内容、交付要求、开票类目（清单 A07/A08/A10 已提取），v24 按“自报不是核实”没有填进 BusinessCheck。要不要填，是业务口径问题。
- **E05 的语义**：你的 desc 里写了“违背常识的情况、AI生成痕迹”，v25 的做法是有具体时间点和画面才 true，且不据此填 E10。如果你的本意不同，改 video skill 的 E05 一段即可。

## 部署

- 先注册七个新名称 `admission-v25-claude-*`，再更新主提示词 `主提示词_v25-claude_编排版.md`；导入后检查返回首行含 `admission-noshell-v25-claude`。
- catalog skill 发布 `SKILL.md`、`extract-items-checked.json`、`extract-rows.txt`（各 skill 目录下的 `SKILL.md.zip` 已打包）。
- 清单更新流程不变：只改 `skills/admission-v25-claude-catalog/extract-items-checked.json`，运行 `python3 integration/build_catalog_v25.py` 重新生成 `extract-rows.txt`，再重新打包。
- 运行时 md 总字数 39720（v24 为 38019，增加 1701，主要是第 3 条的算法和自审的④⑤）。

## 未验证

- **没有做线上回归**。上面第 3 条（unfilled 变短）和由此带来的提速，只在离线用 v24 的真实产物验证了检查器能报出问题，没有验证模型按新写法会少登记多少，也没有测耗时。
- 第 1 条的效果（视频问法不再被改写）取决于模型是否照做，需要再跑一次同一条请求看 ReadVideo 的入参。

---

# 以下是 v24 的说明（保留作背景，名称以 v25 为准）

## v24-claude 原说明

**基线：v23-claude。本版以你人工核对过的清单 `skills/admission-v25-claude-catalog/extract-items-checked.json`（144 条）为蓝本。**

## 相对 v23 的变化

1. **清单换成人工核对版（144 条，A–J）**，id/group/name/desc 逐字取自蓝本，脚本不改它（只对行首里的 ASCII 双引号、首尾空白做安全处理，涉及 A11、H14、H16、H17、H19、H20）。对 v23（122 条）的差异：
   - 删除 I 组（管理员信息、登记表 10 条）；
   - 新增：A13 岗位名称；B18–B23（是否分公司、是否合伙企业、登记机关、盖章名称、快到期提醒、营业执照是否有伪造嫌疑）；B09 经营范围属敏感类；B13 鲜章复印件；C08–C12；D06–D12（含账号 D10、核准号 D11）；E07 招牌/logo 与公司名不匹配、E10；F06；G07、G08；H 组改为发票（H01–H11）、上下游合同（H12–H15）、社保（H16–H18）、完税（H19–H21）、官网（H22、H23）；
   - 条目改名或顺序后移：营业执照 B09→B10（注册资本）… B16 成立月数、B17 主体类型（四选一标签）；C07 改为“是否彩色复印”，持证人核实状态移到 C11；E07–E09 后移为 E08–E10；
   - 去掉了原来直接提取的判断类条目（具备独立用工主体资格、独立用工依据已就绪、经营佐证材料已提供、二选一替代材料成立、证据链完整），这些本体属性改为**在 combine 阶段由多条明细按规则条件的语义推出**（不再有预设的派生规则表）。
2. **明细只有 id / name / desc / value / source 五个字段**。**清单只是抽取的原始数据，只发布人工核对版 `extract-items-checked.json`**：不再有 `extract-items.json` 索引，也就没有 `kind / dependsOn / hintKeys / how / derivedKeys / fixedNull`——规则和本体属性经常变，清单与规则不是强匹配，条目对到哪个属性、规则引用了取不到的键怎么登记，都由 Agent 在 combine 阶段按语义处理。每条的取值与判定口径只看它自己的 `desc`。
3. **不再有 K001–K122，也不再有固定不填键名单**：v23 把清单 sheet 1 的 122 个固定不填键放进明细，核对版没有它们，v24 以核对版为准。规则引用、但对不上任何清单条目的键（结果类 R14、外部来源 R13、其余 R10），只在 combine.unfilled 和 notes.unresolvedProperties 登记，原因码由 Agent 按 catalog skill 第四节现场判断。
4. **轮次回到 9 轮**：1 加载+规则+工商 → 2 其余 skill + Read 行首 + 属性 + 视频 → 3 Write 明细（144 行，一次）→ 4 Read 明细并做引号扫描 → 5 Write 组装 → 6 审核 A → 7 Read 组装 + run_process → 8 摘要 → 9 提交。
5. **新口径**：伪造嫌疑类 9 条（true 要写具体异常，false 只表示逐项看过没发现异常，不得推出“真实”）、快到期提醒 3 条（暂定 30 天）、开户账号 D10 只写位数和前后各 4 位、身份证号码不抄录，已写进 facts / catalog skill；R06 码扩展为“图像/材料判断拿不准”。**原先只写在 `how` 里的条目级口径（B09 经营范围敏感类逐类核对、E05 AI 生成痕迹、G01 三态折布尔等）随 `how` 一起去掉了，旧文本归档在 `integration/catalog_source/_已弃用_不发布/`；需要保留的请写进清单对应条目的 `desc`。** **facts skill 的“可填清单”和“不在清单内”两段已整体改成不点名属性的“属性填写原则”；主提示词“含义对照”表去掉，红线 4、discover 第 7 条、catalog R11 例子改成通用表述。**
6. 工具与测试：`combine_tool.py` 不再读 `hintKeys / derivedKeys / fixedNull`；`--items` 指向 `extract-items-checked.json`，条目→属性的对应用可选的 `--map` 传入（仅离线回归用），只对固定标识（A01–A04）自带来源；`validate` 以 `value_source` 以“派生:”开头识别派生属性。`subject_type` 定义为“核查主体”时仍自动置 null 并写 `N｜R11`。`test_combine_tool.py` 与 `references/examples/` 已重新生成并通过。 固定标识来源、字符串型键、结果类命名、定义冲突特例（`subject_type`）改放 `integration/combine_config.json`，代码里不再写死；该文件只服务离线回归，线上 Agent 不读。
7. 未改：红线 1/3/4/5、固定标识、审核 A/B（条款 10/11 按新清单改）、台账摘要、引擎门禁、引号扫描与自审要求（v23 的 JSON 合法性修复保留）。

## 需要你确认

- **清单里几处疑似复制粘贴**，我按条目名处理、未改你的文字：C12“是否外籍与港澳台人员”的 desc 和 C11 一样；E07“能否判断 log 和公司名称不匹配”的 desc 和 E06 一样；A11 desc 末尾“是否可打开见”缺指向；H16/H17/H19/H20 的 desc 里残留“+ 主体名称原文”；H14 desc 末尾“否则 N ”不完整；B01 的 desc 把“逐字抄录”放在了逗号后。
- **快到期阈值**：30 天是暂定的，没有业务出处，请确认（现在写在 facts skill 里，不再有 `make_overlay.py`）。
- **B09 经营范围属敏感类**：你的 desc 同时列了“建议拦截”类的口径，我只做“类别关键词命中”的事实判断，不下拦截结论。
- **“取不到”仍是 JSON null**，不是字符串 "NULL"。
- **未做线上回归**；明细 144 行约 25–30 KB，一次 Write。

## 清单覆盖说明

- 144 条来自人工核对清单。旧 Excel 的 JSON 转换件（含某次规则快照、已过时）不再发布，归档在 `integration/catalog_source/_已弃用_不发布/`。
- 派生属性、固定不填键的归宿见上文第 1、3 条。

## 部署

- 先注册七个新名称 `admission-v25-claude-*`，再更新主提示词 `主提示词_v24-claude_编排版.md`；导入后检查返回首行含 `admission-noshell-v24-claude`。
- **catalog skill 发布 `SKILL.md`、`extract-items-checked.json`（清单，唯一数据源）、`extract-rows.txt`（由清单生成的 144 行行首，Agent 照抄用）**（`SKILL.md.zip` 已打包全部）；Agent 要能 `Read` skill 目录下的 `extract-rows.txt`。不再发布 `extract-items.json` 和 `提示词提取信息清单.json`。
- 清单更新流程：只改 `skills/admission-v25-claude-catalog/extract-items-checked.json`（id/group/name/desc），运行 `python3 integration/build_catalog_v25.py` 重新生成 `extract-rows.txt`，再重新打包 `SKILL.md.zip`。不需要再维护任何叠加文件。
