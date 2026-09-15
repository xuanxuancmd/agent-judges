你审查的是规格文档(spec)。关注:
- 每条需求是否都有对应的规格定义(可追溯性)
- 接口契约的完整性(输入/输出/错误码/边界)
- 边界条件的显式覆盖
- 验收标准的可测试性
- 规格内部的一致性(无自相矛盾)

对每条发现给出:
1. 严重程度: critical / major / minor
2. 置信度: 0.0-1.0
3. 具体依据(引用被审查内容)
4. 改进建议

你现在进入辩论阶段。其他审查者的观点如下,请挑战你不同意的部分,坚持你有证据的部分:


---

被审查内容:
# 技术规格说明：在 graphify 图谱基础上对标 GitNexus 补齐能力

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.0 |
| 创建日期 | 2026-09-14 |
| 状态 | 草案 |
| 负责模块 | graphify 核心引擎 |

---

## 1. 背景与动机

graphify 是一个通用的知识图谱构建工具，能够将任意文件夹（代码、文档、论文、图片、视频）
转化为可查询的知识图谱，提供社区检测、god nodes 分析、最短路径查询等能力，并以
`.graph/graph.json` 为持久化产物，支持 HTML 可视化、Neo4j/FalkorDB 导出、MCP
stdio 服务等多种消费方式。

GitNexus 是一个开源的代码智能引擎（GitHub: abhigyanpatwari/GitNexus），以 Tree-sitter
AST 解析为基础，构建符号级知识图谱并通过 MCP 工具集向 AI agent 暴露影响分析、执行流
追踪、变更检测等深层代码理解能力。其核心定位是"为 agent 提供代码库的结构化感知层"。

当前 graphify 的 AST 提取（Part A）虽然能以确定性方式抽取代码结构节点与边，但提取粒度
停留在文件内部，缺少跨文件的调用解析、导入解析、类继承关系等语义边。与此同时，
graphify 的查询能力（BFS/DFS 遍历、最短路径、节点解释）面向通用知识图谱，未针对代码
分析场景提供影响范围、执行流追踪等专用工具。这导致在代码审查、重构影响评估、架构理解
等场景下，graphify 的图谱无法替代 GitNexus 提供的深度代码智能能力。

本规格说明旨在定义一组功能需求，在 graphify 现有图谱基础上补齐 GitNexus 已验证的核心
代码智能能力，使 graphify 的代码分析场景达到与 GitNexus 可对标的水平。

---

## 2. graphify 现状

以下能力基于 graphify SKILL.md 的实际定义，非推测：

### 2.1 图谱构建

- **多模态输入**：支持代码、文档（Markdown/TXT）、论文（PDF）、图片、视频（自动转录）
  的混合语料。
- **AST 结构提取（Part A）**：对代码文件执行确定性 AST 提取，生成节点与边，无需 LLM、
  无需 API key。提取结果写入 `.graph/.graphify_ast.json`。
- **文档提取（Part A2）**：对 DDD 文档、Swagger YAML 执行外部提取器，基于 AST 节点进行
  anchor 匹配，生成文档节点与边。
- **语义提取（Part B）**：对文档、论文、图片分派子 agent 执行 LLM 语义提取，生成
  INFERRED 边和超边（hyperedge）。支持 Gemini 后端（可选）或宿主 agent 自身作为 LLM。
- **三层合并（Part C）**：AST 节点优先，文档节点按 ID 去重，语义节点最后合并；边直接
  拼接。

### 2.2 图分析与输出

- **社区检测**：`cluster(G)` 对图执行社区检测，`score_all(G, communities)` 计算每个
  社区的 cohesion 评分。
- **God nodes**：`god_nodes(G)` 识别图中的关键枢纽节点。
- **惊喜连接**：`surprising_connections(G, communities)` 发现跨社区的意外关联。
- **建议问题**：`suggest_questions(G, communities, labels)` 基于社区标签生成探索性问题。
- **图健康检查**：`diagnose_extraction(extraction)` 检测悬空边、缺失端点、自环、边坍缩
  等完整性问题（只读诊断，不中断流程）。

### 2.3 查询与探索

- **query**：BFS（广度优先）或 DFS（深度优先）遍历，支持 `--budget` 限制 token 数。
- **path**：两个概念之间的最短路径。
- **explain**：对单个节点生成自然语言解释。
- **learn**：生成多视角学习内容（数据流、架构、特性文档）。

