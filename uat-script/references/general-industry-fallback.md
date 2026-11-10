# 一般行业兜底（2026-11-09，版本仍为 0.3）

> **已被取代（同日）**：`Employer.usage_scenario` 改为预设，build 直接取请求 projCont 原文（见 README“用工场景预设”）。下文 build 补漏、`generalIndustryFallback` 配置与 `test_industry_fallback.py` 均已删除，仅作历史记录。

依据 trace `d6ca22bf3aa15455fedd581b4a9f3536`：`ontology_agent_job_205` 的所属行业和实际业务都按软件开发判断为一般行业（置信度约95%），但组装时未给 `Employer.usage_scenario` 提交 map/skip/set。build 将遗漏记为 UNDECIDED / R10，仍提交引擎，触发用工场景为空规则。

## 行为

1. 模型先按可读业务证据判断七类特殊类别；未命中且一般行业把握过半时，对本次定义中相关的行业/业务/用工场景键显式提交一般行业及证据。未知、冲突及只看到“违法类规则未命中”不构成兜底依据。
2. build 只补漏：两个已成功组装的来源分类均为本次枚举中的一般行业，目标有定义、被有效规则引用、无显式 map/skip/set，且来源依据全部有值时，补齐目标。三个属性各按自身 enum 转码，无 enum 时用 comment 的选项文字；不猜英文编码。
3. 补齐值保留两来源的全部 extractIds、派生说明和引用规则，移除该遗漏项的 UNDECIDED、unfilled 和 unresolvedProperties，仍通过原有机械校验。每次 build 重新判断，未保留前次分类值。

## 范围

- 修改实际部署目录 `prompt/v41-claude-script`（`admission-v0-3-*`），历史 docs 版本不回填。
- 配置：`skills/admission-v0-3-catalog/scripts/combine_config.json` 的 `generalIndustryFallback`。
- 回归：`integration/test_industry_fallback.py`，覆盖 trace 同类遗漏、独立枚举编码、七类特殊类别、缺分类或缺证据、显式取值/skip/待判断、无定义/无选项/无引用、类型冲突和重跑。
- 本地验证：新增 11 项集成测试通过；`python3 -W ignore::ResourceWarning -m unittest discover -s integration -p 'test_*.py'` 共 129 项通过。catalog / facts / discover 技能包与 manifest 一并更新。
- 本次不修改远端规则库，不改变空值规则的处置级别；本地测试不代表已部署或重跑线上任务。
