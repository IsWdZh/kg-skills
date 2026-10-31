---
name: kg-open-service
description: 通用知识开放服务治理。当需要定义或评审文档接入、检索、证据、推荐、校验、回流和影响通知接口，以及鉴权、版本、审计、限流、幂等和错误降级时使用。
---

# kg-open-service：知识开放服务

## 输入 / 输出

- 输入：调用方需求、知识服务能力、响应 Schema 和安全策略。
- 输出：`70-服务运行/开放服务/`中的接口契约、错误码、权限矩阵、审计字段和兼容策略。

通用契约见 [references/service-contract.md](references/service-contract.md)。校验：

```bash
python scripts/validate_contract.py <集成配置目录>
```

## 必备接口

`document-intake`、`context-retrieve`、`evidence-pack`、`recommend`、`verify`、`feedback`、`impact-notify`。

每次请求必须包含调用方、用户/组织/项目、访问范围、`request_id`、`correlation_id`和业务版本；每次响应必须包含知识版本、结果状态、证据或缺口、审计引用和错误码。

## 服务边界

- 接口只交换引用、只读快照、候选建议、校验发现、确认反馈和发布事件。
- 不提供上层业务对象 CRUD、任务状态流转、审批、正式报告模板或自动写回。
- 双方独立鉴权；外部登录态不能替代知识对象权限判断。
- 破坏性 Schema 变化升主版本；旧版本有明确停用期和影响通知。
- 幂等键用于文档接入、回流和通知，重复请求不得创建重复知识资产。