### 2.4 增量更新与持久化

- **--update**：基于文件 manifest 与内容哈希，仅重新提取新增或变更的文件。
- **--cluster-only**：在现有图上重新执行聚类。
- **提取缓存**：内容寻址缓存，按 prompt 文件指纹标记条目；prompt 变更时旧条目自动失效。
- **持久化格式**：`.graph/graph.json`（JSON 文件），附带 `.graph/GRAPH_REPORT.md` 审计
  报告和 `.graph/.graphify_analysis.json` 分析侧车。
- **#479 收缩保护**：新图节点数少于已有图时拒绝覆写，防止数据丢失。

### 2.5 集成与导出

- **MCP 服务**：`--mcp` 启动 stdio MCP server，供 agent 查询。
- **图数据库**：`--neo4j` / `--falkordb` 生成 Cypher 脚本或直接推送。
- **导出格式**：HTML（默认）、SVG、GraphML、Obsidian vault、Wiki。
- **--watch**：文件变更自动重建（无需 LLM）。
- **--add**：抓取 URL 内容并合并到现有图。
- **跨仓库合并**：多个 GitHub URL 合并为一个跨仓库图。
- **嵌入向量索引**：`build_embeddings` 生成向量索引侧车（配置后端时）。

### 2.6 诚实性规则

- 边标注来源：EXTRACTED（确定性提取）/ INFERRED（LLM 推断）/ AMBIGUOUS（不确定）。
- 空图保护：提取未产生节点时拒绝覆写已有产物。
- 成本透明：每轮运行的 token 消耗记录在 `.graph/cost.json`。

---

## 3. GitNexus 对标分析

### 3.1 GitNexus 能力概览

GitNexus（GitHub: abhigyanpatwari/GitNexus，ISC 许可证）是一个代码智能引擎，通过
六阶段流水线将源代码转化为符号级知识图谱：

1. **Structure** — 遍历文件树，映射目录与文件关系。
2. **Parsing** — 使用 Tree-sitter AST 提取函数、类、方法、接口等符号（支持 15+ 语言：
   TypeScript、JavaScript、Python、Java、Kotlin、C#、Go、Rust、PHP、Ruby、Swift、
   C、C++、COBOL、Dart）。
3. **Resolution** — 跨文件解析导入、函数调用、类继承、构造器类型推断、`self`/`this`
   接收者类型。
4. **Clustering** — 使用 Leiden 算法对符号进行功能社区聚类，附带 cohesion 评分。
5. **Processes** — 从入口点追踪执行流，构建调用链过程。
6. **Search** — 构建 BM25 + 语义向量 + RRF（Reciprocal Rank Fusion, K=60）混合搜索索引。

图存储使用 LadybugDB（嵌入式图数据库，原生向量支持）。MCP 工具集包括 `query`、
`context`、`impact`、`trace`、`detect_changes`、`rename`、`cypher`、`route_map`、
`tool_map`、`shape_check`、`api_impact`、`pdg_query` 等 15+ 工具。

> **待确认**：GitNexus 是否提供显式的"测试到被测代码"映射工具。从入口点检测与执行流
> 追踪能力可推导出该场景，但未在 README 或 ARCHITECTURE.md 中发现独立命名的工具。

### 3.2 能力对标表

