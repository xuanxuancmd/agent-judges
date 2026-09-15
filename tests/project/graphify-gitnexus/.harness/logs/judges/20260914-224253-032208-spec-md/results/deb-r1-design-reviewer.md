[design-reviewer 辩论回复 - Round 1]

design-reviewer 在辩论阶段从架构视角提出新发现：(1) 跨文件解析缺乏技术风险评估与降级方案；(2) AST 解析技术选型未说明；(3) 执行流追踪未处理动态分发，缺少接收者类型推断；(4) 调用链/影响分析缺少循环检测与深度限制；(5) 增量更新悬空边与影响分析一致性未设计。挑战 spec-reviewer 的接口契约 over-judgment（schema 属 design.md 职责）和 deployment-config-reviewer 的可运维性 over-judgment（CLI 工具非服务部署），并 amplify spec-reviewer 的边界条件发现。

```json
{
  "satisfied": false,
  "severity": "major",
  "confidence": 0.82,
  "findings": [
    {
      "id": "DR-1",
      "title": "跨文件解析（FR-2）缺乏技术风险评估与消解方案",
      "severity": "major",
      "confidence": 0.85,
      "evidence": "FR-2 要求为 6 种语言实现跨文件调用/导入/继承解析，spec 仅说'解析应基于语言感知的规则（不同语言的导入系统差异由language-specific resolver处理），不使用LLM'，但未提供：(1) 各语言导入系统复杂度评估；(2) 解析准确率目标；(3) 解析失败时的降级策略；(4) 动态导入处理方案。跨文件解析是本规格技术风险最高的部分——GitNexus 为此独立设置 Resolution 流水线阶段并实现了接收者类型推断。",
      "suggestion": "增加技术风险章节，按语言评估解析复杂度，定义解析准确率目标（如 ≥90% CALLS 边正确解析），明确动态导入等无法静态解析的场景标注为 AMBIGUOUS 并说明对 FR-3/FR-5 的影响。"
    },
    {
      "id": "DR-2",
      "title": "AST 解析技术选型未说明，FR-1 符号类型覆盖可行性未论证",
      "severity": "major",
      "confidence": 0.75,
      "evidence": "FR-1 要求符号类型至少覆盖'函数、方法、类、接口、类型别名、变量声明、模块/命名空间'，语言支持至少 6 种。spec 第 2.1 节提到 graphify 现有'AST结构提取（Part A）'但从未指明使用何种解析技术。GitNexus 明确使用 Tree-sitter（3.1 节）。FR-1 是否能基于现有解析器实现，还是需要引入 Tree-sitter，是影响所有下游能力的基础架构决策。",
      "suggestion": "在 FR-1 或技术方案章节明确 AST 解析技术，论证其对 6 种语言 × 7 种符号类型的覆盖能力，如需引入新依赖则说明集成方式。"
    },
    {
      "id": "DR-3",
      "title": "FR-3 执行流追踪未处理动态分发，FR-2 缺少接收者类型推断",
      "severity": "major",
      "confidence": 0.80,
      "evidence": "FR-3 沿 CALLS 边构建调用链，FR-2 定义 CALLS 边为'函数/方法调用→被调用函数/方法'。但面向对象代码中方法调用通过接口/虚函数分发，CALLS 边只能指向接口方法声明而非具体实现。GitNexus 在 Resolution 阶段实现了'构造器类型推断'和'self/this接收者类型推断'（3.1 节）。spec 的 FR-2 未包含接收者类型推断，导致 FR-3 对 OO 代码的执行流追踪将不完整。",
      "suggestion": "在 FR-2 增加接收者类型推断（或显式记录为 FR-3 的已知限制），描述动态分发场景下 CALLS 边的解析策略。"
    },
    {
      "id": "DR-4",
      "title": "调用链与影响分析缺少循环检测与深度限制设计",
      "severity": "major",
      "confidence": 0.88,
      "evidence": "FR-3 执行流追踪'沿CALLS边从入口点出发，构建有向调用子图'，FR-4 影响分析'按调用深度分层'。两者均涉及图遍历但未提及：(1) 循环调用（递归函数、互递归）的检测与处理；(2) 最大遍历深度限制；(3) 超大调用链的性能保护。实际代码中递归和互递归极为常见，无循环检测的图遍历将导致无限循环或栈溢出。",
      "suggestion": "在 FR-3 和 FR-4 增加循环检测（访问标记或 Tarjan 算法识别 SCC）和最大深度参数（可配置，默认值如 10），循环边标注为 RECURSIVE。"
    },
    {
      "id": "DR-5",
      "title": "增量更新悬空边与 FR-5 影响分析的一致性未设计",
      "severity": "major",
      "confidence": 0.78,
      "evidence": "FR-2 说明'跨文件引用解析在增量更新场景下可能产生短暂的悬空边'。FR-5 影响映射'沿CALLS/HERITAGE边传播影响，返回受影响的执行流列表'。当 CALLS/HERITAGE 边指向已变更但未重新提取的符号时，影响分析结果将不完整或错误。spec 未定义影响分析遇到悬空边时的行为。",
      "suggestion": "定义 FR-5 遇到悬空边时的行为：标注为 STALE_IMPACT，在结果中单独报告，或要求先执行 --update 完成重新提取后再运行影响分析。"
    },
    {
      "id": "DR-6",
      "title": "graph.json 作为图存储格式在遍历查询场景下的性能未论证",
      "severity": "minor",
      "confidence": 0.65,
      "evidence": "非目标 4.2.1 保持 graph.json 为主持久化产物。FR-3/FR-4/FR-5 均需沿 CALLS 边做图遍历。NFR-1 未定义查询性能要求。跨文件边引入后，图的边数量可能远超节点数量，JSON 文件加载与内存遍历的查询延迟未评估。NFR-3 限制'体积增长不超过3倍'但未论证此阈值的合理性。",
      "suggestion": "增加查询性能 NFR（如 5000 文件图谱上影响分析 <5 秒），评估是否需要为 CALLS 边构建邻接表索引侧车。"
    }
  ],
  "challenges": [
    {
      "target": "spec-reviewer",
      "finding_id": "接口契约——多条边类型与MCP工具缺少schema定义",
      "position": "partially_disagree",
      "reasoning": "被审查文档是功能规格说明书（spec.md），而非 API 设计文档。spec 在功能层已描述了每种边类型的语义和每个 MCP 工具的输入输出。形式化 JSON Schema 属于 design.md 或 API 契约的职责，不应在 spec 层要求。但 git-diff 输入格式（FR-5）确实是功能接口的一部分，应在此层明确。"
    },
    {
      "target": "spec-reviewer",
      "finding_id": "边界条件——调用链与影响分析的循环/深度限制未覆盖",
      "position": "agree_and_amplify",
      "reasoning": "完全同意，且从设计角度升级严重程度。这不仅是'未覆盖'，而是会导致实现阶段的实际故障：递归函数和互递归在真实代码中极为普遍，无循环检测的图遍历将导致无限循环或栈溢出。我进一步将其作为独立设计缺陷（DR-4）提出。"
    },
    {
      "target": "spec-reviewer",
      "finding_id": "内部一致性——FR-3(M3)依赖FR-8(M5)框架检测但未说明过渡行为",
      "position": "agree",
      "reasoning": "同意此一致性缺陷。建议在里程碑描述中明确 M3 阶段 FR-3 使用基础启发式，M5 阶段通过 FR-8 增强入口点评分。"
    },
    {
      "target": "deployment-config-reviewer",
      "finding_id": "NFR章节未覆盖可运维性需求",
      "position": "disagree",
      "reasoning": "graphify 是 CLI 工具 + stdio MCP server，不是长运行微服务。非目标 4.2.4 明确排除 Web UI。健康检查、资源限制、优雅停机是服务部署规格的职责，不属于功能规格的范围。deployment-config-reviewer 自己也承认'spec是功能规格而非部署配置'，但仍将其列为 finding，属于范畴越界。"
    },
    {
      "target": "deployment-config-reviewer",
      "finding_id": "外部服务依赖需要凭证但spec未定义配置接口",
      "position": "partially_disagree",
      "reasoning": "Neo4j/FalkorDB 导出、Gemini 后端、嵌入向量索引均为 graphify 现有能力（2.5 节明确列出），其配置接口已在 graphify 现有实现中定义。spec 不应重复定义已有配置接口。但 BM25 倒排索引作为新增制品，其配置参数应提及。"
    },
    {
      "target": "deployment-config-reviewer",
      "finding_id": "BM25倒排索引存储路径未指定",
      "position": "agree",
      "reasoning": "同意。建议明确为 .graph/.bm25_index.json 或类似路径，与现有侧车文件保持命名一致性。"
    }
  ],
  "summary": "spec 在结构完整性、对标分析深度、目标/非目标划分上表现良好，但从设计架构角度存在 5 项 major 级缺陷：(1) 跨文件解析缺乏风险评估与降级方案；(2) AST 解析技术选型未说明；(3) 执行流追踪未处理动态分发，缺少接收者类型推断；(4) 调用链/影响分析缺少循环检测与深度限制；(5) 增量更新悬空边与影响分析的一致性未设计。同时挑战 spec-reviewer 的接口契约 over-judgment 与 deployment-config-reviewer 的可运维性 over-judgment，并 amplify spec-reviewer 的边界条件发现。"
}
```
