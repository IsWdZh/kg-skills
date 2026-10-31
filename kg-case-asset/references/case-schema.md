# 案例资产契约

案例清单必含：`case_id`、`title`、`version`、`review_status`、`region`、`industry`、`organization_level`、`time_range`、`access_scope`、`applicability`、`not_applicable`、`evidence_refs`、`reuse_units`。

每个 `reuse_unit` 必含：

- `unit_id`、`unit_type`、`content`；
- `evidence_refs`、`applicable_conditions`、`differences`、`risks`；
- `outcome`和`feedback`，未知时显式标记；
- 供跨适用域引用的`reuse_unit`必须有`adaptation_checklist`；案例适用范围未命中请求上下文时只能作为跨域参考复用，不得作为目标域确定性依据。

案例清单不保存外部项目任务状态，不把知识版本号写成业务版本号。
