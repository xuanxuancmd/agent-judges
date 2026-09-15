[spec-reviewer 哨兵审查 - plan.md]

作为 spec-reviewer，逐条审查了 plan.md 的可追溯性、接口契约完整性、边界条件覆盖、验收标准可测试性与内部一致性。计划整体结构清晰，FR/NFR/AC 映射表存在，任务依赖关系明确。但发现 3 处 major 级内部不一致（NFR 映射矛盾、INFERRED 边类型未定义却被引用、AMBIGUOUS 边侧车存储策略无实现任务）以及多处 minor 级缺口。

```json
{
  "severity": "major",
  "confidence": 0.82,
  "reasoning": "作为 spec-reviewer，逐条审查了 plan.md 的可追溯性、接口契约完整性、边界条件覆盖、验收标准可测试性与内部一致性。计划整体结构清晰，FR/NFR/AC 映射表存在，任务依赖关系明确。但发现 3 处 major 级内部不一致（NFR 映射矛盾、INFERRED 边类型未定义却被引用、AMBIGUOUS 边侧车存储策略无实现任务）以及多处 minor 级缺口（接口契约未定义、边界条件未系统覆盖、AC-4/AC-8 缺乏量化阈值、FR-8 无对应正式 AC、Tree-sitter 评估无归属任务、NFR 覆盖声明与退出标准脱节）。这些不一致会导致执行阶段对验收范围与接口定义产生歧义，需修正后方可作为可执行规格基线。",
  "findings": [
    {
      "description": "P5 阶段 NFR 映射三方不一致：目标声明 NFR-1/2/3，退出标准引用 NFR-1/3/4，附录映射 NFR-1/2/3。NFR-2 出现在目标与附录但缺失于退出标准；NFR-4 出现在退出标准但附录将其映射到 P1。这会导致 P5 验收时无法确定 NFR-2 是否需要验证、NFR-4 是否属于 P5 验收范围。",
      "severity": "major",
      "confidence": 0.90,
      "evidence": "Section 7.1: 「验证 NFR-1/2/3（性能、增量更新耗时、存储占用）」；Section 7.3: 「NFR-1：500 文件仓库全量索引 ≤ 60 秒。NFR-3：graph.json 体积增长 ≤ 3 倍。NFR-4：旧 graph.json 的 query 行为无退化。」；附录: 「P5 | — | NFR-1, NFR-2, NFR-3 | AC-9, AC-10」。三处对 P5 覆盖的 NFR 集合不一致。",
      "suggestion": "统一 P5 的 NFR 覆盖声明。明确 NFR-2（增量更新耗时）的验证属于 P5，将退出标准补入 NFR-2 的量化阈值；将 NFR-4 从 P5 退出标准移除或在附录中补标 P5 也覆盖 NFR-4。三处必须指向同一 NFR 子集。"
    },
    {
      "description": "T3.2 置信度评分引用 INFERRED 边类型（60%），但全计划中 INFERRED 边从未被任何任务定义或创建。T1.12 仅定义两种边状态：EXTRACTED 与 AMBIGUOUS。这导致 T3.2 的三级置信度模型中中间档（60%）对应的数据源不存在，影响影响分析（FR-4）的置信度计算逻辑完整性。",
      "severity": "major",
      "confidence": 0.88,
      "evidence": "T3.2: 「实现置信度评分：EXTRACTED 边 → 90%、INFERRED 边 → 60%、AMBIGUOUS 边 → 30%」；T1.12: 「新增边类型标注为 EXTRACTED，未解析的调用标注为 AMBIGUOUS」——仅定义两种状态，无任何任务产生 INFERRED 边。",
      "suggestion": "要么在 P1 增加任务定义 INFERRED 边的生成条件，要么将 T3.2 置信度模型改为两级（EXTRACTED 90% / AMBIGUOUS 30%），消除未定义的中间档。"
    },
    {
      "description": "风险表中提出 AMBIGUOUS 边存储到侧车文件以控制 graph.json 体积（NFR-3 风险应对），但没有任何任务实现此存储策略。T1.12 仅标注边来源类型，不涉及分离存储。这意味着该风险缓解措施无归属任务，风险实际未被应对。",
      "severity": "major",
      "confidence": 0.75,
      "evidence": "Section 9 风险表: 「graph.json 体积膨胀超 NFR-3 限制 | … | BM25 索引独立侧车；Resolution 边按需存储（仅 EXTRACTED 边入主图，AMBIGUOUS 边入侧车）」；T1.12: 「新增边类型标注为 EXTRACTED，未解析的调用标注为 AMBIGUOUS」——仅涉及标注，无分离存储逻辑；全阶段任务列表中无任何任务实现 AMBIGUOUS 边侧车存储。",
      "suggestion": "在 P1 或 P5 增加明确任务：实现 AMBIGUOUS 边从主图分离到侧车文件的存储逻辑，并在 Part C 合并流程中集成。或者从风险应对中移除此策略，改为其他体积控制手段。"
    },
    {
      "description": "FR-8（框架检测与入口点配置）在附录中映射到 P4，但 AC-1 至 AC-10 中无一对应框架检测质量。P4 退出标准「入口点识别覆盖率 ≥ 70%」是事实上的验收标准，但未形式化进入 AC 列表，导致 FR-8 缺乏可追溯的正式验收标准。",
      "severity": "minor",
      "confidence": 0.80,
      "evidence": "附录: 「P4 | FR-8 | — | —」——覆盖 AC 列为空；P4.4 退出标准: 「6 个框架的测试仓库中，入口点识别覆盖率 ≥ 70%」；Section 8.3 AC 列表无框架检测相关条目。",
      "suggestion": "新增 AC-11（框架检测覆盖率 ≥ 70%），在附录 P4 行补入 AC-11。"
    },
    {
      "description": "AC-8「混合搜索优于纯向量」缺乏量化阈值定义。Section 8.3 提到「召回率对比」但未定义「优于」的判定标准，使 AC-8 在对标测试中无法给出确定性 pass/fail 判定。",
      "severity": "minor",
      "confidence": 0.82,
      "evidence": "P5.4: 「AC-8（混合搜索优于纯向量）」——无量化阈值；Section 8.3: 「AC-8 混合搜索召回 | P3 | 对标测试：同一查询的召回率对比」——仅说「对比」，未定义通过门槛。",
      "suggestion": "将 AC-8 改为「混合搜索在相同查询集上召回率较纯向量搜索提升 ≥ 10%」，明确测试查询集规模与判定方法。"
    },
    {
      "description": "AC-4「执行流覆盖完整调用链」中「完整」未量化定义。是 100% 覆盖入口点到终端的所有调用路径？还是覆盖率达到某阈值？",
      "severity": "minor",
      "confidence": 0.78,
      "evidence": "P2.4: 「满足 AC-4（执行流覆盖完整调用链）」；Section 8.3: 「AC-4 执行流覆盖 | P2 | 集成测试：入口点到终端调用的路径断言」——「路径断言」未定义覆盖率门槛。",
      "suggestion": "将 AC-4 量化为「对测试仓库中已知入口点，process 节点覆盖的调用链深度达到实际调用链的 ≥ 90%」。"
    },
    {
      "description": "计划引入新接口 LanguageResolver（T1.3）和 4 个新 MCP 工具（T3.5: context/impact/trace/detect_changes），但均未定义接口契约（方法签名、输入/输出 schema、错误码、边界返回）。计划引用 spec.md v1.0 但未指明这些接口在 spec.md 中的对应条目。",
      "severity": "minor",
      "confidence": 0.72,
      "evidence": "T1.3: 「实现语言解析器注册机制：LanguageResolver 接口 + 每语言实现」——无方法签名定义；T3.5: 「扩展 MCP server：注册 context/impact/trace/detect_changes 工具」——无输入/输出 schema；文档头: 「关联规格 | spec.md v1.0」——但未在任何任务中指明对应 spec 条目编号。",
      "suggestion": "在计划中为每个新接口补充契约摘要，并标注对应的 spec.md 条目编号。"
    },
    {
      "description": "边界条件未在任务描述中系统覆盖。导入解析（T0.3）仅提及 named/default/wildcard，未覆盖循环导入、动态导入（import()）、re-export、路径别名；git-diff 解析（T2.5）未提及二进制文件、文件删除、文件重命名；影响分析深度限制（默认最大深度 5 层）仅在风险表中提及，未写入 T3.1/T3.3 任务描述。",
      "severity": "minor",
      "confidence": 0.75,
      "evidence": "T0.3: 仅「解析 import { X } from 'path'、import Y from 'path'、import * as Z from 'path'」——三种形式，无边界情况；T2.5: 「文件级 + 行级 diff → 映射到符号节点」——无二进制/删除/重命名处理说明；Section 9: 「深度限制（默认最大深度 5 层，可配置）」——仅在风险应对中，T3.1 与 T3.3 任务描述未提及。",
      "suggestion": "在 T0.3/T1.4-T1.9 各解析器任务描述中显式列出需处理的边界情况；在 T2.5 补充二进制文件跳过、删除/重命名符号清理逻辑；在 T3.1/T3.3 任务描述中纳入深度限制参数。"
    },
    {
      "description": "附录声明 P1 覆盖 NFR-4/5/6、P2 覆盖 NFR-2，但这两个阶段的退出标准仅引用 AC，未包含任何 NFR 验证条目。这意味着声称覆盖的 NFR 在阶段退出时无验证门槛。",
      "severity": "minor",
      "confidence": 0.70,
      "evidence": "附录: 「P1 | FR-1, FR-2 | NFR-4, NFR-5, NFR-6 | AC-1, AC-2, AC-3」——声明覆盖 3 个 NFR；P1 退出标准: 「满足 AC-1…和 AC-2/AC-3…」「6 种语言各自的测试仓库通过 Resolution 阶段，无崩溃」——无 NFR-4/5/6 验证条目。附录: 「P2 | FR-3, FR-5 | NFR-2 | AC-4, AC-6」；P2 退出标准: 「满足 AC-4…和 AC-6…」——无 NFR-2 验证条目。",
      "suggestion": "在每个声明覆盖 NFR 的阶段退出标准中补充对应 NFR 的量化验证条目。"
    },
    {
      "description": "Section 10 列出依赖项「Tree-sitter Python 绑定 | 如需替换现有 AST 提取为 Tree-sitter（待 P0 评估）| 待确认」，但 P0 任务分解（T0.1–T0.6）中无任何任务明确执行 Tree-sitter 替换评估。依赖状态无法在 P0 结束时更新。",
      "severity": "minor",
      "confidence": 0.68,
      "evidence": "Section 10: 「Tree-sitter Python 绑定 | 如需替换现有 AST 提取为 Tree-sitter（待 P0 评估）| 待确认」；P0 任务表 T0.1–T0.6: T0.2「分析 graphify AST 提取输出的节点/边结构」——分析现有输出，不评估 Tree-sitter；无 T0.x 任务提及 Tree-sitter。",
      "suggestion": "在 P0 增加 T0.7（或扩展 T0.2）：评估是否需要引入 Tree-sitter，输出评估结论，更新 Section 10 依赖状态。"
    }
  ],
  "satisfied": false
}
```
