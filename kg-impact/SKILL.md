---
name: kg-impact
description: 知识变更影响分析。当政策替代、依据失效、规则升级、案例更新、权限变化或知识包换版后，需要识别受影响外部对象并生成重新核验通知时使用。
---

# kg-impact：知识变更影响分析

## 输入 / 输出

- 输入：新旧知识版本清单、知识派生关系、外部对象映射和订阅配置。
- 输出：`70-服务运行/影响通知/{批次ID}.jsonl`及影响摘要。

格式见 [references/impact-contract.md](references/impact-contract.md)。执行：

```bash
python scripts/analyze_impact.py --old old.jsonl --new new.jsonl --mappings mappings.jsonl --output notices.jsonl
```

## 执行步骤

1. 比较内容哈希、有效状态、适用范围、访问范围、证据和规则版本。
2. 沿引用、派生、支撑、替代和外部对象映射关系传播影响。
3. 按`必须复核|建议复核|信息通知`分级，说明旧新版本、变化、影响理由和建议动作。
4. 只发送外部对象 ID 和必要证据；外部应用决定是否创建业务修订任务。
5. 记录通知、签收、忽略和复核结果，用于后续影响规则评估。

## 硬约束

知识平台不得自动修改外部对象或推进外部任务状态。权限收紧时立即停止返回旧内容，并单独通知缓存失效。
