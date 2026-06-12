# kg-skills：分层知识治理技能包

把「文档 → 业务标签 → 全局业务图 → 单元场景 → 地区版本 → 场景知识包 → 对外服务」全链路治理方法沉淀为模型无关的 Agent Skills。任何支持 Agent Skills 的模型/Agent（Claude Code、Codex CLI 等）加载后，即可在纯文件工作区中完成知识治理闭环——**不依赖任何产品系统**。

## 技能清单（按流程顺序）

| 技能 | 职责 | 阶段产物 |
|---|---|---|
| `kg-pipeline` | 总控：判断当前阶段、调度技能、维护工作区规范 | 治理工作区目录 |
| `kg-intake` | 文档接入：登记/解析/去重/图片型文档视觉转写 | 文档台账、解析文档（带锚点） |
| `kg-tagging` | 业务打标：词表先行、文档级+段落级打标 | 词表、打标结果、待确认清单 |
| `kg-scenario-map` | 全局业务图与单元场景：人工边界→LLM候选→人工确认 | 场景目录、业务图、地区版本映射、覆盖盘点 |
| `kg-govern-config` | 治理方式配置与切换：三档评估、任务生成、变更审计 | 治理配置、任务清单、变更记录 |
| `kg-produce` | 四形态生产：知识块/问答对/Wiki/图谱自由搭配 | 四类知识资产/ |
| `kg-coordinate` | 多形态协同：锚点校验、互链、一致性 | 协同校验报告 |
| `kg-package` | 知识包组装发布：审核、不可变快照、哈希、版本回滚、数据库投影 | 知识包/、知识库导出/ |
| `kg-serve` | 对外调取：路由、补问、对比、降级、引用 | 调用协议、问答记录 |

## 安装

**Claude Code**：把本目录下 9 个技能文件夹复制到项目 `.claude/skills/`（或全局 `~/.claude/skills/`），对话中说"用 kg-pipeline 开始治理 XX 文档"即可。

**其他 Agent**：技能全部为纯 Markdown 指令 + 可选 Python 脚本。接入解析按文档格式可能需要 `beautifulsoup4`、`python-docx`、`pypdf`、`Pillow`；校验、冻结、导出使用 Python 标准库。无 Skills 机制的环境，可把对应 SKILL.md 作为系统指令使用。

## 快速开始

```
1. 准备源文档文件夹（按来源/地区分子目录）
2. 触发 kg-pipeline → 创建治理工作区 + 数据规范
3. 依序执行 kg-intake → kg-tagging → kg-scenario-map → kg-govern-config
4. 对选定场景执行 kg-produce → kg-coordinate → kg-package（冻结版本并生成服务投影）
5. 用 kg-serve 对外提供问答（或把知识包目录交给任意 RAG/Agent 消费）
```

人工确认关卡支持**交互式**与**批处理式**。批处理只代表预填建议，未关闭的待确认项必须阻止生产发布；只能标记为受限试跑。
