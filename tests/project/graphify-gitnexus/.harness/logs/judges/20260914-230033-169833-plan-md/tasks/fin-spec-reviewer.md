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

辩论已结束。请基于辩论中的所有信息,给出你的最终裁决。

---

被审查内容:
# 执行计划：在 graphify 图谱基础上对标 GitNexus 补齐能力

| 字段 | 值 |
|------|-----|
| 文档版本 | v1.0 |
| 创建日期 | 2026-09-14 |
| 关联规格 | spec.md v1.0 |
| 状态 | 草案 |

---

## 1. 计划概述

本计划将 spec.md 定义的功能需求拆解为 6 个阶段（P0–P5），按依赖关系串行推进，
阶段内任务尽量并行。核心路径为：AST 符号增强 → 跨文件解析 → 执行流与增量更新 →
查询分析工具 → 对标特性补齐 → 性能验证。

每个阶段交付可验证的中间产物，避免到最后才集成。阶段间的依赖关系：

```
P0 (原型验证) → P1 (符号级图模型) → P2 (增量更新引擎) → P3 (查询与分析)
                                                          ↓
                                        P4 (对标特性) → P5 (性能与集成)
```

P4 依赖 P3 的 MCP 工具框架（框架检测结果需通过 context 工具暴露），但 P4 的 AST
检测规则开发可与 P3 后半段并行。

---

## 2. P0：原型验证（2 周）

### 2.1 目标

验证跨文件调用解析的技术可行性，以 TypeScript 为试点语言，在 graphify 现有 AST
提取（Part A）之后增加一个 Resolution 原型阶段。

### 2.2 任务分解

| 任务 | 描述 | 依赖 | 交付物 |
|------|------|------|--------|
| T0.1 | 选定测试仓库：3 个 TypeScript 开源项目（~100–300 文件），覆盖不同框架 | 无 | 测试仓库集合 + 选型记录 |
| T0.2 | 分析 graphify AST 提取输出的节点/边结构，确定 CALLS 边的接入点 | 无 | AST 输出结构分析文档 |
| T0.3 | 实现 TypeScript 导入解析器原型：解析 `import { X } from 'path'`、`import Y from 'path'`、`import * as Z from 'path'` | T0.2 | `ts_import_resolver.py` 原型 |
| T0.4 | 实现 TypeScript 调用解析器原型：沿 AST 调用节点 + 导入表，生成 CALLS 边 | T0.3 | `ts_call_resolver.py` 原型 |
| T0.5 | 将 Resolution 原型接入 Part A → Part C 合并流程，生成含 CALLS 边的 graph.json | T0.4 | 原型端到端流程 |
| T0.6 | 验证：对测试仓库手动检查 CALLS 边的准确性，记录误解析/漏解析案例 | T0.5 | 验证报告 |

### 2.3 退出标准

- TypeScript 测试仓库的 CALLS 边准确率（人工抽样）≥ 80%。
- 导入解析覆盖 named/default/wildcard 三种形式。
- 原型流程不破坏现有 Part A → Part C 合并逻辑。

---

## 3. P1：符号级图模型（4 周）

### 3.1 目标

将 P0 原型扩展为完整的符号级图模型，实现 FR-1（符号提取增强）和 FR-2（跨文件
调用与引用边解析），覆盖 6 种语言。

### 3.2 任务分解

| 任务 | 描述 | 依赖 | 交付物 |
|------|------|------|--------|
| T1.1 | 扩展 AST 提取的符号类型：函数、方法、类、接口、类型别名、变量声明、模块 | P0 完成 | 增强后的 `extract()` 输出 |
| T1.2 | 为符号节点增加限定名（qualified name）字段，支持跨文件符号去重 | T1.1 | 符号节点 schema 更新 |
| T1.3 | 实现语言解析器注册机制：`LanguageResolver` 接口 + 每语言实现 | T1.1 | `resolver_registry.py` |
| T1.4 | TypeScript 解析器：导入解析 + 调用解析 + 类继承 + DEFINES 边 | T1.3 | `ts_resolver.py` |
| T1.5 | JavaScript 解析器：复用 TypeScript 解析器，处理 CommonJS/ESM 差异 | T1.4 | `js_resolver.py` |
| T1.6 | Python 解析器：`import`/`from...import` 解析 + 调用解析 + 类继承 | T1.3 | `python_resolver.py` |
| T1.7 | Go 解析器：`import` 解析 + 调用解析 + struct 嵌入（Go 继承机制） | T1.3 | `go_resolver.py` |
| T1.8 | Java 解析器：`import` 解析 + 调用解析 + extends/implements | T1.3 | `java_resolver.py` |
| T1.9 | Rust 解析器：`use` 解析 + 调用解析 + trait 实现 | T1.3 | `rust_resolver.py` |
| T1.10 | 更新 Part C 合并逻辑：合并 AST 节点 + Resolution 边 | T1.4–T1.9 | 增强后的合并流程 |
| T1.11 | 更新图健康检查（diagnose_extraction）：覆盖 CALLS/IMPORTS/HERITAGE 边的悬空端点检测 | T1.10 | 增强后的诊断 |
| T1.12 | 新增边类型标注为 EXTRACTED，未解析的调用标注为 AMBIGUOUS | T1.10 | 边来源标注 |

### 3.3 依赖说明

- T1.4–T1.9（6 种语言解析器）可并行开发，共享 T1.3 定义的 `LanguageResolver`
  接口。
- T1.10 和 T1.11 依赖全部解析器完成。

### 3.4 交付物

- 6 种语言的符号提取与 Resolution 阶段，集成到 graphify 主流程。
- 更新后的 `.graph/graph.json` 包含 CALLS/IMPORTS/HERITAGE/DEFINES 边。
- 图健康检查覆盖新增边类型。

### 3.5 退出标准

- 满足 AC-1（符号提取覆盖）和 AC-2/AC-3（调用边与导入边正确性）。
- 6 种语言各自的测试仓库通过 Resolution 阶段，无崩溃。

---

## 4. P2：增量更新引擎（3 周）

### 4.1 目标

实现 FR-3（执行流追踪）和 FR-5（git-diff 影响映射），增强增量更新引擎的代码
分析能力。

### 4.2 任务分解

| 任务 | 描述 | 依赖 | 交付物 |
|------|------|------|--------|
| T2.1 | 设计入口点评分启发式：函数名模式（`main`/`handle`/`test_*`）、框架标记（依赖 P4 但可先用硬编码）、调用入度/出度 | P1 完成 | 入口点评分算法 |
| T2.2 | 实现调用链追踪：沿 CALLS 边从入口点 BFS，构建 process 节点 | T2.1 | `process_detector.py` |
| T2.3 | process 节点 schema：入口点符号、调用步骤列表、覆盖符号集合 | T2.2 | process 节点定义 |
| T2.4 | 集成到 Step 4 构建流程：cluster → process detection → 输出 | T2.3 | 完整构建流程 |
| T2.5 | 实现 git-diff 解析：文件级 + 行级 diff → 映射到符号节点 | P1 完成 | `diff_parser.py` |
| T2.6 | 实现影响传播：从变更符号出发，沿 CALLS/HERITAGE 边传播到受影响 process | T2.5, T2.2 | `impact_mapper.py` |
| T2.7 | 集成到 `--update` 流程：`--update` 触发重新提取后，自动执行影响映射报告 | T2.6 | 增强后的 `--update` |
| T2.8 | 更新 manifest 机制：manifest 记录符号级哈希（非仅文件级），支持符号粒度增量 | T2.5 | 增强后的 manifest |

### 4.3 交付物

- 执行流追踪能力（process 节点）集成到图谱构建流程。
- git-diff 影响映射工具，可作为独立命令或 MCP 工具调用。
- 增强后的 `--update` 流程。

### 4.4 退出标准

- 满足 AC-4（执行流覆盖完整调用链）和 AC-6（git-diff 影响映射正确）。
- 增量更新后，process 节点正确反映变更后的调用链。

---

## 5. P3：查询与分析能力（4 周）

### 5.1 目标

实现 FR-4（影响分析）、FR-6（MCP 工具扩展）和 FR-7（混合搜索），补齐查询层能力。

### 5.2 任务分解

| 任务 | 描述 | 依赖 | 交付物 |
|------|------|------|--------|
| T3.1 | 实现影响分析核心：给定符号 ID，沿 CALLS 边双向遍历，按深度分组 | P1 完成 | `impact_analyzer.py` |
| T3.2 | 实现置信度评分：EXTRACTED 边 → 90%、INFERRED 边 → 60%、AMBIGUOUS 边 → 30% | T3.1 | 置信度评分模块 |
| T3.3 | 实现 trace 工具：两个符号间的最短有向调用路径（BFS on CALLS edges） | P1 完成 | `trace.py` |
| T3.4 | 实现 context 工具：给定符号，聚合调用者、被调用者、社区归属、参与 process | P2 完成 | `context.py` |
| T3.5 | 扩展 MCP server：注册 context/impact/trace/detect_changes 工具 | T3.1–T3.4, T2.6 | 增强后的 MCP server |
| T3.6 | 实现 BM25 倒排索引：索引符号名、限定名、文件路径、文档注释 | P1 完成 | `bm25_index.py` |
| T3.7 | 实现 RRF 融合：BM25 排名 + 语义向量排名 → RRF（K=60）融合结果 | T3.6 | `hybrid_search.py` |
| T3.8 | 集成到 query 工具：query 命令优先使用混合搜索，回退到 BFS/DFS | T3.7 | 增强后的 query |
| T3.9 | 更新嵌入索引：BM25 索引作为独立侧车（`.graph/bm25_index.json`），不膨胀 graph.json | T3.6 | 索引侧车文件 |

### 5.3 交付物

- 影响分析、trace、context 三个分析工具。
- MCP 工具集扩展至 7 个工具（query/path/explain + context/impact/trace/detect_changes）。
- BM25 + RRF 混合搜索引擎。

### 5.4 退出标准

- 满足 AC-5（影响分析深度分组）、AC-7（MCP 工具可调用）、AC-8（混合搜索优于纯向量）。
- 现有 query/path/explain 行为不退化。

---

## 6. P4：GitNexus 对标特性（2 周）

### 6.1 目标

实现 FR-8（框架检测与入口点配置），完善入口点识别能力，使执行流追踪的入口点
质量接近 GitNexus 水平。

### 6.2 任务分解

| 任务 | 描述 | 依赖 | 交付物 |
|------|------|------|--------|
| T4.1 | 定义框架检测规则 schema：AST 节点模式 → 框架标签 + 入口点权重 | P1 完成 | 规则 schema |
| T4.2 | 实现框架检测引擎：AST 模式匹配，标记符号节点 | T4.1 | `framework_detector.py` |
| T4.3 | 编写框架规则集：Express、FastAPI、Spring、React、Gin、Actix | T4.1 | 6 个框架规则文件 |
| T4.4 | 集成到入口点评分（T2.1）：框架标记作为评分输入信号 | T4.2, P2 完成 | 增强后的入口点评分 |
| T4.5 | 框架标签通过 context MCP 工具暴露 | T3.5, T4.2 | context 工具增强 |
| T4.6 | 验证：对使用已知框架的测试仓库，检查入口点识别覆盖率 | T4.4 | 验证报告 |

### 6.3 交付物

- 框架检测引擎 + 6 个框架规则集。
- 增强后的入口点评分（融合框架信号）。
- 框架标签在 context 工具中可见。

### 6.4 退出标准

- 6 个框架的测试仓库中，入口点识别覆盖率 ≥ 70%。
- 框架规则可通过配置文件扩展，无需修改核心代码。

---

## 7. P5：性能与集成（2 周）

### 7.1 目标

验证 NFR-1/2/3（性能、增量更新耗时、存储占用），优化瓶颈，完成文档与示例。

### 7.2 任务分解

| 任务 | 描述 | 依赖 | 交付物 |
|------|------|------|--------|
| T5.1 | 性能基准：对 500/2000/5000 文件仓库执行全量索引，记录各阶段耗时 | P1–P4 完成 | 性能基准报告 |
| T5.2 | 优化 Resolution 阶段：并行化语言解析器调用，减少串行等待 | T5.1 | 性能优化补丁 |
| T5.3 | 增量更新基准：对 5000 文件仓库执行单文件变更的 `--update`，记录耗时 | T5.1 | 增量更新基准 |
| T5.4 | 存储基准：测量 graph.json + BM25 索引 + 嵌入索引的总体积 | T5.1 | 存储报告 |
| T5.5 | 向后兼容验证：对不含 Resolution 边的旧 graph.json 执行 query，确认无退化 | P3 完成 | 兼容性报告 |
| T5.6 | 更新 SKILL.md：增加 Resolution 阶段说明、新 MCP 工具文档 | 全部完成 | SKILL.md 更新 |
| T5.7 | 编写示例：3 个使用场景（影响分析、执行流追踪、变更检测）的端到端示例 | 全部完成 | 示例文档 |

### 7.3 退出标准

- NFR-1：500 文件仓库全量索引 ≤ 60 秒。
- NFR-3：graph.json 体积增长 ≤ 3 倍。
- NFR-4：旧 graph.json 的 query 行为无退化。
- AC-9（向后兼容）通过。
- AC-10（社区检测语义连贯性）通过人工审查。

---

## 8. 测试与验收策略

### 8.1 测试分层

| 层级 | 范围 | 方法 | 自动化 |
|------|------|------|--------|
| 单元测试 | 每个解析器、分析器、索引器的独立逻辑 | pytest + MockLLM（零真实 API） | 全自动 |
| 集成测试 | AST 提取 → Resolution → 合并 → 构建端到端 | 真实测试仓库样本 | 半自动（CI 触发） |
| 对标测试 | 与 GitNexus 对同一仓库的输出对比 | 手动执行 GitNexus + 结果对比 | 手动 |
| 性能测试 | 各阶段耗时与存储占用 | 基准脚本 + 仓库规模矩阵 | 半自动 |

### 8.2 测试仓库

准备 3 组测试仓库样本：

1. **小型仓库**（~50 文件）：单语言，覆盖所有符号类型与边类型，用于单元测试。
2. **中型仓库**（~500 文件）：多语言混合，含框架使用，用于集成测试与性能基准。
3. **大型仓库**（~5000 文件）：真实开源项目，用于性能验证与对标测试。

### 8.3 验收标准映射

| 验收标准 | 验证阶段 | 验证方法 |
|----------|----------|----------|
| AC-1 符号提取覆盖 | P1 | 单元测试：每种语言的固定样本仓库 |
| AC-2 调用边正确 | P1 | 集成测试：已知调用关系的断言 |
| AC-3 导入边正确 | P1 | 单元测试：named/default/wildcard import 测试样本 |
| AC-4 执行流覆盖 | P2 | 集成测试：入口点到终端调用的路径断言 |
| AC-5 影响分析深度 | P3 | 单元测试：已知依赖结构的深度分组断言 |
| AC-6 git-diff 映射 | P2 | 集成测试：模拟 diff → 受影响符号断言 |
| AC-7 MCP 工具调用 | P3 | 集成测试：MCP 客户端调用 + 响应格式断言 |
| AC-8 混合搜索召回 | P3 | 对标测试：同一查询的召回率对比 |
| AC-9 向后兼容 | P5 | 集成测试：旧 graph.json query 无退化 |
| AC-10 社区检测连贯性 | P5 | 人工审查：社区划分与功能模块对比 |

### 8.4 持续集成

- 所有单元测试在 CI 中每次提交自动执行。
- 集成测试在 PR 合并前执行。
- 性能基准在里程碑完成时执行，记录趋势。

---

## 9. 风险与应对

| 风险 | 影响 | 概率 | 应对 |
|------|------|------|------|
| 跨文件解析的语言复杂度超预期 | P1 延期 | 中 | P0 原型阶段提前暴露难点；按语言优先级降序实现（TS > Python > Go > Java > Rust > JS） |
| 增量更新后图谱出现悬空边 | 数据完整性 | 中 | 图健康检查（T1.11）覆盖新增边类型；`--update` 完成后自动执行诊断并报告 |
| graph.json 体积膨胀超 NFR-3 限制 | 存储压力 | 低 | BM25 索引独立侧车；Resolution 边按需存储（仅 EXTRACTED 边入主图，AMBIGUOUS 边入侧车） |
| MCP 工具响应延迟影响 agent 体验 | 用户体验 | 中 | 影响分析结果缓存；深度限制（默认最大深度 5 层，可配置） |
| 框架检测规则误报 | 入口点评分失准 | 低 | 规则可配置；误报案例在验证阶段收集并修正 |
| 旧 graph.json 升级路径不清晰 | 向后兼容 | 低 | NFR-4 保证旧图 query 不退化；新功能在无 Resolution 边时静默降级 |

---

## 10. 依赖与前提

| 依赖项 | 说明 | 状态 |
|--------|------|------|
| graphify 现有 AST 提取（Part A） | Resolution 阶段在其输出基础上工作 | 已就绪 |
| graphify 现有社区检测（cluster） | process detection 需要社区信息作为评分输入 | 已就绪 |
| graphify 现有 MCP server（--mcp） | 新工具注册到现有 server | 已就绪 |
| graphify 现有嵌入索引（build_embeddings） | 混合搜索复用现有向量索引 | 已就绪 |
| NetworkX 图结构 | Resolution 边直接添加到现有 NetworkX 图 | 已就绪 |
| Tree-sitter Python 绑定 | 如需替换现有 AST 提取为 Tree-sitter（待 P0 评估） | 待确认 |

---

## 附录：阶段与 FR 映射

| 阶段 | 覆盖 FR | 覆盖 NFR | 覆盖 AC |
|------|---------|----------|---------|
| P0 | — | — | 原型验证（无正式 AC） |
| P1 | FR-1, FR-2 | NFR-4, NFR-5, NFR-6 | AC-1, AC-2, AC-3 |
| P2 | FR-3, FR-5 | NFR-2 | AC-4, AC-6 |
| P3 | FR-4, FR-6, FR-7 | — | AC-5, AC-7, AC-8 |
| P4 | FR-8 | — | — |
| P5 | — | NFR-1, NFR-2, NFR-3 | AC-9, AC-10 |


辩论后你的立场:
[spec-reviewer R2 辩论 - plan.md]

第 2 轮审查维持不通过。接受 design-reviewer 对 INFERRED 边的纠正。核心规格缺陷 4 项 major：NFR 验收标准与退出标准系统性脱节、AC-10 无对应验证任务、MCP 工具接口契约未定义、P4/FR-8 无正式 AC 编号。与 design-reviewer 在 DR-2/DR-3 上形成跨视角共识。

```json
{
  "satisfied": false,
  "findings": [
    {
      "id": "SR-1",
      "severity": "major",
      "confidence": 0.88,
      "title": "NFR 验收标准与阶段退出标准系统性脱节",
      "evidence": "附录映射表将 NFR-4/5/6 归入 P1、NFR-2 归入 P2 和 P5，但各阶段退出标准均未包含对应 NFR 验证条件。NFR 被声明为已覆盖但从未在退出标准中被验证。",
      "suggestion": "在每个阶段退出标准中显式列出该阶段映射表声称覆盖的 NFR 及其验证方法。"
    },
    {
      "id": "SR-2",
      "severity": "major",
      "confidence": 0.85,
      "title": "AC-10 在 P5 退出标准中声称通过但无对应验证任务",
      "evidence": "P5 退出标准列出 AC-10 通过人工审查，但 P5 任务列表中无任何任务涉及社区检测连贯性验证。T1.10 新增边改变了社区检测所依赖的图结构但无验证任务。",
      "suggestion": "在 P5 增加 AC-10 验证任务：对含 Resolution 边的图执行社区检测，与基线结果对比。"
    },
    {
      "id": "SR-3",
      "severity": "major",
      "confidence": 0.82,
      "title": "新增 4 个 MCP 工具接口契约未定义",
      "evidence": "T3.5 注册 context/impact/trace/detect_changes 四工具，但无任务定义输入参数 schema、输出格式、错误码和边界行为。接口契约完整性是 FR-6 的规格要求。",
      "suggestion": "在 P3 增加任务：定义 4 个新 MCP 工具的接口契约文档。"
    },
    {
      "id": "SR-4",
      "severity": "major",
      "confidence": 0.80,
      "title": "P4（FR-8 框架检测）无正式验收标准编号",
      "evidence": "附录 P4 行 AC 列为空。P4 退出标准定义了指标但未映射到编号 AC。8.3 节 AC-1 到 AC-10 无一条对应 FR-8。FR 到 AC 可追溯性断裂。",
      "suggestion": "补充 AC-11（框架检测入口点覆盖率 ≥ 70%），映射到 P4。"
    },
    {
      "id": "SR-5",
      "severity": "minor",
      "confidence": 0.85,
      "title": "T2.1 依赖标注自相矛盾",
      "evidence": "T2.1 描述列声称依赖 P4 但依赖列标注 P1 完成。与 DR-6 收敛。",
      "suggestion": "修正 T2.1 依赖列。"
    },
    {
      "id": "SR-6",
      "severity": "minor",
      "confidence": 0.78,
      "title": "性能基准环境未定义导致 NFR-1 不可测试（支持 DC-3）",
      "evidence": "T5.1 未定义硬件配置、OS、Python 版本。无环境规格的性能数据不可复现。",
      "suggestion": "在 T5.1 增加环境规格定义。"
    },
    {
      "id": "SR-7",
      "severity": "minor",
      "confidence": 0.75,
      "title": "T2.2 BFS 调用链追踪未定义环检测边界条件（支持 DR-2）",
      "evidence": "T2.2 沿 CALLS 边 BFS 但无环检测。递归调用形成环会导致无限循环。",
      "suggestion": "T2.2 增加 BFS 环检测设计。"
    },
    {
      "id": "SR-8",
      "severity": "minor",
      "confidence": 0.72,
      "title": "Tree-sitter 评估任务缺失影响 FR-1 可实现性（支持 DR-3）",
      "evidence": "Tree-sitter 依赖状态待确认但 P0 无评估任务。FR-1 的规格可实现性悬空。",
      "suggestion": "在 P0 增加 Tree-sitter 评估任务。"
    }
  ],
  "summary": "第 2 轮审查维持不通过。接受 design-reviewer 对 INFERRED 边的纠正。核心规格缺陷 4 项 major。与 design-reviewer 在 DR-2/DR-3 上形成跨视角共识。"
}
```


请给出最终裁决(严重程度/置信度/依据/建议),并用 ```json 代码块返回结构化裁决,包含:
- severity: critical / major / minor / pass
- confidence: 0.0-1.0
- reasoning: 推理过程
- findings: [{description, severity: critical/major/minor, confidence, evidence, suggestion}]
- satisfied: bool