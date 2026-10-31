# 只读校验契约

快照格式：`request_id`、`correlation_id`、`business_version`、`objects[]`、`relations[]`、`evidence_mappings[]`。对象通用字段为`id`、`type`、`fields`，领域字段放入`fields`。

规则格式：`id`、`type`、`object_type`、`path`、`severity`、`applicability`、`exceptions`、`repair_advice`。确定性类型支持`required|enum|regex|evidence_required|relation_exists`；`semantic_review`仅产生待模型/人工审查项。

输出发现包含规则、对象、严重级别、证据、说明、修复建议和`decision_owner=external_business_owner`，不得含补丁或写回命令。
