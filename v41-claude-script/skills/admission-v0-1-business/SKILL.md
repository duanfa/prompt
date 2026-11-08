---
name: admission-v0-1-business
description: 对本次申报主体调用三个工商工具一次，保留可映射事实和冲突；空值不当事实，缺字段不当否定。
metadata:
  prompt-contract: admission-noshell-v0-1
  prompt-version: "0.1"
---
# admission-noshell-v0-1 / admission-v0-1-business

# 工商核验

有申报企业名称/信用代码时，enterprise-get-company-detail（D）、databao-company-basic-info-check-v2（B）、databao-company-details-check-v2（T）三个工具各调用一次，与 mcp_list_rule 同轮，不擅自删减。优先用申报信用代码，否则申报名称；营业执照与申报不一致时仍用申报值查询；不改查附件里的另一主体，成功返回不重复查询。

取值口径（`detail.py init` 按此从三个落盘文件预填 J 组，供你理解和核对；init 仍列出的 J 行按其 desc 填，字段对照见部署包 `references/工商三接口返回字段.md`）：

- 按字段原义取值，value 取第一个成功来源（顺序 D、B、T），source 写 `工商:D.字段｜原值；B.字段=原值；…`；单位未明示不自补。**空值 = 无数据，不传该属性**（`N｜R07`）。三接口同一事实不一致时该事实取 null、`N｜R09`，写 conflicts，不裁决（`detail.py init` 已对注册资本 D 与 B 做了换算比较，不一致时 J08 直接是 `N｜R09`）。J29（请求参数口径）按**本次实际调用入参**如实写，没传的字段不要写。
- 与材料不一致时核对主体并记录双方事实，不裁决真假；逐项比对与二次识别见 materials skill 第二步半，**工商值不得覆盖原件识别值**。
- 工具成功但未查到，只说明该渠道无记录，不据此判“主营业务可核实”类属性为 false；工具失败不能推断企业不存在、违规或通过，记 toolIssues。
- 工商基本信息没列金融/施工/劳务牌照，**不等于明确没有牌照**；许可 false 需要对应许可查询的明确否定，不能以公司名称或行业替代。行业代码可作原文事实，映射敏感/禁入/灰名单须有本次完整分类口径，不沿常识扩展。
