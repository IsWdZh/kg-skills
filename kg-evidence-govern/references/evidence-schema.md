# 证据卡字段契约

| 字段 | 必填 | 说明 |
|---|---|---|
| `evidence_id` | 是 | 稳定证据 ID |
| `document_id/document_version` | 是 | 来源文档及内容版本 |
| `content/content_hash` | 是 | 原文内容及 SHA-256 |
| `source_locator` | 是 | `type`及 paragraph/page/sheet-cell/table/image-region/flow-node 定位 |
| `knowledge_role` | 是 | 有效依据、上位约束、现状事实、历史材料、实践经验、方法规范、模型建议 |
| `region/valid_from/valid_to` | 是 | 适用地区和时间，未知须显式写明 |
| `access_scope/classification` | 是 | 访问范围和密级 |
| `generation_method/confidence/status` | 是 | 抽取、人工确认、规则推导或模型建议 |

事实证据至少含一个精确定位器。模型建议可以无原文定位，但必须引用输入证据并标为建议。