| 能力域 | GitNexus 能力 | graphify 现状 | 差距 |
|--------|--------------|--------------|------|
| AST 符号提取 | Tree-sitter，15+ 语言，函数/类/方法/接口 | AST 结构提取（Part A），支持主流语言（完整列表待确认） | 符号类型覆盖与语言数量需扩展 |
| 跨文件调用解析 | 跨文件函数调用边，语言感知解析逻辑 | 无（AST 仅提取文件内结构） | **完全缺失** |
| 导入解析 | named/wildcard/namespace 导入、re-export 跟踪 | 无 | **完全缺失** |
| 类继承与接口 | heritage 边（继承、接口实现、mixin） | 无 | **完全缺失** |
| 构造器类型推断 | 从构造器调用推断接收者类型（self/this） | 无 | **完全缺失** |
| 社区检测 | Leiden 算法 + cohesion 评分 | 社区检测 + cohesion 评分（算法实现待确认是否为 Leiden） | 基本覆盖，算法一致性待确认 |
| 执行流追踪 | 从入口点追踪调用链，构建 process 节点 | 无 | **完全缺失** |
| 影响分析 | blast radius，按深度分组 + 置信度评分 | 无 | **完全缺失** |
| Git-diff 影响映射 | detect_changes：变更行 → 受影响符号与 process | 无 | **完全缺失** |
| 多文件重命名 | 图辅助协调重命名，dry_run 预览 | 无 | **完全缺失** |
| 混合搜索 | BM25 + 语义向量 + RRF（K=60） | 嵌入向量索引（build_embeddings）+ BFS/DFS 遍历 | 缺 BM25 与 RRF 融合层 |
| Cypher 查询 | 原始 Cypher 查询（交互式，针对 schema） | Cypher 脚本导出（非交互式） | 缺交互式查询能力 |
| MCP 工具集 | 15+ 工具（query/context/impact/trace/...） | MCP stdio server（query/path/explain） | 工具数量与深度差距大 |
| 框架检测 | AST 模式检测（@Controller/@Get 等） | 无 | **完全缺失** |
| 入口点识别 | 入口点评分启发式 | 无 | **完全缺失** |
| 配置解析 | tsconfig/go.mod 等语言工具链配置 | 无 | **完全缺失** |
| 增量索引 | 解析缓存（content-addressed）+ 提交级过期检查；完整文件级增量索引为 TODO | --update（文件 manifest + 内容哈希，仅重新提取变更文件） | graphify 在文件级增量上已有基础，但缺 git-diff 粒度 |
| 图存储 | LadybugDB（嵌入式图数据库，原生向量） | graph.json（JSON 文件）+ Neo4j/FalkorDB 导出 | 架构路线不同 |
| PDG/污点分析 | opt-in --pdg：CFG + 污点传播 | 无 | **完全缺失**（可列为非目标） |
| 多仓库契约 | 跨仓库分组 + 契约注册 + cross-impact | 跨仓库合并（多 URL 合并为一个图） | 缺契约提取与注册 |
| Wiki 生成 | LLM 分组模块文档 + 交叉引用 | --wiki 导出（基于社区的 wiki） | 部分覆盖，缺 LLM 文档生成 |
| Agent skills | 按社区生成 .claude/skills/ 技能定义 | 无 | **完全缺失** |
| Claude Code hooks | PreToolUse/PostToolUse 钩子 | post-commit 钩子 | 部分覆盖 |
| 嵌入向量 | Snowflake arctic-embed-xs（384D） | build_embeddings（配置后端，如 sentence-transformers） | 基本覆盖 |

---

## 4. 目标与非目标

### 4.1 目标

1. 在 graphify 现有 AST 提取基础上，增加跨文件调用/引用边解析能力，使图谱能表达
   函数间调用关系、导入依赖、类继承等代码语义结构。
2. 引入执行流追踪能力，从入口点出发构建调用链 process，使图谱可回答"这个入口点
   执行时经过了哪些代码路径"。
3. 增加影响分析（blast radius）工具，给定一个符号，返回其上游/下游依赖，按深度分组
   并附带置信度评分。
4. 增强增量更新引擎，支持 git-diff 粒度的影响映射（变更行 → 受影响符号与执行流）。
5. 扩展 MCP 工具集，补齐 `context`、`impact`、`trace`、`detect_changes` 等代码分析
   专用工具。
6. 增强搜索能力，在现有嵌入向量索引基础上引入 BM25 + RRF 混合搜索。

### 4.2 非目标

1. **不替换图存储引擎**：保持 `.graph/graph.json` 作为主持久化产物；Neo4j/FalkorDB
   导出继续作为可选集成，不引入 LadybugDB 作为主存储。
2. **不实现 PDG/污点分析**：程序依赖图与污点传播属于安全分析领域，超出本阶段范围。
3. **不实现多文件协调重命名**：重命名是编辑器级操作，不属于图谱引擎职责。
4. **不实现 Web UI**：graphify 的 HTML 可视化已满足基础展示需求，不构建浏览器端
   WASM 索引流水线。
5. **不实现 Agent skills 自动生成**：保持 graphify 的 AGENTS.md 注入机制，不按社区
   生成独立 skill 定义文件。

