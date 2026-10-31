# 回流批次契约

必填：`batch_id`、`caller`、`project_id`、`business_version`、`review_status`、`access_scope`、`correlation_id`。

可选：`artifacts[]`、`object_snapshots[]`、`recommendation_feedback[]`、`review_comments[]`、`return_reasons[]`。建议反馈必须引用原`request_id`和`candidate_id`。

同一`batch_id`与相同载荷重复提交返回幂等成功；同 ID 不同载荷必须拒绝。
