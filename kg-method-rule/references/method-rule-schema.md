# 方法与规则资产契约

`manifest.yaml`公共字段：`asset_id`、`asset_type`、`version`、`applicable_tasks`、`inputs`、`outputs`、`owner`、`sources`、`status`。

校验规则额外包含：`severity`、`applicability`、`evidence_requirement`、`exceptions`、`repair_advice`、`tests`。规则严重级别使用`blocker|warning|suggestion`。

禁止字段：`workflow`、`stages`、`transitions`、`approval`、`business_status`、`auto_writeback`、`form_crud`、`report_template`。