---

## 5. 功能需求

### FR-1：符号级 AST 索引增强

**目标**：扩展现有 AST 提取（Part A）的符号类型覆盖与语言支持。

**要求**：
- 符号类型至少覆盖：函数、方法、类、接口、类型别名、变量声明、模块/命名空间。
- 语言支持至少达到：TypeScript、JavaScript、Python、Go、Java、Rust（与 graphify
  现有支持对齐，不引入新语言依赖）。
- 每个符号节点应包含：符号名、限定名（qualified name）、文件路径、起止行号、符号类别。
- AST 提取保持确定性、无 LLM 依赖。

**优先级**：P1

### FR-2：跨文件调用与引用边解析

**目标**：在 AST 提取之后增加 Resolution 阶段，解析跨文件的语义关系边。

**要求**：
- **调用边（CALLS）**：函数/方法调用 → 被调用函数/方法，需跨文件解析。
- **导入边（IMPORTS）**：文件 → 被导入的模块/符号，支持 named import、default import、
  wildcard import。
- **继承边（HERITAGE）**：类 → 父类/接口实现。
- **定义边（DEFINES）**：文件 → 其定义的符号。
- 解析应基于语言感知的规则（不同语言的导入系统差异由 language-specific resolver
  处理），不使用 LLM。
- 新增边类型应标注为 EXTRACTED（确定性解析）。

**说明**：跨文件引用解析在增量更新场景下可能产生短暂的悬空边（被引用符号所在文件
已变更但尚未重新提取时），这是跨文件解析的固有时序问题。

**优先级**：P1

### FR-3：执行流追踪（Process Detection）

**目标**：从入口点出发追踪调用链，构建 process 节点表示执行流。

**要求**：
- 入口点识别：基于启发式评分（如 `main` 函数、HTTP handler、CLI 入口、测试函数）。
  入口点评分规则应可配置、可扩展。
- 调用链追踪：沿 CALLS 边从入口点出发，构建有向调用子图，记录每一步的调用关系。
- process 节点应包含：入口点符号、调用链步骤列表、覆盖的符号集合。
- 多入口点场景：每个入口点对应一个独立的 process 节点，共享的调用路径应在多个
  process 中均可追溯。

**优先级**：P2

### FR-4：影响分析工具（Blast Radius）

**目标**：给定一个符号，返回其完整的影响范围。

**要求**：
- **下游影响**：沿 CALLS 边方向，返回该符号调用的所有符号，按调用深度分层。
- **上游影响**：逆 CALLS 边方向，返回调用该符号的所有符号，按深度分层。
- **置信度评分**：每条影响路径附带置信度（如 `[CALLS 90%]`），评分基于边的来源
  （EXTRACTED 边高置信、INFERRED 边中置信、AMBIGUOUS 边低置信）。
- **结果分组**：按深度层级分组返回，每层包含符号列表与路径摘要。

**优先级**：P3

### FR-5：增量更新引擎增强（Git-diff 影响映射）

**目标**：在现有 `--update` 基础上，增加 git-diff 粒度的影响映射能力。

**要求**：
- 接收 git diff（文件级 + 行级），映射到受影响的符号节点。
- 沿 CALLS/HERITAGE 边传播影响，返回受影响的执行流（process）列表。
- 与现有 `--update` 的文件 manifest 机制协同：`--update` 负责重新提取变更文件，
  git-diff 影响映射负责报告受影响范围（不触发重新提取）。
- 支持作为 MCP 工具调用（`detect_changes`）。

**优先级**：P2

### FR-6：MCP 工具集扩展

**目标**：在现有 `--mcp` 的 query/path/explain 基础上，补齐代码分析专用工具。

**要求**：
- **context**：给定一个符号，返回其 360 度视图（调用者、被调用者、所属社区、参与的
  执行流）。
- **impact**：FR-4 定义的影响分析，作为 MCP 工具暴露。
- **trace**：两个符号之间的最短有向调用路径（沿 CALLS 边）。
- **detect_changes**：FR-5 定义的 git-diff 影响映射。
- 现有 query/path/explain 保持不变。

**优先级**：P3

### FR-7：混合搜索增强

**目标**：在现有嵌入向量索引基础上引入 BM25 + RRF 混合搜索。

