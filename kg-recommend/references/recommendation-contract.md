# 推荐响应契约

顶层必含：`request_id`、`correlation_id`、`knowledge_version`、`status`、`candidates`、`questions`、`gaps`。

候选必含：`candidate_id`、`content`、`candidate_status=suggestion`、`confidence`、`evidence_refs`、`knowledge_roles`、`applicable_conditions`、`differences`、`risks`、`prerequisites`。

候选引用跨适用域知识（引用证据的适用范围未命中请求上下文）时，须在`cross_domain_refs`登记对应证据并设置`adaptation_required=true`、返回适配确认检查项；跨域参考不得作为目标域确定性依据，不得填平缺口。无直接证据时只允许`knowledge_roles`包含`模型建议`，且必须降低置信度。
