# 影响通知契约

知识清单每行至少包含`knowledge_id`、`version`、`content_hash`、`status`、`access_scope`。映射每行包含`knowledge_id`、`external_application`、`external_object_id`、`business_version`。

通知包含新旧知识版本、变化字段、影响级别、外部对象 ID 和建议动作。通知不包含业务对象补丁，`write_back`固定为`false`。