**要求**：
- 构建 BM25 倒排索引（覆盖符号名、限定名、文件路径、文档注释）。
- 语义搜索沿用现有嵌入向量索引（build_embeddings）。
- 结果融合使用 RRF（Reciprocal Rank Fusion），K 值默认 60，可配置。
- 搜索结果应包含符号节点引用，而非纯文本片段。

**优先级**：P3

### FR-8：框架检测与入口点配置

**目标**：基于 AST 模式检测常见框架，辅助入口点识别。

**要求**：
- 框架检测：通过 AST 模式匹配识别常见框架使用（如 Express handler、FastAPI 路由、
  Spring Controller、React 组件等），标记相关符号节点。
- 检测规则基于 AST 节点模式，不使用 LLM。
- 检测结果作为入口点评分的输入信号之一（FR-3）。
- 规则应可配置、可扩展（新增框架无需修改核心代码）。

**优先级**：P4

---

## 6. 非功能需求

### NFR-1：索引性能

- 全量索引一个中等规模仓库（~500 文件）应在 60 秒内完成（不含语义提取，仅 AST +
  Resolution + Clustering + Process Detection）。
- 大规模仓库（~5000 文件）应在可接受范围内完成全量索引。

### NFR-2：增量更新耗时

- 增量更新（`--update`）仅重新提取变更文件时，应在合理时间内完成，不应触发全量
  重建。
- git-diff 影响映射应在秒级返回结果（不触发重新提取，仅查询图）。

### NFR-3：存储占用

- `.graph/graph.json` 在新增跨文件边后，体积增长不应超过原有体积的 3 倍。
- BM25 倒排索引作为独立侧车文件存储，不膨胀主 graph.json。

### NFR-4：向后兼容

- 新增边类型（CALLS/IMPORTS/HERITAGE/DEFINES）应向后兼容现有 `graph.json` 格式。
- 现有 `--update`、`--cluster-only`、query/path/explain 等功能在未执行 Resolution
  阶段时保持原有行为。

### NFR-5：确定性

- AST 提取与 Resolution 阶段必须完全确定性（相同输入产生相同输出），不依赖 LLM。
- 影响分析、执行流追踪的结果由图结构决定，同一图谱的查询结果稳定。

### NFR-6：诚实性

- 新增边的来源标注遵循现有 EXTRACTED/INFERRED/AMBIGUOUS 体系。
- 跨文件解析未能解析的调用应标注为 AMBIGUOUS，不应静默丢弃。
- 图健康检查应覆盖新增边类型的完整性诊断。

---

## 7. 验收标准

| 编号 | 验收项 | 判定方法 |
|------|--------|----------|
| AC-1 | FR-1 符号提取覆盖 6 种语言的函数/类/方法/接口 | 对每种语言的测试仓库执行提取，检查节点类型完整性 |
| AC-2 | FR-2 跨文件调用边正确解析 | 对已知调用关系的测试仓库，验证 CALLS 边连接正确 |
| AC-3 | FR-2 导入边正确解析 | 对包含 named/default/wildcard import 的测试文件，验证 IMPORTS 边 |
| AC-4 | FR-3 执行流追踪覆盖完整调用链 | 从已知入口点出发，验证 process 节点包含所有预期调用步骤 |
| AC-5 | FR-4 影响分析结果包含深度分组 | 对已知依赖结构的测试符号，验证按深度分组的影响列表 |
| AC-6 | FR-5 git-diff 影响映射正确 | 对模拟变更，验证受影响符号与 process 列表准确 |
| AC-7 | FR-6 MCP 工具集可通过 stdio 调用 | 通过 MCP 客户端调用 context/impact/trace/detect_changes，验证响应格式 |
| AC-8 | FR-7 混合搜索结果优于纯向量搜索 | 对同一查询，RRF 融合结果的召回率不低于纯向量搜索 |
| AC-9 | NFR-4 向后兼容 | 对现有 graph.json（无 CALLS 边）执行 query，结果与升级前一致 |
| AC-10 | 社区检测结果具有语义连贯性 | 对测试仓库，社区划分应与代码的功能模块划分基本一致 |

---

## 8. 里程碑概览

