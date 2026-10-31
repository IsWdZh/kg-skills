# 集成测试契约

`contract-tests.yaml`逐项声明`payload`和`schema`；`golden-responses.yaml`声明响应文件、调用应用和固定断言；`permission-tests.yaml`声明响应中绝不能出现的敏感标记。

至少包含两个对象模型不同的上层应用测试。任何业务写回字段、权限泄漏、无来源事实或跨适用域知识冒充目标域确定性依据均判失败。
