---
name: kg-recommend
description: 基于可信知识生成候选建议。当外部应用需要对象识别、拆解补齐、问题诊断、流程优化、内容片段或规划候选，并要求每项建议带证据、适用条件、差异、风险和不确定性时使用。
---

# kg-recommend：知识辅助建议

## 输入 / 输出

- 输入：`kg-context-retrieve`证据包、方法/规则版本、外部对象只读快照和目标 Schema。
- 输出：候选建议 JSON；不输出最终业务成果，不执行写回。

格式见 [references/recommendation-contract.md](references/recommendation-contract.md)。生成后运行：

```bash
python scripts/validate_recommendation.py recommendation.json
```

## 执行步骤

1. 明确目标、外部对象类型、禁止变更字段和调用方要求的输出 Schema。
2. 仅使用证据包中的可访问内容；按方法规则生成一个或多个候选。
3. 每个候选登记证据引用、知识角色、适用条件、与目标域现状的差异、收益、风险、前置条件和置信度。
4. 无证据内容标为`模型建议`，不得写成事实；引用跨适用域知识（证据适用范围未命中请求上下文）的候选登记`cross_domain_refs`并标`待适配确认`。
5. 对缺失信息生成渐进式补问；信息不足时宁可返回缺口，不补造业务事实。
6. 由外部应用记录采纳、修改或否决，反馈通过 `kg-feedback` 回流。

## 禁止项

- 禁止设置`auto_apply`、业务状态、审批结论或写回指令。
- 禁止把一个候选包装成唯一正确答案。
- 禁止把跨适用域知识写成目标域确定性事实，或省略不适用条件。