| 里程碑 | 阶段 | 主要交付 | 预计周期 |
|--------|------|---------|---------|
| M1 | P0 原型验证 | 跨文件调用解析原型（单语言：TypeScript），验证技术可行性 | 2 周 |
| M2 | P1 符号级图模型 | FR-1 + FR-2 全量实现，6 种语言符号提取与 Resolution | 4 周 |
| M3 | P2 增量更新引擎 | FR-3 执行流追踪 + FR-5 git-diff 影响映射 | 3 周 |
| M4 | P3 查询与分析 | FR-4 影响分析 + FR-6 MCP 工具扩展 + FR-7 混合搜索 | 4 周 |
| M5 | P4 对标特性 | FR-8 框架检测，入口点评分完善 | 2 周 |
| M6 | P5 性能与集成 | 性能优化、大规模仓库验证、文档与示例 | 2 周 |

详细执行计划见 `plan.md`。

---

## 附录 A：术语表

| 术语 | 定义 |
|------|------|
| AST | Abstract Syntax Tree，抽象语法树 |
| Resolution | 跨文件解析阶段，解析导入、调用、继承等语义关系 |
| Blast Radius | 影响范围分析，给定符号的上游/下游依赖 |
| Process | 执行流，从入口点追踪的调用链 |
| RRF | Reciprocal Rank Fusion，倒数排名融合 |
| BM25 | 词频饱和的文本检索排序算法 |
| LadybugDB | 嵌入式图数据库（GitNexus 使用），前称 KuzuDB |
| Tree-sitter | 增量解析库，支持多语言 AST 提取 |
| EXTRACTED | 确定性提取的边（graphify 诚实性标注） |
| INFERRED | LLM 推断的边（graphify 诚实性标注） |
| AMBIGUOUS | 不确定的边（graphify 诚实性标注） |

## 附录 B：参考来源

- graphify SKILL.md（`C:\Users\Administrator\.config\opencode\skills\graphify\SKILL.md`）
- GitNexus GitHub README: https://github.com/abhigyanpatwari/GitNexus
- GitNexus ARCHITECTURE.md（GitHub 仓库内）
- GitNexus DeepWiki: https://deepwiki.com/abhigyanpatwari/GitNexus


其他审查者观点:
[deployment-config-reviewer]: 被审查内容是一份功能规格说明书（spec.md），而非部署配置文件（无 Dockerfile / K8s manifests / Terraform / CI 配置）。因此，检查清单中关于非 root 运行、具体版本标签、健康检查、资源限制、优雅停机等部署专项条目无法直接评估——内容中根本不包含这些部署制品。但作为 DevOps/平台工程审查者，我审查了 spec 中与配置一致性、可运维性、可复现性相关的方面，发现以下问题：(1) spec 定义了包含服务端组件（MCP stdio server）和外部服务集成（Neo4j/FalkorDB/Gemini/嵌入后端）的系统，但 NFR 章节未覆盖可运维性需求（健康检查、资源限制、日志策略、优雅停机）；(2) 多个外部服务依赖需要凭证，但 spec 未定义任何配置接口（环境变量/配置文件/连接参数/端口），也未提出 secret 管理要求，存在配置漂移与凭证硬编码风险；(3) BM25 倒排索引作为新增侧车制品，与所有现有制品（均有明确路径）不同，未指定存储路径，存在配置一致性缺口。所有发现均为 minor，因为 spec 是功能规格而非部署配置，部署专项缺失属于范畴边界问题而非配置错误。
[design-reviewer]: 该 spec 在结构上较为完整，具备明确的背景动机、对标分析、目标/非目标、FR/NFR 分层、验收标准与里程碑，需求覆盖度较高。但作为设计文档存在以下系统性缺陷：(1) 关键架构选型缺乏对比依据——尤其是保留 graph.json 而非引入 LadybugDB 的决策未给出技术理由，而新增的 blast radius/impact/trace 等查询密集型功能对存储层的查询效率有实质要求；(2) 验收标准覆盖不完整——FR-8 及多数 NFR 无对应 AC，FR-2 的四种边类型仅两种有 AC；(3) 异常路径与失败模式设计不足——执行流追踪(FR-3)未设计循环依赖终止条件、深链路预算限制；跨文件解析(FR-2)已识别悬空边风险但未给出消解方案；(4) NFR-1 对大规模仓库的性能指标不可度量。这些问题不影响 spec 作为草案的整体方向，但会在实现阶段造成可追溯性缺失。

你的反驳: