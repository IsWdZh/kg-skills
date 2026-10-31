# 上下文检索契约

请求必含：`request_id`、`correlation_id`、`caller`、`query`、`caller_context`。`caller_context`至少含用户、组织、项目、地区、时间、角色、密级和`allowed_access_scopes`。

响应必含：`request_id`、`correlation_id`、`status`、`knowledge_version`、`external_object_id`、`evidence`、`conflicts`、`gaps`、`trace`。

`evidence`按知识角色分桶，并在服务时按请求上下文×知识适用范围计算分区：适用命中进入对应角色分桶，跨域参考进入`cross_domain_reference`；跨适用域知识只能进入参考分区，不得作为目标域确定性依据，不得填平缺口。`trace`只记录有权范围内的统计，不泄露被拒绝资产标题或内容。
