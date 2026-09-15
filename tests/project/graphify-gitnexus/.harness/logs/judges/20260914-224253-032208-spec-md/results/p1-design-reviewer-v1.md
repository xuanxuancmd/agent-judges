[design-reviewer 审查回复]

被审查内容是一份技术规格说明书（spec.md），定义了在 graphify 图谱基础上对标 GitNexus 补齐代码智能能力的功能需求。spec 在结构上较为完整，具备明确的背景动机、对标分析、目标/非目标、FR/NFR 分层、验收标准与里程碑，需求覆盖度较高。

但作为设计文档存在以下系统性缺陷：(1) 关键架构选型缺乏对比依据——尤其是保留 graph.json 而非引入 LadybugDB 的决策未给出技术理由，而新增的 blast radius/impact/trace 等查询密集型功能对存储层的查询效率有实质要求；(2) 验收标准覆盖不完整——FR-8 及多数 NFR 无对应 AC，FR-2 的四种边类型仅两种有 AC；(3) 异常路径与失败模式设计不足——执行流追踪(FR-3)未设计循环依赖终止条件、深链路预算限制；跨文件解析(FR-2)已识别悬空边风险但未给出消解方案；(4) NFR-1 对大规模仓库的性能指标不可度量。这些问题不影响 spec 作为草案的整体方向，但会在实现阶段造成可追溯性缺失。

