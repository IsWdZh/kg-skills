# 通用知识服务契约

## 公共请求头

调用方、用户、组织、项目、角色、密级、访问范围、`request_id`、`correlation_id`、业务版本、接口版本和幂等键。

## 公共响应头

`status`、`knowledge_version`、`request_id`、`correlation_id`、`external_object_id`、`audit_ref`、`error_code`。

## 所有权约束

- 请求可携带外部只读快照，知识平台不得形成第二个可编辑业务主数据源。
- 推荐和校验只返回候选与发现。
- 回流只接收确认状态明确的不可变快照。
- 影响通知只建议外部应用复核。