```json
{
  "severity": "major",
  "confidence": 0.82,
  "reasoning": "该 spec 在结构上较为完整，具备明确的背景动机、对标分析、目标/非目标、FR/NFR 分层、验收标准与里程碑，需求覆盖度较高。但作为设计文档存在以下系统性缺陷：(1) 关键架构选型缺乏对比依据——尤其是保留 graph.json 而非引入 LadybugDB 的决策未给出技术理由，而新增的 blast radius/impact/trace 等查询密集型功能对存储层的查询效率有实质要求；(2) 验收标准覆盖不完整——FR-8 及多数 NFR 无对应 AC，FR-2 的四种边类型仅两种有 AC；(3) 异常路径与失败模式设计不足——执行流追踪(FR-3)未设计循环依赖终止条件、深链路预算限制；跨文件解析(FR-2)已识别悬空边风险但未给出消解方案；(4) NFR-1 对大规模仓库的性能指标不可度量。这些问题不影响 spec 作为草案的整体方向，但会在实现阶段造成可追溯性缺失。",
  "findings": [
    {
      "description": "保留 graph.json 作为主存储、拒绝引入 LadybugDB 的关键架构决策缺乏对比依据。新增的 blast radius(FR-4)、impact(FR-6)、trace(FR-6) 等功能本质上是图遍历查询，在 JSON 文件上执行大规模多跳遍历的性能特征未论证。GitNexus 选择 LadybugDB（嵌入式图数据库，原生向量支持）有其查询效率考量，spec 仅在非目标中声明'不引入'但未说明为何 JSON 方案足够。",
      "severity": "major",
      "confidence": 0.85,
      "evidence": "Section 4.2 非目标 1：'不替换图存储引擎：保持 .graph/graph.json 作为主持久化产物；Neo4j/FalkorDB 导出继续作为可选集成，不引入 LadybugDB 作为主存储。' 全文未给出该决策的技术论证。同时 Section 3.2 对标表明确标注 GitNexus 使用 'LadybugDB（嵌入式图数据库，原生向量支持）'，且 FR-4/FR-6 新增功能均为多跳图遍历查询。",
      "suggestion": "增加一节'存储层选型论证'，说明 graph.json 在新增的多跳遍历场景下的性能预期（或在何等规模下需迁移），以及与 LadybugDB/Neo4j 的对比维度（查询延迟、内存占用、增量更新代价）。若 JSON 在特定规模下不可行，应在 NFR 中标注触发迁移的阈值。"
    },
    {
      "description": "验收标准表(AC-1~AC-10)未覆盖全部 FR 和 NFR。FR-8（框架检测）无对应 AC；NFR-1（索引性能）、NFR-2（增量更新耗时）、NFR-3（存储占用）、NFR-5（确定性）、NFR-6（诚实性）均无对应 AC。同时 AC-10（社区检测语义连贯性）未映射到任何 FR。",
      "severity": "major",
      "confidence": 0.90,
      "evidence": "Section 7 验收标准表仅列 AC-1 至 AC-10。逐条核对：FR-8 无 AC；NFR-1~NFR-6 中仅 NFR-4 有对应 AC-9；AC-10 未对应任何具体 FR。FR-2 定义了四种边类型(CALLS/IMPORTS/HERITAGE/DEFINES)，但 AC-2 仅验证 CALLS、AC-3 仅验证 IMPORTS，HERITAGE 和 DEFINES 边无验收标准。",
      "suggestion": "补齐验收标准：为 FR-8、全部 NFR 各增加 AC；为 HERITAGE 和 DEFINES 边增加 AC（如：对已知继承关系的测试类，验证 HERITAGE 边连接正确）。将 AC-10 映射到具体 FR 或标注为横切验收项。"
    },
    {
      "description": "FR-3 执行流追踪未设计循环依赖/递归调用的终止条件。沿 CALLS 边追踪调用链时，递归函数、相互递归（mutual recursion）会产生环，若无终止条件会导致无限遍历或 process 节点无限膨胀。",
      "severity": "major",
      "confidence": 0.80,
      "evidence": "FR-3 要求：'调用链追踪：沿 CALLS 边从入口点出发，构建有向调用子图，记录每一步的调用关系。' 全文未提及循环检测、最大深度、已访问节点集合等终止机制。graphify 现有 query 功能有 --budget 限制 token 数（Section 2.3），但 FR-3 未引用此模式或设计类似限制。",
      "suggestion": "在 FR-3 中增加：process 构建时的环检测策略（如标记已访问符号、检测到环时记录但不再展开）、最大调用深度配置项，以及在 process 节点中标注循环引用（如 'cycle detected at symbol X'）。"
    },
    {
      "description": "FR-2 跨文件解析已识别悬空边风险，但未给出消解方案，仅标注为'固有时序问题'。spec 在 Section 2.2 提到 diagnose_extraction 可检测悬空边，但未设计新增边类型与该诊断的集成方案，也未说明增量更新后悬空边的自动修复机制。",
      "severity": "minor",
      "confidence": 0.72,
      "evidence": "FR-2 说明：'跨文件引用解析在增量更新场景下可能产生短暂的悬空边（被引用符号所在文件已变更但尚未重新提取时），这是跨文件解析的固有时序问题。' NFR-6 要求'跨文件解析未能解析的调用应标注为 AMBIGUOUS，不应静默丢弃'，但'短暂的悬空边'与'未能解析'是不同场景——前者是时序问题（最终可解析但暂时悬空），后者是解析失败。spec 未区分这两种情况的处理策略。",
      "suggestion": "区分两种场景：(1) 时序性悬空边——设计增量更新后的二次解析/修复流程；(2) 永久未解析边——标注 AMBIGUOUS。同时明确 diagnose_extraction 是否扩展覆盖 CALLS/IMPORTS/HERITAGE/DEFINES 边类型的完整性诊断（NFR-6 仅抽象要求'应覆盖'，未具体设计）。"
    },
    {
      "description": "FR-2 规定跨文件解析为纯规则、不使用 LLM，但未讨论规则解析的已知精度局限。动态分派（virtual method/dispatch）、反射调用、依赖注入、动态 import 等场景下纯规则解析必然产生大量 AMBIGUOUS 边，spec 未评估其对下游 FR-3/FR-4/FR-5 功能准确性的影响。",
      "severity": "major",
      "confidence": 0.75,
      "evidence": "FR-2：'解析应基于语言感知的规则（不同语言的导入系统差异由 language-specific resolver 处理），不使用 LLM。' NFR-6：'跨文件解析未能解析的调用应标注为 AMBIGUOUS。' 但全文未讨论动态分派等场景的解析覆盖率预期，也未评估 AMBIGUOUS 边比例对 blast radius(FR-4) 置信度和 process(FR-3) 完整性的影响。",
      "suggestion": "增加一节'解析精度与局限'：(1) 列举纯规则解析不可覆盖的场景（动态分派、反射、依赖注入）；(2) 评估这些场景在典型仓库中的占比；(3) 说明对 FR-3/FR-4 结果置信度的影响——如 process 节点是否标注'因 AMBIGUOUS 边导致覆盖不完整'。"
    },
    {
      "description": "NFR-1 对大规模仓库的性能指标不可度量。'~500 文件应在 60 秒内完成'是可度量的，但'~5000 文件应在可接受范围内完成'中'可接受范围内'无定义，无法作为验收依据。",
      "severity": "minor",
      "confidence": 0.88,
      "evidence": "NFR-1：'全量索引一个中等规模仓库（~500 文件）应在 60 秒内完成...大规模仓库（~5000 文件）应在可接受范围内完成全量索引。' '可接受范围内'未给出具体数值或上限倍率（如线性扩展为 600 秒，或 O(n log n) 预期）。",
      "suggestion": "将'可接受范围内'替换为具体数值（如'~5000 文件应在 10 分钟内完成'），或给出性能预期模型（如'索引时间与文件数呈线性关系，5000 文件预期 ~600 秒'）。"
    },
    {
      "description": "FR-3(P2, M3) 要求入口点评分'可配置、可扩展'，但 FR-8(P4, M5) 框架检测是入口点评分的关键输入信号。M3 交付的 FR-3 评分机制在 M5 之前缺乏框架检测信号，评分功能实质不完整。spec 未说明 M3 阶段评分的降级形态。",
      "severity": "minor",
      "confidence": 0.70,
      "evidence": "FR-3：'入口点识别：基于启发式评分...入口点评分规则应可配置、可扩展。' FR-8：'检测结果作为入口点评分的输入信号之一（FR-3）。' 里程碑 M3（FR-3）在 M5（FR-8）之前交付。FR-3 依赖 FR-8 的框架检测信号，但 FR-8 排在 P4/M5。",
      "suggestion": "在里程碑或 FR-3 中说明：M3 阶段的入口点评分仅基于基础启发式（main 函数、HTTP handler 等），FR-8 框架信号在 M5 接入后评分精度提升。或在 M3 中先交付 FR-8 的基础框架检测子集（如仅 Express/FastAPI），完整规则集留到 M5。"
    },
    {
      "description": "FR-1 将语言列表固定为 6 种，但未描述新增语言的扩展点接口。GitNexus 支持 15+ 语言，对标方向明确需要未来扩展，spec 未定义'language-specific resolver'必须实现的接口契约。",
      "severity": "minor",
      "confidence": 0.68,
      "evidence": "FR-1：'语言支持至少达到：TypeScript、JavaScript、Python、Go、Java、Rust（与 graphify 现有支持对齐，不引入新语言依赖）。' FR-2：'不同语言的导入系统差异由 language-specific resolver 处理。' 但全文未定义 resolver 的接口契约（输入/输出/必须实现的方法），使'可扩展'停留在意图层面而非设计层面。",
      "suggestion": "增加一节'语言扩展点'：定义 language resolver 的接口契约（输入：AST + 文件路径；输出：符号节点 + 边），列出新语言需实现的最小接口集。这不增加实现成本但使扩展路径可追溯。"
    },
    {
      "description": "FR-7 RRF K 值默认 60 直接采用 GitNexus 数值，未给出选型依据或适用场景说明。",
      "severity": "minor",
      "confidence": 0.65,
      "evidence": "FR-7：'结果融合使用 RRF（Reciprocal Rank Fusion），K 值默认 60，可配置。' K=60 与 Section 3.1 中 GitNexus 的描述完全一致（'RRF（Reciprocal Rank Fusion, K=60）'），但 spec 未说明为何采用此值、不同 K 值对融合结果的影响，或是否针对 graphify 的符号搜索场景做了验证。",
      "suggestion": "在 FR-7 中补充 K 值选型说明（如'K=60 为业界常用经验值，对中等规模结果集平衡精度与召回；graphify 场景下结果集规模较小，K=60 仍适用'），或在 AC-8 中增加 K 值敏感度测试。"
    }
  ],
  "satisfied": false
}
```
